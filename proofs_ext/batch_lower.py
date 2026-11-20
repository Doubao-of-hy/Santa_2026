"""Raise certified lower bounds one helper budget at a time on the cheap queue.

For each open puzzle whose analytic certificate stops at helper budget h-1,
run the exhaustive decision at budget h. UNSAT raises the lower bound by one.
Each success is recorded by prove.py; stop on the first inconclusive result.
"""

import argparse
import csv
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from elf import read_puzzles
from lower_bounds import incidence


def queue(max_budget, puzzles_path, bounds_path, gaps_path):
    puzzles = read_puzzles(puzzles_path)
    certified = {r["id"]: int(r["certified_lower"]) for r in csv.DictReader(open(bounds_path))}
    upper = {r["id"]: int(r["replayed_upper"]) for r in csv.DictReader(open(gaps_path))}
    items = []
    for p in puzzles:
        if p.limit <= 128:
            continue
        required, unsupported, *_ = incidence(p)
        if not unsupported:
            continue
        lb = certified[p.id]
        if lb >= upper[p.id]:
            continue
        budget = max(1, lb - len(required))
        if budget > max_budget:
            continue
        items.append((budget, len(unsupported), p.limit, p.id))
    items.sort()
    return items


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-budget", type=int, default=4)
    ap.add_argument("--node-limit", type=int, default=400_000_000)
    ap.add_argument("--jobs", type=int, default=16)
    ap.add_argument("--binary", type=Path, default=ROOT / "work/proofs/exact_helpers.exe")
    ap.add_argument("--limit", type=int, default=0, help="stop after this many proofs (0 = all)")
    args = ap.parse_args()
    done = 0
    for budget, unsupported, limit, pid in queue(
        args.max_budget, ROOT / "data/puzzles.csv", ROOT / "proofs_ext/bounds.csv",
        ROOT / "proofs_ext/gaps.csv",
    ):
        print(f"=== {pid} budget {budget} unsupported {unsupported} limit {limit}", flush=True)
        result = subprocess.run(
            [sys.executable, "-B", str(ROOT / "proofs_ext/prove.py"), pid, str(budget),
             "--binary", str(args.binary), "--node-limit", str(args.node_limit),
             "--jobs", str(args.jobs)],
            text=True,
        )
        if result.returncode != 0:
            print("driver failed; stopping")
            break
        # prove.py prints INCONCLUSIVE / FOUND without recording; detect via receipt.
        import json
        receipt = json.loads((ROOT / "proofs_ext/decisions.json").read_text())
        if not any(d["id"] == pid and d["helpers"] == budget for d in receipt["decisions"]):
            print("no new receipt; stopping")
            break
        done += 1
        if args.limit and done >= args.limit:
            break
    print("proofs recorded:", done)


if __name__ == "__main__":
    main()