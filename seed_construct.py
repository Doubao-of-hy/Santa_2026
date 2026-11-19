"""Construct programs from the puzzle inputs using quotient/remainder and two-step lookups."""

import argparse
import subprocess
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from construct import InstructionBudgetExceeded, compile_dag
from machine import load_programs, load_puzzles, replay, save_verified, score
from schedule import allocate, pressure_order
from tiny import shortest


def solve(job):
    p, binary, width, beam, original, target_first = job
    exact = shortest(p)
    if exact is not None:
        return p.id, exact
    request = f"{p.limit} {len(p.seeds)} {len(p.targets)} {width} {beam}\n"
    request += " ".join(map(str, p.seeds)) + "\n" + " ".join(map(str, p.targets)) + "\n"
    result = subprocess.run(
        [binary, *(["--target-first"] if target_first else [])],
        input=request,
        text=True,
        capture_output=True,
        check=True,
    )
    expr = {}
    for line in result.stdout.splitlines():
        v, a, op, b = line.split()
        expr[int(v)] = (int(a), op, int(b))
    best = original
    for order in [list(expr), pressure_order(expr, p.targets)]:
        if best is not None and len(expr) >= len(best):
            break
        code = allocate(p, expr, order)
        if code is None:
            try:
                code = compile_dag(
                    p,
                    expr,
                    order,
                    max_steps=len(best) - 1 if best is not None else 4096,
                )
            except InstructionBudgetExceeded:
                continue
        replay(p, code)
        if best is None or len(code) < len(best):
            best = code
    if best is None:
        raise ValueError(f"{p.id}: could not fit the instruction budget")
    return p.id, best


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("puzzles")
    ap.add_argument("output")
    ap.add_argument("--binary", default="./seed_search")
    ap.add_argument(
        "--fallback", help="Optional existing programs, retained per puzzle if shorter"
    )
    ap.add_argument(
        "--target-first",
        action="store_true",
        help="Derive available targets before building the constant basis",
    )
    ap.add_argument("--basis", type=int, default=32)
    ap.add_argument("--beam", type=int, default=10)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    if not 2 <= args.basis <= 63 or args.beam < 1 or args.workers < 1:
        ap.error("invalid basis/beam/workers")
    puzzles = load_puzzles(args.puzzles)
    previous = load_programs(args.fallback) if args.fallback else {}
    if args.fallback:
        score(puzzles, previous)
    exe = str(Path(args.binary).resolve())
    jobs = (
        (p, exe, args.basis, args.beam, previous.get(p.id), args.target_first)
        for p in puzzles
    )
    with ProcessPoolExecutor(args.workers) as pool:
        result = dict(pool.map(solve, jobs, chunksize=1))
    print(save_verified(args.output, puzzles, result), flush=True)
