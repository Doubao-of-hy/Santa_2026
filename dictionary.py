"""Compile and run the mixed-radix dictionary search."""

import argparse
import os
import subprocess
import time
import uuid
from collections import Counter
from pathlib import Path

from elf import check, read_puzzles, read_submission, score, sha256, write_submission
from graph import active_graph, compile_graph, first_recipes

ROOT = Path(__file__).resolve().parent
BUILD = Path(os.environ.get("SANTA_BUILD_DIR", ROOT / "work"))


def prepare():
    BUILD.mkdir(exist_ok=True)
    source = ROOT / "DictionarySearch.cs"
    executable = BUILD / f"dictionary-{sha256(source)[:12]}.exe"
    if not executable.exists():
        compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
        temporary = BUILD / f"compile-{uuid.uuid4().hex}.exe"
        try:
            subprocess.run([str(compiler), "/nologo", "/optimize+", "/platform:x64",
                            f"/out:{temporary}", str(source)], check=True,
                           env={**os.environ, "TEMP": str(BUILD), "TMP": str(BUILD)})
            try:
                temporary.rename(executable)
            except FileExistsError:
                pass
        finally:
            temporary.unlink(missing_ok=True)
    return executable


def warm_recipes(puzzle, program, quota):
    graph = active_graph(puzzle, first_recipes(puzzle, program))
    counts = Counter(value for recipe in graph.values() for value in set(recipe[1:]))
    seeds = set(puzzle.seeds)
    selected = {}
    for value in sorted(graph, key=lambda n: (-counts[n], n.bit_length(), n)):
        if counts[value] < 2:
            break
        pending = [value]
        dependencies = set()
        while pending:
            node = pending.pop()
            if node in seeds or node in selected or node in dependencies:
                continue
            dependencies.add(node)
            pending.extend(graph[node][1:])
        if len(dependencies) + len(selected) <= quota:
            selected.update((node, graph[node]) for node in graph if node in dependencies)
    return selected


