"""Construct candidate programs from starting values and targets."""

from itertools import combinations_with_replacement

from elf import Program, Puzzle, check
from graph import Graph, Recipe, compile_graph


def one_step(values: set[int], target: int, limit: int):
    """Enumerate all single instructions for target with inputs in values."""
    for value in values:
        complement = target - value
        if complement >= value and complement in values:
            yield "+", value, complement
        complement = target + value
        if complement <= limit and complement in values:
            yield "-", complement, value
        complement, remainder = divmod(target, value)
        if not remainder and complement >= value and complement in values:
            yield "*", value, complement
        multiple = target * value
        if multiple <= limit and multiple in values:
            yield "/", multiple, value


def seed_dictionary(puzzle: Puzzle) -> Graph:
    seeds = set(puzzle.seeds)
    recipes = {}
    for left, right in combinations_with_replacement(sorted(seeds), 2):
        candidates = [(left + right, "+", left, right), (right - left, "-", right, left),
                      (left * right, "*", left, right)]
        quotient, remainder = divmod(right, left)
        if not remainder:
            candidates.append((quotient, "/", right, left))
        for value, op, first, second in candidates:
            if 1 <= value <= puzzle.limit and value not in seeds:
                recipes.setdefault(value, (op, first, second))
    return recipes


class Constructor:
    def __init__(self, puzzle: Puzzle, base: int, balanced: bool, indirect: bool):
        self.puzzle = puzzle
        self.base = base
        self.balanced = balanced
        self.indirect = indirect
        self.known = set(puzzle.seeds)
        self.graph: Graph = {}
        self.dictionary = seed_dictionary(puzzle)
        self.cheap = self.known | self.dictionary.keys()

    def add(self, value: int, recipe: Recipe) -> None:
        if value not in self.known:
            self.graph[value] = recipe
            self.known.add(value)

    def direct(self, value: int) -> bool:
        if value in self.dictionary:
            self.add(value, self.dictionary[value])
            return True
        recipe = next(one_step(self.known, value, self.puzzle.limit), None)
        if recipe is not None:
            self.add(value, recipe)
            return True
        return False

    def constant(self, value: int) -> None:
        if value in self.known or self.direct(value):
            return
        if value == 1:
            first = self.puzzle.seeds[0]
            self.add(1, ("/", first, first))
            return
        quotient, remainder = divmod(value, 2)
        self.constant(quotient)
        self.add(2 * quotient, ("+", quotient, quotient))
        if remainder:
            self.constant(1)
            self.add(value, ("+", 2 * quotient, 1))

    def indirect_recipe(self, value: int) -> Recipe | None:
        available = self.cheap | self.known
        return min(one_step(available, value, self.puzzle.limit),
                   key=lambda r: len({r[1], r[2]} - self.known), default=None)

    def synthesize(self, value: int) -> None:
        if value in self.known or self.direct(value):
            return
        if self.indirect:
            best = self.indirect_recipe(value)
            if best is not None:
                for child in set(best[1:]) - self.known:
                    self.add(child, self.dictionary[child])
                self.add(value, best)
                return
        if value <= self.base:
            self.constant(value)
            return
        quotient, remainder = divmod(value, self.base)
        rounded = (quotient + 1) * self.base
        if self.balanced and remainder * 2 > self.base and rounded <= self.puzzle.limit:
            quotient += 1
            remainder -= self.base
        scaled = quotient * self.base
        self.synthesize(quotient)
        self.constant(self.base)
        if scaled not in self.known and not self.direct(scaled):
            self.add(scaled, ("*", self.base, quotient))
        if remainder:
            self.constant(abs(remainder))
            self.add(value, ("+" if remainder > 0 else "-", scaled, abs(remainder)))


def binary_stream(puzzle: Puzzle) -> Program | None:
    if set(puzzle.targets).issubset(puzzle.seeds):
        return ()
    if puzzle.registers < 2:
        return None
    instructions = []
    if 1 in puzzle.seeds:
        unit = puzzle.seeds.index(1)
    else:
        unit = 0
        instructions.append(("/", unit, unit, unit))
    work = 1 if unit == 0 else 0
    for target in sorted(set(puzzle.targets) - set(puzzle.seeds) - {1}):
        first = unit
        for digit in bin(target)[3:]:
            instructions.append(("+", first, first, work))
            if digit == "1":
                instructions.append(("+", work, unit, work))
            first = work
    return tuple(instructions)


def construct_candidates(puzzle: Puzzle, wide: bool = False) -> list[Program]:
    candidates = []
    fallback = binary_stream(puzzle)
    if fallback is not None and len(fallback) <= 4096:
        check(puzzle, fallback)
        candidates.append(fallback)
    bases = {3, 5, 8, 16, 31, 64, 127, 256, 1024}
    if wide:
        bases.update(range(2, 65))
        bases.update(value for value in puzzle.seeds if 2 <= value <= 2000)
    else:
        bases.update(value for value in puzzle.seeds if 2 <= value <= 128)
    targets = sorted(set(puzzle.targets))
    for index, base in enumerate(sorted(bases)):
        configs = [(False, True, targets), (True, True, targets[::-1])]
        if wide:
            configs.extend(((True, True, targets), (False, False, targets[::-1])))
        for balanced, indirect, order in configs:
            solver = Constructor(puzzle, base, balanced, indirect)
            for target in order:
                solver.synthesize(target)
            program = compile_graph(puzzle, solver.graph)
            if program is not None:
                candidates.append(program)
    return sorted(set(candidates), key=lambda p: (len(p), p))
