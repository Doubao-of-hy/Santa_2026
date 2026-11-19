"""Recombine alternative program graphs around shared target neighborhoods with CP-SAT."""

import hashlib
import random
import subprocess
from collections import defaultdict

from improve import ordered, value_graph
from ortools.sat.python import cp_model
from schedule import allocate, pressure_order


def closure(roots, graph, free):
    seen = set(free)
    order = []

    def visit(v):
        if v in seen:
            return
        seen.add(v)
        a, _, b = graph[v]
        visit(a)
        visit(b)
        order.append(v)

    for v in roots:
        visit(v)
    return order


def canonical(a, op, b):
    return (b, op, a) if op in ("+", "*") and b < a else (a, op, b)


def make_catalog(p, programs, binary):
    recipes = defaultdict(dict)
    for code in programs:
        for v, a, op, b in value_graph(p, code):
            recipes[v][canonical(a, op, b)] = None
    values = sorted(set(recipes) | set(p.seeds))
    request = f"{p.limit} {len(values)}\n" + " ".join(map(str, values)) + "\n"
    proc = subprocess.run(
        [binary], input=request, text=True, capture_output=True, check=True
    )
    for line in proc.stdout.splitlines():
        v, a, op, b = line.split()
        if int(v) in recipes:
            recipes[int(v)][canonical(int(a), op, int(b))] = None
    return {v: list(opts) for v, opts in recipes.items()}


def components(selected, free):
    """Tarjan SCCs of the selected producer relation, ignoring free boundary values."""
    numbers = {}
    low = {}
    stack = []
    on = set()
    cycles = []

    def visit(v):
        numbers[v] = low[v] = len(numbers)
        stack.append(v)
        on.add(v)
        a, _, b = selected[v]
        for x in {a, b} - free:
            if x not in numbers:
                visit(x)
                low[v] = min(low[v], low[x])
            elif x in on:
                low[v] = min(low[v], numbers[x])
        if low[v] == numbers[v]:
            group = set()
            while True:
                x = stack.pop()
                on.remove(x)
                group.add(x)
                if x == v:
                    break
            if len(group) > 1 or any(
                x in (selected[x][0], selected[x][2]) for x in group
            ):
                cycles.append(group)

    for v in selected:
        if v not in numbers:
            visit(v)
    return cycles


def optimize_cut(p, base, keep, group, recipes, effort):
    free = set(p.seeds) | set(keep)
    roots = [v for v in group if v not in free]
    if not roots:
        return None
    incumbent = closure(roots, base, free)
    if len(incumbent) < len(roots) + 1:
        return None
    incumbent_set = set(incumbent)
    # Rank candidate recipes by expansion cost from the actual surviving circuit.
    # Original recipes remain admissible even if their tree cost is larger.
    inf = 10**6
    dist = {v: 0 for v in free}
    for _ in range(16):
        changed = False
        for v, opts in recipes.items():
            if v in free:
                continue
            cost = dist.get(v, inf)
            for a, _, b in opts:
                candidate = 1 + dist.get(a, inf) + (dist.get(b, inf) if a != b else 0)
                if candidate < cost:
                    cost = candidate
            if cost < dist.get(v, inf):
                changed = True
                dist[v] = cost
        if not changed:
            break
    selected = {}
    todo = list(roots)
    while todo:
        v = todo.pop()
        if v in free or v in selected:
            continue
        pairs = recipes.get(v, ())
        opt = sorted(
            (
                (1 + dist.get(a, inf) + (dist.get(b, inf) if a != b else 0), (a, op, b))
                for a, op, b in pairs
            ),
            key=lambda x: x[0],
        )
        # Never discard the incoming graph on account of recipe screening.
        choices = []
        if v in incumbent_set:
            a, op, b = base[v]
            choices.append(canonical(a, op, b))
        for c, e in opt:
            if c > dist.get(v, inf) + 2 or c > len(incumbent):
                break
            if e not in choices:
                choices.append(e)
            if len(choices) >= 9:
                break
        selected[v] = choices
        for a, _, b in choices:
            todo.extend((a, b))

    model = cp_model.CpModel()
    y = {v: model.new_bool_var("") for v in selected}
    r = {v: [model.new_bool_var("") for _ in opts] for v, opts in selected.items()}
    for v, opts in selected.items():
        model.add(sum(r[v]) == y[v])
        for j, (a, _, b) in enumerate(opts):
            for arg in {a, b} - free:
                model.add_implication(r[v][j], y[arg])
    for v in roots:
        model.add(y[v] == 1)
    model.add(sum(y.values()) <= len(incumbent) - 1)
    model.minimize(sum(y.values()))
    # Add connectivity cuts only for cycles actually used by a candidate. For
    # any selected value in S, at least one selected producer for S must enter
    # from two operands outside S (the first constructible member).
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.max_deterministic_time = effort
    solver.parameters.random_seed = 1
    for _ in range(6):
        status = solver.solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return None
        picked = {
            v: e
            for v, opts in selected.items()
            for j, e in enumerate(opts)
            if solver.value(r[v][j])
        }
        cycles = components(picked, free)
        if not cycles:
            answer = {v: base[v] for v in keep}
            seq = closure(roots, picked, free)
            answer.update((v, picked[v]) for v in seq)
            return answer
        for s in cycles:
            entering = [
                r[v][j]
                for v in s
                for j, (a, _, b) in enumerate(selected[v])
                if a not in s and b not in s
            ]
            for v in s:
                model.add(sum(entering) >= y[v])
    return None