def find_programs(puzzles, variant, width, depth, jobs, executable, warm=None, quota=38, hints=None,
                  schedule_width=0):
    rows = []
    by_id = {puzzle.id: puzzle for puzzle in puzzles}
    for puzzle in puzzles:
        seeds = ",".join(map(str, puzzle.seeds))
        targets = ",".join(map(str, puzzle.targets))
        roots = ""
        if warm is not None and puzzle.id in warm:
            recipes = warm_recipes(puzzle, warm[puzzle.id], quota)
            roots = ";".join(f"{v},{op},{a},{b}" for v, (op, a, b) in recipes.items())
        factorizations = ""
        if hints is not None:
            factorizations = ";".join(f"{target},{a},{b},{r}" for target, splits in hints[puzzle.id].items()
                                      for a, b, r in splits)
        rows.append(f"{puzzle.id}\t{puzzle.limit}\t{seeds}\t{targets}\t{roots}\t{factorizations}"
                    f"\t{puzzle.registers}\n")
    process = subprocess.run([str(executable), str(variant), str(width), str(depth), str(jobs)],
                             input="".join(rows), text=True, stdout=subprocess.PIPE, check=True)
    programs = {}
    unscheduled = []
    for row in process.stdout.splitlines():
        identifier, *instructions = row.split("\t")
        if instructions[:1] == ["!"]:
            unscheduled.append(identifier)
            continue
        if instructions[:1] == ["@"]:
            decoded = [instruction.split(",") for instruction in instructions[1:]]
            program = tuple((op, int(left), int(right), int(dest)) for op, left, right, dest in decoded)
            check(by_id[identifier], program)
            programs[identifier] = program
            continue
        graph = {}
        for instruction in instructions:
            out, op, a, b = instruction.split(",")
            graph[int(out)] = (op, int(a), int(b))
        program = compile_graph(by_id[identifier], graph, recompute=True, schedule_width=schedule_width)
        if program is None:
            unscheduled.append(identifier)
        else:
            programs[identifier] = program
    if len(programs) + len(unscheduled) != len(by_id):
        raise ValueError("native search did not return one graph per puzzle")
    return programs, unscheduled


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("puzzles", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--fallback", type=Path)
    parser.add_argument("--warm", action="store_true", help="Reuse helpers from the current best program")
    parser.add_argument("--quota", type=int, default=38)
    parser.add_argument("--factor-hints", type=int, default=0, metavar="WIDTH")
    parser.add_argument("--scale-hints", type=int, default=0, metavar="WIDTH")
    parser.add_argument("--independent", action="store_true",
                        help="Only search the independent-shaped puzzles, using a complete fallback")
    parser.add_argument("--pilot", type=int, default=0, metavar="PUZZLES")
    parser.add_argument("--focus", choices=("even", "expensive"), default="even")
    parser.add_argument("--variants", nargs="+", type=int, default=[0])
    parser.add_argument("--width", type=int, default=6)
    parser.add_argument("--depth", type=int, default=2)
    parser.add_argument("--jobs", type=int, default=6)
    parser.add_argument("--schedule-width", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=80,
                        help="Validate and checkpoint after each group of puzzles")
    args = parser.parse_args()
    if (args.width < 1 or args.depth < 0 or args.jobs < 1 or args.batch_size < 1
            or args.schedule_width < 0 or any(variant < 0 for variant in args.variants)):
        parser.error("invalid search width, depth, worker count, batch size, or variant")
    puzzles = read_puzzles(args.puzzles)
    best = read_submission(args.fallback) if args.fallback else {}
    if best:
        score(puzzles, best)
    if (args.pilot or args.independent) and not best:
        parser.error("--pilot and --independent require a complete --fallback")
    selection = puzzles
    if args.independent:
        from factorization import independent_shape
        selection = [puzzle for puzzle in selection if independent_shape(puzzle)]
    if args.pilot:
        if args.focus == "expensive":
            selection = sorted(selection, key=lambda p: -len(best[p.id]))[:args.pilot]
        else:
            selection = selection[::max(1, len(selection) // args.pilot)][:args.pilot]
    executable = prepare()
    hints = None
    if args.factor_hints or args.scale_hints:
        from factorization import factor_hints, scale_hints
        print("Computing arithmetic hints", flush=True)
        hints = {}
        for puzzle in selection:
            factors = factor_hints(puzzle, args.factor_hints) if args.factor_hints else {}
            scales = scale_hints(puzzle, args.scale_hints) if args.scale_hints else {}
            for target, recipes in scales.items():
                factors[target] = list(dict.fromkeys(factors.get(target, []) + recipes))
            hints[puzzle.id] = factors
    batches = [selection[offset:offset + args.batch_size]
               for offset in range(0, len(selection), args.batch_size)]
    for variant in args.variants:
        start = time.monotonic()
        compiled = unscheduled = replaced = savings = 0
        for batch in batches:
            programs, failed = find_programs(batch, variant, args.width, args.depth, args.jobs,
                                             executable, best if args.warm else None, args.quota,
                                             hints, args.schedule_width)
            compiled += len(programs)
            unscheduled += len(failed)
            for identifier, program in programs.items():
                previous = best.get(identifier)
                if previous is None or len(program) < len(previous):
                    best[identifier] = program
                    replaced += 1
                    if previous is not None:
                        savings += len(previous) - len(program)
            if len(best) == len(puzzles):
                total = write_submission(args.output, puzzles, best)
                print(f"variant {variant}, {compiled + unscheduled}/{len(selection)}: "
                      f"{total} verified instructions", flush=True)
        print(f"variant {variant}: {compiled} compiled, {unscheduled} unscheduled, "
              f"{replaced} selected, {savings} instructions saved, {time.monotonic() - start:.1f}s",
              flush=True)
    if not batches and best:
        write_submission(args.output, puzzles, best)
    if len(best) != len(puzzles):
        raise RuntimeError(f"no valid programs for {len(puzzles) - len(best)} puzzles")


if __name__ == "__main__":
    main()
