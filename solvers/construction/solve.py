"""Run construction and portfolio experiments, with exact replay before publication."""

import argparse
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from solvers.construction.construct import construct_candidates
from elf import read_puzzles, read_submission, score, write_submission


def make_program(task):
    puzzle, wide = task
    candidates = construct_candidates(puzzle, wide)
    return puzzle.id, candidates[0] if candidates else None


def build(args):
    puzzle_set = read_puzzles(args.puzzles)
    fallback = read_submission(args.reference) if args.reference else {}
    if args.reference:
        score(puzzle_set, fallback)
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        results = pool.map(make_program, ((puzzle, args.wide) for puzzle in puzzle_set), chunksize=2)
        programs = {}
        for identifier, program in results:
            if identifier in fallback and (program is None or len(fallback[identifier]) < len(program)):
                program = fallback[identifier]
            if program is None:
                raise RuntimeError(f"could not synthesize a program for {identifier}")
            programs[identifier] = program
    return write_submission(args.output, puzzle_set, programs)


def merge(args):
    puzzles = read_puzzles(args.puzzles)
    best = {}
    for path in args.candidates:
        programs = read_submission(path)
        total = score(puzzles, programs)
        improvements = 0
        for identifier, program in programs.items():
            if identifier not in best or len(program) < len(best[identifier]):
                best[identifier] = program
                improvements += 1
        print(f"{path}: {total} instructions; selected {improvements} rows")
    return write_submission(args.output, puzzles, best)


def main():
    command = argparse.ArgumentParser(description=__doc__)
    subcommands = command.add_subparsers(required=True)
    constructor = subcommands.add_parser("construct")
    constructor.add_argument("puzzles", type=Path)
    constructor.add_argument("output", type=Path)
    constructor.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 1))
    constructor.add_argument("--wide", action="store_true")
    constructor.add_argument("--reference", type=Path)
    constructor.set_defaults(handler=build)
    portfolio = subcommands.add_parser("merge")
    portfolio.add_argument("puzzles", type=Path)
    portfolio.add_argument("output", type=Path)
    portfolio.add_argument("candidates", nargs="+", type=Path)
    portfolio.set_defaults(handler=merge)
    args = command.parse_args()
    start = time.monotonic()
    total = args.handler(args)
    print(json.dumps({"instructions": total, "seconds": round(time.monotonic() - start, 2),
                      "output": str(args.output)}))


if __name__ == "__main__":
    main()
