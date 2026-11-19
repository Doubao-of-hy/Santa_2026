"""Convert independently verified short hub constructions to acyclic matrix headers."""
import argparse
from itertools import product
import json
from pathlib import Path

from run_source import ROOT
from elf import read_puzzles,read_submission
from graph import active_graph,first_recipes


def select(p,m,observed,tape):
    hubs=set(m["hubs"]);seeds=set(p.seeds)
    options={}
    for row in observed:
        if row["query"]=="matched_seeds":continue
        route=tuple(tuple(e) for e in row["recipe"])
        if route and row["hub"] in hubs:options.setdefault(row["hub"],set()).add(route)
    if not options:return None,()
    warm=first_recipes(p,tape)
    estimate={h:max(2,min(10,(h.bit_length()-2)/2.1)) for h in hubs}
    for h in hubs&warm.keys():estimate[h]=min(estimate[h],len(active_graph(p,warm,(h,))))
    best=sum(estimate.values());winning={}
    for paths in product(*[[()]+sorted(group,key=lambda r:(len(r),r)) for group in options.values()]):
        g={}
        for path in paths:
            for v,op,a,b in path:g.setdefault(v,(op,a,b))
        if not g:continue
        pending=g.keys()&hubs
        free=hubs-g.keys()|seeds
        done=set(free);ordered={};stack=set()
        def visit(v):
            if v in done:return True
            if v in stack or v not in g:return False
            stack.add(v);r=g[v]
            if not visit(r[1]) or not visit(r[2]):return False
            stack.remove(v);done.add(v);ordered[v]=r
            return True
        if not all(visit(h) for h in pending):continue
        cost=len(ordered)+sum(estimate[h] for h in hubs-ordered.keys())
        if cost<best:best=cost;winning=ordered
    edges=tuple(dict.fromkeys(e for group in options.values() for path in group for e in path))
    if not winning:return None,edges
    altered=m.copy();altered["hubs"]=[h for h in m["hubs"] if h not in winning]
    altered["derived"]=[(v,*r) for v,r in winning.items()]
    altered["hub_credit"]="enumerated from official seeds and peer factors"
    return altered,edges


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for k in ("puzzles","models","grammar","programs","headers","edges"):
        ap.add_argument(k,type=Path)
    a=ap.parse_args();ps={p.id:p for p in read_puzzles(a.puzzles)}
    models={m["id"]:m for line in a.models.read_text().splitlines() if (m:=json.loads(line))}
    routes=json.loads(a.grammar.read_text())["routes"];programs=read_submission(a.programs)
    headers=[];support=[]
    for item in routes:
        i=item["id"];model=models[i]
        altered,edges=select(ps[i],model,item["found"],programs[i])
        if altered:headers.append(altered)
        if edges:support.append(dict(id=i,hubs=model["hubs"],targets=[],derived=edges))
    for path,items in ((a.headers,headers),(a.edges,support)):
        path.write_text("".join(json.dumps(m,separators=(",",":"))+"\n" for m in items),encoding="utf8")
    print("acyclic headers",len(headers),"puzzles with conditional support",len(support))


if __name__=="__main__":
    main()
