"""Optimize structurally distinct near-best source programs before comparing their scores."""

import argparse
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from improve import value_graph
from machine import load_programs, load_puzzles, save_verified, score
from resynthesize import optimize


def signature(p, code):
    definitions = []
    for value, a, op, b in value_graph(p, code):
        if op in ("+", "*") and a > b:
            a, b = b, a
        definitions.append((value, a, op, b))
    return tuple(sorted(definitions))


def search_row(p, sources, slack, alternatives, binaries):
    best = sources[0]
    seen = {signature(p, best)}
    starts = []
    for code in sorted(sources[1:], key=len):
        if len(code) > len(best) + slack:
            break
        key = signature(p, code)
        if key in seen:
            continue
        seen.add(key)
        starts.append(code)
        if len(starts) >= alternatives:
            break
    for branch, code in enumerate(starts):
        # Preserve alternative equal-cost structures until all transformations finish.
        for binary, width, depth, passes, extra in binaries:
            _, code = optimize(
                p, code, binary, width, depth, passes, extra, 123 + branch
            )
        if len(code) < len(best):
            best = code
    return p.id, best, len(starts)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("puzzles")
    ap.add_argument("output")
    ap.add_argument(
        "--sources",
        nargs="+",
        required=True,
        help="First file is the verified incumbent",
    )
    ap.add_argument("--bin-dir", type=Path, required=True)
    ap.add_argument("--slack", type=int, default=4)
    ap.add_argument("--alternatives", type=int, default=4)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    if args.slack < 0 or min(args.alternatives, args.workers) < 1:
        ap.error("Invalid search limits")
    puzzles = load_puzzles(args.puzzles)
    sources = [load_programs(f, reference=True) for f in args.sources]
    for s in sources:
        score(puzzles, s)
    best = dict(sources[0])
    settings = [
        ("affine", 52, 0, 2, 0),
        ("round2_search", 40, 5, 1, 1),
        ("eviction", 6, 0, 2, 0),
    ]
    commands = [
        (str((args.bin_dir / name).resolve()), w, d, n, e)
        for name, w, d, n, e in settings
    ]
    branches = saved = 0
    start = time.monotonic()
    with ProcessPoolExecutor(args.workers) as pool:
        jobs = [
            pool.submit(
                search_row,
                p,
                [s[p.id] for s in sources],
                args.slack,
                args.alternatives,
                commands,
            )
            for p in puzzles
        ]
        for count, job in enumerate(as_completed(jobs), 1):
            k, code, number = job.result()
            saved += len(best[k]) - len(code)
            branches += number
            best[k] = code
            if count % 100 == 0:
                print(
                    count,
                    branches,
                    saved,
                    round(time.monotonic() - start, 1),
                    flush=True,
                )
    print(save_verified(args.output, puzzles, best), flush=True)


if __name__ == "__main__":
    main()
