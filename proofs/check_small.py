"""Cross-check the helper search against unpruned breadth-first enumeration."""

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from elf import Puzzle, read_puzzles
from prefix_bounds import lower
from solvers.proofs.verify_optimality import query


def breadth_first(p):
    layer = {frozenset(p.seeds)}
    targets = set(p.targets)
    length = 0
    while layer:
        if any(s >= targets for s in layer):
            return length
        next_layer = set()
        for state in layer:
            for a in state:
                for b in state:
                    for v in (a + b, a - b, a * b, a // b if a % b == 0 else 0):
                        if 1 <= v <= p.limit and v not in state:
                            next_layer.add(state | {v})
        layer = next_layer
        length += 1
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("puzzles", type=Path)
    ap.add_argument("practice", type=Path)
    ap.add_argument("--binary", type=Path, required=True)
    args = ap.parse_args()
    tests = [
        p
        for f in (args.puzzles, args.practice)
        for p in read_puzzles(f)
        if p.limit <= 128
    ]
    real = len(tests)
    rng = random.Random(1711)
    for _ in range(300):
        cap = rng.randint(3, 16)
        seeds = tuple(rng.sample(range(1, cap + 1), rng.randint(1, 3)))
        goals = tuple(rng.sample(range(1, cap + 1), rng.randint(1, min(cap, 6))))
        tests.append(Puzzle("random", seeds, goals, cap))
    for i, p in enumerate(tests):
        optimum = breadth_first(p)
        missing = len(set(p.targets) - set(p.seeds))
        if optimum is not None and lower(p) > optimum:
            raise AssertionError((p.id, "bound exceeds optimum"))
        budgets = (
            range(3)
            if optimum is None
            else range(max(0, optimum - missing - 1), optimum - missing + 1)
        )
        for h in budgets:
            shards = 2 if i % 5 == 0 else 1
            statuses = {
                query(args.binary.resolve(), p, h, 10000000, j, shards)[0]
                for j in range(shards)
            }
            feasible = optimum is not None and optimum <= missing + h
            if "UNKNOWN" in statuses or ("FOUND" in statuses) != feasible:
                raise AssertionError((p.id, optimum, h, statuses))
    print(
        f"Passed {real} official small puzzles and {len(tests) - real} generated cases"
    )


if __name__ == "__main__":
    main()
