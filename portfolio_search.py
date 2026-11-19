"""Optimize structurally distinct near-best source programs before comparing their scores."""

import argparse
import hashlib
import json
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from improve import value_graph
from machine import load_programs, load_puzzles, replay, save_verified, score
from resynthesize import optimize, write_row


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
    ap.add_argument(
        "--cache", type=Path, help="Resume completed puzzle rows after an interruption"
    )
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
    cache_key = None
    if args.cache:
        args.cache.mkdir(parents=True, exist_ok=True)
        checksum = hashlib.sha256()
        for file in [__file__, args.puzzles, *args.sources, *(c[0] for c in commands)]:
            checksum.update(hashlib.sha256(Path(file).read_bytes()).digest())
        checksum.update(repr((args.slack, args.alternatives, settings)).encode())
        cache_key = checksum.hexdigest()
    with ProcessPoolExecutor(args.workers) as pool:
        jobs = {}
        for puzzle in puzzles:
            filename = hashlib.sha256(puzzle.id.encode()).hexdigest() + ".json"
            path = args.cache / filename if args.cache else None
            if path and path.exists():
                item = json.loads(path.read_text())
                if item["key"] == cache_key and item["id"] == puzzle.id:
                    candidate = item["code"]
                    if candidate is not None and replay(puzzle, candidate) < len(
                        best[puzzle.id]
                    ):
                        best[puzzle.id] = candidate
                    branches += item["branches"]
                    continue
            job = pool.submit(
                search_row,
                puzzle,
                [s[puzzle.id] for s in sources],
                args.slack,
                args.alternatives,
                commands,
            )
            jobs[job] = path
        for count, job in enumerate(as_completed(jobs), 1):
            k, code, number = job.result()
            improvement = len(best[k]) - len(code)
            saved += improvement
            branches += number
            best[k] = code
            if jobs[job]:
                write_row(
                    jobs[job],
                    dict(
                        id=k,
                        key=cache_key,
                        branches=number,
                        code=code if improvement else None,
                    ),
                )
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
