"""Rebuild one program's shared intermediates using a different program's arithmetic."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor,as_completed
import hashlib
import json
from pathlib import Path
import random
import sqlite3

from elf import read_puzzles, read_submission, sha256, check, write_submission
from graph import active_graph, first_recipes, compile_graph
from gpu_schedule import schedule_like
from matrix_construct import native


def orders(p,program):
    trace=first_recipes(p,program)
    active=active_graph(p,trace)
    return {v:r for v,r in trace.items() if v in active}


def split(p,graph,head):
    if not head:return None
    needs=(head&set(p.targets))|{x for v,r in graph.items() if v not in head for x in r[1:] if x in head}
    if not 4<=len(needs)<=48 or len(head)-len(needs)<2:return None
    return tuple(sorted(needs)),{v:r for v,r in graph.items() if v not in head},len(head)


def cuts(p,g):
    values=list(g)
    use=Counter(x for _,a,b in g.values() for x in {a,b})
    result={}
    for n in (16,30,48,72):
        if n<.8*len(g):
            q=split(p,g,set(values[:n]))
            if q:result[q[0]]=q
    for limit in (512,8192,1<<19,1<<28):
        keep=set(p.seeds);head=set()
        for v,(_,a,b) in g.items():
            if v<=limit and a in keep and b in keep:head.add(v);keep.add(v)
        q=split(p,g,head)
        if q:result[q[0]]=q
    # A dependency-closed prefix containing hubs gathered across the whole program.
    for budget in (24,46):
        head=set(); seeds=set(p.seeds)
        for v in sorted(g,key=lambda x:-use[x]):
            if use[v]<2:break
            cone=set()
            stack=[v]
            while stack:
                x=stack.pop()
                if x in seeds or x in head or x in cone:continue
                cone.add(x);stack.extend(g[x][1:])
            if len(head)+len(cone)<=budget:head.update(cone)
        q=split(p,g,head)
        if q:result[q[0]]=q
    return list(result.values())


def bases(p,g):
    v=list(g)
    nodes=set()
    out=[]
    for n in (12,25,42):
        nodes=frozenset(v[:n])
        if len(nodes)<4 or any(nodes==old[0] for old in out):continue
        prefix={x:g[x] for x in v[:n]}
        known=set(p.seeds)|nodes
        reach=set(known)
        vals=sorted(known)
        for i,a in enumerate(vals):
            for b in vals[:i+1]:
                if a+b<=p.limit:reach.add(a+b)
                if a>b:reach.add(a-b)
                if a*b<=p.limit:reach.add(a*b)
                if a%b==0:reach.add(a//b)
        out.append((nodes,prefix,reach))
    return out


def solve(p,programs,exe,trials,seed):
    best=min(programs,key=len)
    records=[orders(p,tape) for tape in programs]
    contexts=[bases(p,g) for g in records]
    rng=random.Random(seed)
    proposals=[]
    for i,g in enumerate(records):
        penalty=len(programs[i])-len(best)
        if penalty>max(30,len(best)//4):continue
        for required,suffix,size in cuts(p,g):
            b=set(required)
            for j,variants in enumerate(contexts):
                if i==j:continue
                for nodes,prefix,reach in variants:
                    exact=len(b&nodes);one=len((b&reach)-nodes)
                    if exact+one<3 or exact==len(b):continue
                    diverse=len(nodes-g.keys())
                    if not diverse:continue
                    rank=(1.1*exact+.72*one)/len(b)+.033*min(15,size-len(b))-.011*penalty
                    rank+=.009*min(12,diverse)-.0025*len(nodes)+rng.random()*.15
                    proposals.append((rank,i,j,required,suffix,prefix))
    proposals.sort(key=lambda z:-z[0])
    used=set();tested=0
    for _,i,j,required,suffix,prefix in proposals:
        # Alternate the selected boundaries and the direction of the exchange.
        key=i,j,required
        if key in used:continue
        used.add(key)
        initial=tuple(dict.fromkeys((*p.seeds,*prefix)))
        learned=native(p,initial,required,exe,(77,2125,4173)[tested%3],8,rng.randrange(1<<22),records[i])
        graph=dict(prefix)
        for source in (learned,suffix):
            for v,r in source.items():graph.setdefault(v,r)
        active=active_graph(p,graph)
        if len(active)<len(best):
            result=schedule_like(p,programs[i],active)
            if not result or len(result)>len(active):
                other=compile_graph(p,active,attempts=5,recompute=True,schedule_width=9)
                if other and (not result or len(other)<len(result)):result=other
            if result and len(result)<len(best):check(p,result);best=result
        tested+=1
        if tested>=trials:break
    return best,tested


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("base",type=Path);ap.add_argument("out",type=Path)
    ap.add_argument("donors",nargs="+",type=Path)
    ap.add_argument("--rows",type=int,default=60);ap.add_argument("--jobs",type=int,default=3)
    ap.add_argument("--trials",type=int,default=5);ap.add_argument("--seed",type=int,default=54677)
    a=ap.parse_args()
    ps=read_puzzles("data/puzzles.csv");base=read_submission(a.base)
    sources=[read_submission(d) for d in a.donors]
    exe=Path("work/virtual/planner-powers.exe").resolve()
    config=(sha256(Path(__file__)),sha256(exe),a.seed,a.trials)
    db=sqlite3.connect(a.out.with_suffix(".sqlite"))
    db.execute("CREATE TABLE IF NOT EXISTS runs (k TEXT PRIMARY KEY, program TEXT, trials INTEGER)")
    groups={}
    for p in ps:
        if len(p.targets)<6:continue
        tapes=tuple(dict.fromkeys([base[p.id],*(d[p.id] for d in sources if p.id in d)]))
        if len(tapes)>1:groups[p.id]=tapes
    selected=[p for p in ps if p.id in groups]
    random.Random(a.seed).shuffle(selected)
    if a.rows:selected=selected[:a.rows]
    out={};saved=0;attempts=0
    def add(p,program,n):
        nonlocal saved,attempts
        check(p,program);out[p.id]=program;attempts+=n
        saved+=min(map(len,groups[p.id]))-len(program)
    def checkpoint():
        write_submission(a.out,[p for p in ps if p.id in out],out)
        print(f"{len(out)}/{len(selected)} rows, {attempts} transfers, {saved} steps beyond donor selection",flush=True)
    with ProcessPoolExecutor(a.jobs) as pool:
        jobs={}
        for p in selected:
            group=groups[p.id]
            k=hashlib.sha256(repr((p,config,group)).encode()).hexdigest()
            hit=db.execute('SELECT program,trials FROM runs WHERE k=?',(k,)).fetchone()
            if hit:
                add(p,tuple(map(tuple,json.loads(hit[0]))),hit[1]);continue
            jobs[pool.submit(solve,p,group,exe,a.trials,a.seed+int(p.id.split('_')[-1]))]=p,k
        for future in as_completed(jobs):
            p,k=jobs[future];program,n=future.result();add(p,program,n)
            db.execute('INSERT OR REPLACE INTO runs VALUES(?,?,?)',(k,json.dumps(program),n));db.commit()
            if len(out)%8==0:checkpoint()
    if out:checkpoint()
    db.close()


if __name__=="__main__":main()