def solve_cut_crossover(p, programs, binary, sweeps, effort, salt):
    best = programs[0]
    cur = value_graph(p, best)
    base = {v: canonical(a, op, b) for v, a, op, b in cur}
    recipes = make_catalog(p, programs, binary)
    rng = random.Random(
        int.from_bytes(hashlib.sha256(p.id.encode()).digest()[:8], "big") + salt
    )
    for i in range(sweeps):
        roots = list(p.targets)
        rng.shuffle(roots)
        # A whole-puzzle trial allows switching the common prefix. Smaller cuts
        # concentrate the budget on interchangeable target subgraphs.
        step = len(roots) if i == 0 else (7 if i % 2 else 12)
        for j in range(0, len(roots), max(1, step)):
            group = roots[j : j + step]
            keep = closure(roots[:j] + roots[j + step :], base, set(p.seeds))
            expr = optimize_cut(p, base, keep, group, recipes, effort)
            if expr is None or len(expr) >= len(best):
                continue
            original_pos = {row[0]: k for k, row in enumerate(value_graph(p, best))}
            for ordering in (
                list(expr),
                ordered(expr, original_pos),
                pressure_order(expr, p.targets),
            ):
                cand = allocate(p, expr, ordering)
                if cand is not None and len(cand) < len(best):
                    from machine import replay

                    replay(p, cand)
                    best = cand
                    base = expr
                    break
    return p.id, best


if __name__ == "__main__":
    import argparse
    from concurrent.futures import ProcessPoolExecutor, as_completed
    from pathlib import Path

    from machine import load_programs, load_puzzles, save_verified, score

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("puzzles")
    ap.add_argument("output")
    ap.add_argument(
        "--sources",
        nargs="+",
        required=True,
        help="The first file is the starting checkpoint",
    )
    ap.add_argument("--binary", default="./crossover_catalog")
    ap.add_argument("--stride", type=int, default=1)
    ap.add_argument("--sweeps", type=int, default=2)
    ap.add_argument(
        "--effort", type=float, default=0.08, help="Deterministic time per CP-SAT solve"
    )
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    if min(args.stride, args.sweeps, args.workers) < 1 or args.effort <= 0:
        ap.error("Positive search parameters required")
    puzzles = load_puzzles(args.puzzles)
    library = [load_programs(file, reference=True) for file in args.sources]
    for candidate in library:
        score(puzzles, candidate)
    out = dict(library[0])
    exe = str(Path(args.binary).resolve())
    with ProcessPoolExecutor(args.workers) as pool:
        jobs = [
            pool.submit(
                solve_cut_crossover,
                p,
                [c[p.id] for c in library],
                exe,
                args.sweeps,
                args.effort,
                args.seed,
            )
            for p in puzzles[:: args.stride]
        ]
        for job in as_completed(jobs):
            key, code = job.result()
            out[key] = code
    print(save_verified(args.output, puzzles, out))
