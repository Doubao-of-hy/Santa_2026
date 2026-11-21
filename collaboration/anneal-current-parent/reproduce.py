#!/usr/bin/env python3
"""Re-run the annealing sweep on the repository's own parent and check the rows.

The parent is `public-assisted/submission.csv` (134,063 instructions). For each
requested configuration the script calls `generative/wang/replay_search.py`
(unmodified in-repo engine, Apache-2.0), compares row by row with the parent,
replays every program that got shorter, and finally checks lengths and program
hashes against `wins.csv`.

Nothing from any external repository is needed: the parent is a file in this
repository, so the result is self-contained.

Example:
    python -B collaboration/anneal-current-parent/reproduce.py \
        --puzzles data/puzzles.csv --binary-dir /tmp --rounds 35
    python -B collaboration/anneal-current-parent/reproduce.py \
        --puzzles data/puzzles.csv --binary-dir /tmp --rounds 200
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import elf  # noqa: E402


def program_hash(program) -> str:
    payload = json.dumps([list(row) for row in program], separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--puzzles", type=Path, default=ROOT / "data/puzzles.csv")
    parser.add_argument("--base", type=Path,
                        default=ROOT / "public-assisted/submission.csv")
    parser.add_argument("--binary-dir", type=Path, required=True,
                        help="directory holding the compiled anneal binaries")
    parser.add_argument("--rounds", type=int, default=35)
    parser.add_argument("--mode", default="anneal",
                        choices=("anneal", "incremental", "anneal_diverse"))
    parser.add_argument("--seed-offset", type=int, default=737049)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--wins", type=Path,
                        default=Path(__file__).with_name("wins.csv"))
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.csv"
        subprocess.run(
            [sys.executable, "-B", str(ROOT / "generative/wang/replay_search.py"),
             str(args.puzzles), str(args.base), str(out),
             "--binary-dir", str(args.binary_dir), "--rounds", str(args.rounds),
             "--mode", args.mode, "--seed-offset", str(args.seed_offset),
             "--jobs", str(args.jobs)],
            check=True, cwd=str(ROOT))
        candidate = elf.read_submission(out)

    base = elf.read_submission(args.base)
    puzzles = {p.id: p for p in elf.read_puzzles(args.puzzles)}
    rows = []
    for identifier, program in candidate.items():
        if len(program) >= len(base[identifier]):
            continue
        elf.replay(puzzles[identifier], program)
        rows.append((identifier, len(base[identifier]), len(program),
                     len(base[identifier]) - len(program), program_hash(program)))

    rows.sort()
    print("rounds", args.rounds, "mode", args.mode,
          "total", sum(len(p) for p in candidate.values()))
    print("id,incumbent,improved,saved,program_sha256")
    for row in rows:
        print(",".join(map(str, row)))

    if args.wins.exists():
        expected = {row["id"]: row for row in csv.DictReader(args.wins.open())}
        mismatch = [row[0] for row in rows
                    if expected.get(row[0], {}).get("program_sha256") != row[4]]
        print("hash mismatches against wins.csv:", len(mismatch), mismatch[:5])
        return 1 if mismatch else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
