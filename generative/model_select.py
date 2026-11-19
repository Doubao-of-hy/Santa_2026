"""Select arithmetic recipes from complete recovered models and local program traces."""
import argparse
from collections import Counter,defaultdict
from concurrent.futures import ProcessPoolExecutor,as_completed
import hashlib
import json
from pathlib import Path
import random
import sqlite3
from types import SimpleNamespace

from component_select import bank,canonical,solve
from reachability_select import rooted_solution
from parallel_solve import arithmetic
from elf import check,read_puzzles,read_submission,sha256,write_submission
from model_edges import support


def enriched(p,programs,models,capacity):
    primary,original=bank(p,programs)
    core=set(original)|set(p.seeds)
    additional=defaultdict(set)
    edges={edge for model in models for edge in support(p,model)}
    wanted={x for v,op,a,b in edges for x in (v,a,b)}
    for v,op,a,b in edges:
        if v not in p.seeds:additional[v].add((op,a,b))
    # Real roots for model constants and previously unseen hubs. Small constants
    # have a guaranteed binary construction whenever a one is available.
    if 1 in core:
        constants={v for v in wanted if v<=256}|{v for m in models for v in m["hubs"]}
        for v in constants-core:
            value=v
            while value not in core and value>1:
                if value%2:
                    additional[value].add(canonical(("+",value-1,1)))
                    value-=1
                else:
                    additional[value].add(("+",value//2,value//2))
                    value//=2
    extras=set(additional)-core
    values=list(dict.fromkeys((*p.seeds,*primary,*sorted(core-set(primary)-set(p.seeds)))))
    for i,a in enumerate(values):
        for b in values[:i+1]:
            for v,r in arithmetic(a,b,p.limit):
                if v in extras and len(additional[v])<42:additional[v].add(canonical(r))
    all_ways={v:set(rs) for v,rs in original.items()}
    for v,rs in additional.items():all_ways.setdefault(v,set()).update(rs)

    # Explore complete, constructible additions from a paid prefix of a donor.
    # Roots from only the portion before any target prevent a target's inverse
    # edge being mistaken for a way to produce that very target.
    prefix=set(p.seeds)
    for v,(_,a,b) in primary.items():
        if a in prefix and b in prefix and v not in p.targets:prefix.add(v)
    candidates={};touch=defaultdict(set)
    for roots in (sorted(prefix),values):
        _,tree=rooted_solution(SimpleNamespace(seeds=roots),all_ways,set(core),True)
        plans={v:(frozenset(),frozenset((v,))) for v in roots}
        def plan(v,visiting):
            if v in plans:return plans[v]
            if v in visiting or v not in tree:return None
            _,a,b=tree[v];visiting.add(v)
            left=plan(a,visiting);right=plan(b,visiting);visiting.remove(v)
            if left is None or right is None:return None
            nodes=left[0]|right[0]|({v} if v not in core else set())
            plans[v]=nodes,left[1]|right[1]|({v} if v in core else set())
            return plans[v]
        for v in core-set(p.seeds):
            for _,a,b in additional.get(v,()):
                left=plan(a,set());right=plan(b,set())
                if left is None or right is None or v in left[1] or v in right[1]:continue
                nodes=left[0]|right[0]
                if not 0<len(nodes)<=9:continue
                candidates.setdefault(v,set()).add(nodes)
                for x in nodes:touch[x].add(v)
    selected=set()
    choices=sorted(((sum(1/min(12,len(touch[x]))**.65 for x in nodes),len(nodes),v,tuple(sorted(nodes)))
                    for v,plans in candidates.items() for nodes in plans))
    for _,_,v,nodes in choices:
        if len(selected.union(nodes))<=capacity:selected.update(nodes)
    keep=core|selected
    ways={v:{r for r in all_ways.get(v,()) if r[1] in keep and r[2] in keep}
          for v in keep-set(p.seeds)}
    return (primary,ways),[len(edges),len(selected),sum(len(rs) for rs in ways.values())-
                           sum(len(rs) for rs in original.values())]


def job(p,tapes,models,trials,seconds,capacity):
    programs=sorted(dict.fromkeys(tapes),key=len)
    candidate_bank,stats=enriched(p,programs,models,capacity)
    pid,found,counts=solve(p,programs,trials,seconds,candidate_bank)
    return pid,found,stats+counts


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("puzzles",type=Path);ap.add_argument("output",type=Path)
    ap.add_argument("donors",type=Path,nargs="+")
    ap.add_argument("--model",type=Path,action="append",required=True);ap.add_argument("--ids",type=Path)
    ap.add_argument("--seconds",type=float,default=.8)
    for key,value in (("rows",0),("jobs",2),("checkpoint",8),("trials",3),("capacity",230)):
        ap.add_argument("--"+key,type=int,default=value)
    args=ap.parse_args()
    models=defaultdict(list)
    for path in args.model:
        for line in path.read_text().splitlines():
            item=json.loads(line);models[item["id"]].append(item)
    sources=[read_submission(path) for path in args.donors]
    puzzles=read_puzzles(args.puzzles);selection=[p for p in puzzles if p.id in models]
    if args.ids:
        ids=set(args.ids.read_text().split());selection=[p for p in selection if p.id in ids]
    random.Random(8631).shuffle(selection)
    if args.rows:selection=selection[:args.rows]
    db=sqlite3.connect(args.output.with_suffix(".sqlite"))
    db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT,hash TEXT,tape TEXT,stats TEXT,PRIMARY KEY(id,hash))")
    here=Path(__file__).resolve()
    code=tuple(sha256(f) for f in (here,here.with_name("component_select.py"),
                                   here.with_name("reachability_select.py"),here.parents[1]/"model_edges.py"))
    done={};base={};totals=Counter()
    def flush():
        write_submission(args.output,[p for p in puzzles if p.id in done],done)
        print(len(done),"/",len(selection),"saved",sum(base[i]-len(t) for i,t in done.items()),
              "edge/values/new/blocks/optimal/logical/scheduled",[totals[i] for i in range(7)],flush=True)
    with ProcessPoolExecutor(args.jobs) as pool:
        jobs={}
        for p in selection:
            tapes=tuple(dict.fromkeys(s[p.id] for s in sources if p.id in s))
            base[p.id]=min(map(len,tapes))
            signature=hashlib.sha256(repr((code,args.trials,args.seconds,args.capacity,models[p.id],tapes)).encode()).hexdigest()
            saved=db.execute("SELECT tape,stats FROM runs WHERE id=? AND hash=?",(p.id,signature)).fetchone()
            if saved:
                done[p.id]=tuple(map(tuple,json.loads(saved[0])));check(p,done[p.id])
                totals.update(dict(enumerate(json.loads(saved[1]))));continue
            job_id=pool.submit(job,p,tapes,models[p.id],args.trials,args.seconds,args.capacity)
            jobs[job_id]=signature
        for result in as_completed(jobs):
            pid,tape,stats=result.result();done[pid]=tape;totals.update(dict(enumerate(stats)))
            db.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?,?)",(pid,jobs[result],json.dumps(tape),json.dumps(stats)))
            db.commit()
            if len(done)%args.checkpoint==0:flush()
    flush();db.close()


if __name__=="__main__":
    main()
