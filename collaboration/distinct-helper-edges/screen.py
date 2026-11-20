"""Price the hypothetical Turan cap before asking an arithmetic clique oracle."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import csv
import hashlib
import io
import json
from itertools import permutations
from math import isqrt
from pathlib import Path
import subprocess
import sys


def capacities(p, allowed):
    from domain_bounds import operands, unary_capacity
    from lower_bounds import values, double_witnesses
    base = allowed | set(p.targets)
    unsupported = set()
    members = defaultdict(set)
    for t in set(p.targets) - allowed:
        candidates = set()
        if t % 2 == 0:
            candidates.add(t // 2)
        root = isqrt(t)
        if root * root == t:
            candidates.add(root)
        for b in base - {t}:
            opts = operands(t, b, p.limit)
            if opts & base:
                break
            candidates.update(opts)
        else:
            unsupported.add(t)
            for h in candidates - base:
                members[h].add(t)
    incidence = {h: unary_capacity(h, s, base, p.limit) for h, s in members.items()}
    pairs = {(a, b) for x, y in permutations(unsupported, 2) for a, b in double_witnesses(x, y)
             if 1 <= b < a <= p.limit and a not in base and b not in base}
    degree = Counter()
    bonuses = []
    for a, b in pairs:
        bonus = len(values(a, b, p.limit) & unsupported) - 1
        if bonus > 0:
            degree.update({a: bonus, b: bonus})
            bonuses.append(bonus)
    def prefix(seq):
        result = [0]
        for val in sorted(seq, reverse=True)[:len(unsupported) + 2]:
            result.append(result[-1] + val)
        return result
    unary = prefix(incidence.values())
    extra = prefix(degree.values())
    mixed = prefix(2 * incidence.get(v, 0) + degree[v] for v in incidence.keys() | degree.keys())
    bonuses = sorted(bonuses, reverse=True)
    def capacity(h, bound):
        surplus = min(sum(bonuses[:bound]), extra[min(h, len(extra) - 1)] // 2)
        return bound + min(unary[min(h, len(unary) - 1)] + surplus, mixed[min(h, len(mixed) - 1)] // 2)
    def required(turan):
        for h in range(len(unsupported) + 2):
            simple = h * (h - 1) // 2
            pair_cap = min(simple, h * h // 3) if turan else simple
            if capacity(h, pair_cap) >= len(unsupported):
                return h
        raise AssertionError
    return sorted(unsupported), required(False), required(True)


def work(entry):
    repo, p, prior = entry
    sys.path.insert(0, str(repo))
    from domain_bounds import domains
    from lower_bounds import certificate
    required, _, minimum_helpers, _ = certificate(p)
    checks = []
    for k, allowed in [(0, set(p.seeds)), *domains(p, min(minimum_helpers, 4), 3500)]:
        labels, classic, hypothetical = capacities(p, allowed)
        total = required + k + hypothetical
        checks.append(dict(k=k, allowed_count=len(allowed),
                           allowed_sha256=hashlib.sha256((",".join(map(str, sorted(allowed))) + "\n").encode()).hexdigest(),
                           labels=labels, classic=classic, optimistic=hypothetical, total=total))
    return dict(id=p.id, prior=prior, missing=required, states=checks,
                best=max(r["total"] for r in checks), eligible=[r["k"] for r in checks if r["total"] > prior])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--puzzles", type=Path, required=True)
    parser.add_argument("--phase", choices=("screen", "replicate"), required=True)
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.repo))
    from elf import read_puzzles
    design = json.loads((Path(__file__).resolve().parent / "design.json").read_bytes())
    assert hashlib.sha256(args.puzzles.read_bytes()).hexdigest() == design["puzzles_sha256"]
    blob = subprocess.check_output(["git", "-C", str(args.repo), "show", design["snapshot"] + ":collaboration/puzzle-bounds.csv"])
    assert hashlib.sha256(blob).hexdigest() == design["bound_table_sha256"]
    previous = {r["id"]: int(r["certified_lower"]) for r in csv.DictReader(io.StringIO(blob.decode()))}
    ps = {p.id: p for p in read_puzzles(args.puzzles)}
    rows = []
    with ProcessPoolExecutor(args.jobs) as pool:
        for r in pool.map(work, [(args.repo, ps[k], previous[k]) for k in design[args.phase]]):
            rows.append(r)
            args.out.write_bytes((json.dumps(rows, separators=(",", ":")) + "\n").encode())
            print(r["id"], r["prior"], r["best"], r["eligible"], flush=True)


if __name__ == "__main__":
    main()
