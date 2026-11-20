"""Replay the two recorded optimizer comparisons on a local copy of the competition inputs."""
import argparse
import csv
import hashlib
import io
import json
import subprocess
import zipfile
from pathlib import Path, PurePosixPath


DIRECTORY = Path(__file__).resolve().parent
METHODS = ("group", "exchange", "factor", "paid")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fingerprint(value):
    return digest(json.dumps(value, separators=(",", ":")).encode("utf-8"))


def official_puzzles(path, expected):
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist() if PurePosixPath(name).name == "puzzles.csv"]
            require(len(names) == 1, "Expected exactly one scored puzzles.csv in the official archive")
            data = archive.read(names[0])
    else:
        data = path.read_bytes()
    require(digest(data.replace(b"\r\n", b"\n")) == expected, "Official scored puzzle file digest differs")
    puzzles = {}
    for row in csv.DictReader(io.StringIO(data.decode("utf-8-sig"))):
        key = row["id"]
        require(key not in puzzles, f"Duplicate puzzle {key}")
        puzzles[key] = [key, json.loads(row["starting_values"]), json.loads(row["targets"]),
                        int(row["value_limit"]), int(row["registers"])]
    return puzzles


def run_program(puzzle, instructions):
    key, seeds, targets, limit, register_count = puzzle
    require(isinstance(instructions, list) and len(instructions) <= 4096, f"{key}: program length")
    registers = list(seeds) + [None] * (register_count - len(seeds))
    produced = set(seeds)
    for index, instruction in enumerate(instructions, 1):
        where = f"{key} instruction {index}"
        require(isinstance(instruction, list) and len(instruction) == 4, f"{where}: invalid instruction")
        op, left, right, dest = instruction
        require(all(type(k) is int and 0 <= k < register_count for k in (left, right, dest)),
                f"{where}: register index out of range")
        a, b = registers[left], registers[right]
        require(a is not None and b is not None, f"{where}: read from an empty register")
        if op == "+":
            value = a + b
        elif op == "-":
            value = a - b
        elif op == "*":
            value = a * b
        elif op == "/" and b and a % b == 0:
            value = a // b
        else:
            raise ValueError(f"{where}: invalid operator or inexact division")
        require(1 <= value <= limit, f"{where}: result outside puzzle limits")
        registers[dest] = value
        produced.add(value)
    require(set(targets) <= produced, f"{key}: missing target values")
    return len(instructions)


def parse_program(row):
    raw = row["program"]
    require(len(raw.encode("utf-8")) <= 131072, f"{row['id']}: program field too large")
    return json.loads(raw)


def replay_cases(puzzles, manifest):
    path = DIRECTORY / "programs.csv"
    require(digest(path.read_bytes()) == manifest["programs_csv_sha256"], "Recorded program table digest differs")
    scores = {}
    with path.open(encoding="utf-8", newline="") as file:
        for row in csv.DictReader(file):
            key, program_hash = row["id"], row["program_sha256"]
            program = parse_program(row)
            require((key, program_hash) not in scores and fingerprint(program) == program_hash, "Invalid program digest")
            scores[key, program_hash] = run_program(puzzles[key], program)
    reports = {}
    referenced = set()
    for key, case in manifest["cases"].items():
        require(fingerprint(puzzles[key]) == case["puzzle_fingerprint"], f"{key}: puzzle fingerprint differs")
        current = case["independent_parent"]
        require(current == case["parent_provenance"]["matching_row_sha256"], f"{key}: parent digest differs")
        parent = scores[key, current]
        referenced.add((key, current))
        standalones = case["single_outputs"]
        require(set(standalones) == set(METHODS), f"{key}: expected all four single runs")
        solo = {}
        for name in METHODS:
            program_hash = standalones[name]
            solo[name] = scores[key, program_hash]
            referenced.add((key, program_hash))
            require(solo[name] <= parent, f"{key}: regressing retained solo")
        events = []
        for event in case["accepted_chain"]:
            name, before, after = event["method"], event["input"], event["output"]
            require(name in METHODS and before == current, f"{key}: broken program chain")
            a, b = scores[key, before], scores[key, after]
            require(b < a, f"{key}: accepted change did not shorten program")
            events.append({"method": name, "before": a, "after": b, "saved": a - b})
            referenced.add((key, after))
            current = after
        require(current == case["published_result"], f"{key}: final program differs from recorded result")
        chain = scores[key, current]
        reports[key] = {"parent": parent, "solo": solo, "best_solo": min(solo.values()), "chain": chain,
                        "extra_over_best_solo": min(solo.values()) - chain, "events": events}
    require(set(scores) == referenced, "Program table contains unreferenced rows")
    return reports


