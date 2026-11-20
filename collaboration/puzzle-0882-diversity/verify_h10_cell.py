"""Check the 24 third-coordinate receipts for cell (11, 4) of puzzle 882.

Optionally supply --binary compiled from proofs/local/work/gpu/closest-36729/hot.cpp
and --third N (repeatable), or --all, to rerun the final exclusions.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--puzzles", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=here.parents[1])
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--third", type=int, action="append", default=[])
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    sys.path.insert(0, str(args.repo.resolve()))
    from elf import read_puzzles, sha256

    data = json.loads((here / "h10-cell-11-4.json").read_bytes())
    assert sha256(args.puzzles) == data["official_sha256"]
    assert args.jobs > 0 and data["puzzle"] == "scored_0882" and data["helpers"] == 10
    assert [data[k] for k in ("first", "first_parts", "second", "second_parts", "third_parts",
                              "group_width")] == [11, 24, 4, 32, 24, 16]
    p = next(p for p in read_puzzles(args.puzzles) if p.id == data["puzzle"])
    rows = {r["third"]: r for r in data["records"]}
    assert set(rows) == set(range(24)) and len(data["records"]) == 24
    assert data["decision"] == "UNSAT" and data["previous_parent"]["status"] == "UNKNOWN"
    assert data["counted_nodes"] == sum(r["metrics"][0] for r in rows.values())
    assert data["terminal_candidates"] == sum(r["metrics"][1] for r in rows.values())
    for r in rows.values():
        assert r["status"] == "UNSAT" and len(r["metrics"]) == 7 and 0 < r["metrics"][0] <= r["budget"]
        expected = "UNSAT " + " ".join(map(str, r["metrics"])) + "\n"
        assert hashlib.sha256(expected.encode()).hexdigest() == r["stdout_lf_sha256"]
    print("24/24 third coordinates exhausted", data["counted_nodes"], "nodes")
    selected = list(rows) if args.all else sorted(set(args.third))
    if not selected:
        return
    if args.binary is None:
        parser.error("native replay requires --binary")
    assert all(k in rows for k in selected)

    def run(k):
        r = rows[k]
        values = [p.limit, len(p.seeds), len(p.targets), 10, r["budget"], *p.seeds, *p.targets]
        process = subprocess.run([str(args.binary.resolve()), "star", "11", "24", "4", "32", str(k), "24"],
                                 input=" ".join(map(str, values)) + "\n", text=True, capture_output=True,
                                 env={**os.environ, "SANTA_GROUP_WIDTH": "16"}, check=True)
        assert hashlib.sha256(process.stdout.encode()).hexdigest() == r["stdout_lf_sha256"]
        return k

    with ThreadPoolExecutor(args.jobs) as pool:
        for k in pool.map(run, selected):
            print("replayed", k, flush=True)


if __name__ == "__main__":
    main()
