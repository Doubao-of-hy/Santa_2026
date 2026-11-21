"""Reduce a program by combining alternative recipes across solution graphs."""

import argparse
import heapq
import os
import random
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from elf import read_puzzles, read_submission, score, write_submission
from graph import active_graph, compile_graph, first_recipes, recipes_from


def make_bank(puzzle, candidates, joins):
    bank = defaultdict(set)
    for program in candidates:
        for value, recipes in recipes_from(puzzle, program).items():
            bank[value].update(recipes)
    if not joins:
        return bank
    seeds = set(puzzle.seeds)
    values = set(bank) | seeds
    common = Counter(value for program in candidates
                     for value in first_recipes(puzzle, program))
    anchors = sorted(seeds | set(value for value, _ in common.most_common(160)))
    for output, recipes in bank.items():
        for anchor in anchors:
            addend = output - anchor
            if addend in values:
                recipes.add(("+", min(anchor, addend), max(anchor, addend)))
            higher = output + anchor
            if higher in values:
                recipes.add(("-", higher, anchor))
            if output % anchor == 0:
                factor = output // anchor
                if factor in values and factor != output and anchor != output:
                    recipes.add(("*", min(anchor, factor), max(anchor, factor)))
            multiple = output * anchor
            if multiple in values and multiple != output and anchor != output:
                recipes.add(("/", multiple, anchor))
    return bank


def tree_recipes(puzzle, bank):
    waiting = defaultdict(list)
    for value, choices in bank.items():
        for recipe in sorted(choices):
            _, left, right = recipe
            waiting[left].append((value, recipe))
            if right != left:
                waiting[right].append((value, recipe))
    queue = [(0, value, ("+", 0, 0)) for value in set(puzzle.seeds)]
    heapq.heapify(queue)
    costs, recipes = {}, {}
    while queue:
        cost, value, recipe = heapq.heappop(queue)
        if value in costs:
            continue
        costs[value] = cost
        if cost:
            recipes[value] = recipe
        for output, choice in waiting[value]:
            _, left, right = choice
            other = right if value == left else left
            if output not in costs and other in costs:
                total = cost + 1 + (costs[other] if value != other else 0)
                heapq.heappush(queue, (total, output, choice))
    return recipes


class State:
    def __init__(self, puzzle, recipes):
        self.seeds = set(puzzle.seeds)
        self.recipes = recipes.copy()
        active = active_graph(puzzle, self.recipes)
        self.counts = Counter(target for target in set(puzzle.targets) if target not in self.seeds)
        for _, left, right in active.values():
            self.counts.update({left, right} - self.seeds)

    def safe(self, output, replacement):
        checking = {output}
        done = set(self.seeds)
        stack = [(replacement[1], False), (replacement[2], False)]
        while stack:
            value, ready = stack.pop()
            if value in done:
                continue
            if ready:
                done.add(value)
                checking.remove(value)
                continue
            if value in checking or value not in self.recipes:
                return False
            checking.add(value)
            _, left, right = self.recipes[value]
            stack.extend(((value, True), (left, False), (right, False)))
        return True

    def shift(self, recipe, delta):
        pending = [*set(recipe[1:])]
        while pending:
            value = pending.pop()
            if value in self.seeds:
                continue
            before = self.counts.get(value, 0)
            after = before + delta
            if after:
                self.counts[value] = after
            else:
                del self.counts[value]
            if before == 0 or after == 0:
                pending.extend(set(self.recipes[value][1:]))

    def replace(self, output, recipe):
        self.shift(self.recipes[output], -1)
        self.shift(recipe, 1)
        self.recipes[output] = recipe


def optimize(puzzle, candidates, joins=False, trials=3, passes=4):
    best = min(candidates, key=len)
    bank = make_bank(puzzle, candidates, joins)
    default = tree_recipes(puzzle, bank)
    for trial in range(trials):
        if trial < len(candidates):
            base = candidates[trial]
            initial = default | first_recipes(puzzle, base)
        else:
            initial = default
        state = State(puzzle, initial)
        rng = random.Random(trial)
        for pass_number in range(passes):
            changed = 0
            neutral = trial > 0 and pass_number % 2 == 0
            outputs = sorted(state.counts)
            rng.shuffle(outputs)
            for output in outputs:
                if output not in state.counts:
                    continue
                choices = bank[output]
                if len(choices) < 2:
                    continue
                start = state.recipes[output]
                winner = start
                best_count = len(state.counts)
                for candidate in sorted(choices):
                    if candidate == start or not state.safe(output, candidate):
                        continue
                    state.replace(output, candidate)
                    cost = len(state.counts)
                    if cost < best_count or (cost == best_count and neutral and rng.random() < 0.2):
                        winner, best_count = candidate, cost
                    state.replace(output, start)
                if winner != start:
                    state.replace(output, winner)
                    changed += 1
            if len(state.counts) < len(best):
                program = compile_graph(puzzle, state.recipes, recompute=True)
                if program is not None and len(program) < len(best):
                    best = program
            if not changed and not neutral:
                break
    return best


