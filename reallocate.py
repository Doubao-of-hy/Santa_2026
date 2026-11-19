"""Improve register allocation and remove provably unused intermediate instructions."""

import argparse
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from elf import read_puzzles, read_submission, score, write_submission
from graph import active_graph, compile_graph, first_recipes


def allocate(task):
    puzzle, original, width, operation_width, minimum_gap = task
    graph = first_recipes(puzzle, original)
    gap = len(original) - len(active_graph(puzzle, graph))
    if gap < minimum_gap:
        return puzzle.id, original, 0
    candidate = compile_graph(puzzle, graph, attempts=8, recompute=True, schedule_width=width,
                              operation_width=operation_width)
    if candidate is None or len(candidate) >= len(original):
        return puzzle.id, original, 0
    return puzzle.id, candidate, len(original) - len(candidate)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("puzzles", type=Path)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--jobs", type=int, default=min(6, os.cpu_count() or 1))
    parser.add_argument("--schedule-width", type=int, default=8)
    parser.add_argument("--operation-width", type=int, default=0)
    parser.add_argument("--minimum-gap", type=int, default=1)
    args = parser.parse_args()
    puzzles = read_puzzles(args.puzzles)
    programs = read_submission(args.input)
    before = score(puzzles, programs)
    improved = 0
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        for identifier, program, savings in pool.map(
                allocate, ((puzzle, programs[puzzle.id], args.schedule_width,
                            args.operation_width, args.minimum_gap)
                           for puzzle in puzzles), chunksize=3):
            programs[identifier] = program
            improved += savings > 0
    after = write_submission(args.output, puzzles, programs)
    print(f"{before} -> {after} instructions; {improved} puzzles improved")


if __name__ == "__main__":
    main()
