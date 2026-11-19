"""Build documented public arithmetic synthesizers and verify freshly generated programs."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
WORK = ROOT / "work" / "gen"
sys.path.insert(0, str(ROOT))
from elf import check, read_puzzles, read_submission, score, sha256, write_submission
from graph import first_recipes

SOURCES = {
    "tony": ("tony.cpp", "c++17", ("3",)),
    "konbu": ("konbu.cpp", "c++17", ("10", ".18", "72", "88", "24")),
    "arsen-base": ("recovered/solver.cpp", "c++17", ("3", "64", ".18", "0", "0")),
    "arsen": ("arsen.cpp", "c++17", ("3", "128", ".18", "0", "100", "32")),
    "arsen-fast": ("arsen_v4/solver_fast.cpp", "c++17", ("2", "0")),
    "arsen-depth4": ("arsen_current/solver_depth4.cpp", "c++17", ("2", "0")),
    "arsen-joint": ("arsen_v7/solver_joint.cpp", "c++17", ("2","0")),
    "juan": ("juan.cpp", "c++17", ("10", ".18", "72", "88", "24", "0", "0")),
    "rudolph": ("rudolph.cpp", "c++17", ("20", ".18", "60", "80", "16", "40", "1")),
    "rank-samples": ("rank_samples.cpp", "c++17", ()),
    "parallels": ("parallels.cpp", "c++17", ()),
    "trajectory": ("trajectory.cpp", "c++17", ("3","5","2","64","6")),
    "reverse-set": ("reverse_set.cpp", "c++17", ("3","7","2","60","12")),
    "atlas": ("atlas.cpp", "c++20", ()),
    "atakan-frontier": ("atakan_v15/elf_multiplier_frontier.cpp", "c++17", ("2", "6", "4", "6", "4", "257")),
    "atakan-whole": ("atakan_v15/elf_whole_graph.cpp", "c++17", ("18", "2", "300", "3", "2", "257")),
    "atakan-window": ("atakan_v15/elf_window.cpp", "c++17", ("12", "4")),
}


def compiler_path(explicit):
    if explicit is not None:
        return str(explicit.resolve())
    local = WORK / "toolchain" / "mingw64" / "bin" / "g++.exe"
    if local.is_file():
        return str(local)
    compiler = shutil.which("g++")
    if compiler is None:
        raise FileNotFoundError("g++ is required; specify its path with --compiler")
    return compiler


def compile_engine(engine, compiler):
    WORK.mkdir(parents=True, exist_ok=True)
    filename, std, _ = SOURCES[engine]
    source = HERE / filename
    hashes = {filename: sha256(source)}
    if engine == "atlas":
        hashes["atlas_splice.hpp"] = sha256(HERE / "atlas_splice.hpp")
    if engine in ("rudolph","rank-samples","trajectory","reverse-set"):
        hashes["residual_rank.hpp"] = sha256(HERE / "residual_rank.hpp")
    if engine in ("rank-samples","trajectory","reverse-set"):
        hashes["rudolph.cpp"] = sha256(HERE / "rudolph.cpp")
    if engine == "reverse-set":
        hashes["trajectory.cpp"] = sha256(HERE / "trajectory.cpp")
    if engine == "arsen":
        hashes["recovered/solver.cpp"] = sha256(HERE / "recovered/solver.cpp")
    if engine in ("arsen-fast", "arsen-depth4"):
        name = (source.parent / "recovered" / "solver.cpp").relative_to(HERE).as_posix()
        hashes[name] = sha256(HERE / name)
    if engine == "arsen-joint":
        for part in ("arsen_v7/solver_fast.cpp","arsen_v7/recovered/solver.cpp"):
            hashes[part]=sha256(HERE / part)
    if engine.startswith("atakan-"):
        for part in sorted(source.parent.iterdir()):
            if part.suffix in (".cpp", ".h") and part != source:
                hashes[part.relative_to(HERE).as_posix()] = sha256(part)
    architecture = "-march=x86-64" if os.name == "nt" else "-march=native"
    flags = ["-O3", architecture, "-pthread", f"-std={std}"]
    if os.name == "nt":
        flags.append("-static")
    recipe = json.dumps([hashes, flags], sort_keys=True).encode("utf8")
    token = hashlib.sha256(recipe).hexdigest()[:18]
    stem = engine + "-" + token + (".exe" if os.name == "nt" else "")
    target = WORK / stem
    if not target.is_file():
        with tempfile.TemporaryDirectory(dir=WORK, prefix="compile-") as scratch:
            pending = Path(scratch) / target.name
            subprocess.run([compiler, *flags, str(source), "-o", str(pending)],
                           check=True, env={**os.environ, "TEMP": scratch, "TMP": scratch},
                           cwd=WORK)
            if not target.is_file():
                try:
                    pending.rename(target)
                except FileExistsError:
                    pass
    return target, hashes, flags


def shared_order(puzzle, program, strength):
    graph = first_recipes(puzzle, program)
    closure = {v: set() for v in puzzle.seeds}
    for value, (_, a, b) in graph.items():
        closure[value] = closure[a] | closure[b] | {value}
    remaining = list(puzzle.targets)
    result = []
    paid = set()
    while remaining:
        frequency = {}
        for target in remaining:
            for v in closure[target] - paid:
                frequency[v] = frequency.get(v, 0) + 1
        def marginal(target):
            needs = closure[target] - paid
            # Prefer known short prefixes when prices tie. A helper needed by
            # several future targets merits a discount at the first purchase.
            return sum(1 / (1 + strength * math.log2(frequency[v])) for v in needs), target
        chosen = min(remaining, key=marginal)
        result.append(chosen)
        paid.update(closure[chosen])
        remaining.remove(chosen)
    return result


def solve_stream(binary, config, batch, hints, target_order, seed, ordered=None):
    inputs = []
    for puzzle in batch:
        targets = list(puzzle.targets)
        if target_order == "reverse":
            targets.reverse()
        if target_order == "shuffled":
            random.Random(f"{seed}:{puzzle.id}").shuffle(targets)
        if ordered is not None:
            targets = ordered[puzzle.id]
        row = [puzzle.id, puzzle.limit, len(puzzle.seeds), len(targets), *puzzle.seeds, *targets]
        if hints is not None:
            program = hints[puzzle.id]
            row.append(len(program))
            row.extend(piece for step in program for piece in step)
        inputs.append(" ".join(map(str, row)))
    result = subprocess.run([str(binary), *config], input="\n".join(inputs) + "\n",
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            encoding="utf8", cwd=WORK)
    if result.returncode:
        labels = ", ".join(puzzle.id for puzzle in batch)
        raise RuntimeError(f"engine exited with status {result.returncode} on {labels}; "
                           f"{result.stderr[-700:].strip()}")
    rows = result.stdout.splitlines()
    if len(rows) != len(batch):
        raise RuntimeError(f"expected output for {len(batch)} puzzles, received {len(rows)}")
    programs = {}
    for puzzle, row in zip(batch, rows, strict=True):
        identifier, raw = row.split(" ", 1)
        if identifier != puzzle.id:
            raise RuntimeError(f"unexpected response {identifier} for {puzzle.id}")
        program = tuple(tuple(step) for step in json.loads(raw))
        check(puzzle, program)
        programs[identifier] = program
    return programs


def run_atlas(binary, source, puzzles, jobs):
    selected = {p.id for p in puzzles}
    with tempfile.TemporaryDirectory(dir=WORK, prefix="atlas-") as scratch:
        puzzle_path = Path(scratch) / "puzzles.csv"
        candidate = Path(scratch) / "result.csv"
        with source.open(encoding="utf-8-sig", newline="") as input_file, \
             puzzle_path.open("w", encoding="utf-8", newline="") as selected_file:
            reader = csv.DictReader(input_file)
            writer = csv.DictWriter(selected_file, fieldnames=reader.fieldnames, lineterminator="\n")
            writer.writeheader()
            writer.writerows(row for row in reader if row["id"] in selected)
        subprocess.run([str(binary), str(puzzle_path), str(candidate), str(jobs)],
                       check=True, cwd=WORK)
        programs = read_submission(candidate)
        score(puzzles, programs)
        return programs


def rewrite_atakan(binary, config, batch, hints):
    lines = []
    for puzzle in batch:
        program = hints[puzzle.id]
        header = [puzzle.id, puzzle.limit, len(puzzle.seeds), len(puzzle.targets), len(program)]
        lines.append(" ".join(map(str, [*header, *puzzle.seeds, *puzzle.targets])))
        lines.extend(" ".join(map(str, step)) for step in program)
    result = subprocess.run([str(binary), *config], input="\n".join(lines) + "\n",
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf8", cwd=WORK)
    if result.returncode:
        raise RuntimeError(f"optimizer exited {result.returncode}: {result.stderr[-700:]}")
    rows = iter(result.stdout.splitlines())
    programs = {}
    for puzzle in batch:
        header = next(rows, "").split()
        if len(header) < 2 or header[0] != puzzle.id:
            raise ValueError(f"wrong optimizer header for {puzzle.id}")
        length = int(header[1])
        if not 0 <= length <= len(hints[puzzle.id]):
            raise ValueError(f"{puzzle.id}: optimizer regressed")
        program = []
        for _ in range(length):
            op, a, b, d = next(rows, "").split()
            program.append((op, int(a), int(b), int(d)))
        candidate = tuple(program)
        check(puzzle, candidate)
        programs[puzzle.id] = candidate
    if next(rows, None) is not None:
        raise ValueError("unexpected optimizer output after final puzzle")
    return programs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engine", choices=[name for name in SOURCES if name not in ("rank-samples","parallels")])
    parser.add_argument("puzzles", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--compiler", type=Path)
    parser.add_argument("--exe", type=Path, help="Use an already compiled local binary")
    parser.add_argument("--jobs", type=int, default=6)
    parser.add_argument("--batch", type=int, default=2)
    parser.add_argument("--limit", type=int, help="Evaluate a spread-out subset of this size")
    parser.add_argument("--ids", type=Path, help="Evaluate only these puzzle IDs, one per line")
    parser.add_argument("--config", nargs="+")
    parser.add_argument("--target-order", choices=("input", "reverse", "shuffled"), default="input")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--order-trace", type=Path,
                        help="Order targets from dependency overlap in a locally generated graph")
    parser.add_argument("--shared-weight", type=float, default=1.0)
    parser.add_argument("--own-trace", type=Path, help="A program generated previously in this experiment")
    parser.add_argument("--resume-from", type=Path,
                        help="Reuse the exactly validated rows of an earlier local generation run")
    args = parser.parse_args()
    if args.jobs < 1 or args.batch < 1 or args.limit is not None and args.limit < 1:
        parser.error("jobs, batch size and limit must be positive")
    if args.ids and args.limit is not None:
        parser.error("choose --ids or --limit")
    if args.order_trace and args.target_order != "input":
        parser.error("choose either --order-trace or --target-order")
    if args.shared_weight < 0 or not math.isfinite(args.shared_weight):
        parser.error("shared weight must be finite and nonnegative")
    if args.engine == "atlas" and (args.config or args.own_trace or args.order_trace or args.target_order != "input"):
        parser.error("Atlas runs in standalone mode")
    is_atakan = args.engine.startswith("atakan-")
    if (args.engine in ("arsen-fast","arsen-depth4","arsen-joint","trajectory","reverse-set") or is_atakan) and args.own_trace is None:
        parser.error(f"{args.engine} requires a locally generated --own-trace")
    if is_atakan and (args.order_trace or args.target_order != "input"):
        parser.error("Atakan rewrites a fixed trace and keeps the target list in official order")

    puzzles = read_puzzles(args.puzzles)
    if args.ids:
        selected = set(args.ids.read_text(encoding="utf-8-sig").split())
        unknown = selected - {p.id for p in puzzles}
        if unknown or not selected:
            parser.error(f"invalid selection: {len(unknown)} unknown IDs")
        puzzles = [p for p in puzzles if p.id in selected]
    elif args.limit is not None and args.limit < len(puzzles):
        puzzles = [puzzles[i * len(puzzles) // args.limit] for i in range(args.limit)]

    hints = None
    hints_digest = None
    ordered = None
    order_digest = None
    if args.order_trace:
        WORK.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=WORK, prefix="order-") as directory:
            source = Path(directory) / "source.csv"
            content = args.order_trace.read_bytes()
            source.write_bytes(content)
            order_digest = hashlib.sha256(content).hexdigest()
            paths = read_submission(source)
        ordered = {p.id: shared_order(p, paths[p.id], args.shared_weight) for p in puzzles}
    if args.own_trace:
        with tempfile.TemporaryDirectory(dir=WORK, prefix="trace-") as directory:
            source = Path(directory) / "source.csv"
            content = args.own_trace.read_bytes()
            source.write_bytes(content)
            hints_digest = hashlib.sha256(content).hexdigest()
            hints = read_submission(source)
        score(puzzles, {p.id: hints[p.id] for p in puzzles})
    programs = {}
    resume_hash = None
    if args.resume_from:
        programs = read_submission(args.resume_from)
        score([p for p in puzzles if p.id in programs], programs)
        resume_hash = sha256(args.resume_from)
    resumed = len(programs)
    remaining = [puzzle for puzzle in puzzles if puzzle.id not in programs]
    config = args.config or SOURCES[args.engine][2]
    WORK.mkdir(parents=True, exist_ok=True)
    if args.exe:
        binary = args.exe.resolve()
        hashes, flags = {}, []
    else:
        binary, hashes, flags = compile_engine(args.engine, compiler_path(args.compiler))

    start = time.monotonic()
    fallback_ids = []
    if args.engine == "atlas" and remaining:
        programs.update(run_atlas(binary, args.puzzles.resolve(), remaining, args.jobs))
    elif remaining:
        with ThreadPoolExecutor(max_workers=args.jobs) as executor:
            batches = [remaining[i:i + args.batch] for i in range(0, len(remaining), args.batch)]
            if is_atakan:
                tasks = {executor.submit(rewrite_atakan, binary, config, batch, hints): batch for batch in batches}
            else:
                tasks = {executor.submit(solve_stream, binary, config, batch, hints,
                                         args.target_order, args.seed, ordered): batch for batch in batches}
            next_report = resumed + 25
            for task in as_completed(tasks):
                try:
                    programs.update(task.result())
                except (RuntimeError, ValueError) as error:
                    if hints is None:
                        raise
                    print(f"retained validated local trace: {error}", flush=True)
                    for puzzle in tasks[task]:
                        programs[puzzle.id] = hints[puzzle.id]
                        fallback_ids.append(puzzle.id)
                if len(programs) >= next_report:
                    complete = [p for p in puzzles if p.id in programs]
                    total = write_submission(args.output, complete, programs)
                    print(f"{len(programs)}/{len(puzzles)} verified, {total} steps, "
                          f"{time.monotonic() - start:.1f}s", flush=True)
                    next_report += 25
    total = write_submission(args.output, puzzles, programs)
    report = {
        "engine": args.engine,
        "rows": len(puzzles),
        "resumed_rows": resumed,
        "instructions": total,
        "seconds": round(time.monotonic() - start, 2),
        "configuration": list(config),
        "target_order": args.target_order,
        "order_trace_sha256": order_digest,
        "shared_weight": args.shared_weight if args.order_trace else None,
        "seed": args.seed,
        "compiler_flags": flags,
        "source_sha256": hashes,
        "input_sha256": sha256(args.puzzles),
        "output_sha256": sha256(args.output),
        "binary_sha256": sha256(binary),
        "own_intermediate_trace_sha256": hints_digest,
        "own_resume_sha256": resume_hash,
        "retained_trace_ids": sorted(fallback_ids),
    }
    args.output.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
