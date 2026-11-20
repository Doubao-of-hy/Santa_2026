"""Bank strict lower-bound gains over the collaboration's published certificates.

The parallel session (collaboration/puzzle-bounds.csv) already certifies a strong
floor per puzzle. Searching at a budget whose UNSAT only matches that floor adds
nothing. This driver therefore targets, for each open puzzle, the *smallest*
helper budget b with missing + b + 1 > floor, where
floor = max(their certified_lower, our own certified_lower). An all-UNSAT decision
at b raises the certified lower bound strictly above everything published so far.

Reserved grids owned by the parallel session (0882 h10, 0901 h10, 0149 h10,
0212 h11) are skipped to avoid duplicating their active deep searches. Puzzles
already decided at budget b (decisions.d or decisions.json) are skipped. Hard
puzzles that hit the node cap are skipped fast so the cheap queue keeps moving.
"""

import argparse
import csv
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from elf import read_puzzles
from prefix_bounds import available

RESERVED = {
    ("scored_0882", 10),
    ("scored_0901", 10),
    ("scored_0149", 10),
    ("scored_0212", 11),
}


def decided(pid, budget):
    if (ROOT / "proofs_ext/decisions.d" / f"{pid}_h{budget}.json").exists():
        return True
    dj = ROOT / "proofs_ext/decisions.json"
    if dj.exists():
        for d in json.loads(dj.read_text(encoding="utf8"))["decisions"]:
            if d["id"] == pid and d["helpers"] == budget:
                return True
    return False


def queue(puzzles_path, collab_path, bounds_path, max_limit, max_budget, max_opts=0):
    puzzles = read_puzzles(puzzles_path)
    theirs = {
        r["id"]: (int(r["certified_lower"]), int(r["best_verified_upper"]))
        for r in csv.DictReader(open(collab_path, newline="", encoding="utf8"))
    }
    ours = {
        r["id"]: int(r["certified_lower"])
        for r in csv.DictReader(open(bounds_path, newline="", encoding="utf8"))
    }
    items = []
    for p in puzzles:
        if p.limit <= 128 or p.limit > max_limit:
            continue
        if p.id not in theirs:
            continue
        their_cert, upper = theirs[p.id]
        floor = max(their_cert, ours.get(p.id, 0))
        if floor >= upper:
            continue
        missing = len(set(p.targets) - set(p.seeds))
        budget = max(1, floor - missing)
        if budget > max_budget or budget > upper - missing - 1:
            continue
        if (p.id, budget) in RESERVED or decided(p.id, budget):
            continue
        opts = len(available(p.seeds, set(p.targets), p.limit))
        if max_opts and opts > max_opts:
            continue
        items.append((budget, p.limit, opts, p.id, missing, floor, upper))
    items.sort()
    return items


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-budget", type=int, default=8)
    ap.add_argument("--max-opts", type=int, default=0,
                    help="skip puzzles with more root helper options than this (0 = no filter)")
    ap.add_argument("--max-limit", type=int, default=1_000_000_000)
    ap.add_argument("--node-limit", type=int, default=1_000_000)
    ap.add_argument("--jobs", type=int, default=16)
    ap.add_argument("--binary", type=Path, default=ROOT / "work/proofs/exact_helpers.exe")
    ap.add_argument("--limit", type=int, default=0, help="stop after this many proofs (0 = all)")
    ap.add_argument("--collab", type=Path, default=ROOT / "collaboration/puzzle-bounds.csv")
    ap.add_argument("--skip", default="",
                    help="comma-separated id_hN stems to skip (known expensive grids)")
    args = ap.parse_args()
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    done = 0
    for budget, limit, opts, pid, missing, floor, upper in queue(
        ROOT / "data/puzzles.csv", args.collab, ROOT / "proofs_ext/bounds.csv",
        args.max_limit, args.max_budget, args.max_opts,
    ):
        if f"{pid}_h{budget}" in skip:
            print(f"=== {pid} h{budget} skipped by request", flush=True)
            continue
        print(f"=== {pid} h{budget} opts {opts} limit {limit} floor {floor} upper {upper}", flush=True)
        result = None
        for attempt in range(4):
            result = subprocess.run(
                [sys.executable, "-B", str(ROOT / "proofs_ext/prove.py"), pid, str(budget),
                 "--binary", str(args.binary), "--node-limit", str(args.node_limit),
                 "--jobs", str(args.jobs)],
                text=True,
            )
            if result.returncode == 0:
                break
            # Transient Windows file locks (AV scanning the exe) clear quickly;
            # retry a few times before giving up on this puzzle.
            print(f"driver attempt {attempt + 1} failed (rc {result.returncode}); retrying", flush=True)
            time.sleep(8)
        if result is None or result.returncode != 0:
            print("driver still failing; skipping to next puzzle", flush=True)
            continue
        if not (ROOT / "proofs_ext/decisions.d" / f"{pid}_h{budget}.json").exists():
            print("inconclusive or FOUND; skipping to next puzzle", flush=True)
            continue
        done += 1
        print(f"STRICT GAIN {pid}: lower {missing + budget + 1} > floor {floor}", flush=True)
        if args.limit and done >= args.limit:
            break
    print("strict gains recorded:", done)


if __name__ == "__main__":
    main()