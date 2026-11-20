"""Replay a registered instance using its pinned parent and the local official puzzle file."""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import subprocess

from instances import HERE, ROOT, case, read_puzzles
from elf import check
from local_trial import controls, one


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--puzzles", type=Path)
    parser.add_argument("--id", default="scored_0487")
    parser.add_argument("--controls", action="store_true")
    args = parser.parse_args()
    if args.controls:
        for arm, tests in controls().items():
            print(arm, "passed", ", ".join(tests))
        return
    if not args.puzzles:
        parser.error("--puzzles is required for an official case")
    design = json.loads((HERE / "design.json").read_bytes())
    if args.id not in {row["id"] for row in design["rows"]}:
        parser.error("ID must be in the registered cohort")
    parent = subprocess.check_output(
        ["git", "-C", str(args.repo), "show", design["git_commit"] + ":submission.csv"]
    )
    if hashlib.sha256(parent).hexdigest() != design["baseline_sha256"]:
        raise ValueError("Parent SHA-256 differs from the design")
    puzzles = {p.id: p for p in read_puzzles(args.puzzles)}
    puzzle = puzzles[args.id]
    match = next(row for row in csv.DictReader(io.StringIO(parent.decode("utf-8-sig"))) if row["id"] == args.id)
    tape = tuple(map(tuple, json.loads(match["program"])))
    check(puzzle, tape)
    problem = case(puzzle, tape)
    for arm in ("single", "multi"):
        record, candidate = one((puzzle, tape, problem, arm))
        assert check(puzzle, candidate or tape) == record["after"]
        print(json.dumps(record, separators=(",", ":")))


if __name__ == "__main__":
    main()
