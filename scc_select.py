"""Shorten a submission using only its incumbent arithmetic values.

Each puzzle has a finite bank of recipes formed from values in its incumbent
arithmetic graph. OPTIMAL certifies a minimum DAG size only within that bank,
not the puzzle minimum or the minimum after register allocation.
"""

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "generative"))
from checkpoint import independent_score
from component_select import canonical
from crossover_lns import load_solver
from elf import check, read_puzzles, read_submission, score, sha256, write_submission
from graph import active_graph, first_recipes
from parallel_solve import arithmetic, compile_best



def strongly_connected_components(ways):
    """Iterative Kosaraju on the union of all possible dependencies."""
    adjacency = {
        v: sorted({x for _, a, b in recipes for x in (a, b) if x in ways})
        for v, recipes in ways.items()
    }
    reverse = {v: [] for v in ways}
    for v, links in adjacency.items():
        for x in links:
            reverse[x].append(v)
    visited = set()
    finish_order = []
    for seed in ways:
        if seed in visited:
            continue
        visited.add(seed)
        stack = [(seed, iter(adjacency[seed]))]
        while stack:
            v, children = stack[-1]
            child = next(children, None)
            if child is None:
                finish_order.append(v)
                stack.pop()
            elif child not in visited:
                visited.add(child)
                stack.append((child, iter(adjacency[child])))
    visited.clear()
    groups = []
    for seed in reversed(finish_order):
        if seed in visited:
            continue
        group = []
        stack = [seed]
        visited.add(seed)
        while stack:
            v = stack.pop()
            group.append(v)
            for x in reverse[v]:
                if x not in visited:
                    visited.add(x)
                    stack.append(x)
        groups.append(group)
    return groups


def incumbent_bank(puzzle, tape):
    """Build the same one-tape bank without an arbitrary incumbent value cap."""
    primary = active_graph(puzzle, first_recipes(puzzle, tape))
    values = tuple(dict.fromkeys((*puzzle.seeds, *primary)))
    ways = {v: {canonical(r)} for v, r in primary.items()}
    for i, a in enumerate(values):
        for b in values[:i + 1]:
            for v, recipe in arithmetic(a, b, puzzle.limit):
                if v in ways and v not in (a, b) and len(ways[v]) < 45:
                    ways[v].add(canonical(recipe))
    return primary, ways



def optimize(p, incumbent, primary, ways, seconds):
    roots=set(p.seeds)
    forced=set(p.targets)-roots
    # All recipes agree on these requirements; a fixed flag is unnecessary.
    todo=list(sorted(forced))
    while todo:
        v=todo.pop()
        shared=set.intersection(*[set(r[1:]) for r in ways[v]])-roots
        for x in sorted(shared-forced):
            todo.append(x);forced.add(x)
    groups=strongly_connected_components(ways)
    location={v:i for i,g in enumerate(groups) if len(g)>1 for v in g}
    cp=load_solver(); model=cp.CpModel()
    mandatory=model.new_constant(1)
    use={v:mandatory if v in forced else model.new_bool_var('') for v in ways}
    rank={}
    for v,i in location.items():rank[v]=model.new_int_var(0,len(groups[i])-1,'')
    base_depth={}
    for v,(_,a,b) in primary.items():
        if v not in rank:continue
        local=[base_depth.get(x,-1) for x in (a,b) if x in location and location[x]==location[v]]
        base_depth[v]=max(local,default=-1)+1
        model.add_hint(rank[v],base_depth[v])
    edges={}
    for v,rs in ways.items():
        options=[]
        for r in sorted(rs):
            _,a,b=r
            z=model.new_bool_var('')
            edges[z]=(v,r);options.append(z)
            model.add_hint(z,int(r==canonical(primary[v])))
            for x in set((a,b))-roots:
                if x not in forced:model.add_implication(z,use[x])
                if v in location and location.get(x)==location[v]:
                    model.add(rank[v]>rank[x]).only_enforce_if(z)
        model.add(sum(options)==use[v])
        if v not in forced:model.add_hint(use[v],1)
    objective=sum(u for v,u in use.items() if v not in forced)
    model.minimize(objective)
    model.add(objective<=len(primary)-len(forced))
    solver=cp.CpSolver();settings=solver.parameters
    settings.num_search_workers=1;settings.max_time_in_seconds=float(seconds)
    status=solver.solve(model)
    meta=dict(sccs=len(groups),cyclic_sizes=sorted((len(g) for g in groups if len(g)>1),reverse=True),forced=len(forced),status=solver.status_name(status),solver_sec=solver.wall_time)
    if status not in (cp.OPTIMAL,cp.FEASIBLE):return incumbent,meta
    graph=active_graph(p,{v:r for z,(v,r) in edges.items() if solver.value(z)})
    meta.update(logical=len(graph),finite_bank_node_lower_bound=solver.best_objective_bound+len(forced))
    if len(graph)>=len(incumbent):return incumbent,meta
    physical=compile_best(p,first_recipes(p,incumbent),graph)
    if physical is not None and len(physical)<len(incumbent):
        check(p,physical);return physical,meta
    return incumbent,meta

