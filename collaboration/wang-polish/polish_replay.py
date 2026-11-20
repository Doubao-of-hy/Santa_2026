"""Rerun both registered orders of the four Wang-parent polishing passes on one puzzle."""
import argparse
import csv
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARENTS = {
    "own": ("22e78c3f04b1d3059f2a166f510979e75895ea31", "submission.csv", "origins.csv"),
    "assisted": ("767761d54afd14927f67dec216c47ee4ded91c2c", "public-assisted/submission.csv",
                 "public-assisted/origins.csv"),
}
ORDERS = (("group", "exchange", "factor", "paid"), ("paid", "factor", "exchange", "group"))
SOURCES = {
    "group": ("group_elfopt.cpp", "16f12d4963acfe795f89f9632e941fb1aea9d8d8de55ac958a45b17a02881db2"),
    "exchange": ("value_exchange.cpp", "dd25da69aec44917500b235368b3e6870534b66bbd5640216af9dc8c6fb24d77"),
    "factor": ("factor_resynthesis.cpp", "84937aa177dd12f4728ca18148ece321195471d9d19c13776afdb48787193c44"),
    "order": ("work/creative/pressure/order_search.cpp", "cdbea39d09c502198737ccb2374dfec2fc669489a3365a934b8330a4d958146a"),
}


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def checked(condition, message):
    if not condition:
        raise ValueError(message)


def git_blob(repo, commit, rel):
    return subprocess.run(["git", "-C", str(repo), "show", f"{commit}:{rel}"], check=True, capture_output=True).stdout


def csv_row(blob, identifier):
    matches = [r for r in csv.DictReader(io.StringIO(blob.decode("utf-8-sig"))) if r["id"] == identifier]
    checked(len(matches) == 1, f"Expected one row for {identifier}")
    return matches[0]


def native_group(exe, puzzle, tape, seed):
    header = ["P", puzzle.id, len(puzzle.seeds), *puzzle.seeds, len(puzzle.targets), *puzzle.targets,
              puzzle.limit, puzzle.registers, len(tape)]
    stream = "\n".join(" ".join(map(str, row)) for row in (header, *tape)) + "\n"
    cmd = [str(exe), "--time", "1.15", "--seed", str(seed), "--group", "8", "--pairs", "1",
           "--helpers", "1", "--kicks", "1000", "--kslack", "2"]
    r = subprocess.run(cmd, input=stream, capture_output=True, text=True, encoding="ascii", check=True,
                       creationflags=getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0))
    if not r.stdout.strip():
        checked(puzzle.id in r.stderr and any(s in r.stderr for s in ("evals ", "parse-fail", "emit-fail")),
                f"Group search returned no execution counters: {r.stderr}")
        return tape, r.stderr.strip()
    head, *lines = r.stdout.strip().splitlines()
    flag, pid, old, size = head.split()
    checked((flag, pid, int(old), int(size)) == ("R", puzzle.id, len(tape), len(lines)), head)
    return tuple((op, int(a), int(b), int(dest)) for op, a, b, dest in (s.split() for s in lines)), r.stderr.strip()


def binaries(args, repo, temp):
    answer = {}
    for name, (filename, expected) in SOURCES.items():
        src = (HERE if name == "group" else repo) / filename
        checked(digest(src.read_bytes()) == expected, f"Changed {name} native source")
        supplied = getattr(args, name + "_binary")
        if supplied is None:
            path = temp / ("order-search.exe" if name == "order" else name + ".exe")
            flags = ["-static"] if os.name == "nt" else []
            env = {**os.environ, "TMP": str(temp), "TEMP": str(temp), "TMPDIR": str(temp)}
            subprocess.run([args.cxx, "-std=c++17", "-O3", *flags, str(src), "-o", str(path)],
                           env=env, check=True)
        else:
            path = supplied.resolve(strict=True)
            if name == "order" and path.name != "order-search.exe":
                # The upstream scheduler resolves this filename from its own directory.
                path = Path(shutil.copy2(path, temp / "order-search.exe"))
        answer[name] = path
    return answer


