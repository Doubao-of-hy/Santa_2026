"""Infer shared arithmetic scales by matching the residues of distinct targets."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations
from math import gcd, isqrt, prod
from pathlib import Path
from time import perf_counter

from construct import seed_dictionary
from dictionary import find_programs, prepare
from elf import Program, Puzzle, check, read_puzzles, read_submission, score, write_submission
from factorization import cheap_layers, independent_shape
from graph import Graph, active_graph, compile_graph, first_recipes


SMALL_PRIMORIAL = prod((2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43,
                       47, 53, 59, 61, 67, 71, 73, 79, 83, 89, 97, 101, 103, 107,
                       109, 113, 127))


@dataclass(frozen=True)
class Expression:
    target: int
    scale: int
    quotient: int
    residual: int

    def ingredients(self) -> tuple[int, ...]:
        values = (self.scale,) if self.quotient == 1 else (self.scale, self.quotient)
        return values + (abs(self.residual),) if self.residual else values


@dataclass
class Group:
    scale: int
    expressions: tuple[Expression, ...]
    priority: float


@dataclass
class Model:
    puzzle: Puzzle
    reduced: Puzzle
    scaffold: Graph
    independent: Graph
    motif: Graph


def strip_small(value: int) -> int:
    factor = gcd(value, SMALL_PRIMORIAL)
    while factor > 1:
        value //= factor
        factor = gcd(value, SMALL_PRIMORIAL)
    return value


def cost_model(puzzle: Puzzle):
    seeds, first, second = cheap_layers(puzzle)
    atoms = {value: cost for cost, layer in enumerate((seeds, first, second)) for value in layer}

    def cost(value: int) -> float:
        if value in atoms:
            return atoms[value]
        bits = value.bit_length()
        if bits <= 7:
            return 2.8
        if bits <= 13:
            return 3.3
        if bits <= 21:
            return 4.4
        return 2.0 + bits / 8

    return atoms, cost


def neighborhood(puzzle: Puzzle, atoms: dict[int, int], count: int) -> tuple[int, ...]:
    one_step = sorted(x for x in puzzle.seeds + tuple(seed_dictionary(puzzle)) if x <= 2**17)
    offsets = dict.fromkeys((*range(1, 13), *one_step))
    if len(offsets) < count:
        layers: dict[int, list[int]] = defaultdict(list)
        for value, cost in sorted(atoms.items()):
            if cost == 2 and 1 <= value <= 2**20:
                layers[value.bit_length()].append(value)
        candidates = []
        for values in layers.values():
            if len(values) <= 6:
                candidates.extend(values)
            else:
                candidates.extend(values[i * (len(values) - 1) // 5] for i in range(6))
        for value in candidates:
            if len(offsets) >= count:
                break
            offsets.setdefault(value, None)
    return (0, *(direction * value for value in list(offsets)[:count] for direction in (1, -1)))


def gcd_scales(puzzle: Puzzle, residuals: tuple[int, ...]) -> set[int]:
    """Discover common factors across neighborhoods by first comparing their products."""
    groups = []
    estimates: set[int] = set()
    for target in sorted(set(puzzle.targets)):
        options = []
        for residual in residuals:
            exact = target - residual
            if 1 < exact <= puzzle.limit:
                options.append((exact, strip_small(exact)))
                root = isqrt(exact)
                if root * root == exact and root >= 8:
                    estimates.add(root)
        signatures = {cofactor for _, cofactor in options}
        groups.append((target, options, prod(signatures)))
    for (target, choices, left), (other, others, right) in combinations(groups, 2):
        exact_factor = gcd(target, other)
        if exact_factor >= 8:
            estimates.add(exact_factor)
        shared = gcd(left, right)
        if shared == 1:
            continue
        left_matches = [(value, overlap) for value, cofactor in choices
                        if (overlap := gcd(cofactor, shared)) > 1]
        right_matches = [(value, overlap) for value, cofactor in others
                         if (overlap := gcd(cofactor, shared)) > 1]
        for x, left_factor in left_matches:
            for y, right_factor in right_matches:
                if gcd(left_factor, right_factor) == 1:
                    continue
                factor = gcd(x, y)
                if factor >= 128 and (factor >= 4096 or min(x, y) // factor <= 256):
                    estimates.add(factor)
    return estimates


def ratio_scales(puzzle: Puzzle, atoms: dict[int, int]) -> set[int]:
    """Intersect approximate low-multiplier grids even when two residues are unknown."""
    multipliers = sorted(set(range(1, 65)) |
                         {x for x, cost in atoms.items() if 65 <= x <= 256 and cost <= 1})
    ratios = sorted((target // scale, target, scale)
                    for target in set(puzzle.targets) if target >= 512
                    for scale in multipliers if scale <= target // 128)
    estimates = set(puzzle.targets)
    for index, (value, target, coefficient) in enumerate(ratios):
        for neighbor in range(index + 1, min(index + 9, len(ratios))):
            other, other_target, other_coefficient = ratios[neighbor]
            if other - value > min(2048, max(3, value // 1000)):
                break
            if other_target == target:
                continue
            radius = max(16, min(2048, min(target, other_target) // 1000))
            lower = max((target - radius + coefficient - 1) // coefficient,
                        (other_target - radius + other_coefficient - 1) // other_coefficient)
            upper = min((target + radius) // coefficient, (other_target + radius) // other_coefficient)
            if lower > upper:
                continue
            estimates.update((value, other, (value + other) // 2, lower, upper))
            for power in (16, 64, 256, 1024, 4096):
                multiple = ((lower + power - 1) // power) * power
                if multiple <= upper:
                    estimates.add(multiple)
    return estimates


def difference_scales(puzzle: Puzzle) -> set[int]:
    """Shared residues are revealed by common factors of pairwise differences."""
    values = sorted(set(puzzle.targets))
    differences = sorted({right - left for left, right in combinations(values, 2)
                          if right - left >= 1024})
    support: Counter[int] = Counter()
    for left, right in combinations(differences, 2):
        scale = gcd(left, right)
        if scale >= 1024:
            support[scale] += 1
    ranked = sorted(support, key=lambda value: (-(value.bit_length() + 2 * support[value]), value))
    result = set()
    for scale in ranked[:144]:
        residues = Counter(target % scale for target in values)
        if max(residues.values(), default=0) >= 3 or sum(count >= 2 for count in residues.values()) >= 2:
            result.add(scale)
    return result


def continued_scales(puzzle: Puzzle, residuals: tuple[int, ...]) -> set[int]:
    """Recover a lattice scale from unusually accurate rational target ratios."""
    estimates = set()
    for lower_target, upper_target in combinations(sorted(set(puzzle.targets)), 2):
        if lower_target < 2**15:
            continue
        a, b = upper_target, lower_target
        p_before, p = 0, 1
        q_before, q = 1, 0
        while b:
            coefficient, remainder = divmod(a, b)
            p_before, p = p, coefficient * p + p_before
            q_before, q = q, coefficient * q + q_before
            a, b = b, remainder
            if p > 2**24 or q > 2**18:
                break
            if p <= 64 or not q:
                continue
            disagreement = abs(upper_target * q - lower_target * p)
            if disagreement * min(p, q) * 16 > lower_target:
                continue
            radius = max(1024, min(65536, lower_target // 8192))
            lower = max((lower_target - radius + q - 1) // q,
                        (upper_target - radius + p - 1) // p,
                        8)
            upper = min((lower_target + radius) // q, (upper_target + radius) // p)
            if lower > upper:
                continue
            for center in (lower, upper, (lower + upper) // 2,
                           (lower_target + q // 2) // q, (upper_target + p // 2) // p):
                if lower <= center <= upper:
                    estimates.add(center)
            for target, multiplier in ((lower_target, q), (upper_target, p)):
                for residual in residuals:
                    scale, remainder = divmod(target - residual, multiplier)
                    if not remainder and lower <= scale <= upper:
                        estimates.add(scale)
    return estimates


def cut_dependencies(puzzle: Puzzle, graph: Graph, modeled: set[int]) -> Graph:
    """Retain all other target recipes and treat modeled roots as new inputs."""
    retained = set()
    boundaries = modeled | set(puzzle.seeds)
    pending = list(set(puzzle.targets) - boundaries)
    while pending:
        value = pending.pop()
        if value in boundaries or value in retained:
            continue
        retained.add(value)
        pending.extend(graph[value][1:])
    return {value: recipe for value, recipe in graph.items() if value in retained}


def exclusive_costs(puzzle: Puzzle, program: Program) -> dict[int, int]:
    graph = active_graph(puzzle, first_recipes(puzzle, program))
    return {target: len(graph) - len(cut_dependencies(puzzle, graph, {target}))
            for target in puzzle.targets}


def choose_groups(puzzle: Puzzle, incumbent: Program, residual_budget: int, width: int,
                  use_differences: bool = False, use_continued: bool = False) -> list[Group]:
    atoms, price = cost_model(puzzle)
    residuals = neighborhood(puzzle, atoms, residual_budget)
    cheap_residuals = set(residuals)
    exact_scales = gcd_scales(puzzle, residuals)
    difference_hypotheses = difference_scales(puzzle) if use_differences else set()
    continued = continued_scales(puzzle, residuals) if use_continued else set()
    scales = exact_scales | ratio_scales(puzzle, atoms) | difference_hypotheses | continued
    single_cost = exclusive_costs(puzzle, incumbent)
    targets = sorted(set(puzzle.targets) - set(puzzle.seeds))
    target_set = set(targets)
    groups = []
    for scale in scales:
        if scale < 8 or scale > puzzle.limit:
            continue
        options = []
        gain = 0.0 if scale in target_set else -price(scale)
        residue_counts = Counter(target % scale for target in targets) if scale in difference_hypotheses else {}
        for target in targets:
            if target == scale:
                continue
            quotient, residual = divmod(target, scale)
            coarse = [(quotient, residual)]
            if residual and target + scale - residual <= puzzle.limit:
                coarse.append((quotient + 1, residual - scale))
            possible = []
            for q, r in coarse:
                if q < 1 or q == target or abs(r) == target:
                    continue
                multiplicity = residue_counts.get(r % scale, 1)
                if (r not in cheap_residuals and multiplicity < 2
                        and abs(r) > min(65536, max(16, target // 512))):
                    continue
                price_q = 0 if q == 1 or q in target_set else price(q)
                expense = price_q + int(q != 1)
                if r:
                    expense += 1 + (0 if abs(r) in target_set else price(abs(r)) / multiplicity)
                expected = max(price(target), single_cost[target]) - expense
                if expected > -0.75:
                    possible.append((expected, -abs(r), Expression(target, scale, q, r)))
            if possible:
                expected, _, expression = max(possible, key=lambda option: option[:2])
                gain += expected
                options.append(expression)
        support = len(options) + int(scale in target_set)
        if support < 2 or gain < -1:
            continue
        confidence = sum(expr.residual == 0 or abs(expr.residual) in atoms for expr in options)
        groups.append(Group(scale, tuple(options), gain + 0.7 * confidence + 0.5 * support))
    groups.sort(key=lambda group: (-group.priority, group.scale))
    selected = []
    signatures = set()
    for group in groups:
        signature = tuple(expression.target for expression in group.expressions)
        if (signature, group.scale.bit_length()) in signatures:
            continue
        signatures.add((signature, group.scale.bit_length()))
        selected.append(group)
        if len(selected) >= width:
            break
    return selected


def make_plans(groups: list[Group], width: int) -> list[tuple[Expression, ...]]:
    plans = [group.expressions for group in groups]
    if groups:
        covered = set()
        plan = []
        for group in groups:
            additions = [expression for expression in group.expressions if expression.target not in covered]
            if len(additions) >= 2 or (len(additions) == 1 and group.scale not in covered):
                plan.extend(additions)
                covered.update(expression.target for expression in additions)
            if len(plan) >= 8:
                break
        if plan and tuple(plan) not in plans:
            plans.insert(0, tuple(plan))
    return plans[:width]


def structural_strength(puzzle: Puzzle) -> tuple[int, int, int]:
    hits = 0
    touched = set()
    for left, right in combinations(sorted(set(puzzle.targets)), 2):
        if left < 256:
            continue
        scale = gcd(left, right)
        if scale >= 1024 and min(left, right) // scale <= 128:
            hits += 3
            touched.update((left, right))
        ratio = (right + left // 2) // left
        if 1 <= ratio <= 64 and abs(right - left * ratio) <= min(65536, 1024 * ratio, left // 512):
            hits += 2
            touched.update((left, right))
    return len(touched), hits, len(puzzle.targets)


def lifted_motif(puzzle: Puzzle, plan: tuple[Expression, ...], lift: bool) -> Graph:
    """Build products in a shared coefficient lattice before adding the residuals."""
    recipe: Graph = {}
    by_scale: dict[int, set[int]] = defaultdict(set)
    for expression in plan:
        by_scale[expression.scale].add(expression.quotient)
    _, price = cost_model(puzzle) if lift else ({}, lambda _: 0)
    constants = set(puzzle.seeds)
    constants.update(abs(expression.residual) for expression in plan if expression.residual)
    for base, choices in by_scale.items():
        normalized = {1}
        pending = choices - normalized
        while pending:
            alternatives = []
            for q in sorted(pending):
                # A rented integer multiplier costs nothing once another expression needs it.
                alternatives.append((1 + (0 if q in constants else price(q)),
                                     q, "*", base, q, q))
                if not lift:
                    continue
                for known in sorted(normalized):
                    difference = q - known
                    if difference in normalized:
                        alternatives.append((1, q, "+", base * known, base * difference, 0))
                    if -difference in normalized:
                        alternatives.append((1, q, "-", base * known, -base * difference, 0))
                    quotient, remainder = divmod(q, known)
                    if not remainder and known != 1:
                        alternatives.append((1 + (0 if quotient in constants else price(quotient)),
                                             q, "*", base * known, quotient, quotient))
                    quotient, remainder = divmod(known, q)
                    if not remainder:
                        alternatives.append((1 + (0 if quotient in constants else price(quotient)),
                                             q, "/", base * known, quotient, quotient))
            _, q, operation, left, right, coefficient = min(alternatives)
            output = q * base
            if output not in recipe and output not in puzzle.seeds:
                recipe[output] = operation, left, right
            if coefficient:
                constants.add(coefficient)
            normalized.add(q)
            pending.remove(q)
    for expression in plan:
        if expression.residual and expression.target not in puzzle.seeds:
            recipe.setdefault(expression.target,
                              ("+" if expression.residual > 0 else "-",
                               expression.quotient * expression.scale, abs(expression.residual)))
    return recipe


def useful_anchors(puzzle: Puzzle, scaffold: Graph, wanted: set[int], quota: int) -> tuple[int, ...]:
    uses = Counter(child for _, left, right in scaffold.values() for child in {left, right})

    def ranking(value):
        evidence = 0
        for target in wanted:
            if value > 1 and target % value == 0 and target // value <= 4096:
                evidence += 11
            difference = abs(value - target)
            if difference <= 512:
                evidence += 17
            elif difference <= 3 * min(value, target) // 1000:
                evidence += 5
        return evidence + min(9, uses[value]) * 2 + (3 if value <= 4096 else 0)

    quota = min(quota, puzzle.registers - len(puzzle.seeds))
    return tuple(sorted(scaffold, key=lambda value: (-ranking(value), value.bit_length(), value))[:quota])


def make_model(puzzle: Puzzle, incumbent: Program, plan: tuple[Expression, ...], index: int,
               lift: bool, retained: bool, anchor_quota: int) -> Model:
    explicitly_modeled = {expression.target for expression in plan}
    kept = set(puzzle.targets) - explicitly_modeled
    motif = lifted_motif(puzzle, plan, lift)
    scaffold = (cut_dependencies(puzzle, first_recipes(puzzle, incumbent), explicitly_modeled)
                if retained else {})
    seeds = set(puzzle.seeds)
    known = seeds.copy()
    independent = {}
    for value, recipe in scaffold.items():
        if recipe[1] in known and recipe[2] in known:
            known.add(value)
            independent[value] = recipe
    frontier = {child for edge in motif.values() for child in edge[1:]} - motif.keys() - known
    if not retained:
        frontier.update(kept - motif.keys() - known)
    reusable = useful_anchors(puzzle, independent, frontier, anchor_quota) if retained else ()
    reduced = Puzzle(f"{puzzle.id}_model{index}", puzzle.seeds + reusable,
                     tuple(sorted(frontier)), puzzle.limit, puzzle.registers)
    return Model(puzzle, reduced, scaffold, independent, motif)


def expand_program(model: Model, program: Program, scheduling: int) -> Program | None:
    graph = model.scaffold | first_recipes(model.reduced, program) | model.motif | model.independent
    try:
        return compile_graph(model.puzzle, graph, recompute=True, schedule_width=scheduling)
    except (KeyError, ValueError):
        # Overlapping numeric identities can create a cyclic proposed graph.
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("puzzles", type=Path)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--pilot", type=int, default=60)
    parser.add_argument("--residuals", type=int, default=44)
    parser.add_argument("--plans", type=int, default=5)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=12)
    parser.add_argument("--variants", type=int, nargs="+", default=[13, 19])
    parser.add_argument("--schedule-width", type=int, default=12)
    parser.add_argument("--retained", action="store_true",
                        help="jointly re-solve the latent group with unaffected target work fixed")
    parser.add_argument("--lift", action="store_true",
                        help="generate related scaled products with a shared arithmetic ladder")
    parser.add_argument("--differences", action="store_true",
                        help="also infer common unknown residues from target differences")
    parser.add_argument("--continued", action="store_true",
                        help="infer scale candidates from large-coefficient rational coincidences")
    parser.add_argument("--focus", choices=("even", "structural"), default="even")
    parser.add_argument("--anchors", type=int, default=18)
    args = parser.parse_args()
    if (args.pilot < 0 or min(args.residuals, args.plans, args.batch_size, args.workers) < 1
            or min(args.schedule_width, args.anchors) < 0):
        parser.error("invalid portfolio size, worker count, or sample size")
    puzzles = read_puzzles(args.puzzles)
    base = read_submission(args.baseline)
    best = base.copy()
    start_score = score(puzzles, base)
    # Focus on cases whose target spread suggests structured generation.
    selection = [puzzle for puzzle in puzzles if puzzle.limit > 1024 and not independent_shape(puzzle)]
    selection.sort(key=lambda p: len(base[p.id]), reverse=True)
    if args.focus == "structural":
        selection.sort(key=structural_strength, reverse=True)
        if args.pilot:
            selection = selection[:args.pilot]
    elif args.pilot:
        selection = selection[::max(1, len(selection) // args.pilot)][:args.pilot]
    executable = prepare()
    start = perf_counter()
    model_count = 0
    for index in range(0, len(selection), args.batch_size):
        batch = selection[index:index + args.batch_size]
        models = {}
        for puzzle in batch:
            groups = choose_groups(puzzle, base[puzzle.id], args.residuals, args.plans * 2,
                                   args.differences, args.continued)
            for offset, plan in enumerate(make_plans(groups, args.plans)):
                model = make_model(puzzle, base[puzzle.id], plan, offset, args.lift,
                                   args.retained, args.anchors)
                models[model.reduced.id] = model
        model_count += len(models)
        for variant in args.variants:
            if not models:
                continue
            programs, _ = find_programs([item.reduced for item in models.values()],
                                         variant, 8, 2, args.workers, executable,
                                         schedule_width=0)
            for identifier, program in programs.items():
                model = models[identifier]
                puzzle = model.puzzle
                constructed = expand_program(model, program, args.schedule_width)
                if constructed is not None and len(constructed) < len(best[puzzle.id]):
                    check(puzzle, constructed)
                    best[puzzle.id] = constructed
        total = write_submission(args.output, puzzles, best)
        print(f"{index + len(batch)}/{len(selection)}, {model_count} models, {total} valid instructions",
              flush=True)
    total = write_submission(args.output, puzzles, best)
    improved = sum(len(best[key]) < len(base[key]) for key in best)
    print(f"total {total}, saved {start_score - total} in {improved} puzzles, {perf_counter()-start:.1f}s")


if __name__ == "__main__":
    main()
