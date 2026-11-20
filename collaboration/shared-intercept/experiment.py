"""Reproduce the preregistered two-branch affine-intercept pilot."""
import argparse
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load_rows(data):
    return {r["id"]: r for r in csv.DictReader(io.StringIO(data.decode("utf-8-sig")))}


def save_json(path, data):
    path.write_bytes((json.dumps(data, ensure_ascii=False, indent=1) + "\n").encode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    here = Path(__file__).resolve().parent
    parser.add_argument("--repo", type=Path, default=next((p for p in here.parents if (p / "elf.py").is_file()), here.parents[1]))
    parser.add_argument("--puzzles", required=True, type=Path)
    parser.add_argument("--design", default=here / "design.json", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--phase", choices=("toy", "development", "holdout", "all"), default="all")
    args = parser.parse_args()
    args.output.mkdir(exist_ok=True, parents=True)
    repo = args.repo.resolve()
    sys.path.insert(0, str(repo))
    from elf import Puzzle, check, read_puzzles, write_submission
    from graph import compile_graph
    from intercept import run
    path = repo / "collaboration/polish/replay.py"
    spec = importlib.util.spec_from_file_location("independent_registers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def replay(p, program):
        return module.run_program([p.id, list(p.seeds), list(p.targets), p.limit, p.registers],
                                  [list(step) for step in program])

    design = json.loads(args.design.read_bytes())
    assert digest(args.puzzles.read_bytes()) == design["puzzles_sha256"]
    def git_file(f):
        return subprocess.check_output(["git", "-C", str(repo), "show",
                                        design["commit"] + ":" + design["track"] + "/" + f])
    parent_bytes, origin_bytes = git_file("submission.csv"), git_file("origins.csv")
    assert digest(parent_bytes) == design["parent_sha256"] and digest(origin_bytes) == design["origin_sha256"]
    parents, credits = load_rows(parent_bytes), load_rows(origin_bytes)
    puzzles = {p.id: p for p in read_puzzles(args.puzzles)}
    if args.phase in ("all", "toy"):
        toy = Puzzle("intercept_toy", (1, 3, 5, 31, 37, 263, 269, 212305, 353799),
                     (212309, 353803), 1000000)
        old = {}
        for start in (212305, 353799):
            for offset in range(1, 5):
                old[start + offset] = ("+", start + offset - 1, 1)
        tape = compile_graph(toy, old)
        programs, record = run(toy, tape, design["search"], replay)
        record["tapes"] = {"parent": tape, **programs}
        save_json(args.output / "positive.json", record)
        print("toy", len(tape), record["lengths"], flush=True)
        assert record["lengths"] == {"single": 8, "joint": 6}
        assert record["witness"]["joint"][0]["scale"] == 70747
        assert record["witness"]["joint"][0]["intercept"] == 68
    for phase in ("development", "holdout"):
        if args.phase not in ("all", phase):
            continue
        results, winner_rows, origins = {}, {}, []
        for row in design["rows"]:
            if row["split"] != phase:
                continue
            key = row["id"]
            raw = parents[key]["program"]
            assert digest(raw.encode()) == row["program_sha256"]
            tape = tuple(tuple(op) for op in json.loads(raw))
            assert len(tape) == row["parent"]
            start = perf_counter()
            programs, record = run(puzzles[key], tape, design["search"], replay)
            record["seconds"] = round(perf_counter() - start, 3)
            results[key] = record
            winner = programs["joint"]
            if len(winner) < len(tape):
                winner_rows[key] = winner
                arm = "single" if len(programs["single"]) == len(winner) else "joint"
                sources = credits[key]
                origins.append([key, arm, len(winner), json.dumps(sources, ensure_ascii=False)])
            save_json(args.output / (phase + ".json"),
                      dict(design_sha256=digest(args.design.read_bytes()), rows=results))
            print(phase, key, len(tape), record["lengths"], record["stats"], record["seconds"], flush=True)
        write_submission(args.output / (phase + "-wins.csv"), [puzzles[k] for k in winner_rows], winner_rows)
        with (args.output / (phase + "-origins.csv")).open("w", newline="", encoding="utf-8") as f:
            out = csv.writer(f, lineterminator="\n")
            out.writerow(("id", "arm", "length", "frozen_parent_credit"))
            out.writerows(origins)


if __name__ == "__main__":
    main()
