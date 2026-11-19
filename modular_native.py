"""Build and verify programs with the native modular-residue constructor."""

import argparse
import os
import subprocess
import tempfile
import time
from pathlib import Path

from dictionary import warm_recipes
from elf import read_puzzles, read_submission, score, sha256, write_submission
from graph import compile_graph


ROOT = Path(__file__).resolve().parent


def prepare() -> Path:
    build = Path(os.environ.get("SANTA_BUILD_DIR", ROOT / "work"))
    build.mkdir(exist_ok=True)
    source = ROOT / "ModularSearch.cs"
    executable = build / f"modular-{sha256(source)[:12]}.exe"
    if not executable.exists():
        compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
        with tempfile.TemporaryDirectory(dir=build, prefix="modular-build-") as temporary:
            compiled = Path(temporary) / executable.name
            subprocess.run([str(compiler), "/nologo", "/optimize+", "/platform:x64",
                            f"/out:{compiled}", str(source)], check=True,
                           env={**os.environ, "TEMP": temporary, "TMP": temporary})
            try:
                compiled.rename(executable)
            except FileExistsError:
                pass
    return executable


def construct_native(
    puzzles, executable: Path, width: int, depth: int, span: int, jobs: int,
    direction: str, baseline=None, warm_quota: int = 0, profile: str = "even",
    schedule_width: int = 0,
):
    lines = []
    for puzzle in puzzles:
        seeds = ",".join(map(str, puzzle.seeds))
        targets = ",".join(map(str, puzzle.targets))
        warm = warm_recipes(puzzle, baseline[puzzle.id], warm_quota) if warm_quota else {}
        recipes = ";".join(f"{value},{op},{left},{right}"
                           for value, (op, left, right) in warm.items())
        lines.append("\t".join((puzzle.id, str(puzzle.limit), seeds, targets, recipes)))
    run = subprocess.run(
        [str(executable), str(width), str(depth), str(span), str(jobs), direction, profile],
        input="\n".join(lines) + "\n", text=True, stdout=subprocess.PIPE, check=True,
    )
    raw = run.stdout.splitlines()
    if len(raw) != len(puzzles):
        raise ValueError(f"expected {len(puzzles)} native graphs, received {len(raw)}")
    result = {}
    for puzzle, row in zip(puzzles, raw, strict=True):
        identifier, *cells = row.split("\t")
        if identifier != puzzle.id:
            raise ValueError(f"native solver returned {identifier} for {puzzle.id}")
        graph = {}
        for cell in cells:
            value, operator, left, right = cell.split(",")
            graph[int(value)] = (operator, int(left), int(right))
        program = compile_graph(puzzle, graph, recompute=True, schedule_width=schedule_width)
        if program is not None:
            result[identifier] = program
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("puzzles", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--min-count", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--width", type=int, default=7)
    parser.add_argument("--depth", type=int, default=4)
    parser.add_argument("--span", type=int, default=12)
    parser.add_argument("--jobs", type=int, default=5)
    parser.add_argument("--direction", nargs="+", choices=("forward", "reverse", "greedy"),
                        default=("forward",))
    parser.add_argument("--warm-quota", type=int, default=0)
    parser.add_argument("--radix-profile", choices=("even", "tuned"), default="even")
    parser.add_argument("--schedule-width", type=int, default=0)
    args = parser.parse_args()
    if args.width < 1 or args.depth < 0 or args.span < 1 or args.jobs < 1:
        parser.error("width, span, and jobs must be positive, and depth nonnegative")
    if (args.min_count or args.limit is not None or args.warm_quota) and args.baseline is None:
        parser.error("a complete baseline is required for filtering or warm recipes")

    puzzles = read_puzzles(args.puzzles)
    best = read_submission(args.baseline) if args.baseline else {}
    if best:
        print(f"Validated baseline {score(puzzles, best)}", flush=True)
    selection = (
        sorted((p for p in puzzles if len(best[p.id]) >= args.min_count),
               key=lambda puzzle: -len(best[puzzle.id]))[:args.limit]
        if best else puzzles
    )
    if not selection:
        write_submission(args.output, puzzles, best)
        return
    print(f"Selected {len(selection)} puzzles", flush=True)
    executable = prepare()
    for direction in args.direction:
        start = time.monotonic()
        programs = construct_native(selection, executable, args.width, args.depth, args.span, args.jobs,
                                    direction, best, args.warm_quota, args.radix_profile,
                                    args.schedule_width)
        savings = 0
        selected = 0
        for identifier, program in programs.items():
            previous = best.get(identifier)
            if previous is None or len(previous) > len(program):
                selected += 1
                savings += 0 if previous is None else len(previous) - len(program)
                best[identifier] = program
        failed = len(selection) - len(programs)
        print(f"{direction}: {len(programs)} compiled, {failed} unscheduled, "
              f"{selected} selected, {savings} instructions saved in {time.monotonic() - start:.1f}s",
              flush=True)
        if len(best) == len(puzzles):
            print(f"{write_submission(args.output, puzzles, best)} instructions in {args.output}", flush=True)
    if len(best) != len(puzzles):
        raise RuntimeError(f"no valid programs for {len(puzzles) - len(best)} puzzles")


if __name__ == "__main__":
    main()
