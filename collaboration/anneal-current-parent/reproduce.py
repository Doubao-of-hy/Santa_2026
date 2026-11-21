"""Reproduce the two recorded improvements from their pinned repository parent."""

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PARENT = "62e194b3541cad7e28cd58e4fa3551e9455dd806"
PARENT_PATH = "public-assisted/submission.csv"
PARENT_SHA256 = "49d1ac9e9c8e9435e18c516e1748cad13022ee3148596cf245fc53adbd859d8b"
sys.path.insert(0, str(ROOT))

import elf


def verify(base, candidate, rows_path, wins_path):
    if candidate.keys() != base.keys():
        raise ValueError("Candidate puzzle IDs differ from the parent")
    changed = {key: value for key, value in candidate.items() if value != base[key]}
    recorded = elf.read_submission(rows_path)
    if changed != recorded:
        raise ValueError(f"Changed programs differ from {rows_path.name}; got {sorted(changed)}")
    with wins_path.open(encoding="utf-8-sig", newline="") as handle:
        wins = list(csv.DictReader(handle))
    if len(wins) != len(changed) or {row["id"] for row in wins} != changed.keys():
        raise ValueError(f"Recorded puzzle IDs differ in {wins_path.name}")
    for row in wins:
        key = row["id"]
        program = changed[key]
        before, after = len(base[key]), len(program)
        lengths = tuple(int(row[field]) for field in ("incumbent", "improved", "saved"))
        if after >= before or lengths != (before, after, before - after):
            raise ValueError(f"{key}: recorded lengths differ from the reproduced improvement")
        digest = hashlib.sha256(json.dumps(program, separators=(",", ":")).encode()).hexdigest()
        if digest != row["program_sha256"]:
            raise ValueError(f"{key}: recorded program hash differs")
        print(f"{key}: {before} -> {after}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--puzzles", type=Path, default=ROOT / "data/puzzles.csv")
    parser.add_argument("--base", type=Path, help="An existing copy of the pinned parent CSV")
    parser.add_argument("--binary-dir", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=35)
    parser.add_argument("--mode", default="anneal", choices=("anneal", "incremental", "anneal_diverse"))
    parser.add_argument("--seed-offset", type=int, default=737049)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--wins", type=Path, default=HERE / "wins.csv")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        parent = args.base
        if parent is None:
            parent = Path(tmp) / "parent.csv"
            with parent.open("wb") as output:
                subprocess.run(["git", "show", f"{PARENT}:{PARENT_PATH}"], cwd=ROOT,
                               stdout=output, check=True)
        if elf.sha256(parent) != PARENT_SHA256:
            parser.error(f"Expected the parent CSV from commit {PARENT}")
        out = Path(tmp) / "out.csv"
        subprocess.run(
            [sys.executable, "-B", str(ROOT / "generative/wang/replay_search.py"),
             str(args.puzzles.resolve()), str(parent.resolve()), str(out),
             "--binary-dir", str(args.binary_dir.resolve()), "--rounds", str(args.rounds),
             "--mode", args.mode, "--seed-offset", str(args.seed_offset),
             "--jobs", str(args.jobs)], check=True, cwd=ROOT)
        base = elf.read_submission(parent)
        candidate = elf.read_submission(out)
        verify(base, candidate, HERE / "rows.csv", args.wins)
        print(f"Verified {len(candidate)} puzzles, {sum(map(len, candidate.values()))} instructions")


if __name__ == "__main__":
    main()
