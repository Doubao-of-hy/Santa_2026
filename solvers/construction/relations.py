"""Shorten an existing calculator program by re-synthesizing its dependency graph."""

import argparse
from collections.abc import Callable
import concurrent.futures
import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from time import perf_counter

from elf import Program, Puzzle, check, read_puzzles, read_submission, score, write_submission


def build_executable(directory: Path) -> Path:
    framework = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64"
    compiler = shutil.which("csc") or framework / "v4.0.30319" / "csc.exe"
    source = Path(__file__).resolve().parents[2] / "solvers/native/RelationSearch.cs"
    executable = directory / "relation-search.exe"
    environment = dict(os.environ, TEMP=str(directory), TMP=str(directory))
    subprocess.run(
        [str(compiler), "/nologo", "/optimize+", "/platform:x64", f"/out:{executable}", str(source)],
        env=environment,
        check=True,
    )
    return executable


def optimize_batch(
    executable: Path,
    batch: list[tuple[Puzzle, Program]],
    depth: int,
    passes: int,
    neutral: int,
    additive: bool = False,
    product: bool = False,
    factor: bool = False,
    wide_bridges: bool = False,
    affine_only: bool = False,
) -> dict[str, Program]:
    lines = []
    for puzzle, program in batch:
        lines.extend((
            f"{puzzle.limit} {puzzle.registers} {len(program)}",
            " ".join(map(str, puzzle.seeds)),
            " ".join(map(str, puzzle.targets)),
        ))
        lines.extend(f"{op} {left} {right} {destination}" for op, left, right, destination in program)
    result = subprocess.run(
        [str(executable), str(depth), str(passes), str(neutral), str(additive),
         str(product), str(factor), str(wide_bridges), str(affine_only)],
        input="\n".join(lines) + "\n",
        capture_output=True,
        text=True,
        encoding="ascii",
        errors="replace",
    )
    if result.returncode:
        output = iter(result.stdout.splitlines())
        for puzzle, _ in batch:
            count = next(output, None)
            if count is None:
                break
            for _ in range(int(count)):
                next(output)
        raise RuntimeError(f"native relation search failed on {puzzle.id}\n{result.stderr}")
    output = iter(result.stdout.splitlines())
    improved = {}
    for puzzle, original in batch:
        count = int(next(output))
        instructions = []
        for _ in range(count):
            op, left, right, destination = next(output).split()
            instructions.append((op, int(left), int(right), int(destination)))
        if len(instructions) < len(original):
            candidate = tuple(instructions)
            check(puzzle, candidate)
            improved[puzzle.id] = candidate
    if next(output, None) is not None:
        raise ValueError("unexpected output from relation search")
    return improved


def optimize(
    puzzles: list[Puzzle],
    programs: dict[str, Program],
    work: Path,
    depth: int = 2,
    passes: int = 20,
    workers: int = 4,
    neutral: int = 0,
    checkpoint: Callable[[dict[str, Program], int], None] | None = None,
    additive: bool = False,
    product: bool = False,
    factor: bool = False,
    wide_bridges: bool = False,
    affine_only: bool = False,
) -> dict[str, Program]:
    work.mkdir(exist_ok=True, parents=True)
    jobs = sorted(
        ((puzzle, programs[puzzle.id]) for puzzle in puzzles),
        key=lambda entry: len(entry[1]),
        reverse=True,
    )
    result = programs.copy()
    with TemporaryDirectory(prefix="relations-", dir=work) as directory:
        executable = build_executable(Path(directory))
        workers = min(workers, len(jobs))
        batch_count = max(workers, (len(jobs) + 15) // 16) if checkpoint else workers
        completed = 0
        with concurrent.futures.ThreadPoolExecutor(workers) as executor:
            futures = {}
            for index in range(batch_count):
                batch = jobs[index::batch_count]
                future = executor.submit(optimize_batch, executable, batch, depth, passes,
                                         neutral, additive, product, factor, wide_bridges, affine_only)
                futures[future] = len(batch)
            for future in concurrent.futures.as_completed(futures):
                result.update(future.result())
                completed += futures[future]
                if checkpoint and (completed // 100 != (completed - futures[future]) // 100
                                   or completed >= len(jobs)):
                    checkpoint(result, completed)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("puzzles", type=Path)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--depth", type=int, choices=(0, 1, 2, 3, 4), default=2,
                        help="maximum steps in a one- or two-root replacement")
    parser.add_argument("--passes", type=int, default=20)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--sample", type=int, default=0)
    parser.add_argument("--checkpoint", action="store_true",
                        help="write the best full valid CSV every 100 completed puzzles")
    parser.add_argument("--neutral", type=int, default=0,
                        help="allow cost-neutral rewiring to expose later deletions")
    parser.add_argument("--additive", action="store_true",
                        help="reassociate additive expressions to share sums and differences")
    parser.add_argument("--product", action="store_true",
                        help="reassociate multiplicative expressions to share products")
    parser.add_argument("--factor", action="store_true",
                        help="extract common factors from signed sums of products")
    parser.add_argument("--wide-bridges", action="store_true",
                        help="try shared intermediates that require two instructions")
    parser.add_argument("--affine-only", action="store_true",
                        help="replace cones with four-instruction affine expressions only")
    args = parser.parse_args()
    if args.passes < 1 or args.workers < 1 or args.sample < 0 or args.neutral < 0:
        parser.error("passes and workers must be positive; sample and neutral must be nonnegative")
    puzzles = read_puzzles(args.puzzles)
    if args.sample:
        puzzles = puzzles[::max(1, len(puzzles) // args.sample)][:args.sample]
    programs = read_submission(args.baseline)
    programs = {puzzle.id: programs[puzzle.id] for puzzle in puzzles}
    before = score(puzzles, programs)
    start = perf_counter()

    def checkpoint(result: dict[str, Program], completed: int) -> None:
        total = write_submission(args.output, puzzles, result)
        print(json.dumps({"completed": completed, "instructions": total}), flush=True)

    result = optimize(puzzles, programs, args.output.parent, args.depth, args.passes,
                      args.workers, args.neutral, checkpoint if args.checkpoint else None,
                      args.additive, args.product, args.factor, args.wide_bridges, args.affine_only)
    after = write_submission(args.output, puzzles, result)
    improved = sum(len(result[key]) < len(program) for key, program in programs.items())
    print(json.dumps({
        "puzzles": len(puzzles),
        "baseline": before,
        "instructions": after,
        "saved": before - after,
        "improved": improved,
        "seconds": round(perf_counter() - start, 3),
    }))


if __name__ == "__main__":
    main()
