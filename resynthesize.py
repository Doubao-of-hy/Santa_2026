"""Search alternative multi-target arithmetic circuits and verify every accepted row."""

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from construct import InstructionBudgetExceeded, compile_dag
from improve import ordered, value_graph
from machine import load_programs, load_puzzles, replay, save_verified, score
from schedule import allocate, pressure_order


def optimize(p, code, binary, width, depth, passes, pivots, seed):
    graph = value_graph(p, code)
    salt = (
        int.from_bytes(hashlib.sha256(p.id.encode()).digest()[:4], "big") + seed
    ) % 2**32
    inputs = [
        f"{p.limit} {len(p.seeds)} {len(p.targets)} {len(graph)} {width} {depth} {passes} {pivots} {salt}",
        " ".join(map(str, p.seeds)),
        " ".join(map(str, p.targets)),
    ]
    inputs.extend(f"{v} {a} {op} {b}" for v, a, op, b in graph)
    proc = subprocess.run(
        [binary], input="\n".join(inputs) + "\n", text=True, capture_output=True
    )
    if proc.returncode:
        raise RuntimeError(
            f"{p.id}: native search exited {proc.returncode}: {proc.stderr}"
        )
    output = iter(proc.stdout.splitlines())
    position = {row[0]: i for i, row in enumerate(graph)}
    best = code
    for header in output:
        expr = {}
        for _ in range(int(header)):
            v, a, op, b = next(output).split()
            expr[int(v)] = (int(a), op, int(b))
        if len(expr) >= len(best):
            continue
        orders = [ordered(expr, position), list(expr), pressure_order(expr, p.targets)]
        for seq in orders:
            program = allocate(p, expr, seq)
            if program is None:
                try:
                    program = compile_dag(p, expr, seq, max_steps=len(best) - 1)
                except InstructionBudgetExceeded:
                    continue
            if len(program) < len(best):
                replay(p, program)
                best = program
            if len(best) == len(expr):
                break
    return p.id, best


def write_row(path, payload):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False, mode="w") as temp:
        json.dump(payload, temp, separators=(",", ":"))
        tmp = Path(temp.name)
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def run(args):
    puzzles = load_puzzles(args.puzzles)
    codes = load_programs(args.input)
    score(puzzles, codes)
    inputs = {p.id: len(codes[p.id]) for p in puzzles}
    selected = puzzles[args.offset :: args.stride]
    start = time.monotonic()
    engines = {
        "meet": ("round2_search", args.width, args.depth, args.pivots),
        "evict": ("eviction", args.beam, 0, 0),
        "affine": ("affine", args.width, 0, 0),
        "regrow": ("neighborhood", args.width, args.group_size, args.beam),
    }
    executable, width, depth, extra = engines[args.engine]
    binary = Path(args.binary or executable).resolve()
    options = (str(binary), width, depth, args.passes, extra, args.seed)
    store = Path(args.cache) if args.cache else None
    key = None
    if store:
        store.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256()
        for file in [args.puzzles, args.input, binary, __file__]:
            h.update(hashlib.sha256(Path(file).read_bytes()).digest())
        h.update(repr(options[1:]).encode())
        key = h.hexdigest()
    done = 0
    with ProcessPoolExecutor(args.workers) as pool:
        jobs = {}
        for p in selected:
            name = hashlib.sha256(p.id.encode()).hexdigest()
            path = store / (name + ".json") if store else None
            if path and path.exists():
                record = json.loads(path.read_text())
                if record["key"] == key and record["id"] == p.id:
                    candidate = record.get("code")
                    if candidate is not None and replay(p, candidate) < inputs[p.id]:
                        codes[p.id] = candidate
                    done += 1
                    continue
            jobs[pool.submit(optimize, p, codes[p.id], *options)] = (p, path)
        for future in as_completed(jobs):
            p, path = jobs[future]
            pid, best = future.result()
            assert pid == p.id
            codes[pid] = best
            if path:
                write_row(
                    path,
                    dict(
                        id=pid, key=key, code=best if len(best) < inputs[pid] else None
                    ),
                )
            done += 1
            if done % 50 == 0:
                print(
                    f"{done}/{len(selected)}; saved {sum(inputs[k] - len(v) for k, v in codes.items())}",
                    flush=True,
                )
    total = save_verified(args.output, puzzles, codes)
    print(
        json.dumps(
            dict(
                processed=done,
                total=total,
                saved=sum(inputs.values()) - total,
                improved=sum(len(c) < inputs[k] for k, c in codes.items()),
                seconds=round(time.monotonic() - start, 1),
            )
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ["puzzles", "input", "output"]:
        parser.add_argument(arg)
    parser.add_argument(
        "--engine", choices=["meet", "evict", "affine", "regrow"], default="meet"
    )
    parser.add_argument(
        "--binary", help="Override the executable name for the selected engine"
    )
    parser.add_argument(
        "--beam", type=int, default=8, help="Beam size for evict or regrow"
    )
    parser.add_argument(
        "--group-size", type=int, default=4, help="Number of roots per regrow trial"
    )
    for arg, default in [
        ("width", 32),
        ("depth", 5),
        ("passes", 1),
        ("pivots", 1),
        ("seed", 0),
        ("workers", 4),
        ("offset", 0),
        ("stride", 1),
    ]:
        parser.add_argument("--" + arg, type=int, default=default)
    parser.add_argument("--cache")
    opts = parser.parse_args()
    if not (
        opts.beam > 0
        and opts.group_size > 0
        and 1 <= opts.width <= 63
        and 3 <= opts.depth <= 6
        and opts.passes >= 0
        and opts.pivots >= 0
        and opts.workers > 0
        and 0 <= opts.offset < opts.stride
    ):
        parser.error("Invalid search parameters")
    run(opts)