def allocation_control(second):
    """Exercise the native pressure reducer and the CP-SAT fallback on a schedulable graph."""
    from elf import Puzzle, check
    from graph import _allocate
    from operand_allocation import synthesize
    from reorder import peak, schedule
    seeds = (1, 1000)
    leaves = list(range(1001, 1055))
    total = sum(leaves)
    p = Puzzle("allocation_control", seeds, (total,), total, 48)
    chain = {v: ("+", v - 1, 1) for v in leaves}
    sums = {}
    acc = leaves[0]
    interleaved = {leaves[0]: chain[leaves[0]]}
    for v in leaves[1:]:
        sums[acc + v] = ("+", acc, v)
        interleaved[v] = chain[v]
        acc += v
        interleaved[acc] = sums[acc]
    crowded = chain | sums
    parent = _allocate(p, interleaved, False, 0, fixed_order=True)
    initial = peak(p, crowded)
    checked(parent is not None and initial > p.registers, "Invalid pressure control")
    _, scheduled, metrics = schedule((p.id, p, parent, initial, initial, crowded, .2, 1051))
    checked(scheduled is not None and metrics["reordered_peak"] <= 48, "Native scheduler control failed")
    values = list(crowded)
    ordered = {values[i]: crowded[values[i]] for i in metrics["ordered_node_indices"]}
    alternative, status, _, _ = synthesize(p, ordered, .2)
    checked(alternative is not None, "Operand allocation control failed")
    puzzle_data = [p.id, list(seeds), [total], p.limit, 48]
    for tape in (parent, scheduled, alternative):
        checked(check(p, tape) == second.run_program(puzzle_data, [list(s) for s in tape]), "Invalid control tape")
    return dict(input_peak=initial, capacity=48, reordered_peak=metrics["reordered_peak"],
                reordered_steps=len(scheduled), allocation_status=status, allocation_steps=len(alternative))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--puzzles", required=True, type=Path, help="official puzzles.csv")
    ap.add_argument("--id", required=True, help="registered puzzle ID, e.g. scored_0180")
    ap.add_argument("--lane", choices=PARENTS, default="own")
    ap.add_argument("--repo", type=Path, default=HERE.parents[1])
    ap.add_argument("--cxx", default="g++")
    ap.add_argument("--scratch", type=Path, help="parent directory for temporary compilation")
    for name in SOURCES:
        ap.add_argument("--" + name + "-binary", type=Path, help=f"existing executable for the {name} pass")
    ap.add_argument("--output", type=Path, help="write the winning one-puzzle CSV")
    ap.add_argument("--report", type=Path, help="write the replay receipt as JSON")
    ap.add_argument("--allocation-control", action="store_true", help="also run the synthetic register-pressure control")
    args = ap.parse_args()
    repo = args.repo.resolve()
    sys.path[:0] = [str(repo), str(repo / "work/creative/pressure"), str(repo / "collaboration/release-crossover"),
                    str(repo / "generative/arsen_v15"), str(repo / "generative")]
    from elf import Puzzle, check, read_submission, write_submission
    from factor_resynthesis import optimize
    from paid import paid_alternatives
    from recombine2026 import solve
    from value_exchange import run_row

    independent = importlib.util.spec_from_file_location("polish_independent", repo / "collaboration/polish/replay.py")
    second = importlib.util.module_from_spec(independent)
    independent.loader.exec_module(second)
    official = args.puzzles.read_bytes()
    normalized = digest(official.replace(b"\r\n", b"\n"))
    expected_official = json.loads((repo / "proofs/decisions.json").read_bytes())["puzzles_lf_sha256"]
    checked(normalized == expected_official, "Official scored puzzle file differs")
    raw = csv_row(official, args.id)
    puzzle = Puzzle(args.id, tuple(json.loads(raw["starting_values"])), tuple(json.loads(raw["targets"])),
                    int(raw["value_limit"]), int(raw["registers"]))
    second_input = [args.id, list(puzzle.seeds), list(puzzle.targets), puzzle.limit, puzzle.registers]
    design = json.loads((repo / "collaboration/evidence/wang-polish-design.json").read_bytes())[args.lane]
    parts = [key for key in ("pilot", "holdout", "remaining") if args.id in design[key]]
    checked(len(parts) == 1, f"{args.id} is outside the frozen {args.lane} design")
    commit, parent_name, origin_name = PARENTS[args.lane]
    blob = git_blob(repo, commit, parent_name)
    checked(digest(blob) == design["parent"], "Frozen Git submission differs from the preregistered input")
    original = tuple(tuple(s) for s in json.loads(csv_row(blob, args.id)["program"]))
    credit = csv_row(git_blob(repo, commit, origin_name), args.id)
    checked(int(credit["instructions"]) == len(original), "Parent attribution length differs")

    def verify(tape):
        checked(check(puzzle, tape) == second.run_program(second_input, [list(s) for s in tape]) == len(tape),
                "The puzzle interpreters disagree")
        return tape

    verify(original)
    seed = 1731 + int(args.id[-4:]) * 73
    report = dict(id=args.id, lane=args.lane, part=parts[0], parent_commit=commit, parent_file_sha256=design["parent"],
                  parent_origin=credit, official_lf_sha256=normalized, before=len(original), seed=seed,
                  interpreters=["elf.check", "collaboration/polish/replay.py:run_program"])
    cache, choices, traces, calls = {}, [], [], []
    with tempfile.TemporaryDirectory(dir=args.scratch) as scratch:
        exes = binaries(args, repo, Path(scratch))
        import reorder
        reorder.HERE = exes["order"].parent
        if args.allocation_control:
            report["synthetic_allocation_control"] = allocation_control(second)
        report["binary_sha256"] = {name: digest(f.read_bytes()) for name, f in exes.items()}
        def transform(name, tape):
            if name == "group":
                result, counters = native_group(exes[name], puzzle, tape, seed)
                calls.append(dict(method=name, before=len(tape), after=len(result), native=counters))
                return result
            if name == "exchange":
                return run_row(puzzle, tape, exes[name], 192, 96, 2, 0, reschedule=.2)[1]
            if name == "factor":
                return optimize(puzzle, tape, exes[name], 36, 64, False, 32, True)[1]
            source = [list(s) for s in tape]
            out, _ = solve(raw, [source], budget=.32, helpers=0, extra=paid_alternatives(raw, source, 24))
            return out

        for order in ORDERS:
            tape, changes = original, []
            while True:
                initial = len(tape)
                for name in order:
                    key = name, tape
                    if key not in cache:
                        offer = tuple(tuple(s) for s in transform(name, tape))
                        cache[key] = verify(offer)
                    offer = cache[key]
                    if len(offer) < len(tape):
                        changes.append([name, len(tape), len(offer)])
                        tape = offer
                if len(tape) == initial:
                    break
            choices.append(tape)
            traces.append(changes)
    winner = verify(min(choices, key=len))
    report.update(after=len(winner), forward=len(choices[0]), reverse=len(choices[1]), traces=traces,
                  evaluated_offers=len(cache), group_calls=calls,
                  program_sha256=digest(json.dumps(winner, separators=(",", ":")).encode()))
    history = repo / "collaboration/wang-polish" / f"{args.lane}-{parts[0]}.json"
    if history.is_file():
        recorded = json.loads(history.read_bytes())
        checked(recorded["parent"] == design["parent"], "Published comparison uses another input")
        old = recorded["rows"].get(args.id)
        if old is not None:
            report["published"] = dict((k, old[k]) for k in ("before", "after", "forward", "reverse", "traces"))
            report["matches_published"] = all(report[k] == val for k, val in report["published"].items())
            saved = history.with_suffix(".csv")
            if saved.is_file() and old["after"] < old["before"]:
                recorded_winner = verify(read_submission(saved)[args.id])
                report["published_program_sha256"] = digest(json.dumps(recorded_winner, separators=(",", ":")).encode())
                report["matches_published_program"] = recorded_winner == winner
    if args.output:
        write_submission(args.output, [puzzle], {args.id: winner})
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.report:
        args.report.write_bytes((text + "\n").encode())
    print(text)


if __name__ == "__main__":
    main()
