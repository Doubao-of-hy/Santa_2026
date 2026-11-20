"""Independently replay witnesses and rerun the complete helper-budget lower-bound searches."""

import argparse
import csv
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path

from elf import read_puzzles, read_submission, score
from prefix_bounds import lower
from tiny import encode

PROOFS = Path(__file__).resolve().parent / "proofs"


def native_input(puzzle, helpers, node_limit):
    return (
        f"{puzzle.limit} {len(puzzle.seeds)} {len(puzzle.targets)} {helpers} {node_limit}\n"
        + " ".join(map(str, puzzle.seeds + puzzle.targets))
        + "\n"
    )


def query(binary, puzzle, helpers, node_limit, shard, total, subshard=None, subshards=1):
    arguments = [binary, str(shard), str(total)]
    if subshard is not None:
        arguments.extend((str(subshard), str(subshards)))
    output = subprocess.run(
        arguments,
        input=native_input(puzzle, helpers, node_limit),
        text=True,
        check=True,
        capture_output=True,
    ).stdout.splitlines()
    status, nodes, last_candidates = output[0].split()
    if status not in ("FOUND", "UNKNOWN", "UNSAT"):
        raise ValueError("Unrecognized decision")
    if status == "FOUND":
        values = tuple(map(int, output[1].split()))
        starts = tuple(dict.fromkeys(puzzle.seeds))
        if values[: len(starts)] != starts:
            raise ValueError("Starting values differ")
        program = encode(puzzle, values[len(starts) :])
        missing = len(set(puzzle.targets) - set(puzzle.seeds))
        if len(program) > missing + helpers:
            raise ValueError("Replayed witness exceeds its declared budget")
    return status, int(nodes), int(last_candidates)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("puzzles", type=Path)
    ap.add_argument("submission", type=Path)
    ap.add_argument("--binary", type=Path, required=True)
    ap.add_argument("--jobs", type=int, default=4)
    args = ap.parse_args()
    if args.jobs < 1:
        ap.error("Expected a positive worker count")
    proof = json.loads((PROOFS / "decisions.json").read_text())
    # The official file and the public mirror use different line endings.
    normalized = args.puzzles.read_bytes().replace(b"\r\n", b"\n")
    if sha256(normalized).hexdigest() != proof["puzzles_lf_sha256"]:
        raise ValueError("Unexpected puzzle file")
    puzzles = read_puzzles(args.puzzles)
    programs = read_submission(args.submission)
    score(puzzles, programs)
    bounds = {p.id: lower(p) for p in puzzles}
    analytic = dict(bounds)
    by_id = {p.id: p for p in puzzles}
    with ThreadPoolExecutor(args.jobs) as pool:
        for row in proof["decisions"]:
            p = by_id[row["id"]]
            audit = subprocess.run(
                [args.binary.resolve(), "--audit-pairs"],
                input=native_input(p, 0, 0),
                text=True,
                capture_output=True,
                check=True,
            )
            if audit.stdout.strip() != "OK":
                raise ValueError("Pair coverage audit failed")
            subshards = row.get("subshards", 1)
            shards = row.get("root_shards", len(row["shard_nodes"]))
            if shards * subshards != len(row["shard_nodes"]):
                raise ValueError("Invalid shard coverage receipt")
            jobs = [
                pool.submit(
                    query,
                    args.binary.resolve(),
                    p,
                    row["helpers"],
                    row["max_nodes_per_shard"],
                    i,
                    shards,
                    None if subshards == 1 else j,
                    subshards,
                )
                for j in range(subshards)
                for i in range(shards)
            ]
            result = [job.result() for job in jobs]
            if any(status != "UNSAT" for status, _, _ in result):
                raise ValueError(f"{p.id}: not all branches proved impossible")
            if [nodes for _, nodes, _ in result] != row["shard_nodes"] or sum(
                last for _, _, last in result
            ) != row["terminal_candidates"]:
                raise ValueError(f"{p.id}: search trace differs from the receipt")
            missing = len(set(p.targets) - set(p.seeds))
            bounds[p.id] = max(bounds[p.id], missing + row["helpers"] + 1)
            print(p.id, "lower", bounds[p.id], "upper", len(programs[p.id]), flush=True)
    with (PROOFS / "bounds.csv").open(newline="") as f:
        published = list(csv.DictReader(f))
    expected = [
        (p.id, str(analytic[p.id]), str(bounds[p.id]), str(len(programs[p.id])))
        for p in puzzles
    ]
    if expected != [
        (r["id"], r["prefix_lower"], r["certified_lower"], r["verified_upper"])
        for r in published
    ]:
        raise ValueError("Per-puzzle table differs")
    if any(bounds[p.id] > len(programs[p.id]) for p in puzzles):
        raise ValueError("Inconsistent bounds")
    print(
        "Total",
        sum(bounds.values()),
        sum(map(len, programs.values())),
        "proved optimal",
        sum(bounds[p.id] == len(programs[p.id]) for p in puzzles),
    )


if __name__ == "__main__":
    main()
