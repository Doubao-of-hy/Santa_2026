"""Choose whole arithmetic subgraphs from multiple parents at specified shared values."""
from collections import Counter, defaultdict
from pathlib import Path
import sys

from ortools.sat.python import cp_model

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from elf import check
from graph import active_graph, compile_graph, first_recipes


def pieces(p, parents, extra):
    seeds = set(p.seeds)
    goals = set(p.targets) - seeds
    graphs = [active_graph(p, first_recipes(p, t)) for t in parents]
    occurrences = Counter(v for g in graphs for v in g)
    users = Counter(v for g in graphs for _, a, b in g.values() for v in {a, b})
    def priority(v):
        recipes = len({g[v] for g in graphs if v in g})
        return (recipes > 1, recipes, users[v] / occurrences[v], occurrences[v], -v)
    shared = sorted((v for v,n in occurrences.items() if n >= 2 and v not in goals),
                    key=priority, reverse=True)
    cut = goals | set(shared[:extra])
    options = {}
    for end in sorted(cut):
        choices = []
        seen = set()
        for index, graph in enumerate(graphs):
            if end not in graph:
                continue
            needed = set()
            inside = set()
            stack = [end]
            while stack:
                v = stack.pop()
                if v in seeds or v in inside:
                    continue
                if v in cut and v != end:
                    needed.add(v)
                    continue
                inside.add(v)
                stack.extend(graph[v][1:])
            key = (frozenset(inside), frozenset(needed))
            if key not in seen:
                seen.add(key)
                choices.append((index, *key))
        options[end] = choices
    return goals, graphs, options


def solve(p, parents, extra, deterministic_budget=0.45):
    goals, graphs, options = pieces(p, parents, extra)
    model = cp_model.CpModel()
    ranks = {x:model.new_int_var(0,len(options)-1,"") for x in options}
    used = {x:model.new_bool_var("") for x in options}
    charged = {}
    pick = {}
    for x, choices in options.items():
        pick[x] = [model.new_bool_var("") for _ in choices]
        model.add(sum(pick[x]) == used[x])
        if x in goals:
            model.add(used[x]==1)
        for flag, (_, values, needs) in zip(pick[x],choices):
            for v in values:
                if v not in charged:
                    charged[v] = model.new_bool_var("")
                model.add_implication(flag, charged[v])
            for y in needs:
                model.add_implication(flag, used[y])
                model.add(ranks[y] < ranks[x]).only_enforce_if(flag)
        # The first complete program is a feasible warm start.
        take = x in graphs[0]
        model.add_hint(used[x], int(take))
        for flag, (idx, _, _) in zip(pick[x], choices):
            model.add_hint(flag, int(take and idx == 0))
    for v, flag in charged.items():
        model.add_hint(flag, int(v in graphs[0]))
    model.minimize(sum(charged.values()))
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.max_deterministic_time = deterministic_budget
    solver.parameters.random_seed = 33
    status = solver.solve(model)
    best = min(parents,key=len)
    report = dict(status=solver.status_name(status), cuts=len(options), choices=sum(map(len,options.values())))
    if status not in (cp_model.FEASIBLE,cp_model.OPTIMAL):
        return best, report
    assigned = []
    for v, choices in options.items():
        for flag, (idx, inside, needs) in zip(pick[v],choices):
            if solver.value(flag):
                assigned.append((solver.value(ranks[v]),v,idx,inside))
    # Prerequisite cuts have lower ranks. When two pieces use the same integer,
    # the first construction is available to successors in either parent.
    for flip in (False,True):
        combined = {}
        for _,v,idx,inside in sorted(assigned,key=lambda row:(row[0], -row[1] if flip else row[1])):
            for x,recipe in graphs[idx].items():
                if x in inside:
                    combined.setdefault(x,recipe)
        t = compile_graph(p,combined,recompute=True,schedule_width=3)
        if t is None:
            continue
        assert check(p,t)==len(t)
        if len(t)<len(best):
            best=t
    report.update(charged=round(solver.objective_value), bound=round(solver.best_objective_bound))
    return best,report