def optimize_one(task):
    puzzle, incumbent, seconds = task
    start = time.process_time()
    primary, ways = incumbent_bank(puzzle, incumbent)
    if not ways:
        tape, info = incumbent, {"status": "TRIVIAL", "finite_bank_node_lower_bound": 0}
    else:
        tape, info = optimize(puzzle, incumbent, primary, ways, seconds)
    check(puzzle, tape)
    if len(tape) > len(incumbent):
        raise ValueError(f"{puzzle.id}: candidate regressed")
    info.update(id=puzzle.id, before=len(incumbent), after=len(tape),
                process_cpu_seconds=round(time.process_time() - start, 6))
    return puzzle.id, tape, info


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("puzzles", type=Path, help="Official puzzle CSV")
    parser.add_argument("incumbent", type=Path, help="Existing complete submission")
    parser.add_argument("output", type=Path, help="New complete CSV; must not already exist")
    parser.add_argument("--ids-file", type=Path, help="Optional newline-separated puzzle IDs")
    parser.add_argument("--seconds", type=float, default=2.75, help="CP-SAT wall time per case")
    parser.add_argument("--jobs", type=int, default=1, help="Concurrent cases, each using one SAT worker")
    args = parser.parse_args()
    if args.jobs < 1 or not math.isfinite(args.seconds) or args.seconds <= 0:
        parser.error("positive --jobs and finite positive --seconds are required")
    inputs = {path.resolve() for path in (args.puzzles, args.incumbent, args.ids_file) if path is not None}
    if args.output.resolve() in inputs or args.output.exists():
        parser.error("output must be a different, unused path")
    try:
        load_solver()
    except ImportError:
        parser.error("this optimizer requires OR-Tools (tested with 9.15.6755)")
    puzzles = read_puzzles(args.puzzles)
    prior = read_submission(args.incumbent)
    prior_score = score(puzzles, prior)
    ids = set(args.ids_file.read_text(encoding="utf-8").split()) if args.ids_file else set(prior)
    if not ids or ids - prior.keys():
        parser.error("IDs must be a nonempty subset of incumbent puzzle IDs")
    tasks = [(p, prior[p.id], args.seconds) for p in puzzles if p.id in ids]
    best = dict(prior)
    with ProcessPoolExecutor(args.jobs) as pool:
        for pid, tape, info in pool.map(optimize_one, tasks, chunksize=1):
            print(json.dumps(info), flush=True)
            if len(tape) < len(best[pid]):
                best[pid] = tape
    # Replay a provisional complete copy before the final destination exists.
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(dir=args.output.parent, prefix=".scc-") as directory:
        provisional = Path(directory) / "candidate.csv"
        new_score = write_submission(provisional, puzzles, best)
        secondary = independent_score(args.puzzles, provisional)
        if secondary != sorted(map(len, best.values())) or sum(secondary) != new_score or new_score > prior_score:
            raise ValueError("full output disagrees with independent replay")
        # A concurrent invocation must not silently overwrite an existing candidate.
        # Open exclusive, then copy only the already-verified file.
        with args.output.open("xb") as destination:
            destination.write(provisional.read_bytes())
    print(json.dumps(dict(score=new_score, prior_score=prior_score, saved=prior_score-new_score,
                          improvements=sum(len(best[k]) < len(prior[k]) for k in ids),
                          replayed=len(puzzles), sha256=sha256(args.output),
                          incumbent_sha256=sha256(args.incumbent),
                          arithmetic_bank_only=True)), flush=True)


if __name__ == "__main__":
    main()

