"""Find shorter target-private arithmetic cones in an existing independent program.

The native helper checks bounded two-, three-, and four-step arithmetic
patterns from a selected pool of existing values. This is not an exhaustive
search over full programs, and failure does not prove a lower bound.

From the repository root:
    g++ -O3 -std=c++17 private_cone.cpp -o private_cone_planner
    python -B private_cone.py data/puzzles.csv submission.csv cone_candidates.csv

The output contains only strictly shorter, replayed candidate rows.
"""
from argparse import ArgumentParser
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from math import isfinite
from pathlib import Path
import subprocess

from elf import arithmetic, check, read_puzzles, read_submission, score, write_submission
from gpu_schedule import schedule_like
from graph import active_graph, compile_graph, first_recipes


def rate(x, target, uses, limit):
    """Rank potential roots by reuse, offset size, and quotient size."""
    quotient, residue = divmod(target, x)
    near = min(residue, x - residue) if quotient and x - residue <= limit - target else residue
    if x < target:
        value = max(0, 24 - near.bit_length()) * .12 + max(0, 12 - quotient.bit_length()) * .12
    else:
        value = max(0, 28 - (x - target).bit_length()) * .14
    return min(5, uses[x]) * .29 + value


def choose(puzzle, graph, limit):
    uses = Counter(k for _, a, b in graph.values() for k in {a, b})
    needed = defaultdict(set)
    for target in puzzle.targets:
        for value in active_graph(puzzle, graph, (target,)):
            needed[value].add(target)

    contexts = []
    for target in puzzle.targets:
        if target not in graph:
            continue
        cone = {v for v, users in needed.items() if users == {target}}
        if len(cone) < 4:
            continue

        # An apparent root that depends on the target could create a cycle.
        # first_recipes returns each definition in execution order.
        descendants = {target}
        for v, (_, a, b) in graph.items():
            if a in descendants or b in descendants:
                descendants.add(v)
        available = set(graph) - cone - descendants
        if len(available) < 15:
            continue

        boundary = {v for u in cone for v in graph[u][1:] if v in available}
        ranked = sorted(available, key=lambda v: (-rate(v, target, uses, puzzle.limit), v))
        small = sorted(available)[:12]
        recent = []
        offsets = [v for v in ranked if v not in boundary and v not in small]
        for v in reversed(graph):
            if v == target:
                break
            if v in available:
                recent.append(v)
        roots = list(dict.fromkeys((*puzzle.seeds, *sorted(boundary),
                                    *small, *offsets[:34], *recent[:10])))[:64]
        if len(roots) >= 10:
            contexts.append((target, len(cone), tuple(sorted(roots))))
    return sorted(contexts, key=lambda item: (-item[1], item[0]))[:limit]


def parse_results(text, contexts, limit):
    lines = iter(text.splitlines())

    def expect(size, what):
        line = next(lines, None)
        parts = line.split() if line is not None else []
        if len(parts) != size:
            raise ValueError(f"missing or malformed {what}")
        return parts

    def number(raw):
        try:
            return int(raw)
        except ValueError as exc:
            raise ValueError(f"invalid numeric field {raw!r}") from exc

    for row, (target, budget, roots) in enumerate(contexts):
        index, count = map(number, expect(2, "result header"))
        if index != row or not 0 <= count <= 32:
            raise ValueError(f"invalid result header for query {row}")
        candidates = []
        for _ in range(count):
            size = number(expect(1, "plan length")[0])
            if not 1 <= size <= min(4, budget - 1):
                raise ValueError(f"invalid plan length for query {row}")
            known = set(roots)
            plan = {}
            for _ in range(size):
                raw, op, lhs, rhs = expect(4, "instruction")
                out, a, b = map(number, (raw, lhs, rhs))
                if (not 1 <= out <= limit or out in known or a not in known or
                        b not in known or op not in {"+", "-", "*", "/"}):
                    raise ValueError(f"invalid instruction for query {row}")
                if arithmetic(op, a, b) != out:
                    raise ValueError(f"incorrect arithmetic for query {row}")
                known.add(out)
                plan[out] = op, a, b
            if out != target:
                raise ValueError(f"missing final target in query {row}")
            candidates.append(plan)
        yield candidates
    if next(lines, None) is not None:
        raise ValueError("unexpected trailing result rows")


