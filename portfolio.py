"""Publish the shortest locally verified candidate for each puzzle."""

import argparse
import json
from collections import Counter
from pathlib import Path

from elf import check, read_puzzles, read_submission, score, sha256, write_submission
from tiny import solve_tiny


def select(puzzles, paths, exact=True):
    best = {}
    sources = {}
    references = {}
    for path in paths:
        candidate = read_submission(path)
        references[path.name] = {"steps": score(puzzles, candidate), "sha256": sha256(path)}
        for identifier, program in candidate.items():
            if identifier not in best or len(program) < len(best[identifier]):
                best[identifier] = program
                sources[identifier] = path.name
    exact_ids = []
    if exact:
        for puzzle in puzzles:
            optimum = solve_tiny(puzzle)
            if optimum is None:
                continue
            check(puzzle, optimum)
            if len(optimum) > len(best[puzzle.id]):
                raise RuntimeError(f"exact result is longer than a reference for {puzzle.id}")
            best[puzzle.id] = optimum
            sources[puzzle.id] = "exact"
            exact_ids.append(puzzle.id)
    return best, sources, references, exact_ids


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("puzzles", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("candidates", nargs="+", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--no-exact", action="store_true")
    args = parser.parse_args()
    if args.report and args.report.resolve() == args.output.resolve():
        parser.error("--report and output must be different files")
    puzzles = read_puzzles(args.puzzles)
    best, sources, references, exact = select(puzzles, args.candidates, not args.no_exact)
    total = write_submission(args.output, puzzles, best)
    report = {
        "puzzles": len(puzzles), "instructions": total, "sha256": sha256(args.output),
        "puzzles_sha256": sha256(args.puzzles),
        "longest_program": max(map(len, best.values())),
        "arithmetic_lower_bound": sum(len(set(p.targets) - set(p.seeds)) for p in puzzles),
        "exact_puzzles": len(exact), "exact_steps": sum(len(best[identifier]) for identifier in exact),
        "selected": Counter(sources.values()), "inputs": references,
    }
    summary = json.dumps(report, indent=2)
    if args.report:
        args.report.write_text(summary + "\n", encoding="utf-8")
    print(summary)


if __name__ == "__main__":
    main()
