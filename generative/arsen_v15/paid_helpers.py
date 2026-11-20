"""Rank alternative arithmetic values by the number of removable predecessor operations."""
import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
from recipe_milp import read_graph, ops, inverse, canonical
from recombine2026 import solve
from run_solver import replay

def paid_alternatives(row,prog,width,return_plans=False):
    starts=json.loads(row['starting_values']); targets=set(json.loads(row['targets'])); cap=int(row['value_limit'])
    graph=read_graph(starts,prog); values=list(dict.fromkeys([*starts,*graph])); known=set(values)
    demand=Counter(p for _,a,b in graph.values() for p in {a,b})
    bits={v:1<<i for i,v in enumerate(values)};closure={v:bits[v] for v in starts};private={v:0 for v in starts}
    for v,(_,a,b) in graph.items():
        closure[v]=bits[v]|closure[a]|closure[b]
        private[v]=0
        for p in {a,b}:
            if p in graph and p not in targets and demand[p]==1:private[v]|=bits[p]|private[p]
    possibilities=defaultdict(list)
    for i,a in enumerate(values):
        for b in values[:i+1]:
            for h,recipe in ops(a,b,cap):
                if h not in known:possibilities[h].append(canonical(recipe))
    uses=defaultdict(list)
    for v in graph:
        if not private[v]:continue
        for c in values:
            if closure[c]&bits[v] or not (private[v]&~closure[c]):continue
            for h,recipe in inverse(v,c,cap):
                if h in possibilities:uses[h].append((v,c,canonical(recipe)))
    ranked=[]
    for h,candidates in uses.items():
        options=[]
        for birth in set(possibilities[h]):
            deps=closure[birth[1]]|closure[birth[2]]; replaced=0; wins={}
            for v,c,recipe in candidates:
                if deps&bits[v]:continue
                saving=private[v]&~(deps|closure[c])
                if not saving:continue
                replaced|=saving
                if v not in wins or wins[v][0].bit_count()<saving.bit_count():wins[v]=(saving,recipe)
            if replaced:
                options.append((replaced.bit_count(),len(wins),birth,wins))
        if not options:continue
        options.sort(key=lambda x:(-x[0],-x[1],x[2]))
        score,nuses=options[0][:2]
        material=[(*o[2],h) for o in options[:3]]
        for _,_,_,win in options[:3]:
            material.extend((*r[1],v) for v,r in win.items())
        ranked.append((score,nuses,h,material,options[:3] if return_plans else None))
    ranked.sort(key=lambda x:(-x[0],-x[1],x[2]))
    if return_plans:return [(h,options) for _,_,h,_,options in ranked[:width]]
    recipes={r for _,_,_,rs,_ in ranked[:width] for r in rs}
    return sorted(recipes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("puzzles", type=Path)
    parser.add_argument("parent", type=Path)
    parser.add_argument("id")
    parser.add_argument("output", type=Path)
    parser.add_argument("--helpers", type=int, default=24)
    parser.add_argument("--budget", type=float, default=0.22)
    args = parser.parse_args()
    def row_of(path):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return next(row for row in csv.DictReader(handle) if row["id"] == args.id)
    puzzle = row_of(args.puzzles)
    parent = json.loads(row_of(args.parent)["program"])
    replay(puzzle, parent)
    recipes = paid_alternatives(puzzle, parent, args.helpers)
    program, stats = solve(puzzle, [parent], helpers=0, budget=args.budget, extra=recipes)
    replay(puzzle, program)
    with args.output.open("x", encoding="utf8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "program"])
        writer.writerow([args.id, json.dumps(program, separators=(",", ":"))])
    print(args.id, len(parent), len(program), stats["status"])

if __name__ == "__main__":
    main()