def improve(puzzle, base, planner, sites, timeout):
    graph = first_recipes(puzzle, base)
    contexts = choose(puzzle, graph, sites)
    if not contexts:
        return base, (0, 0, 0)
    input_text = "".join(
        " ".join(map(str, (i, puzzle.limit, len(roots), budget, *roots, target))) + "\n"
        for i, (target, budget, roots) in enumerate(contexts))
    try:
        run = subprocess.run([str(planner)], input=input_text, text=True,
                             capture_output=True, timeout=timeout)
        if run.returncode:
            raise RuntimeError(f"planner exited {run.returncode}: {run.stderr.strip()}")
        proposals = list(parse_results(run.stdout, contexts, puzzle.limit))
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"{puzzle.id}: {exc}") from exc

    accepted = found = 0
    result = base
    for (target, _, _), patches in zip(contexts, proposals, strict=True):
        found += bool(patches)
        best = None
        for patch in patches:
            merged = graph.copy()
            # Preserve incumbent recipes except the chosen target. A patch
            # generated from the initial graph may no longer be usable after
            # a different target's patch removes a formerly available root.
            merged.update((v, edge) for v, edge in patch.items()
                          if v not in merged or v == target)
            try:
                if len(active_graph(puzzle, merged)) >= len(result):
                    continue
            except KeyError:
                continue
            except ValueError as exc:
                if str(exc) != "arithmetic graph has a cycle":
                    raise
                continue
            tape = schedule_like(puzzle, result, merged)
            if tape is None or len(tape) >= len(result):
                tape = compile_graph(puzzle, merged, attempts=6, recompute=True, schedule_width=8)
            if tape is None or len(tape) >= len(result):
                continue
            check(puzzle, tape)
            if best is None or len(tape) < len(best):
                best = tape
        if best is not None:
            accepted += 1
            result = best
            graph = first_recipes(puzzle, result)
    return result, (len(contexts), found, accepted)


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("puzzles", type=Path)
    parser.add_argument("incumbent", type=Path)
    parser.add_argument("output", type=Path, help="new partial CSV with strict improvements")
    parser.add_argument("--planner", type=Path, default=Path("private_cone_planner"))
    parser.add_argument("--rows", type=int, default=220, help="highest incumbent costs first; 0 for all")
    parser.add_argument("--sites", type=int, default=30, help="max target cones per puzzle")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=45)
    args = parser.parse_args()
    if args.rows < 0 or min(args.sites, args.jobs, args.timeout) <= 0 or not isfinite(args.timeout):
        parser.error("invalid row, site, worker, or timeout limit")
    if args.output.resolve() in {args.puzzles.resolve(), args.incumbent.resolve(), args.planner.resolve()}:
        parser.error("output must not overwrite an input")
    if not args.planner.resolve().is_file():
        parser.error(f"planner not found: {args.planner}")

    puzzles = read_puzzles(args.puzzles)
    incumbent = read_submission(args.incumbent)
    score(puzzles, incumbent)
    by_id = {p.id: p for p in puzzles}
    order = sorted(puzzles, key=lambda p: (-len(incumbent[p.id]), p.id))
    if args.rows:
        order = order[:args.rows]
    wins = {}
    total_sites = total_found = total_used = 0
    with ThreadPoolExecutor(args.jobs) as workers:
        jobs = {workers.submit(improve, p, incumbent[p.id], args.planner.resolve(),
                               args.sites, args.timeout): p.id for p in order}
        for future in as_completed(jobs):
            i = jobs[future]
            try:
                tape, (sites, found, used) = future.result()
            except Exception as exc:
                raise RuntimeError(f"failed to process puzzle {i}: {exc}") from exc
            total_sites += sites
            total_found += found
            total_used += used
            if len(tape) < len(incumbent[i]):
                print(f"{i}: {len(incumbent[i])} -> {len(tape)}", flush=True)
                wins[i] = tape

    write_submission(args.output, [by_id[i] for i in sorted(wins)], wins)
    savings = sum(len(incumbent[i]) - len(t) for i, t in wins.items())
    print(f"{len(order)} puzzles, {total_sites} cones, {total_found} with proposals, "
          f"{total_used} accepted cones, {len(wins)} shorter puzzles, {savings} instructions saved")


if __name__ == "__main__":
    main()
