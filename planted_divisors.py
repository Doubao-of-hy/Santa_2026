"""Construct groups of targets by selecting an entire shared divisor lattice."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from time import perf_counter
from warnings import catch_warnings, filterwarnings

from dictionary import find_programs, prepare
from elf import Puzzle, read_puzzles, read_submission, score, write_submission
from factorization import independent_shape, splits
from planted import (Expression, cost_model, exclusive_costs, expand_program, make_model,
                     neighborhood, structural_strength)


def ingredients(expression: Expression) -> set[int]:
    return set(expression.ingredients())


def direct_options(puzzle: Puzzle, offsets: tuple[int, ...]) -> dict[int, list[Expression]]:
    candidates: dict[int, list[Expression]] = {}
    seeds = set(puzzle.seeds)
    for target in set(puzzle.targets) - seeds:
        forms = []
        for residual in offsets:
            exact = target - residual
            if exact < 4 or exact > puzzle.limit or abs(residual) >= target // 2:
                continue
            for a, b in splits(exact):
                if a < target and b < target:
                    forms.append(Expression(target, a, b, residual))
        candidates[target] = forms
    return candidates


def candidate_network(puzzle: Puzzle, residual_count: int, width: int):
    atoms, estimate = cost_model(puzzle)
    offsets = neighborhood(puzzle, atoms, residual_count)
    targets = set(puzzle.targets) - set(puzzle.seeds)
    exact = direct_options(puzzle, offsets)
    support = Counter(k for options in exact.values() for k in
                      {k for expression in options for k in ingredients(expression)})

    def rank(expression: Expression):
        price = (1 + int(expression.residual != 0)
                 + sum(estimate(value) / (min(support[value], 8) ** 0.37)
                       for value in ingredients(expression)))
        return price, max(expr.bit_length() for expr in ingredients(expression)), abs(expression.residual)

    # All promising factor pairs compete jointly. Keep exact products and
    # nonzero residue alternatives even when a single local rank favors one mode.
    network = {}
    for value, proposals in exact.items():
        direct = sorted((expr for expr in proposals if not expr.residual), key=rank)[:width]
        nearby = sorted((expr for expr in proposals if expr.residual), key=rank)[:width]
        network[value] = list(dict.fromkeys((*direct, *nearby)))
    discovered = {term for forms in network.values() for expr in forms for term in ingredients(expr)}
    helper_values = [value for value in discovered - targets - set(puzzle.seeds)
                     if value >= 64 and value not in atoms]
    helper_values.sort(key=lambda value: (-support[value], -value.bit_length(), value))
    for value in helper_values[:160]:
        options = []
        for a, b in splits(value):
            # Reuse a divisor only when it is already a likely ingredient, or
            # when both factors are in the short-operation starting library.
            if (a in discovered or b in discovered or (a in atoms and b in atoms)):
                options.append(Expression(value, a, b, 0))
        for expression in options:
            for term in ingredients(expression):
                support[term] = max(support[term], 1)
        if options:
            network[value] = sorted(options, key=rank)[:4]
    return network, estimate


def select_network(puzzle: Puzzle, incumbent, network, estimate, seconds: float):
    """Choose factor recipes jointly while paying once for every shared ingredient."""
    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import coo_array

    seeds = set(puzzle.seeds)
    required = set(puzzle.targets) - seeds
    vertices = required | {term for options in network.values() for option in options
                           for term in ingredients(option)} | set(network)
    vertices -= seeds
    standalone = exclusive_costs(puzzle, incumbent)
    options_by_value: dict[int, list[int]] = defaultdict(list)
    recipes: list[Expression | None] = []
    weights = []
    for value in sorted(vertices):
        options_by_value[value].append(len(recipes))
        recipes.append(None)
        weights.append(max(1.0, standalone.get(value, estimate(value))))
        for recipe in network.get(value, ()):
            options_by_value[value].append(len(recipes))
            recipes.append(recipe)
            weights.append(1.0 + int(recipe.residual != 0))

    rows, columns, entries, lower, upper = [], [], [], [], []

    def constraint(terms, minimum, maximum):
        row = len(lower)
        for index, coefficient in terms:
            rows.append(row)
            columns.append(index)
            entries.append(coefficient)
        lower.append(minimum)
        upper.append(maximum)

    for value, alternatives in options_by_value.items():
        constraint([(choice, 1) for choice in alternatives], int(value in required), 1)
    for index, recipe in enumerate(recipes):
        if recipe is None:
            continue
        for child in ingredients(recipe) - seeds:
            constraint([(index, 1), *((choice, -1) for choice in options_by_value[child])],
                       -np.inf, 0)
    matrix = coo_array((entries, (rows, columns)), shape=(len(lower), len(recipes))).tocsc()
    with catch_warnings():
        # SciPy forwards this supported HiGHS option and warns about it itself.
        filterwarnings("ignore", message=r"Unrecognized options detected: .*threads", category=RuntimeWarning)
        answer = milp(
            np.array(weights), integrality=np.ones(len(recipes)), bounds=Bounds(0, 1),
            constraints=LinearConstraint(matrix, lower, upper),
            options={"time_limit": seconds, "threads": 1},
        )
    if answer.x is None:
        return ()
    return tuple(recipe for yes, recipe in zip(answer.x, recipes) if yes > 0.5 and recipe is not None)


def model_job(job):
    puzzle, incumbent, offsets, width, seconds, anchors = job
    network, estimate = candidate_network(puzzle, offsets, width)
    selected = select_network(puzzle, incumbent, network, estimate, seconds)
    covered = {expr.target for expr in selected} & set(puzzle.targets)
    if not covered:
        return None
    return make_model(puzzle, incumbent, selected, 0, True, True, anchors), len(covered)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("puzzles", type=Path)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--pilot", type=int, default=64)
    parser.add_argument("--offsets", type=int, default=18)
    parser.add_argument("--width", type=int, default=12)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--seconds", type=float, default=3.0)
    parser.add_argument("--anchors", type=int, default=10)
    parser.add_argument("--variant", type=int, default=12)
    args = parser.parse_args()
    if (args.pilot < 0 or args.seconds <= 0 or args.anchors < 0
            or min(args.offsets, args.width, args.workers, args.batch_size) < 1):
        parser.error("invalid search settings")
    puzzles = read_puzzles(args.puzzles)
    baseline = read_submission(args.baseline)
    original = score(puzzles, baseline)
    best = baseline.copy()
    eligible = [p for p in puzzles if p.limit >= 1024 and not independent_shape(p)]
    eligible.sort(key=lambda puzzle: (structural_strength(puzzle), len(baseline[puzzle.id])), reverse=True)
    if args.pilot:
        concentrated = min(args.pilot, len(eligible)) // 2
        broad = sorted(eligible[concentrated:], key=lambda p: (-len(baseline[p.id]), p.id))
        spread = max(1, len(broad) // max(1, args.pilot - concentrated))
        eligible = eligible[:concentrated] + broad[::spread][:args.pilot - concentrated]
    native = prepare()
    predicted = solved = sampled_coverage = 0
    start = perf_counter()
    with ProcessPoolExecutor(args.workers) as pool:
        for offset in range(0, len(eligible), args.batch_size):
            batch = eligible[offset:offset + args.batch_size]
            jobs = [(p, baseline[p.id], args.offsets, args.width, args.seconds, args.anchors) for p in batch]
            found = [out for out in pool.map(model_job, jobs) if out is not None]
            sampled_coverage += sum(covered for _, covered in found)
            models = {model.reduced.id: model for model, _ in found}
            predicted += len(models)
            if models:
                programs, _ = find_programs([model.reduced for model in models.values()],
                                             args.variant, 8, 2, args.workers, native)
                for key, program in programs.items():
                    model = models[key]
                    answer = expand_program(model, program, 0)
                    if answer is None:
                        continue
                    solved += 1
                    if len(answer) < len(best[model.puzzle.id]):
                        best[model.puzzle.id] = answer
            total = write_submission(args.output, puzzles, best)
            print(f"{offset + len(batch)}/{len(eligible)}, {predicted} models, "
                  f"{sampled_coverage} modeled targets, {solved} compiled, {total} steps", flush=True)
    total = write_submission(args.output, puzzles, best)
    replacements = sum(len(best[key]) < len(baseline[key]) for key in best)
    print(f"total {total}, saved {original - total} across {replacements} puzzles, "
          f"{perf_counter()-start:.1f}s")


if __name__ == "__main__":
    main()
