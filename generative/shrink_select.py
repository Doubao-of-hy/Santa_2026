"""Evaluate native feasible-set deletion against independent or attributed donor tapes."""
import argparse
from concurrent.futures import ProcessPoolExecutor,as_completed
import hashlib
import json
from pathlib import Path
import random
import sqlite3
import subprocess
import sys

from component_select import bank,canonical
from graph import active_graph,first_recipes
from parallel_solve import arithmetic,compile_best
from elf import check,read_puzzles,read_submission,sha256,write_submission


def connect_helpers(p,ways,original,order):
    # A helper from an equal-length rewrite of one branch can shorten another
    # branch when paired with a value available in one operation.
    helpers=set(ways)-original
    if not helpers:return
    single={}
    for i,a in enumerate(order):
        for b in order[:i+1]:
            for v,r in arithmetic(a,b,p.limit):
                if v not in original and v not in (a,b):single.setdefault(v,canonical(r))
    proposals={}
    for output in sorted(original-set(p.seeds)):
        for h in helpers:
            candidates=[(output-h,("+",h,output-h)),(h-output,("-",h,h-output))]
            if output<=p.limit-h:candidates.append((output+h,("-",output+h,h)))
            if output%h==0:candidates.append((output//h,("*",h,output//h)))
            if h%output==0:candidates.append((h//output,("/",h,h//output)))
            if output<=p.limit//h:candidates.append((output*h,("/",output*h,h)))
            for x,r in candidates:
                if x not in single or x in ways or output in single[x][1:]:continue
                proposals.setdefault(x,set()).add((output,canonical(r)))
    # Prefer values that open more than one independently feasible binding.
    candidates=sorted(proposals,key=lambda x:(-len({o for o,_ in proposals[x]}),
                                              -len(proposals[x]),x))
    for x in candidates[:max(70,min(300,len(order)))]:
        ways[x]={single[x]}
        for output,r in proposals[x]:ways[output].add(r)


def run_one(p,tapes,models,exe,rounds,capacity,patches=(),connect=False,component_seconds=0,
            close_pairs=True):
    tapes=sorted(dict.fromkeys(tapes),key=len)
    graphs=[active_graph(p,first_recipes(p,t)) for t in tapes]
    if models:
        from model_select import enriched
        (_,ways),_=enriched(p,tapes,models,capacity)
    else:_,ways=bank(p,tapes)
    if capacity:
        sys.path.insert(0,str(Path(__file__).resolve().parent/"arsen_v7"))
        from recipe_milp import make_pool
        # Multi-user helpers are arithmetic candidates computed anew per puzzle.
        extra,_=make_pool(p.seeds,p.targets,tapes,p.limit,capacity)
        for v,rs in extra.items():ways.setdefault(v,set()).update(rs)
    for graph in graphs:
        for v,r in graph.items():ways.setdefault(v,set()).add(canonical(r))
    if patches:
        original=set(ways)|set(p.seeds)
        for patch in patches:
            for v,r in patch.items():ways.setdefault(v,set()).add(canonical(r))
        if close_pairs:
            values=sorted(set(ways)|set(p.seeds))
            for i,a in enumerate(values):
                for b in values[:i+1]:
                    for v,r in arithmetic(a,b,p.limit):
                        if a in original and b in original and v in original:continue
                        if v in ways and v not in (a,b) and len(ways[v])<45:
                            ways[v].add(canonical(r))
        if connect:
            order=list(dict.fromkeys((*p.seeds,*(v for g in graphs for v in g))))
            connect_helpers(p,ways,original,order)
    values=sorted(set(p.seeds)|set(ways));ids={v:i for i,v in enumerate(values)}
    edges=[(v,*r) for v,rs in ways.items() for r in sorted(rs) if r[1] in ids and r[2] in ids]
    codes={edge:i for i,edge in enumerate(edges)}
    sources=[[codes[v,*canonical(r)] for v,r in g.items()] for g in graphs]
    lines=[" ".join(map(str,(len(values),len(edges),len(p.seeds),len(p.targets),len(sources),
                             3967+int(p.id.rsplit("_",1)[-1])))),
           " ".join(str(ids[v]) for v in p.seeds)," ".join(str(ids[v]) for v in p.targets)]
    lines.extend(f"{ids[v]} {ids[a]} {ids[b]}" for v,op,a,b in edges)
    lines.extend(" ".join(map(str,(len(row),*row))) for row in sources)
    result=subprocess.run([str(exe),str(rounds)],input="\n".join(lines)+"\n",
                          capture_output=True,text=True,check=True)
    output=iter(result.stdout.splitlines());count=int(next(output))
    best=tapes[0];hint=first_recipes(p,best);shortest=len(best);accepted=0
    for _ in range(count):
        size,*chosen=map(int,next(output).split())
        if size!=len(chosen):raise ValueError("invalid native witness length")
        if size>=len(best):continue
        g={v:(op,a,b) for v,op,a,b in (edges[i] for i in chosen)}
        active=active_graph(p,g)
        if len(active)!=size:raise ValueError("invalid native dependency set")
        shortest=min(shortest,size)
        found=compile_best(p,hint,active)
        if found is not None and len(found)<len(best):best=found;accepted+=1
    if component_seconds>0:
        from component_select import solve
        primary=active_graph(p,first_recipes(p,best))
        _,selected,_=solve(p,[best],2,component_seconds,(primary,ways))
        if len(selected)<len(best):best=selected;accepted+=1
    check(p,best)
    return p.id,best,[len(ways),len(edges),count,len(tapes[0])-shortest,accepted]


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for field in ("puzzles","output"):ap.add_argument(field,type=Path)
    ap.add_argument("donors",type=Path,nargs="+")
    ap.add_argument("--exe",required=True,type=Path);ap.add_argument("--model",type=Path,action="append")
    ap.add_argument("--ids",type=Path)
    for k,v in (("rows",0),("jobs",2),("checkpoint",8),("rounds",55),("capacity",160)):
        ap.add_argument("--"+k,type=int,default=v)
    a=ap.parse_args();exe=a.exe.resolve();puzzles=read_puzzles(a.puzzles)
    models={}
    for path in a.model or ():
        for line in path.read_text().splitlines():
            m=json.loads(line);models.setdefault(m["id"],[]).append(m)
    selection=puzzles.copy()
    if a.ids:
        keep=set(a.ids.read_text().split());selection=[p for p in selection if p.id in keep]
    random.Random(8631).shuffle(selection)
    if a.rows:selection=selection[:a.rows]
    sources=[read_submission(f) for f in a.donors]
    here=Path(__file__).resolve();signature=[sha256(f) for f in (exe,here,here.with_name("model_select.py"),
        here.with_name("component_select.py"),here.parent/"arsen_v7"/"recipe_milp.py")]
    db=sqlite3.connect(a.output.with_suffix(".sqlite"))
    db.execute("CREATE TABLE IF NOT EXISTS runs(id TEXT, hash TEXT, tape TEXT, stats TEXT, PRIMARY KEY(id,hash))")
    done={};base={};total=[0]*5
    def save():
        write_submission(a.output,[p for p in puzzles if p.id in done],done)
        print(f"{len(done)}/{len(selection)} saved {sum(base[i]-len(v) for i,v in done.items())}, "
              f"values,edges,elite,logical,allocations {total}",flush=True)
    with ProcessPoolExecutor(a.jobs) as pool:
        jobs={}
        for p in selection:
            tapes=tuple(dict.fromkeys(s[p.id] for s in sources if p.id in s))
            if not tapes:continue
            base[p.id]=min(map(len,tapes))
            m=models.get(p.id,[])
            key=hashlib.sha256(repr((signature,a.rounds,a.capacity,m,tapes)).encode()).hexdigest()
            old=db.execute("SELECT tape,stats FROM runs WHERE id=? AND hash=?",(p.id,key)).fetchone()
            if old:
                done[p.id]=tuple(map(tuple,json.loads(old[0])));check(p,done[p.id])
                total=[x+y for x,y in zip(total,json.loads(old[1]))];continue
            jobs[pool.submit(run_one,p,tapes,m,exe,a.rounds,a.capacity)]=key
        for f in as_completed(jobs):
            pid,tape,stats=f.result();done[pid]=tape
            total=[x+y for x,y in zip(total,stats)]
            db.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?,?)",(pid,jobs[f],json.dumps(tape),json.dumps(stats)))
            db.commit()
            if len(done)%a.checkpoint==0:save()
    save();db.close()


if __name__=="__main__":
    main()
