"""Estimate what one more helper budget costs before spending it.

Probes a few shards with a node cap, so a cheap grid is not queued behind an
expensive one.  Reported per-shard node counts come from the same binary that
would run the full grid, and the growth factor per extra helper is around
``6h`` (see OPTIMALITY-BARRIER.md), so the probe is the cheapest honest way to
tell "minutes" from "next week".
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from elf import read_puzzles
from prefix_bounds import available

RATE_PER_CORE = 164_000  # measured nodes per second on one core


def native_input(puzzle, helpers, node_limit):
    return (
        f"{puzzle.limit} {len(puzzle.seeds)} {len(puzzle.targets)} {helpers} {node_limit}\n"
        + " ".join(map(str, puzzle.seeds + puzzle.targets))
        + "\n"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("puzzle_id")
    parser.add_argument("helpers", type=int)
    parser.add_argument("--binary", type=Path, default=ROOT / "work/proofs/exact_helpers.exe")
    parser.add_argument("--cap", type=int, default=5_000_000, help="node cap per probe")
    parser.add_argument("--samples", type=int, default=3, help="shards to probe")
    parser.add_argument("--cores", type=int, default=2)
    parser.add_argument("--threshold", type=int, default=1_000_000_000,
                        help="refuse to run when the estimate exceeds this node count")
    parser.add_argument("--puzzles", type=Path, default=ROOT / "data/puzzles.csv")
    parser.add_argument("--run", action="store_true", help="run the full grid when it fits")
    parser.add_argument("--jobs", type=int, default=1)
    args = parser.parse_args()

    puzzle = next(p for p in read_puzzles(args.puzzles) if p.id == args.puzzle_id)
    missing = len(set(puzzle.targets) - set(puzzle.seeds))
    shards = max(1, len(available(puzzle.seeds, set(puzzle.targets), puzzle.limit)))
    samples = sorted({round(i * (shards - 1) / max(1, args.samples - 1))
                      for i in range(args.samples)})
    print(f"{puzzle.id}: limit {puzzle.limit}, {missing} missing targets, {shards} shards, "
          f"budget h{args.helpers} -> lower bound {missing + args.helpers + 1}", flush=True)

    counts, seconds, unknown = [], [], False
    for shard in samples:
        start = time.time()
        out = subprocess.run(
            [str(args.binary), str(shard), str(shards)],
            input=native_input(puzzle, args.helpers, args.cap),
            text=True, capture_output=True, check=True,
        ).stdout.split()
        status, nodes = out[0], int(out[1])
        counts.append(nodes)
        seconds.append(time.time() - start)
        print(f"  shard {shard}/{shards}: {status} {nodes:,} nodes, {seconds[-1]:.1f} s", flush=True)
        if status == "FOUND":
            print("a witness exists; nothing to prove here", flush=True)
            return
        if status == "UNKNOWN":
            unknown = True
            print(f"  probe hit the {args.cap:,} node cap: the shard is bigger than this probe",
                  flush=True)

    mean = sum(counts) / len(counts)
    total_mean = int(mean * shards)
    total_max = max(counts) * shards
    rate = sum(counts) / sum(seconds) if sum(seconds) else RATE_PER_CORE
    cores = max(1, args.cores)
    wall = total_mean / (rate * cores)
    print(f"  estimate: {total_mean:,} nodes (mean×shards), {total_max:,} nodes (max×shards)", flush=True)
    print(f"  at {rate:,.0f} nodes/s on {cores} core(s): {wall/60:.1f} min wall clock", flush=True)
    if unknown:
        print("  verdict: indeterminate at this cap; re-probe with a larger --cap "
              "(each extra helper multiplies the work by roughly 6h)", flush=True)
        return
    if total_max > args.threshold:
        print(f"  verdict: too big for one box (threshold {args.threshold:,}); queue elsewhere", flush=True)
        return
    print("  verdict: fits; run the full grid", flush=True)
    if args.run:
        command = [sys.executable, "-B", str(ROOT / "proofs_ext/prove.py"), puzzle.id,
                   str(args.helpers), "--node-limit", str(max(args.cap, 2 * max(counts)),
                                                        ), "--jobs", str(args.jobs), "--binary",
                   str(args.binary)]
        print("  running:", " ".join(command), flush=True)
        subprocess.run(command, check=True, cwd=ROOT)


if __name__ == "__main__":
    main()
