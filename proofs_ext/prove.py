"""Run sharded helper-budget decisions and record receipts, additively.

Original proofs/ files are never modified. New decisions are appended to
proofs_ext/decisions.json; the combined table is written to proofs_ext/bounds.csv.
"""

import argparse
import csv
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from elf import read_puzzles, read_submission, score
from prefix_bounds import available, lower
from tiny import encode
EXT = ROOT / "proofs_ext"


def native_input(puzzle, helpers, node_limit):
    return (
        f"{puzzle.limit} {len(puzzle.seeds)} {len(puzzle.targets)} {helpers} {node_limit}\n"
        + " ".join(map(str, puzzle.seeds + puzzle.targets))
        + "\n"
    )


def query(binary, puzzle, helpers, node_limit, shard, total):
    output = subprocess.run(
        [str(binary), str(shard), str(total)],
        input=native_input(puzzle, helpers, node_limit),
        text=True,
        check=True,
        capture_output=True,
    ).stdout.splitlines()
    status, nodes, last_candidates = output[0].split()
    if status not in ("FOUND", "UNKNOWN", "UNSAT"):
        raise ValueError("Unrecognized decision")
    witness = None
    if status == "FOUND":
        values = tuple(map(int, output[1].split()))
        starts = tuple(dict.fromkeys(puzzle.seeds))
        if values[: len(starts)] != starts:
            raise ValueError("Starting values differ")
        program = encode(puzzle, values[len(starts) :])
        missing = len(set(puzzle.targets) - set(puzzle.seeds))
        if len(program) > missing + helpers:
            raise ValueError("Replayed witness exceeds its declared budget")
        witness = list(values)
    return status, int(nodes), int(last_candidates), witness


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("puzzle_id")
    ap.add_argument("helpers", type=int)
    ap.add_argument("--binary", type=Path, default=ROOT / "work/proofs/exact_helpers.exe")
    ap.add_argument("--shards", type=int, default=0, help="0 = one per root helper option")
    ap.add_argument("--node-limit", type=int, default=2_000_000_000)
    ap.add_argument("--jobs", type=int, default=16)
    ap.add_argument("--puzzles", type=Path, default=ROOT / "data/puzzles.csv")
    ap.add_argument("--submission", type=Path, default=ROOT / "improve/submission.csv")
    args = ap.parse_args()

    puzzles = read_puzzles(args.puzzles)
    programs = read_submission(args.submission)
    score(puzzles, programs)
    p = next(q for q in puzzles if q.id == args.puzzle_id)
    missing = len(set(p.targets) - set(p.seeds))

    audit = subprocess.run(
        [str(args.binary), "--audit-pairs"],
        input=native_input(p, 0, 0),
        text=True,
        capture_output=True,
        check=True,
    )
    if audit.stdout.strip() != "OK":
        raise ValueError("Pair coverage audit failed")

    shards = args.shards or max(1, len(available(p.seeds, set(p.targets), p.limit)))
    start = time.time()
    with ThreadPoolExecutor(args.jobs) as pool:
        jobs = [
            pool.submit(query, args.binary, p, args.helpers, args.node_limit, i, shards)
            for i in range(shards)
        ]
        results = [job.result() for job in jobs]
    elapsed = round(time.time() - start, 1)
    statuses = [r[0] for r in results]
    print(args.puzzle_id, "helpers", args.helpers, "shards", shards, statuses)
    print("nodes", [r[1] for r in results], "seconds", elapsed)

    if "UNKNOWN" in statuses:
        print("INCONCLUSIVE: node cap reached; nothing recorded")
        return
    if "FOUND" in statuses:
        winner = next(r for r in results if r[0] == "FOUND")
        print("FOUND witness values:", winner[3])
        print("program length", missing + args.helpers, "vs upper", len(programs[p.id]))
        return

    decision = {
        "id": p.id,
        "helpers": args.helpers,
        "max_nodes_per_shard": args.node_limit,
        "shard_nodes": [r[1] for r in results],
        "terminal_candidates": sum(r[2] for r in results),
        "seconds_16_threads": elapsed,
        "lower_bound": missing + args.helpers + 1,
    }
    receipt_path = EXT / "decisions.json"
    receipt = (
        json.loads(receipt_path.read_text())
        if receipt_path.exists()
        else {
            "puzzles_lf_sha256": sha256(
                args.puzzles.read_bytes().replace(b"\r\n", b"\n")
            ).hexdigest(),
            "decisions": [],
        }
    )
    receipt["decisions"] = [d for d in receipt["decisions"] if d["id"] != p.id or d["helpers"] != args.helpers]
    receipt["decisions"].append(decision)
    receipt["decisions"].sort(key=lambda d: (d["id"], d["helpers"]))
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf8")

    # Combined per-puzzle table: original certificates plus the new decisions.
    original = {r["id"]: r for r in csv.DictReader((ROOT / "proofs/bounds.csv").open(newline=""))}
    analytic = {q.id: lower(q) for q in puzzles}
    certified = {pid: max(int(r["certified_lower"]), analytic[pid]) for pid, r in original.items()}
    for d in receipt["decisions"]:
        certified[d["id"]] = max(certified[d["id"]], d["lower_bound"])
    rows = []
    for q in puzzles:
        lb = certified[q.id]
        ub = len(programs[q.id])
        if lb > ub:
            raise AssertionError((q.id, lb, ub))
        rows.append((q.id, analytic[q.id], lb, ub))
    with (EXT / "bounds.csv").open("w", encoding="utf8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(("id", "prefix_lower", "certified_lower", "verified_upper"))
        writer.writerows(rows)
    print(
        "Total lower", sum(r[2] for r in rows),
        "upper", sum(r[3] for r in rows),
        "proved optimal", sum(r[2] == r[3] for r in rows),
    )


if __name__ == "__main__":
    main()