def exact_union(puzzle, candidates, incumbent, seconds, joins):
    """Search a restricted recipe bank globally, adding cuts for invalid cycles."""
    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import coo_array

    start = time.monotonic()
    bank = make_bank(puzzle, (*candidates, incumbent), joins)
    seeds = set(puzzle.seeds)
    required = set(puzzle.targets) - seeds
    recipes = [(value, recipe) for value in sorted(bank) for recipe in sorted(bank[value])]
    by_value = defaultdict(list)
    for index, (value, _) in enumerate(recipes):
        by_value[value].append(index)
    if len(recipes) > 15000 or len(incumbent) <= len(required):
        return incumbent
    rows, columns, entries, lower, upper = [], [], [], [], []

    def constrain(terms, minimum, maximum):
        for index, coefficient in terms:
            rows.append(len(lower))
            columns.append(index)
            entries.append(coefficient)
        lower.append(minimum)
        upper.append(maximum)

    for value, alternatives in by_value.items():
        constrain(((index, 1) for index in alternatives), int(value in required), 1)
    for index, (_, (_, left, right)) in enumerate(recipes):
        for operand in {left, right} - seeds:
            constrain([(index, 1)] + [(choice, -1) for choice in by_value[operand]],
                      -np.inf, 0)
    constrain(((index, 1) for index in range(len(recipes))), len(required), len(incumbent) - 1)

    def find_cycles(selected):
        stack, in_stack, finished, cycles = [], {}, set(), set()

        def visit(value):
            if value in seeds or value in finished:
                return
            if value in in_stack:
                cycles.add(tuple(sorted(selected[node] for node in stack[in_stack[value]:])))
                return
            in_stack[value] = len(stack)
            stack.append(value)
            _, (_, left, right) = recipes[selected[value]]
            for operand in {left, right}:
                visit(operand)
            stack.pop()
            del in_stack[value]
            finished.add(value)

        for target in sorted(required):
            visit(target)
        return cycles

    dimension = len(recipes)
    objective = np.ones(dimension)
    integral = np.ones(dimension)
    bounds = Bounds(0, 1)
    while (remaining := seconds - (time.monotonic() - start)) > 0.02:
        matrix = coo_array((entries, (rows, columns)), shape=(len(lower), dimension)).tocsc()
        result = milp(objective, integrality=integral, bounds=bounds,
                      constraints=LinearConstraint(matrix, lower, upper),
                      options={"time_limit": remaining})
        if result.x is None:
            break
        selected = {recipes[index][0]: index for index, yes in enumerate(result.x) if yes > 0.5}
        cycles = find_cycles(selected)
        if not cycles:
            program = compile_graph(puzzle, {value: recipes[index][1]
                                             for value, index in selected.items()}, recompute=True)
            if program is not None and len(program) < len(incumbent):
                return program
            break
        for cycle in sorted(cycles):
            constrain(((index, 1) for index in cycle), -np.inf, len(cycle) - 1)
    return incumbent


def work(task):
    puzzle, programs, joins, trials, passes, global_seconds = task
    model = tuple(sorted(set(programs), key=lambda p: (len(p), p)))
    best = optimize(puzzle, model, joins, trials, passes)
    if global_seconds > 0:
        best = exact_union(puzzle, model, best, global_seconds, joins)
    return puzzle.id, best, len(model[0]) - len(best)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("puzzles", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("candidates", nargs="+", type=Path)
    parser.add_argument("--joins", action="store_true")
    parser.add_argument("--jobs", type=int, default=min(6, os.cpu_count() or 1))
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--passes", type=int, default=4)
    parser.add_argument("--pilot", type=int, default=0)
    parser.add_argument("--global-seconds", type=float, default=0.0)
    args = parser.parse_args()
    start = time.monotonic()
    puzzles = read_puzzles(args.puzzles)
    files = [read_submission(path) for path in args.candidates]
    for file in files:
        score(puzzles, file)
    selected = puzzles[::max(1, len(puzzles) // args.pilot)][:args.pilot] if args.pilot else puzzles
    tasks = ((puzzle, tuple(file[puzzle.id] for file in files), args.joins, args.trials, args.passes,
              args.global_seconds)
             for puzzle in selected)
    best = {p.id: min((file[p.id] for file in files), key=len) for p in puzzles}
    gains = 0
    improvements = 0
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        for identifier, program, saved in pool.map(work, tasks, chunksize=2):
            best[identifier] = program
            gains += saved
            improvements += saved > 0
    total = write_submission(args.output, puzzles, best)
    print(f"{len(selected)} searched, {improvements} improved, {gains} saved beyond portfolio, "
          f"{total} total, {time.monotonic() - start:.1f}s")


if __name__ == "__main__":
    main()