def full_submission(puzzles, cases, path):
    seen = {}
    with path.open(encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            key = row["id"]
            require(key in puzzles and key not in seen, f"Unknown or duplicate submission row {key}")
            seen[key] = run_program(puzzles[key], parse_program(row))
    require(seen.keys() == puzzles.keys(), "Submission is missing scored puzzles")
    total = sum(seen.values())
    saved = sum(max(0, seen[key] - r["chain"]) for key, r in cases.items())
    return {"puzzles": len(seen), "instructions": total, "with_strictly_shorter_case_results": total - saved}


def rerun_group(puzzles, manifest, engine):
    """Run GoodPJW's original optimizer on each recorded positive group transition."""
    with (DIRECTORY / "programs.csv").open(encoding="utf-8", newline="") as file:
        programs = {(r["id"], r["program_sha256"]): parse_program(r) for r in csv.DictReader(file)}
    events = []
    for key, case in manifest["cases"].items():
        _, seeds, targets, limit, register_count = puzzles[key]
        for event in case["accepted_chain"]:
            if event["method"] != "group":
                continue
            program = programs[key, event["input"]]
            header = ["P", key, len(seeds), *seeds, len(targets), *targets, limit, register_count, len(program)]
            data = "\n".join(" ".join(map(str, row)) for row in [header, *program]) + "\n"
            command = [str(engine.resolve()), "--time", "1.15", "--seed", str(case["seed"]), "--group", "8",
                       "--pairs", "1", "--helpers", "1", "--kicks", "1000", "--kslack", "2"]
            run = subprocess.run(command, input=data, text=True, capture_output=True, check=True)
            if run.stdout.strip():
                header_line, *instructions = run.stdout.strip().splitlines()
                marker, emitted_key, old, length = header_line.split()
                require((marker, emitted_key, int(old)) == ("R", key, len(program)), f"{key}: engine header differs")
                out = [[op, int(a), int(b), int(dest)] for op, a, b, dest in (line.split() for line in instructions)]
                require(run_program(puzzles[key], out) == int(length), f"{key}: engine length differs")
            else:
                require(key in run.stderr and any(tag in run.stderr for tag in ("evals ", "emit-fail", "parse-fail")),
                        f"{key}: missing engine result")
                out = program
            events.append({"id": key, "input_steps": len(program), "regenerated_steps": len(out),
                           "recorded_steps": len(programs[key, event["output"]]),
                           "same_physical_instructions": fingerprint(out) == event["output"]})
    return events


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("puzzles", type=Path, help="official santa-2026.zip or its scored puzzles.csv")
    parser.add_argument("--submission", type=Path, help="also replay every row of this submission CSV")
    parser.add_argument("--group-engine", type=Path, help="also rerun GoodPJW's group moves using a local executable")
    args = parser.parse_args()
    manifest = json.loads((DIRECTORY / "manifest.json").read_bytes())
    puzzles = official_puzzles(args.puzzles, manifest["official_csv_lf_sha256"])
    cases = replay_cases(puzzles, manifest)
    result = {"cases": cases, "case_totals": {k: sum(r[k] for r in cases.values())
              for k in ("parent", "best_solo", "chain", "extra_over_best_solo")}}
    if args.submission:
        result["full_submission"] = full_submission(puzzles, cases, args.submission)
    if args.group_engine:
        result["fresh_group_searches"] = rerun_group(puzzles, manifest, args.group_engine)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
