"""Replay archived arithmetic programs and optionally repeat their discovery runs."""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from elf import Puzzle, read_puzzles, read_submission, replay, sha256
from tiny import encode


def run_search(binary, puzzle, parents, seed, iterations):
    fields = [puzzle.limit, len(puzzle.seeds), len(puzzle.targets), len(parents), len(parents[0]),
              *puzzle.seeds, *puzzle.targets]
    rows = [" ".join(map(str, fields))]
    for steps in parents:
        rows.append(str(len(steps)))
        rows.extend(f"{s.output} {s.left} {s.right}" for s in steps)
    result = subprocess.run([str(binary.resolve()), str(seed), str(iterations)],
                            input="\n".join(rows) + "\n", capture_output=True, text=True, check=True)
    return result.stdout.splitlines()


def expand_parents(binary, puzzle, parents, settings):
    lines = run_search(binary, puzzle, parents, settings["seed"], settings["iterations"])
    sequences = []
    for line in lines:
        if line.startswith("POOL "):
            _, count, *values = line.split()
            if int(count) <= settings["max_sequence_length"]:
                sequences.append(list(map(int, values)))
    packed = json.dumps(sequences, separators=(",", ":")).encode()
    assert hashlib.sha256(packed).hexdigest() == settings["population_digest"]
    assert len(sequences) == settings["accepted_sequences"]
    extra = {}
    for seq in sequences:
        extra.setdefault(frozenset(seq), replay(puzzle, encode(puzzle, tuple(seq))))
    return parents + list(extra.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", choices=("0711", "0818", "0250", "0387"), default="0711")
    parser.add_argument("--puzzles", type=Path, help="Full, unmodified official puzzles.csv")
    parser.add_argument("--binary", type=Path, help="Compiled generator for this case's profile")
    parser.add_argument("--warmup-binary", type=Path, help="Compiled balanced.cpp, for case 0387")
    args = parser.parse_args()
    directory = HERE if args.id == "0711" else HERE / "siblings" / args.id
    source = json.loads((directory / "parents.json").read_bytes())
    receipt = json.loads((directory / "verification.json").read_bytes())
    settings = source.get("search", {"seed": 1991, "discovery_iteration": 1105, "steps": 21,
                                     "profile": "balanced"})
    p = Puzzle(source["id"], tuple(source["starting_values"]), tuple(source["targets"]),
               source["value_limit"], source["registers"])
    if args.puzzles:
        assert sha256(args.puzzles) == source["official_puzzles_sha256"]
        assert next(q for q in read_puzzles(args.puzzles) if q.id == p.id) == p
    assert receipt.get("independent_source_input_sha256", receipt.get("frozen_parents")) == source["frozen_inputs_sha256"]
    witness_file = directory / "witness.csv"
    assert sha256(witness_file) == receipt.get("winning_csv_sha256", receipt.get("program_sha256"))
    witness = read_submission(witness_file)[p.id]
    trace = replay(p, witness)
    assert len(trace) == receipt.get("steps", receipt.get("program_steps")) == settings["steps"]
    assert [s.output for s in trace] == receipt.get("outputs", receipt.get("trace_values"))
    parents = [replay(p, entry["program"]) for entry in source["parents"]]
    for entry, steps in zip(source["parents"], parents):
        values = {s.output for s in steps} - set(p.seeds) - set(p.targets)
        assert sorted(values) == entry["helpers"]
    print(f"{p.id}: independent parents {[len(s) for s in parents]}, verified winner {len(trace)}.")
    if not args.binary:
        return
    if "warmup" in settings:
        if not args.warmup_binary:
            parser.error("case 0387 reproduction requires --warmup-binary")
        parents = expand_parents(args.warmup_binary, p, parents, settings["warmup"])
    if settings["profile"] == "balance_sparse":
        parents.sort(key=len)
    iteration = settings["discovery_iteration"]
    lines = iter(run_search(args.binary, p, parents, settings["seed"], iteration + 1))
    for line in lines:
        if not line.startswith("WIN "):
            continue
        _, discovered, length = line.split()
        outputs = [int(next(lines).split()[0]) for _ in range(int(length))]
        generated = encode(p, tuple(outputs))
        if int(discovered) == iteration and generated == witness:
            print(f"Seed {settings['seed']} reproduced every archived instruction at iteration {iteration}.")
            return
    raise RuntimeError("the fixed compiler-dependent search did not reproduce the archived witness")


if __name__ == "__main__":
    main()
