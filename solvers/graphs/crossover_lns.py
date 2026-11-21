"""Search exact target neighborhoods using attributed arithmetic recipe donors."""

import argparse
import heapq
import json
import random
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from itertools import combinations_with_replacement
from pathlib import Path

from elf import Puzzle, Program, read_puzzles, read_submission, score, sha256, write_submission
from graph import Graph, Recipe, active_graph, compile_graph, first_recipes, recipes_from

DEFAULT_LIBRARIES = Path(__file__).resolve().parents[2] / "work/crossover/deps"


def load_solver():
    if DEFAULT_LIBRARIES.is_dir() and str(DEFAULT_LIBRARIES) not in sys.path:
        # A local optional installation avoids changes to the user's Python.
        sys.path.insert(0, str(DEFAULT_LIBRARIES))
    from ortools.sat.python import cp_model
    return cp_model


def target_neighborhoods(puzzle: Puzzle, incumbent: Graph, donors, count: int, seed: int):
    targets = sorted(set(puzzle.targets) - set(puzzle.seeds))
    closures = {value: set(active_graph(puzzle, incumbent, (value,))) for value in targets}
    owners = Counter(node for closure in closures.values() for node in closure)
    donor_sizes = {}
    for target, closure in closures.items():
        outside = incumbent.keys() - {value for value in closure if owners[value] == 1}
        lengths = []
        for donor in donors:
            if target in donor:
                path = active_graph(puzzle, donor, (target,))
                lengths.append(len(path.keys() - outside))
        donor_sizes[target] = min(lengths, default=len(closure))
    rng = random.Random(seed)
    urgency = {}
    for target in targets:
        unique = sum(owners[value] == 1 for value in closures[target])
        urgency[target] = unique + max(0, unique - donor_sizes[target]) + 0.1 * rng.random()
    ordered = sorted(targets, key=lambda value: -urgency[value])
    seen = set()

    # Single expensive targets find simple wins. The larger blocks can trade
    # several locally neutral recipe changes for a globally useful helper.
    singletons = max(1, count // 3)
    for index in range(count):
        width = 1 if index < singletons else (3, 5, 2, 7, 4, 9, 6)[
            (index - singletons) % 7]
        center = ordered[index % len(ordered)]
        block = {center}
        union = closures[center].copy()
        while len(block) < min(len(targets), width):
            available = [target for target in targets if target not in block]
            choice = max(available, key=lambda target: (
                sum(1 / owners[value] for value in closures[target] & union)
                + 0.2 * urgency[target] + 0.08 * rng.random()))
            block.add(choice)
            union.update(closures[choice])
        frozen_targets = set(targets) - block
        frozen = set().union(*(closures[t] for t in frozen_targets))
        wanted = tuple(sorted(block - frozen))
        signature = frozenset(wanted), frozenset(frozen)
        if wanted and signature not in seen:
            seen.add(signature)
            yield wanted, frozen, set()


def helper_neighborhoods(puzzle: Puzzle, incumbent: Graph, count: int, seed: int):
    targets = set(puzzle.targets) - set(puzzle.seeds)
    consumers = defaultdict(set)
    for output, (_, left, right) in incumbent.items():
        for source in {left, right}:
            consumers[source].add(output)
    rng = random.Random(seed)

    def neighborhood(roots):
        removed = set(roots)
        frontier = list(roots)
        while frontier and len(removed) < 48:
            value = frontier.pop()
            for source in set(incumbent[value][1:]) - removed - targets:
                if source in incumbent and consumers[source] <= removed:
                    removed.add(source)
                    frontier.append(source)
        forbidden = set()
        frontier = list(roots)
        while frontier:
            for value in consumers[frontier.pop()] - forbidden - removed:
                forbidden.add(value)
                frontier.append(value)
        frozen = incumbent.keys() - removed
        return tuple(sorted(roots)), frozen, forbidden

    candidates = []
    seen = set()
    for value in incumbent.keys() - targets:
        alternatives = [(value,)]
        if 2 <= len(consumers[value]) <= 4:
            alternatives.append(tuple(sorted(consumers[value])))
        for roots in alternatives:
            if roots in seen:
                continue
            seen.add(roots)
            wanted, frozen, forbidden = neighborhood(roots)
            freed = len(incumbent) - len(frozen)
            if freed <= len(roots) + 1:
                continue
            weight = (freed - len(roots)) * (1 + 0.12 * min(4, len(consumers[value]))) + rng.random()
            candidates.append((weight, value, wanted, frozen, forbidden))
    candidates.sort(reverse=True)
    for _, _, wanted, frozen, forbidden in candidates[:count]:
        yield wanted, frozen, forbidden


def tree_costs(available: set[int], bank: dict[int, set[Recipe]]) -> dict[int, int]:
    neighbors = defaultdict(list)
    for output, recipes in bank.items():
        for _, left, right in recipes:
            neighbors[left].append((output, right, left == right))
            if right != left:
                neighbors[right].append((output, left, False))
    todo = [(0, value) for value in available]
    heapq.heapify(todo)
    costs = {}
    while todo:
        cost, value = heapq.heappop(todo)
        if value in costs:
            continue
        costs[value] = cost
        for output, operand, same in neighbors[value]:
            if operand in costs and output not in costs:
                heapq.heappush(todo, (1 + cost + (0 if same else costs[operand]), output))
    return costs


def inverses(target, anchor):
    quotient, remainder = divmod(target, anchor)
    inverse, inverse_remainder = divmod(anchor, target)
    return (
        (target - anchor, "+", False), (anchor - target, "-", True),
        (target + anchor, "-", False), (quotient if not remainder else 0, "*", False),
        (target * anchor, "/", False), (inverse if not inverse_remainder else 0, "/", True),
    )


def bridge_recipes(values, pivots, costs, limit, bank, capacity, deep_count):
    """Add new two-operation bridges joining values exposed by different traces."""
    ranked = sorted(values, key=lambda value: (costs[value], value.bit_length(), value))
    anchors = set(ranked[:capacity // 3])
    by_size = defaultdict(list)
    for value in ranked:
        if value not in anchors:
            by_size[(value.bit_length() + 2) // 3].append(value)
    radius = 0
    while len(anchors) < min(capacity, len(ranked)):
        for group in by_size.values():
            if radius < len(group):
                anchors.add(group[radius])
                if len(anchors) == capacity:
                    break
        radius += 1
    pair_index = defaultdict(list)
    for first, second in combinations_with_replacement(sorted(anchors), 2):
        quotient, remainder = divmod(second, first)
        pairs = ((first + second, "+", first, second),
                 (second - first, "-", second, first),
                 (first * second, "*", first, second),
                 (quotient if remainder == 0 else 0, "/", second, first))
        for value, op, left, right in pairs:
            cost = 1 + sum(costs[node] for node in {left, right})
            if 1 <= value <= limit and value not in (left, right) and cost < costs.get(value, 1000):
                recipe = (op, left, right)
                if len(pair_index[value]) < 3 and recipe not in pair_index[value]:
                    pair_index[value].append(recipe)
    bridge_costs = {value: min(1 + sum(costs[node] for node in set(recipe[1:])) for recipe in options)
                    for value, options in pair_index.items()}
    fresh = tuple(value for value, cost in bridge_costs.items() if cost <= 2)
    for index, output in enumerate(pivots):
        joins = {}
        for anchor in values:
            if anchor == output:
                continue
            for other, op, anchor_first in inverses(output, anchor):
                if other == output or (other not in values and other not in pair_index):
                    continue
                left, right = (anchor, other) if anchor_first else (other, anchor)
                if op in "+*" and left > right:
                    left, right = right, left
                recipe = (op, left, right)
                estimate = 1 + sum(costs.get(value, 1000) for value in {left, right})
                if other in pair_index:
                    helper = pair_index[other][0]
                    estimate = min(estimate, 2 + sum(costs[value]
                                                    for value in (set(helper[1:]) | {anchor})))
                joins[recipe] = estimate
        if index < deep_count:
            for anchor in fresh:
                if anchor == output:
                    continue
                for other, op, anchor_first in inverses(output, anchor):
                    if other == output or other not in pair_index:
                        continue
                    left, right = (anchor, other) if anchor_first else (other, anchor)
                    if op in "+*" and left > right:
                        left, right = right, left
                    recipe = (op, left, right)
                    estimate = 1 + sum(min(bridge_costs[n], costs.get(n, 1000))
                                       for n in {left, right})
                    joins[recipe] = min(joins.get(recipe, 1000), estimate)
        for recipe in sorted(joins, key=lambda recipe: (joins[recipe], recipe))[:18]:
            bank[output].add(recipe)
            for value in set(recipe[1:]) & pair_index.keys():
                bank[value].update(pair_index[value])


def build_model_bank(puzzle, bank, incumbent, wanted, frozen, forbidden, bridge_capacity,
                     maximum_recipes, deep_bridge):
    available = (frozen - forbidden) | set(puzzle.seeds)
    if bridge_capacity:
        original_costs = tree_costs(available, bank)
        mutable = incumbent.keys() - frozen
        pivots = sorted(mutable - set(wanted),
                        key=lambda value: (-original_costs.get(value, 0), value))[:12]
        bridge_recipes(set(original_costs), (*wanted, *pivots), original_costs,
                       puzzle.limit, bank, bridge_capacity, len(wanted) if deep_bridge else 0)
    costs = tree_costs(available, bank)
    selected = defaultdict(set)

    def add(output, recipe):
        selected[output].add(recipe)
        for operand in set(recipe[1:]) - available:
            if operand not in visited:
                heapq.heappush(pending, (costs[operand], operand))

    # Retain the entire incumbent cut as a feasible reference for the model.
    visited = set(available)
    pending = [(costs[value], value) for value in wanted]
    heapq.heapify(pending)
    for output in incumbent.keys() - frozen:
        add(output, incumbent[output])
    recipe_count = sum(map(len, selected.values()))
    while pending and recipe_count < maximum_recipes:
        _, output = heapq.heappop(pending)
        if output in visited:
            continue
        visited.add(output)
        choices = sorted(
            (recipe for recipe in bank[output] if all(child in costs for child in recipe[1:])),
            key=lambda recipe: (sum(costs[child] for child in set(recipe[1:])), recipe),
        )
        for recipe in choices[:10]:
            if recipe not in selected[output]:
                add(output, recipe)
                recipe_count += 1
    # Remove only recipes whose operands fell outside the closed size cutoff.
    while True:
        valid = set(selected) | available
        reduced = {value: {recipe for recipe in options if set(recipe[1:]) <= valid}
                   for value, options in selected.items()}
        reduced = {value: options for value, options in reduced.items() if options}
        if len(reduced) == len(selected):
            return reduced, available
        selected = reduced


def cp_select(puzzle, bank, available, frozen_graph, wanted, incumbent, seconds, schedule, stats):
    cp = load_solver()
    # The incumbent may rematerialize a value. In that case compare against
    # its true instruction count, rather than just the number of DAG nodes.
    ceiling = len(incumbent) - len(frozen_graph) - 1
    if ceiling < len(wanted):
        stats["lower_bound_skipped"] += 1
        return incumbent
    model = cp.CpModel()
    present = {value: model.new_bool_var(f"value_{i}") for i, value in enumerate(sorted(bank))}
    time_index = {value: model.new_int_var(0, ceiling, f"order_{i}")
                  for i, value in enumerate(sorted(bank))}
    recipes = []
    for value in sorted(bank):
        choices = []
        for recipe in sorted(bank[value]):
            use = model.new_bool_var(f"recipe_{len(recipes)}")
            recipes.append((value, recipe, use))
            choices.append(use)
            for operand in set(recipe[1:]) - available:
                model.add_implication(use, present[operand])
                model.add(time_index[operand] < time_index[value]).only_enforce_if(use)
        model.add(sum(choices) == present[value])
    for value in wanted:
        model.add(present[value] == 1)
    size = sum(present.values())
    model.add(size <= ceiling)
    model.minimize(size)
    started = time.monotonic()
    best = incumbent
    for _ in range(4):
        remaining = seconds - (time.monotonic() - started)
        if remaining <= 0:
            break
        solver = cp.CpSolver()
        solver.parameters.num_search_workers = 1
        solver.parameters.max_time_in_seconds = remaining
        status = solver.solve(model)
        stats[solver.status_name(status)] += 1
        if status not in (cp.FEASIBLE, cp.OPTIMAL):
            break
        chosen = [(value, recipe, use) for value, recipe, use in recipes if solver.value(use)]
        graph = frozen_graph | {value: recipe for value, recipe, _ in chosen}
        program = compile_graph(puzzle, graph, recompute=True, schedule_width=schedule)
        if program is None:
            stats["unscheduled"] += 1
        if program is not None and len(program) < len(best):
            best = program
            if len(best) == len(frozen_graph) + len(chosen):
                break
        model.add(sum(use for _, _, use in chosen) <= len(chosen) - 1)
    return best


def fit_window(puzzle, program, donors, count, seconds, capacity, maximum_recipes, schedule, seed,
               mode="targets", deep_bridge=False, stats=None):
    if stats is None:
        stats = Counter()
    incumbent = active_graph(puzzle, first_recipes(puzzle, program))
    in_scope = set(puzzle.targets) - set(puzzle.seeds)
    if not in_scope or len(program) <= len(in_scope):
        return program
    donor_graphs = []
    donor_bank = defaultdict(set)
    for active in (program, *donors):
        if active != program:
            donor_graphs.append(first_recipes(puzzle, active))
        for value, recipes in recipes_from(puzzle, active).items():
            donor_bank[value].update(recipes)
    neighborhoods = []
    if mode in ("targets", "mixed"):
        neighborhoods.extend(target_neighborhoods(puzzle, incumbent, donor_graphs, count, seed))
    if mode in ("helpers", "mixed"):
        neighborhoods.extend(helper_neighborhoods(puzzle, incumbent, count, seed))
    best = program
    for wanted, frozen, forbidden in neighborhoods:
        # Multiple roots can be linked through a frozen consumer. This
        # restricted model cannot borrow that consumer as a free value
        # while also guaranteeing acyclicity.
        if any(set(incumbent[value][1:]) & forbidden for value in incumbent.keys() - frozen):
            stats["linked_roots_skipped"] += 1
            continue
        base_graph = {value: incumbent[value] for value in incumbent if value in frozen}
        local = defaultdict(set, {
            value: {recipe for recipe in choices if not (set(recipe[1:]) & forbidden)}
            for value, choices in donor_bank.items() if value not in forbidden
        })
        cut, available = build_model_bank(puzzle, local, incumbent, wanted, frozen, forbidden,
                                          capacity, maximum_recipes, deep_bridge)
        candidate = cp_select(puzzle, cut, available, base_graph, wanted, best, seconds, schedule, stats)
        if len(candidate) < len(best):
            best = candidate
    return best


def run_puzzle(task):
    puzzle, program, donors, options = task
    stats = Counter()
    result = fit_window(puzzle, program, donors, *options, stats=stats)
    return puzzle.id, result, stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("puzzles", type=Path)
    parser.add_argument("incumbent", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--donor", type=Path, nargs="+", required=True)
    parser.add_argument("--puzzles-limit", type=int, default=0)
    parser.add_argument("--focus", choices=("expensive", "even", "diverse"), default="even")
    parser.add_argument("--windows", type=int, default=8)
    parser.add_argument("--mode", choices=("targets", "helpers", "mixed"), default="targets")
    parser.add_argument("--seconds", type=float, default=0.22)
    parser.add_argument("--bridge-capacity", type=int, default=0)
    parser.add_argument("--deep-bridge", action="store_true")
    parser.add_argument("--maximum-recipes", type=int, default=1800)
    parser.add_argument("--schedule", type=int, default=3)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    load_solver()
    puzzles = read_puzzles(args.puzzles)
    def load(path):
        digest = sha256(path)
        programs = read_submission(path)
        if digest != sha256(path):
            raise RuntimeError(f"reference changed while reading: {path}")
        return path, programs, digest

    _, incumbent, incumbent_digest = load(args.incumbent)
    donors = [load(path) for path in args.donor]
    score(puzzles, incumbent)
    for _, program, _ in donors:
        score(puzzles, program)
    selected = puzzles
    if args.puzzles_limit:
        if args.focus == "diverse":
            selected = sorted(puzzles, key=lambda p: -len(set().union(
                *(first_recipes(p, program[p.id]).keys() for _, program, _ in donors))))
        elif args.focus == "expensive":
            selected = sorted(puzzles, key=lambda p: -len(incumbent[p.id]))
        else:
            selected = selected[::max(1, len(selected) // args.puzzles_limit)]
        selected = selected[:args.puzzles_limit]
    settings = (args.windows, args.seconds, args.bridge_capacity, args.maximum_recipes,
                args.schedule, args.seed, args.mode, args.deep_bridge)
    started = time.monotonic()
    result = incumbent.copy()
    tasks = ((p, incumbent[p.id], tuple(program[p.id] for _, program, _ in donors), settings)
             for p in selected)
    changes = []
    statuses = Counter()
    previous = score(puzzles, incumbent)
    options = vars(args)
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        for index, (key, candidate, stats) in enumerate(pool.map(run_puzzle, tasks, chunksize=1), 1):
            statuses.update(stats)
            if len(candidate) < len(incumbent[key]):
                changes.append((key, len(incumbent[key]), len(candidate)))
                result[key] = candidate
            if index % 20 == 0:
                savings = sum(old - new for _, old, new in changes)
                print(index, len(changes), savings, dict(statuses),
                      round(time.monotonic() - started, 1), flush=True)
    new = write_submission(args.output, puzzles, result)
    manifest = {
        "input": {"incumbent": str(args.incumbent.resolve()), "sha256": incumbent_digest},
        "donors": [{"path": str(path.resolve()), "sha256": digest} for path, _, digest in donors],
        "output": {"path": str(args.output.resolve()), "sha256": sha256(args.output)},
        "selected": len(selected), "previous": previous, "final": new, "changes": changes,
        "settings": options, "status_counts": statuses, "seconds": round(time.monotonic() - started, 3),
    }
    args.output.with_suffix(".json").write_text(json.dumps(manifest, default=str, indent=2) + "\n",
                                                encoding="utf-8")
    print(f"{previous} -> {new} on {len(selected)} trials, {len(changes)} rows improved")


if __name__ == "__main__":
    main()
