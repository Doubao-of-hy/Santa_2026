"""Temporarily replace one or two targets by differences or exact quotients of targets."""

import argparse
import csv
import gzip
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from itertools import combinations
from pathlib import Path
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from checkpoint import independent_score
from elf import check, read_puzzles, sha256, write_submission
from graph import active_graph, compile_graph, first_recipes
from solvers.gpu.pooled_joins import inverse

spec = importlib.util.spec_from_file_location("partition", HERE.parent / "target-partition/compare.py")
partition = importlib.util.module_from_spec(spec)
spec.loader.exec_module(partition)
BASE = "7fa1fb5cf8f3677764f9e0862896c6bd571adc3c"
ROUNDS = 320


def fingerprint(obj):
    return hashlib.sha256(json.dumps(obj, separators=(",", ":")).encode()).hexdigest()


def parent(lane):
    path = ("public-assisted/" if lane == "public" else "") + "submission.csv"
    blob = subprocess.check_output(["git", "show", BASE + ":" + path], cwd=ROOT)
    with io.StringIO(blob.decode("utf-8-sig")) as source:
        return {r["id"]: tuple(tuple(op) for op in json.loads(r["program"])) for r in csv.DictReader(source)}


def choose(p, graph):
    goals = set(p.targets) - set(p.seeds)
    closures = {t: set(active_graph(p, graph, [t])) for t in goals}
    moves = []
    for t in sorted(goals):
        kept = set(p.seeds).union(*(s for a, s in closures.items() if a != t))
        private = len(closures[t] - kept)
        if private < 2:
            continue
        candidates = []
        for a in sorted(goals - {t}):
            if t > a:
                candidates.append((t-a, ("-", t, a), ("+", a, t-a), a))
            else:
                candidates.append((a-t, ("-", a, t), ("-", a, a-t), a))
            if t % a == 0:
                candidates.append((t//a, ("/", t, a), ("*", a, t//a), a))
            if a % t == 0:
                candidates.append((a//t, ("/", a, t), ("/", a, a//t), a))
        for d, forward, recover, a in candidates:
            if d in goals or d in p.seeds or d == a or d == t:
                continue
            # Prefer residuals already available to other goals or one step from them.
            route = None
            if d not in kept:
                for x in sorted(kept, key=lambda x: (x.bit_length(), x)):
                    route = next((edge for y, edge in inverse(d, x, p.limit)
                                  if y in kept and d not in edge[1:]), None)
                    if route:
                        break
            cost = 0 if d in kept else 1 if route else 2 + d.bit_length()/12
            rank = (private-cost, t.bit_length()-d.bit_length(), -d, -a, -t)
            moves.append((rank, (t, a, d, forward, recover, route)))
    selected = []
    for _, move in sorted(moves, key=lambda item: item[0], reverse=True):
        t, a, d = move[:3]
        if any(t in m[:3] or m[0] in (a,d) or d == m[2] for m in selected):
            continue
        selected.append(move)
        if len(selected) == 2:
            break
    return selected


def run_arm(p, tape, graph, moves, seeds, exe):
    stage = p
    start = tape
    if moves:
        omitted = {m[0] for m in moves}
        stage = replace(p, targets=tuple(t for t in p.targets if t not in omitted) + tuple(m[2] for m in moves))
        augmented = graph.copy()
        for _, _, d, forward, _, route in moves:
            if route:
                augmented[d] = route
            else:
                augmented.setdefault(d, forward)
        start = compile_graph(stage, augmented, recompute=True, schedule_width=2)
        if start is None:
            # Old target programs always provide the operands of each forward recipe.
            augmented = graph.copy()
            for _, _, d, forward, _, _ in moves:
                augmented.setdefault(d, forward)
            start = compile_graph(stage, augmented, recompute=True, schedule_width=2)
    restored = [tape]
    stage_size = None
    if start is not None:
        first = partition.run_native(stage, start, exe, seeds[0], ROUNDS)
        stage_size = len(first)
        if moves:
            body = active_graph(stage, first_recipes(stage, first))
            for count in range(len(moves)+1):
                for subset in combinations(moves, count):
                    joined = graph | body | {m[0]: m[4] for m in subset}
                    rebuilt = compile_graph(p, joined, recompute=True, schedule_width=2)
                    if rebuilt is not None:
                        restored.append(rebuilt)
        else:
            restored.append(first)
    best = min(restored, key=len)
    final = partition.run_native(p, best, exe, seeds[1], ROUNDS)
    best = min([*restored, final], key=len)
    assert check(p, best) == len(best)
    return {"start": None if start is None else len(start), "stage": stage_size,
            "restored": min(map(len, restored)), "score": len(best), "hash": fingerprint(best),
            **({"program": best} if len(best) < len(tape) else {})}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--puzzles", required=True, type=Path)
    cli.add_argument("--exe", type=Path)
    cli.add_argument("--out", required=True, type=Path)
    cli.add_argument("--lane", choices=("public", "own"), required=True)
    cli.add_argument("--phase", choices=("development", "holdout"), required=True)
    cli.add_argument("--jobs", type=int, default=4)
    cli.add_argument("--replay-only", action="store_true")
    args = cli.parse_args()
    if not args.replay_only and args.exe is None:
        cli.error("--exe is required for a new search")
    assert sha256(args.puzzles) == "b0c70d849eca078a0e1cf9a4f7b47fd40b7435663f6f84de6725f84724500428"
    puzzles = read_puzzles(args.puzzles)
    parents = parent(args.lane)
    eligible = sorted((p for p in puzzles if 5 <= len(set(p.targets)) <= 40 and
                       35 <= len(parents[p.id]) <= 255),
                      key=lambda p: fingerprint(["goal-difference-v1", args.lane, p.id]))
    lo, hi = (0, 12) if args.phase == "development" else (12, 36)
    chosen = eligible[lo:hi]
    args.out.mkdir(parents=True, exist_ok=True)
    stem = args.lane + "-" + args.phase
    dest = args.out / (stem + ".json.gz")
    if not args.replay_only:
        def solve(p):
            tape = parents[p.id]
            graph = active_graph(p, first_recipes(p, tape))
            moves = choose(p, graph)
            seeds = [int(fingerprint([p.id, "goal-difference-v1", j])[:8], 16) for j in (1, 2)]
            groups = []
            for count in range(3):
                selected = moves[:count]
                if count > len(moves):
                    groups.append(groups[-1])
                else:
                    groups.append(run_arm(p, tape, graph, selected, seeds, args.exe.resolve()))
            return p.id, dict(before=len(tape), parent=fingerprint(tape), moves=moves, arms=groups)
        with ThreadPoolExecutor(args.jobs) as pool:
            rows = dict(pool.map(solve, chosen))
        dest.write_bytes(gzip.compress(json.dumps(rows, separators=(",", ":")).encode(), mtime=0))
    rows = json.loads(gzip.decompress(dest.read_bytes()))
    assert set(rows) == {p.id for p in chosen}
    wins = {}
    arms = [0, 0, 0]
    beats = []
    for p in chosen:
        tape = parents[p.id]
        record = rows[p.id]
        assert record["parent"] == fingerprint(tape) and len(record["arms"]) == 3
        for j, row in enumerate(record["arms"]):
            candidate = tuple(tuple(x) for x in row.get("program", tape))
            assert check(p, candidate) == row["score"] <= len(tape) and fingerprint(candidate) == row["hash"]
            arms[j] += len(tape) - len(candidate)
            if len(candidate) < len(wins.get(p.id,tape)):
                wins[p.id] = candidate
        if len(wins.get(p.id,tape)) < record["arms"][0]["score"]:
            beats.append(p.id)
    with TemporaryDirectory(dir=args.out) as tmp:
        full = Path(tmp) / "candidate.csv"
        total = write_submission(full, puzzles, parents | wins)
        assert total == sum(independent_score(args.puzzles, full))
    write_submission(args.out / (stem + ".csv"), [p for p in chosen if p.id in wins], wins)
    summary = dict(phase=args.phase,lane=args.lane,tested=len(chosen),improved=len(wins),arms=arms,
                   saved=sum(len(parents[i])-len(t) for i,t in wins.items()),beats_ordinary=beats,score=total)
    (args.out / (stem + ".json")).write_bytes((json.dumps(summary,indent=2)+"\n").encode())
    print(summary,flush=True)


if __name__ == "__main__":
    main()
