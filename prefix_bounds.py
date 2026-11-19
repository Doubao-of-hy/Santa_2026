"""Certify lower bounds by restricting where the first two helper values can come from."""

import argparse
import csv
from pathlib import Path

from elf import read_puzzles, read_submission, score
from lower_bounds import incidence, values
from tiny import solve_tiny


def available(known, goals, limit):
    """Return possible first helpers after eagerly producing all reachable goals."""
    known = set(known)
    while True:
        choices = set()
        for a in known:
            for b in known:
                if b <= a:
                    choices.update(values(a, b, limit))
        fresh = choices - known
        targets = fresh & goals
        if not targets:
            return fresh
        known.update(targets)


def prefix_domains(p):
    goals = set(p.targets)
    first = available(p.seeds, goals, p.limit)
    second = first.copy()
    for helper in first:
        second.update(available((*p.seeds, helper), goals, p.limit))
    return first, second


def prefix_sums(weights, domains, length):
    """Maximum possible weights, assigning nested domains in increasing order."""
    ranked = sorted(weights, key=weights.get, reverse=True)
    used = set()
    result = [0]
    for i in range(length):
        domain = domains[i] if i < len(domains) else None
        best = next(
            (v for v in ranked if v not in used and (domain is None or v in domain)),
            None,
        )
        if best is not None:
            used.add(best)
        result.append(result[-1] + weights.get(best, 0))
    return result


def lower(p):
    required, unsupported, unary, degree, bonuses = incidence(p)
    if not unsupported:
        helper_bound = 0
    else:
        domains = prefix_domains(p)
        # The universal pair allowance alone eventually covers every target.
        length = len(unsupported) + 2
        u = prefix_sums(unary, domains, length)
        d = prefix_sums(degree, domains, length)
        m = prefix_sums(
            {x: 2 * unary[x] + degree[x] for x in unary.keys() | degree.keys()},
            domains,
            length,
        )
        bonuses.sort(reverse=True)
        for helper_bound in range(length + 1):
            pairs = helper_bound * (helper_bound - 1) // 2
            extra = min(sum(bonuses[:pairs]), d[helper_bound] // 2)
            capacity = pairs + min(u[helper_bound] + extra, m[helper_bound] // 2)
            if capacity >= len(unsupported):
                break
    first_steps = 0
    if required:
        peak = max(p.seeds)
        while peak < min(required):
            peak = max(2 * peak, peak * peak)
            first_steps += 1
    bound = len(required) + max(0, first_steps - 1, helper_bound)
    if p.limit <= 128:
        optimum = solve_tiny(p)
        if optimum is not None:
            if bound > len(optimum):
                raise AssertionError(p.id)
            bound = len(optimum)
    return bound


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    for key in ("puzzles", "submission", "output"):
        ap.add_argument(key, type=Path)
    args = ap.parse_args()
    puzzles = read_puzzles(args.puzzles)
    programs = read_submission(args.submission)
    score(puzzles, programs)
    rows = []
    for p in puzzles:
        lb = lower(p)
        ub = len(programs[p.id])
        if lb > ub:
            raise AssertionError((p.id, lb, ub))
        rows.append((p.id, lb, ub))
    with args.output.open("w", encoding="utf8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(("id", "prefix_lower", "replayed_upper"))
        writer.writerows(rows)
    print(
        len(rows),
        sum(r[1] for r in rows),
        sum(r[2] for r in rows),
        sum(r[1] == r[2] for r in rows),
    )
