"""Construct programs using cheap representatives of modular residue classes."""

import argparse
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from functools import cache
from pathlib import Path

from elf import Program, Puzzle, check, read_puzzles, read_submission, score, write_submission
from graph import Recipe, compile_graph


type Plan = tuple[tuple[int, Recipe], ...]


class ResiduePlanner:
    def __init__(self, puzzle: Puzzle, width: int = 7, span: int = 12) -> None:
        self.puzzle = puzzle
        self.width = width
        self.span = span
        self.known = set()
        self.graph = {}
        self.atoms = {}
        self.columns = {}
        self.radices = ()
        for value in puzzle.seeds:
            self.commit(value)
        unit = puzzle.seeds[0]
        self.commit(1, ("/", unit, unit))
        if puzzle.limit >= 2:
            self.commit(2, ("+", 1, 1))
        if puzzle.limit >= 3:
            self.commit(3, ("+", 2, 1))
        for value in (4, 8, 16, 32, 64, 256, 1024, 1 << 16, 1 << 20, 1 << 32):
            if value > puzzle.limit:
                continue
            if value in self.atoms:
                self.commit(value, self.atoms[value])
            else:
                smaller = value // 2
                if smaller not in self.known:
                    half = 1 << ((value.bit_length() - 1) // 2)
                    self.add_power(half)
                    other = value // half
                    self.add_power(other)
                    self.commit(value, ("*", half, other))
                else:
                    self.commit(value, ("+", smaller, smaller))
        scales = defaultdict(list)
        for value in self.known | self.atoms.keys():
            if 16 <= value <= min(1 << 29, puzzle.limit // 2):
                scales[value.bit_length()].append(value)
        preferred = {value for value in self.known if value >= 16}
        for options in scales.values():
            options.sort()
            for position in (len(options) // 6, len(options) // 2, 5 * len(options) // 6):
                preferred.add(options[position])
        self.radices = tuple(sorted(preferred))
        self.columns = {radix: defaultdict(list) for radix in self.radices}
        for value in sorted(self.known | self.atoms.keys()):
            self.index(value)

    def add_power(self, value: int) -> None:
        if value not in self.known:
            half = value // 2
            self.add_power(half)
            self.commit(value, ("+", half, half))

    def index(self, value: int) -> None:
        for radix in self.radices:
            if value <= self.span * radix:
                column = self.columns[radix][value % radix]
                if value not in column:
                    column.append(value)

    def atom(self, value: int, recipe: Recipe) -> None:
        if 1 <= value <= self.puzzle.limit and value not in self.known and value not in self.atoms:
            self.atoms[value] = recipe
            self.index(value)

    def commit(self, value: int, recipe: Recipe | None = None) -> None:
        if value in self.known:
            return
        self.known.add(value)
        self.atoms.pop(value, None)
        self.index(value)
        if recipe is not None:
            self.graph[value] = recipe
        for other in self.known:
            first, second = max(value, other), min(value, other)
            self.atom(first + second, ("+", first, second))
            self.atom(first - second, ("-", first, second))
            self.atom(first * second, ("*", first, second))
            if first % second == 0:
                self.atom(first // second, ("/", first, second))

    def cheap(self, value: int) -> Plan | None:
        if value == 0 or value in self.known:
            return ()
        if value in self.atoms:
            return ((value, self.atoms[value]),)
        return None

    def estimate(self, value: int) -> int:
        if value == 0 or value in self.known:
            return 0
        if value in self.atoms:
            return 10
        size = value.bit_length()
        return 21 + size + (size // 10) * 9

    def join(self, value: int) -> Plan | None:
        for anchor in self.known:
            if anchor < value:
                residual = value - anchor
                plan = self.cheap(residual)
                if plan is not None:
                    return (*plan, (value, ("+", anchor, residual)))
            elif anchor > value:
                residual = anchor - value
                plan = self.cheap(residual)
                if plan is not None:
                    return (*plan, (value, ("-", anchor, residual)))
            if value + anchor <= self.puzzle.limit:
                plan = self.cheap(value + anchor)
                if plan is not None:
                    return (*plan, (value, ("-", value + anchor, anchor)))
            if anchor > 1 and value % anchor == 0:
                plan = self.cheap(value // anchor)
                if plan is not None:
                    return (*plan, (value, ("*", anchor, value // anchor)))
            if anchor > 1 and value * anchor <= self.puzzle.limit:
                plan = self.cheap(value * anchor)
                if plan is not None:
                    return (*plan, (value, ("/", value * anchor, anchor)))
            if anchor > value and anchor % value == 0:
                plan = self.cheap(anchor // value)
                if plan is not None:
                    return (*plan, (value, ("/", anchor, anchor // value)))
        return None

    def split_candidates(self, value: int, wide: bool):
        for radix in self.radices:
            if radix * 2 > value:
                break
            residue = value % radix
            deltas = {residue, residue - radix}
            if wide:
                column = self.columns[radix]
                deltas.update(column.get(residue, ()))
                deltas.update(-representative for representative in column.get((-residue) % radix, ()))
            for delta in deltas:
                product = value - delta
                quotient = product // radix
                if quotient < 2 or product > self.puzzle.limit or abs(delta) >= value // 2:
                    continue
                cost = self.estimate(quotient) + self.estimate(abs(delta))
                cost += self.estimate(radix) + (0 if product in self.known else 10) + 10 * bool(delta)
                yield cost, radix, quotient, delta

    def assemble(self, value: int, radix: int, quotient: int, delta: int, q_plan: Plan, r_plan: Plan) -> Plan:
        product = radix * quotient
        # Child programs are interpreted in isolation. Preserve their first
        # recipes when they independently produce the same exact integer.
        pieces = {}
        for operand in (*q_plan, *r_plan, *(self.cheap(radix) or ())):
            pieces.setdefault(*operand)
        product_plan = self.cheap(product)
        if product_plan is not None:
            for operand in product_plan:
                pieces.setdefault(*operand)
        else:
            pieces.setdefault(product, ("*", radix, quotient))
        if delta:
            pieces.setdefault(value, ("+" if delta > 0 else "-", product, abs(delta)))
        return tuple(pieces.items())

    def plan(self, target: int, depth: int) -> Plan:
        @cache
        def binary(value: int) -> Plan:
            initial = self.cheap(value)
            if initial is not None:
                return initial
            smaller, odd = divmod(value, 2)
            recipes = dict(binary(smaller))
            recipes.setdefault(2 * smaller, ("+", smaller, smaller))
            if odd:
                recipes.setdefault(value, ("+", 2 * smaller, 1))
            return tuple(recipes.items())

        @cache
        def search(value: int, remaining: int) -> Plan:
            direct = self.cheap(value)
            if direct is not None:
                return direct
            joined = self.join(value)
            if joined is not None:
                return joined
            best = binary(value)
            if remaining <= 0:
                return best
            candidates = sorted(self.split_candidates(value, wide=remaining >= 2))
            visited = set()
            for _, radix, quotient, delta in candidates:
                rank = quotient, abs(delta)
                if rank in visited:
                    continue
                if len(visited) >= self.width:
                    break
                visited.add(rank)
                q_plan = search(quotient, remaining - 1)
                if len(q_plan) + 1 >= len(best):
                    continue
                r_plan = search(abs(delta), remaining - 1)
                option = self.assemble(value, radix, quotient, delta, q_plan, r_plan)
                if len(option) < len(best):
                    best = option
            return best

        result = search(target, depth)
        binary.cache_clear()
        search.cache_clear()
        return result

    def run(self, depth: int, reverse: bool = False) -> Program | None:
        for target in sorted(set(self.puzzle.targets), reverse=reverse):
            for value, recipe in self.plan(target, depth):
                self.commit(value, recipe)
        return compile_graph(self.puzzle, self.graph, recompute=True)


def construct_modular(puzzle: Puzzle, width: int = 7, depth: int = 4, span: int = 12,
                      reverse: bool = False) -> Program | None:
    return ResiduePlanner(puzzle, width, span).run(depth, reverse)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("puzzles", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--exclude-ids", type=Path)
    parser.add_argument("--only-ids", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--min-count", type=int, default=0)
    parser.add_argument("--width", type=int, default=6)
    parser.add_argument("--depth", type=int, default=4)
    parser.add_argument("--span", type=int, default=12)
    parser.add_argument("--jobs", type=int, default=6)
    parser.add_argument("--priority", choices=("count", "excess"), default="count")
    parser.add_argument("--reverse", action="store_true")
    args = parser.parse_args()
    if args.width < 1 or args.span < 1 or args.jobs < 1 or args.depth < 0:
        parser.error("width, span, and jobs must be positive, and depth nonnegative")

    puzzles = read_puzzles(args.puzzles)
    best = read_submission(args.baseline)
    total = score(puzzles, best)
    excluded = set(args.exclude_ids.read_text(encoding="utf-8-sig").split()) if args.exclude_ids else set()
    included = (set(args.only_ids.read_text(encoding="utf-8-sig").split())
                if args.only_ids else {puzzle.id for puzzle in puzzles})
    unrecognized = included - best.keys()
    if unrecognized:
        raise ValueError(f"unknown included puzzle ID {min(unrecognized)}")

    def priority(puzzle):
        count = len(best[puzzle.id])
        burden = 5 * len(set(puzzle.targets) - set(puzzle.seeds)) if args.priority == "excess" else 0
        return burden - count, puzzle.id

    selected = sorted((puzzle for puzzle in puzzles if puzzle.id in included and puzzle.id not in excluded
                       and len(best[puzzle.id]) >= args.min_count), key=priority)[:args.limit]
    print(f"Validated baseline {total}, selected {len(selected)} puzzles", flush=True)
    start = time.monotonic()
    wins = 0
    with ProcessPoolExecutor(max_workers=args.jobs) as executor:
        pending = {
            executor.submit(construct_modular, puzzle, args.width, args.depth, args.span, args.reverse): puzzle
            for puzzle in selected
        }
        for index, result in enumerate(as_completed(pending), 1):
            puzzle = pending[result]
            candidate = result.result()
            if candidate is not None:
                steps = check(puzzle, candidate)
                if steps < len(best[puzzle.id]):
                    total += steps - len(best[puzzle.id])
                    best[puzzle.id] = candidate
                    wins += 1
            if index % 20 == 0:
                verified = write_submission(args.output, puzzles, best)
                print(f"{index}/{len(selected)} completed, {wins} improved, {verified} instructions, "
                      f"{time.monotonic() - start:.1f}s", flush=True)
    verified = write_submission(args.output, puzzles, best)
    print(f"Validated {verified} instructions, {wins} improvements in {time.monotonic() - start:.1f}s", flush=True)


if __name__ == "__main__":
    main()
