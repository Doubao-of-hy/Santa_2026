"""Replay scored_0134 and optionally recompute all four finite-pool comparisons."""
import argparse
import csv
import importlib.util
import json
import sys
from pathlib import Path


DIRECTORY = Path(__file__).resolve().parent
validation_spec = importlib.util.spec_from_file_location("polish_replay", DIRECTORY.parent / "polish" / "replay.py")
validation = importlib.util.module_from_spec(validation_spec)
validation_spec.loader.exec_module(validation)


def read_recorded(manifest, puzzle):
    table = DIRECTORY / "programs.csv"
    validation.require(validation.digest(table.read_bytes()) == manifest["recorded_program_csv_sha256"],
                       "Program table digest differs")
    programs = {}
    with table.open(encoding="utf-8", newline="") as file:
        for row in csv.DictReader(file):
            role, instructions = row["role"], validation.parse_program(row)
            validation.require(row["id"] == puzzle[0] and role not in programs, "Ambiguous program role")
            digest = validation.fingerprint(instructions)
            validation.require(digest == row["sha256"] == manifest["programs"][role]["program_sha256"],
                               f"Unexpected program digest for {role}")
            validation.run_program(puzzle, instructions)
            programs[role] = instructions
    validation.require(programs.keys() == manifest["programs"].keys(), "Program table is incomplete")
    return programs


def search(manifest, puzzle, programs):
    vendor = DIRECTORY / "vendor" / "arsen_v15"
    config = manifest["solver"]
    for name, expected in config["pinned_sources"].items():
        validation.require(validation.digest((vendor / name).read_bytes()) == expected, f"Changed vendor file {name}")
    sys.path.insert(0, str(vendor))
    from recombine2026 import solve
    try:
        import ortools
    except ImportError as error:
        raise SystemExit("Install ortools==9.15.6755 to run the optional --search comparison.") from error
    key, seeds, targets, cap, registers = puzzle
    raw = {"id": key, "starting_values": json.dumps(seeds), "targets": json.dumps(targets),
           "value_limit": str(cap), "registers": str(registers)}
    rows = []
    for group in manifest["groups"]:
        candidates = [programs[name] for name in group["inputs"]]
        program, info = solve(raw, candidates, budget=config["deterministic_time_budget"], slack=config["slack"],
                              helpers=config["optional_helpers"], seed=config["seed"])
        steps = validation.run_program(puzzle, program)
        rows.append({"inputs": group["inputs"], "steps": steps, "finite_pool_status": info["status"],
                     "candidate_values": info["values"], "candidate_recipes": info["recipes"],
                     "matches_recorded_tape": program == programs[group["selected"]]})
    reproduced = all(observed["finite_pool_status"] == recorded["finite_pool_status"]
                     and observed["steps"] == recorded["steps"] and observed["matches_recorded_tape"]
                     for observed, recorded in zip(rows, manifest["groups"]))
    return {"ortools_version": ortools.__version__, "groups": rows, "reproduced_all_four": reproduced}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("puzzles", type=Path, help="local official competition ZIP or scored puzzles.csv")
    parser.add_argument("--search", action="store_true", help="run all four optimization groups using OR-Tools")
    parser.add_argument("--submission", type=Path, help="replay all submitted rows and apply the witness if shorter")
    args = parser.parse_args()
    manifest = json.loads((DIRECTORY / "manifest.json").read_bytes())
    puzzles = validation.official_puzzles(args.puzzles, manifest["official_scored_csv_lf_sha256"])
    puzzle = puzzles[manifest["puzzle_id"]]
    validation.require(validation.fingerprint(puzzle) == manifest["official_puzzle_fingerprint"], "Puzzle mismatch")
    programs = read_recorded(manifest, puzzle)
    groups = []
    for entry in manifest["groups"]:
        program = programs[entry["selected"]]
        steps = validation.run_program(puzzle, program)
        validation.require(steps == entry["steps"], "Recorded case length differs")
        groups.append({"inputs": entry["inputs"], "retained": entry["selected"], "physical_steps": steps})
    result = {"puzzle": puzzle[0], "inputs_and_output_steps": {k: len(v) for k, v in programs.items()},
              "recorded_comparisons": groups}
    if args.submission:
        result["submission"] = validation.full_submission(puzzles, {puzzle[0]: {"chain": len(programs["result"])}},
                                                         args.submission)
    if args.search:
        result["fresh_search"] = search(manifest, puzzle, programs)
    print(json.dumps(result, indent=2))
    if args.search and not result["fresh_search"]["reproduced_all_four"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
