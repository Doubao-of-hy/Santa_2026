"""List open helper-budget searches after consulting both proof sets and published assignments."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from elf import read_puzzles


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--puzzles", type=Path, default=HERE.parent/"data/puzzles.csv")
    parser.add_argument("--limit", type=int, default=20, help="number of rows to print; zero prints all")
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("--limit must be nonnegative")
    snapshot = json.loads((HERE/"evidence/ongoing-at-checkpoint.json").read_bytes())
    assigned = {(pid,r["helpers"]) for pid,r in snapshot["instances"].items() if r["status"]=="INCOMPLETE"}
    with (HERE/"puzzle-bounds.csv").open(encoding="utf8",newline="") as stream:
        bounds = {r["id"]:r for r in csv.DictReader(stream)}
    normalized = hashlib.sha256(args.puzzles.read_bytes().replace(b"\r\n",b"\n")).hexdigest()
    expected = json.loads((HERE.parent/"proofs_ext/decisions.json").read_bytes())["puzzles_lf_sha256"]
    if normalized != expected:
        raise ValueError("Puzzle data differs from the official proof input")
    jobs = []
    for p in read_puzzles(args.puzzles):
        row = bounds.pop(p.id)
        lower = int(row["certified_lower"])
        upper = int(row["best_verified_upper"])
        missing = len(set(p.targets)-set(p.seeds))
        h = lower-missing
        if lower==upper or (p.id,h) in assigned:
            continue
        if p.limit>10**18 or len(p.targets)>64 or not 0<=h<=4096:
            continue
        jobs.append((upper-lower,h,p.limit,p.id,missing,lower,upper))
    if bounds:
        raise ValueError("Incomplete official puzzle table")
    writer=csv.writer(sys.stdout,lineterminator="\n")
    writer.writerow(("id","helpers","certified_lower","verified_upper","gap","missing_targets","value_limit"))
    for gap,h,limit,pid,missing,lower,upper in sorted(jobs)[:args.limit or None]:
        writer.writerow((pid,h,lower,upper,gap,missing,limit))


if __name__=="__main__":
    main()
