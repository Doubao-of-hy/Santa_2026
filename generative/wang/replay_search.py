"""Replay arithmetic search from a single parent CSV or a per-row recipe manifest."""
import argparse
import csv
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def repository():
    for p in Path(__file__).resolve().parents:
        if (p / "elf.py").exists() and (p / "checkpoint.py").exists():
            return p
    raise RuntimeError("Place this runner in the Santa 2026 repository")


sys.path.insert(0, str(repository()))
from checkpoint import independent_score
from elf import check, read_puzzles, read_submission, sha256, write_submission


def encode(puzzle, mode, rounds, seed, parents):
    fields = [
        [1],
        [puzzle.limit, puzzle.registers, rounds, 0, seed],
        [len(puzzle.seeds), *puzzle.seeds],
        [len(puzzle.targets), *sorted(puzzle.targets)],
        [len(parents)],
    ]
    for tape in parents:
        check(puzzle, tape)
        fields.append([len(tape)])
        fields.extend(tape)
    return "\n".join(" ".join(map(str, row)) for row in fields) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("puzzles", type=Path)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--binary-dir", type=Path, required=True)
    parser.add_argument("--allow-different-parents", action="store_true", help="Replay credited manifests assembled from multiple baseline versions")
    parser.add_argument("--recipes", type=Path, help="Override specified rows using ranked, credited parents")
    parser.add_argument("--mode", choices=("anneal", "incremental", "anneal_diverse", "compact_rotate"), default="anneal")
    parser.add_argument("--rounds", type=int, default=35)
    parser.add_argument("--seed-offset", type=int, default=737049)
    parser.add_argument("--jobs", type=int, default=1)
    args = parser.parse_args()
    puzzles = read_puzzles(args.puzzles)
    baseline = read_submission(args.baseline)
    if set(baseline) != {p.id for p in puzzles}:
        raise ValueError("Input rows do not match the puzzle identifiers")
    if args.output.resolve() in {args.puzzles.resolve(), args.baseline.resolve()}:
        raise ValueError("Choose a separate output path")

    settings = {}
    if args.recipes:
        with args.recipes.open(encoding="utf-8-sig", newline="") as source:
            for row in csv.DictReader(source):
                key = row["id"]
                params = (row["mode"], int(row["rounds"]), int(row["seed"]))
                if key not in baseline or params[0] not in {"anneal", "anneal_seeded", "incremental", "anneal_diverse", "compact_rotate"}:
                    raise ValueError(f"Unsupported manifest row {key}")
                mode, rounds, seed, parents = settings.setdefault(key, (*params, []))
                if (mode, rounds, seed) != params or int(row["rank"]) != len(parents):
                    raise ValueError(f"Conflicting manifest order for {key}")
                parents.append(tuple(tuple(op) for op in json.loads(row["program"])))
        for key, (_, _, _, parents) in settings.items():
            if parents[0] != baseline[key] and not args.allow_different_parents:
                raise ValueError(f"Incorrect baseline for {key}")
    else:
        for puzzle in puzzles:
            seed = args.seed_offset + int(puzzle.id.rsplit("_", 1)[1])
            settings[puzzle.id] = (args.mode, args.rounds, seed, [baseline[puzzle.id]])

    def execute(puzzle):
        mode, rounds, seed, parents = settings[puzzle.id]
        exe = args.binary_dir / (mode + (".exe" if sys.platform == "win32" else ""))
        result = subprocess.run([str(exe.resolve())], input=encode(puzzle, mode, rounds, seed, parents),
                                text=True, capture_output=True, check=True)
        nums = result.stdout.split()
        size = int(nums[0])
        if len(nums) != 4 * size + 1:
            raise ValueError(f"Truncated solver output for {puzzle.id}")
        tape = tuple((nums[i], int(nums[i+1]), int(nums[i+2]), int(nums[i+3]))
                     for i in range(1, len(nums), 4))
        if check(puzzle, tape) != size or size > len(parents[0]):
            raise ValueError(f"Invalid solver result for {puzzle.id}")
        return puzzle.id, tape

    result = baseline.copy()
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for key, tape in pool.map(execute, [p for p in puzzles if p.id in settings]):
            if len(tape) < len(result[key]):
                result[key] = tape
    count = write_submission(args.output, puzzles, result)
    if count != sum(independent_score(args.puzzles, args.output)):
        raise RuntimeError("Independent score differs")
    print(json.dumps({"rows_searched": len(settings), "score": count, "sha256": sha256(args.output)}))


if __name__ == "__main__":
    main()