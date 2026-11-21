"""Construct arithmetic programs using exact factors and nearby products."""

from collections import Counter
from functools import lru_cache
from itertools import combinations_with_replacement
from math import isqrt

from solvers.construction.construct import Constructor, seed_dictionary
from elf import Program, Puzzle
from graph import Recipe, compile_graph


@lru_cache(maxsize=32768)
def splits(value: int) -> tuple[tuple[int, int], ...]:
    from sympy import factorint

    factors = factorint(value, limit=768)
    middle = isqrt(value)
    divisors = [1]
    for prime, exponent in factors.items():
        factor_values = []
        for power in range(1, exponent + 1):
            multiplier = int(prime) ** power
            factor_values.extend(x * multiplier for x in divisors if x * multiplier <= middle)
        divisors += factor_values
    return tuple((d, value // d) for d in divisors if d > 1)


class FactorConstructor(Constructor):
    def __init__(self, puzzle: Puzzle, base: int, indexed: bool):
        super().__init__(puzzle, base, balanced=True, indirect=True)
        self.changes: list[int] = []
        self.indexed = indexed
        self.committed = self.known.copy()
        self.stable_length = 0
        self.pairs: dict[int, Recipe] = {}
        if indexed:
            for first, second in combinations_with_replacement(sorted(self.cheap), 2):
                self.index_pair(first, second)

    def add(self, value: int, recipe: Recipe) -> None:
        if value not in self.known:
            super().add(value, recipe)
            self.changes.append(value)

    def index_pair(self, first, second):
        if first < second:
            first, second = second, first
        quotient, remainder = divmod(first, second)
        options = ((first + second, "+", second, first),
                   (first - second, "-", first, second),
                   (first * second, "*", second, first),
                   (quotient if not remainder else 0, "/", first, second))
        cost = (first not in self.committed) + (first != second and second not in self.committed)
        for value, op, left, right in options:
            if not 1 <= value <= self.puzzle.limit or value in self.committed or value in (left, right):
                continue
            prior = self.pairs.get(value)
            if prior is not None:
                _, a, b = prior
                prior_cost = (a not in self.committed) + (a != b and b not in self.committed)
                if prior_cost <= cost:
                    continue
            self.pairs[value] = op, left, right

    def commit(self):
        if not self.indexed:
            return
        added = self.changes[self.stable_length:]
        self.stable_length = len(self.changes)
        if not added:
            return
        self.committed.update(added)
        available = sorted(self.committed | self.cheap)
        for value in added:
            self.pairs.pop(value, None)
            for other in available:
                self.index_pair(value, other)

    def lookup(self, target: int, allow_atoms: bool) -> Recipe | None:
        known = self.known
        best = self.pairs.get(target)
        best_cost = 3
        if best is not None:
            _, left, right = best
            best_cost = (left not in known) + (left != right and right not in known)
            if best_cost == 0:
                return best
        for anchor in self.changes[self.stable_length:]:
            quotient, remainder = divmod(target, anchor)
            inverse, inverse_remainder = divmod(anchor, target)
            options = (
                (target - anchor, "+", False),
                (anchor - target, "-", True),
                (target + anchor, "-", False),
                (quotient if not remainder else 0, "*", False),
                (target * anchor, "/", False),
                (inverse if not inverse_remainder else 0, "/", True),
            )
            for other, op, anchor_first in options:
                if not 1 <= other <= self.puzzle.limit or other == target:
                    continue
                cost = 0 if other in known else 1 if allow_atoms and other in self.dictionary else 3
                if cost < best_cost:
                    left, right = (anchor, other) if anchor_first else (other, anchor)
                    best = op, left, right
                    best_cost = cost
                    if not cost:
                        return best
        return best if allow_atoms or best_cost == 0 else None

    def direct(self, value: int) -> bool:
        if not self.indexed:
            return super().direct(value)
        recipe = self.dictionary.get(value) or self.lookup(value, allow_atoms=False)
        if recipe is not None:
            self.add(value, recipe)
            return True
        return False

    def indirect_recipe(self, value: int) -> Recipe | None:
        if not self.indexed:
            return super().indirect_recipe(value)
        return self.lookup(value, allow_atoms=True)

    def keep_recipe(self, target, start):
        new_values = set(self.changes[start:])
        active = set()
        pending = [target]
        while pending:
            value = pending.pop()
            if value in new_values and value not in active:
                active.add(value)
                pending.extend(self.graph[value][1:])
        result = tuple((x, self.graph[x]) for x in self.changes[start:] if x in active)
        for value in new_values:
            self.known.remove(value)
            del self.graph[value]
        del self.changes[start:]
        return result

    def make_operand(self, value: int) -> None:
        if value in self.known or self.direct(value):
            return
        if value <= self.base:
            self.constant(value)
            return
        start = len(self.changes)
        self.synthesize(value)
        best = self.keep_recipe(value, start)
        alternatives = sorted(splits(value), key=lambda pair: (
            sum(x.bit_length() for x in pair if x not in self.known),
            sum(x not in self.known for x in pair),
            -pair[0],
        ))
        for first, second in alternatives[:3]:
            self.synthesize(first)
            self.synthesize(second)
            self.add(value, ("*", first, second))
            candidate = self.keep_recipe(value, start)
            if len(candidate) < len(best):
                best = candidate
        for output, recipe in best:
            self.add(output, recipe)

    def pick(
        self, target: int, proposals: list[tuple[int, int, int]], support: Counter, width: int,
        factor_operands: bool,
    ) -> None:
        if target in self.known or self.direct(target):
            self.commit()
            return
        start = len(self.changes)
        self.synthesize(target)
        best = self.keep_recipe(target, start)
        best_cost = len(best)

        def operand_cost(value):
            if value in self.known:
                return 0
            if value in self.dictionary:
                return 1
            # Share expensive factors from a shape like d*q1, d*q2, ...
            score = max(1, value.bit_length() * 1.55 / self.base.bit_length())
            return score / (1 + min(3, support[value] - 1) * 0.18) if support[value] >= 2 else score

        def rank(proposal):
            first, second, residue = proposal
            return (operand_cost(first) + operand_cost(second)
                    + (operand_cost(abs(residue)) + 0.2 if residue else 0))

        make_leaf = self.make_operand if factor_operands else self.synthesize
        for first, second, delta in sorted(proposals, key=rank)[:width]:
            product = target - delta
            if product not in self.known:
                make_leaf(first)
                make_leaf(second)
                self.add(product, ("*", first, second))
            if delta:
                self.constant(abs(delta))
                self.add(target, ("+" if delta > 0 else "-", product, abs(delta)))
            new = self.keep_recipe(target, start)
            discount = 0.25 * sum(
                min(4, support[value] - 1)
                for value in {first, second} if value not in self.known and support[value] > 1
            )
            cost = len(new) - discount
            if cost < best_cost:
                best, best_cost = new, cost
        for value, recipe in best:
            self.add(value, recipe)
        self.commit()


def proposals_for(puzzle: Puzzle, radius: int):
    targets = sorted(set(puzzle.targets) - set(puzzle.seeds))
    proposals = {}
    support: Counter = Counter()
    residues = (0,) + tuple(i for n in range(1, radius + 1) for i in (n, -n))
    for target in targets:
        candidates = []
        exact = splits(target)
        support.update({value for pair in exact for value in pair if value > 8})
        for residue in residues:
            product = target - residue
            if 4 <= product <= puzzle.limit:
                candidates.extend((a, b, residue) for a, b in (exact if not residue else splits(product)))
        proposals[target] = candidates
    return proposals, support


def cheap_layers(puzzle: Puzzle):
    seeds = set(puzzle.seeds)
    first_layer = set(seed_dictionary(puzzle))
    known = seeds | first_layer
    second_layer = set()
    for left, right in combinations_with_replacement(sorted(known), 2):
        if left in first_layer and right in first_layer and left != right:
            continue
        values = (left + right, right - left, left * right,
                  right // left if right % left == 0 else 0)
        second_layer.update(x for x in values if 1 <= x <= puzzle.limit)
    return seeds, first_layer, second_layer - known


def factor_hints(
    puzzle: Puzzle, width: int = 12, radius: int = 3,
) -> dict[int, list[tuple[int, int, int]]]:
    """Rank candidate scale * quotient + signed residual recipes for each target."""
    if puzzle.limit <= 128 or width < 1:
        return {}
    proposals, support = proposals_for(puzzle, radius)
    seeds, first_layer, second_layer = cheap_layers(puzzle)
    known = seeds | first_layer
    bit_frontier = max(x.bit_length() for x in known)

    def estimate(value):
        if value in seeds:
            return 0.0
        if value in first_layer:
            return 1.0
        if value in second_layer:
            return 2.0
        return max(2.2, 2.5 + (value.bit_length() - bit_frontier) / 4.0)

    def key(candidate):
        first, second, residue = candidate
        ingredient_cost = sum(estimate(x) for x in {first, second})
        sharing = sum(0.32 * min(5, support[x] - 1)
                      for x in {first, second} if x not in known and support[x] > 1)
        cost = ingredient_cost + (1 + estimate(abs(residue)) if residue else 0) - sharing
        return cost, max(first.bit_length(), second.bit_length()), abs(residue)

    return {target: sorted(options, key=key)[:width]
            for target, options in proposals.items() if options}


def scale_hints(puzzle: Puzzle, width: int = 12) -> dict[int, list[tuple[int, int, int]]]:
    """Propose larger cheap scales and permit both quotient and residual to need synthesis."""
    if not independent_shape(puzzle) or width < 1:
        return {}
    seeds, first_layer, second_layer = cheap_layers(puzzle)
    atoms = {value: cost for cost, layer in enumerate((seeds, first_layer, second_layer))
             for value in layer}
    buckets = {}
    for value in sorted(atoms):
        bits = value.bit_length()
        if 9 <= bits <= 27:
            buckets.setdefault(bits, []).append(value)
    scales = []
    for bucket in buckets.values():
        if len(bucket) <= 32:
            scales.extend(bucket)
        else:
            scales.extend(bucket[i * (len(bucket) - 1) // 31] for i in range(32))
    if not scales:
        return {}

    def estimate(value):
        if value in atoms:
            return atoms[value]
        if value < 256:
            return 2.6
        quotient, digit = divmod(value, 256)
        if quotient in atoms and digit in atoms:
            return atoms[quotient] + atoms[digit] + 2.5
        # A large cheap scale removes the most expensive recursive work.
        return 2.5 + 0.19 * value.bit_length()

    def candidates(target):
        shortlist = []
        desired_bits = min(24, target.bit_length() * 0.38)
        for scale in scales:
            if scale > target // 2:
                continue
            quotient, residual = divmod(target, scale)
            if not residual:
                continue
            forms = [(quotient, residual)]
            if scale - residual <= puzzle.limit - target:
                forms.append((quotient + 1, residual - scale))
            for q, r in forms:
                absolute = abs(r)
                if q in atoms or absolute in atoms:
                    continue
                score = (atoms[scale] + estimate(q) + estimate(absolute)
                         + 0.42 * abs(desired_bits - scale.bit_length()))
                shortlist.append((score, scale, q, r))
        shortlist.sort()
        result = []
        bit_counts = Counter()
        used_scales = set()
        for _, scale, q, r in shortlist:
            bits = scale.bit_length()
            if scale in used_scales or bit_counts[bits] >= 3:
                continue
            result.append((scale, q, r))
            used_scales.add(scale)
            bit_counts[bits] += 1
            if len(result) == width:
                break
        return result

    return {target: result for target in sorted(set(puzzle.targets) - seeds)
            if (result := candidates(target))}


def factor_candidates(puzzle: Puzzle, wide: bool = False) -> list[Program]:
    """Generate independently scored candidates without modifying the incumbent."""
    if set(puzzle.targets).issubset(puzzle.seeds):
        return [()]
    if puzzle.limit <= 128:
        return []
    proposals, support = proposals_for(puzzle, radius=8 if wide else 1)
    bases = (31, 64, 127, 256, 1024) if wide else (64, 256)
    programs = []
    for base in bases:
        solver = FactorConstructor(puzzle, base, indexed=wide)
        for target, options in proposals.items():
            solver.pick(target, options, support, width=20 if wide else 8,
                        factor_operands=wide)
        program = compile_graph(puzzle, solver.graph, recompute=True)
        if program is not None:
            programs.append(program)
    return sorted(set(programs), key=lambda p: (len(p), p))


def independent_shape(puzzle: Puzzle) -> bool:
    """Identify the tightly clustered family using the labeled practice set."""
    return len(puzzle.targets) >= 7 and max(puzzle.targets) <= 16 * min(puzzle.targets)


def make_candidate(task):
    puzzle, wide = task
    options = factor_candidates(puzzle, wide)
    return puzzle.id, options[0] if options else None


def main():
    import argparse
    import time
    from concurrent.futures import ProcessPoolExecutor
    from pathlib import Path

    from elf import read_puzzles, read_submission, score, write_submission

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("puzzles", type=Path)
    parser.add_argument("incumbent", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--wide", action="store_true")
    parser.add_argument("--independent", action="store_true")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    puzzles = read_puzzles(args.puzzles)
    programs = read_submission(args.incumbent)
    original = score(puzzles, programs)
    selected = [p for p in puzzles if not args.independent or independent_shape(p)]
    started = time.perf_counter()
    print(f"Selected {len(selected)} of {len(puzzles)} puzzles", flush=True)
    improved = 0
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        tasks = ((puzzle, args.wide) for puzzle in selected)
        for row, (identifier, program) in enumerate(pool.map(make_candidate, tasks, chunksize=1), 1):
            if program is not None and len(program) < len(programs[identifier]):
                programs[identifier] = program
                improved += 1
            if row % 25 == 0:
                print(f"Evaluated {row}, improved {improved}, {time.perf_counter() - started:.1f}s",
                      flush=True)
    result = write_submission(args.output, puzzles, programs)
    print(f"{original:,} -> {result:,} instructions, {improved} rows improved, "
          f"{time.perf_counter() - started:.1f}s")


if __name__ == "__main__":
    main()
