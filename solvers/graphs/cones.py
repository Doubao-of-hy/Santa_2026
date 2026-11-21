"""Cut private expressions from a program and synthesize replacements against its live values."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
import os
from pathlib import Path
import random
import subprocess
from tempfile import TemporaryDirectory
import time

from elf import read_puzzles, read_submission, write_submission
from graph import active_graph, compile_graph, first_recipes


def neighborhoods(puzzle, program, pool_size, count, seed):
    graph = active_graph(puzzle, first_recipes(puzzle, program))
    chronological = {value: i for i, value in enumerate(first_recipes(puzzle, program))}
    references = Counter(puzzle.targets)
    users = defaultdict(set)
    for value, (_, a, b) in graph.items():
        for operand in {a, b}:
            references[operand] += 1
            users[operand].add(value)
    randomizer = random.Random(seed)
    candidates = []
    for pivot in graph:
        retired = {pivot}
        pending = [pivot]
        losses = Counter()
        while pending:
            _, a, b = graph[pending.pop()]
            for operand in {a, b}:
                losses[operand] += 1
                if operand in graph and losses[operand] == references[operand]:
                    retired.add(operand)
                    pending.append(operand)
        if len(retired) >= 3:
            gain = min(len(retired), 9) + randomizer.random() * 4
            candidates.append((gain, pivot, retired))
    output = []
    alternatives = set()
    for _, pivot, retired in sorted(candidates, reverse=True):
        # Prefer independent regions to obtain useful changes from one synthesis pass.
        if len(retired & alternatives) > 0.7 * len(retired):
            continue
        alternatives.update(retired)
        forbidden = set(retired)
        pending = [pivot]
        while pending:
            for child in users[pending.pop()]:
                if child not in forbidden:
                    forbidden.add(child)
                    pending.append(child)
        def priority(value):
            distance = abs(chronological[pivot] - chronological[value])
            return (distance / (2 + min(references[value], 20)) +
                    (8 if chronological[value] > chronological[pivot] else 0)
                    + randomizer.random() * 3)
        atoms = list(dict.fromkeys(puzzle.seeds))
        atoms.extend(sorted((value for value in graph if value not in forbidden), key=priority))
        output.append((pivot, len(retired), atoms[:pool_size]))
        if len(output) >= count:
            break
    return graph, output


def search_one(executable, puzzle, program, pool_size, count, effort, seed):
    graph, cases = neighborhoods(puzzle, program, pool_size, count, seed)
    if not cases:
        return puzzle.id, program, 0
    lines = []
    for pivot, cost, atoms in cases:
        lines.extend((f"{pivot} {puzzle.limit} {min(cost-1, 6)} {effort}", " ".join(map(str, atoms))))
    run = subprocess.run([executable], input="\n".join(lines) + "\n", capture_output=True,
                         encoding="ascii", check=True)
    stream = iter(run.stdout.splitlines())
    proposals = []
    for pivot, cost, _ in cases:
        for _ in range(int(next(stream))):
            new = {}
            for _ in range(int(next(stream))):
                value, op, left, right = next(stream).split()
                new[int(value)] = (op, int(left), int(right))
            proposals.append((cost - len(new), pivot, new))
    if next(stream, None) is not None:
        raise ValueError("unexpected solver output")
    champion = program
    history = []
    for _, pivot, new in sorted(proposals, key=lambda choice: -choice[0]):
        if pivot not in graph:
            continue
        draft = dict(graph)
        for value, edge in new.items():
            if value == pivot or value not in draft:
                draft[value] = edge
        try:
            draft = active_graph(puzzle, draft)
        except (ValueError, KeyError):
            continue
        if len(draft) < len(graph):
            history.append(draft)
            graph = draft
    for index, draft in enumerate(reversed(history)):
        compiled = compile_graph(puzzle, draft, attempts=6, recompute=True,
                                 schedule_width=8 if index<2 else 0)
        if compiled is not None and len(compiled) < len(champion):
            champion = compiled
        if len(champion) <= len(draft) or index >= 5:
            break
    return puzzle.id, champion, len(history)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("puzzles", type=Path)
    parser.add_argument("incumbent", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--jobs", type=int, default=6)
    parser.add_argument("--pool", type=int, default=80)
    parser.add_argument("--cuts", type=int, default=18)
    parser.add_argument("--effort", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--rows", type=int, default=0)
    parser.add_argument("--checkpoint", type=int, default=50)
    args = parser.parse_args()
    puzzles = read_puzzles(args.puzzles)
    programs = read_submission(args.incumbent)
    proposed = puzzles.copy()
    random.Random(args.seed).shuffle(proposed)
    if args.rows:
        proposed = proposed[:args.rows]
    base = Path(__file__).resolve().parents[2]
    work = base / "work"
    work.mkdir(exist_ok=True)
    t0 = time.monotonic()
    total_saved = changed = done = 0
    with TemporaryDirectory(dir=work, prefix="cone-engine-") as scratch:
        compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
        exe = str(Path(scratch) / "cones.exe")
        subprocess.run([str(compiler), "/nologo", "/optimize+", "/platform:x64", f"/out:{exe}",
                        str(base / "solvers/native/ConeSearch.cs")], check=True,
                       env=dict(os.environ, TEMP=scratch, TMP=scratch))
        with ProcessPoolExecutor(max_workers=args.jobs) as executor:
            futures = [executor.submit(search_one, exe, p, programs[p.id], args.pool, args.cuts,
                                       args.effort, args.seed+i) for i, p in enumerate(proposed)]
            for future in as_completed(futures):
                pid, candidate, _ = future.result()
                saving = len(programs[pid]) - len(candidate)
                total_saved += saving
                changed += saving > 0
                programs[pid] = candidate
                done += 1
                if done % args.checkpoint == 0 or done == len(proposed):
                    result = write_submission(args.output, puzzles, programs)
                    print(f"{done}/{len(proposed)} score {result} saved {total_saved} "
                          f"on {changed} rows in {time.monotonic()-t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
