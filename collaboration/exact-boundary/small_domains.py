"""Compare the native helper-budget decision with unpruned BFS on tiny integer domains."""
import argparse
from collections import Counter, deque
import hashlib
import json
from pathlib import Path
import random

from verify import native


def reachable_in_one_step(values, limit):
    results = set()
    for left in values:
        for right in values:
            results.update((left + right, left - right, left * right))
            quotient, remainder = divmod(left, right)
            if remainder == 0:
                results.add(quotient)
    return {v for v in results if 1 <= v <= limit and v not in values}


def bfs(seeds, targets, limit, budget):
    initial = frozenset(seeds)
    free = initial | targets
    queue = deque([initial])
    seen = {initial}
    while queue:
        values = queue.popleft()
        if targets <= values:
            return True
        successors = reachable_in_one_step(values, limit)
        if len(values - free) == budget:
            successors.intersection_update(targets)
        for value in successors:
            child = values | {value}
            if child not in seen:
                seen.add(child)
                queue.append(child)
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("solver", type=Path)
    args = parser.parse_args()
    rng = random.Random(649119118)
    digest = hashlib.sha256()
    outcome = Counter()
    for _ in range(5):
        for target_count in range(2, 9):
            for budget in (0, 1, 2):
                limit = rng.randint(13, 23)
                domain = range(1, limit + 1)
                seeds = sorted(rng.sample(domain, rng.randint(1, 3)))
                targets = sorted(rng.sample([n for n in domain if n not in seeds], target_count))
                expected = bfs(seeds, frozenset(targets), limit, budget)
                status, _, witness = native(args.solver, seeds, targets, limit, budget, 1_000_000)
                assert status == ("FOUND" if expected else "UNSAT"), (seeds, targets, limit, budget, expected, status)
                if status == "FOUND":
                    assert witness[:len(seeds)] == seeds
                    available = set(seeds)
                    for value in witness[len(seeds):]:
                        assert value in reachable_in_one_step(available, limit)
                        available.add(value)
                    assert set(targets) <= available and len(available - set(seeds) - set(targets)) <= budget
                digest.update((json.dumps([seeds, targets, limit, budget, status], separators=(",", ":")) + "\n").encode())
                outcome[budget, status] += 1
    print("105 matched decisions: 5 instances per target count (2..8) and helper budget (0..2)")
    for budget in (0, 1, 2):
        print(f"  {budget} helpers: {outcome[budget, 'FOUND']} FOUND, {outcome[budget, 'UNSAT']} UNSAT")
    print("Case and decision SHA-256:", digest.hexdigest())


if __name__ == "__main__":
    if not __debug__:
        raise SystemExit("Run without -O to enable cross-checks")
    main()
