"""Combine exact-replayed full runs and partial generation checkpoints."""
import argparse
import hashlib
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work" / "gen"
sys.path.insert(0, str(ROOT))
from elf import read_puzzles, read_submission, score, sha256, write_submission
from reallocate import allocate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("puzzles", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("inputs", type=Path, nargs="+")
    parser.add_argument("--schedule-width", type=int, default=0)
    args = parser.parse_args()
    puzzles = read_puzzles(args.puzzles)
    by_id = {puzzle.id: puzzle for puzzle in puzzles}
    best = {}
    selected = {}
    sources = []
    WORK.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=WORK, prefix="merge-") as scratch:
        snapshot = Path(scratch) / "snapshot.csv"
        for source in args.inputs:
            data = source.read_bytes()
            snapshot.write_bytes(data)
            candidate = read_submission(snapshot)
            unknown = candidate.keys() - by_id.keys()
            if unknown or not candidate:
                raise ValueError(f"{source}: empty or unknown IDs {sorted(unknown)[:3]}")
            subset = [by_id[identifier] for identifier in candidate]
            total = score(subset, candidate)
            accepted = 0
            savings = 0
            scheduled = 0
            for identifier, program in candidate.items():
                prior = best.get(identifier)
                if args.schedule_width > 0:
                    minimum_gap = 1 if prior is None else max(1, len(program) - len(prior) + 1)
                    _, program, shortened = allocate((by_id[identifier], program,
                                                       args.schedule_width, 0, minimum_gap))
                    scheduled += shortened
                if prior is None or len(program) < len(prior):
                    accepted += 1
                    if prior is not None:
                        savings += len(prior) - len(program)
                    best[identifier] = program
                    selected[identifier] = str(source)
            sources.append({
                "path": str(source), "rows": len(candidate), "steps": total,
                "sha256": hashlib.sha256(data).hexdigest(), "accepted": accepted,
                "saved_from_preceding_sources": savings, "allocation_savings": scheduled,
            })
    total = write_submission(args.output, puzzles, best)
    report = {
        "rows": len(best), "instructions": total, "sha256": sha256(args.output),
        "models": sources, "selected_counts": dict(Counter(selected.values())),
        "source_by_puzzle": selected,
    }
    args.output.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")
    print(json.dumps({key: value for key, value in report.items() if key != "source_by_puzzle"},
                     indent=2))


if __name__ == "__main__":
    main()
