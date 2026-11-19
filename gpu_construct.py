"""Build a fresh graph in target order with shared GPU banks and a beam fallback."""

from __future__ import annotations

import argparse
import os
from collections import Counter
from pathlib import Path
from time import perf_counter

from construct import Constructor, binary_stream
from elf import Program, Puzzle, check, read_puzzles, read_submission, score, write_submission
from gpu_join import GPUJoin, anchors_for, decode, make_table
from graph import Graph, active_graph, compile_graph, first_recipes


def compile_target(puzzle: Puzzle, target: int, graph: Graph, quota: int, native, variant: int):
    from dictionary import find_programs

    seeds = anchors_for(puzzle, graph, graph, target, quota)
    reduced = Puzzle(puzzle.id, seeds, (target,), puzzle.limit, puzzle.registers)
    if native is not None:
        candidates, _ = find_programs([reduced], variant, 6, 2, 1, native)
        if reduced.id in candidates:
            return first_recipes(reduced, candidates[reduced.id])
    plans = []
    for base in (31, 127, 1024, 4096):
        fallback = Constructor(reduced, base, balanced=True, indirect=True)
        fallback.synthesize(target)
        plans.append(fallback.graph)
    return min(plans, key=len)


def grow(puzzle: Puzzle, gpu: GPUJoin, native, variant: int, quota: int, steps: int,
         raw_scales: int, statistics: Counter) -> Program:
    graph: Graph = {}
    anchors = set(puzzle.seeds)
    targets = sorted(set(puzzle.targets) - anchors)
    if not targets:
        return ()
    for offset in range(0, len(targets), steps):
        batch = targets[offset:offset + steps]
        leaves = anchors_for(puzzle, graph, graph, batch[-1], quota)
        now = perf_counter()
        table = make_table(leaves, puzzle.limit)
        pool, timings = gpu.prepare_pool(table, puzzle.limit)
        statistics["table"] += perf_counter() - now
        statistics["pools"] += 1
        statistics.update(timings)
        for position, target in enumerate(batch, offset):
            if target in graph:
                continue
            previous = tuple(targets[:position])
            required = (*previous, target)
            short, elapsed = gpu.query_balanced(pool, target, puzzle.limit, 7, 36)
            statistics["balanced"] += elapsed
            affine, clocks = gpu.query_affine(pool, target, puzzle.limit, 9, 36, 16, 68, raw_scales)
            statistics.update(clocks)
            witnesses = short + affine
            statistics["raw_witnesses"] += len(witnesses)
            found = None
            for witness in witnesses:
                recipe = decode(leaves, table, witness, target)
                try:
                    candidate = active_graph(puzzle, recipe | graph, targets=required)
                except (KeyError, ValueError):
                    continue
                if found is None or len(candidate) < len(found):
                    found = candidate
            if found is not None:
                statistics["gpu_covered"] += 1
            if found is None or len(found) - len(graph) > 4:
                baseline = compile_target(puzzle, target, graph, min(16, puzzle.registers), native, variant)
                fallback = active_graph(puzzle, baseline | graph, targets=required)
                statistics["beam_calls"] += 1
                if found is None or len(fallback) <= len(found):
                    found = fallback
                else:
                    statistics["gpu_selected"] += 1
            else:
                statistics["gpu_selected"] += 1
            graph = found
    program = compile_graph(puzzle, graph, recompute=True, schedule_width=5)
    if program is None:
        statistics["stream_fallback"] += 1
        program = binary_stream(puzzle)
    if program is None:
        raise ValueError(f"cannot allocate {puzzle.id}")
    check(puzzle, program)
    return program


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("puzzles", type=Path)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--directory", type=Path, default=Path("work/gpu"))
    parser.add_argument("--pilot", type=int, default=8)
    parser.add_argument("--quantity", type=int, default=50)
    parser.add_argument("--steps-per-pool", type=int, default=6)
    parser.add_argument("--raw-scales", type=int, default=1)
    parser.add_argument("--variant", type=int, default=18)
    parser.add_argument("--local-fallback", action="store_true")
    args = parser.parse_args()
    if (min(args.pilot, args.quantity, args.steps_per_pool) < 1
            or args.quantity > 64 or args.raw_scales < 0):
        parser.error("invalid construction settings")
    engine = GPUJoin(args.directory)
    os.environ["SANTA_BUILD_DIR"] = str(args.directory.resolve())
    from dictionary import prepare

    native = None if args.local_fallback else prepare()
    puzzles = read_puzzles(args.puzzles)
    original = read_submission(args.baseline)
    score(puzzles, original)
    ordered = sorted(puzzles, key=lambda puzzle: (-len(original[puzzle.id]), puzzle.id))
    selected = ordered[::max(1, len(ordered) // args.pilot)][:args.pilot]
    untouched = original.copy()
    statistics = Counter()
    start = perf_counter()
    for i, puzzle in enumerate(selected, 1):
        fresh = grow(puzzle, engine, native, args.variant, args.quantity, args.steps_per_pool,
                     args.raw_scales, statistics)
        untouched[puzzle.id] = fresh
        print(f"{i}/{len(selected)} {puzzle.id}: fresh {len(fresh)}, incumbent {len(original[puzzle.id])}, "
              f"{perf_counter() - start:.1f}s", flush=True)
        total = write_submission(args.output, puzzles, untouched)
    print(f"full scored candidate {total}; metrics {dict(statistics)}", flush=True)


if __name__ == "__main__":
    main()
