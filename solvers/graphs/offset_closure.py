"""Resynthesize neighboring outlets, allowing any legal helper between retained values."""
import argparse
from collections import Counter,defaultdict
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import random
import sqlite3
import subprocess
import time

from elf import check,read_puzzles,read_submission,write_submission
from solvers.gpu.gpu_join import cut_many
from solvers.gpu.gpu_schedule import schedule_like
from graph import active_graph,compile_graph,first_recipes


def regions(p,g,limit,variant):
    users=defaultdict(set)
    for v,(_,a,b) in g.items():users[a].add(v);users[b].add(v)
    targets=set(p.targets);positions={v:i for i,v in enumerate(g)}
    groups={}
    def offer(roots,kind):
        key=tuple(sorted(set(roots)&g.keys()))
        if 1<=len(key)<=42:groups.setdefault(key,kind)
    # Grow an internal block across all immedate uses of each shared value.
    # Boundary goals remain available to the solver after being constructed.
    for v in g:
        if len(users[v])<=6:
            offer((v,),'single')
        if 1<=len(users[v])<=6:
            frontier=users[v].copy();block={v}|frontier
            for i in range(3):
                roots={w for w in block if w in targets or users[w]-block}
                offer(roots,'family')
                follow={z for w in frontier if len(users[w])<=3 for z in users[w]}
                if not follow:break
                frontier=follow-block;block.update(follow)
    caps=(128,512,2048,8192,65536,1<<21,1<<32)
    for cap in caps:
        small={v for v in g if v<=cap}
        for cut in (small,{v for v in small if len(users[v])<6}):
            roots={v for v in cut if v in targets or users[v]-cut}
            offer(roots,'scale')
            if len(roots)>=5:
                ordered=sorted(roots,key=positions.get)
                for half in (ordered[:(len(ordered)+1)//2],ordered[len(ordered)//2:]):offer(half,'split')
    smallT=[v for v in g if (v in targets or len(users[v])>=2) and v<=1<<22]
    for values in (smallT,sorted(smallT)):
        for j in range(0,len(values)-2,3):offer(values[j:j+4],'neighbors')
    rng=random.Random(str((p.id,variant)))
    cases=defaultdict(list)
    for roots,kind in groups.items():
        kept,free=cut_many(p,g,set(roots))
        removed=set(g)-kept.keys()
        ub=len(removed)-len(roots)
        if ub<1:continue
        inputs=tuple(dict.fromkeys((*p.seeds,*free)))
        hints=tuple(v for v in g if v in removed and v not in roots)
        # Guarantee a spread of subproblems. Sparse, large branches with many
        # missing steps are unlikely to fit in a small helper budget.
        mass=sum(v.bit_length() for v in roots)/len(roots)
        score=1.55*min(6,ub)-.6*abs(len(roots)-3)-.055*mass+rng.random()*6
        cases[kind].append((score,roots,inputs,hints,ub,kept))
    for items in cases.values():items.sort(key=lambda x:-x[0])
    picked=[]
    for i in range(limit):
        before=len(picked)
        for kind in ('family','scale','neighbors','single','split'):
            if len(cases[kind])>i:picked.append(cases[kind][i][1:])
            if len(picked)==limit:return picked
        if len(picked)==before:break
    return picked


def ownership(graph,kept,roots):
    # Follow each outlet's original operands, stopping at retained values
    # and any other outlet. A private ancestor becomes unnecessary when all
    # outlets bearing its mask have independently been reconstructed.
    stop=set(kept)|set(roots)
    masks=Counter()
    for i,v in enumerate(roots):
        stack=list(graph[v][1:]);seen=set()
        while stack:
            x=stack.pop()
            if x in stop or x in seen or x not in graph:continue
            seen.add(x);masks[x]|=1<<i;stack.extend(graph[x][1:])
    return Counter(masks.values())


def row(p,pg,exe,width,depth,n,variant,maxcap,partial):
    graph=active_graph(p,first_recipes(p,pg))
    cases=regions(p,graph,n,variant)
    cases=[r for r in cases if not maxcap or max(r[0])<=maxcap]
    if not cases:return p.id,pg,{},{}
    wire=[]
    for roots,inputs,hints,ub,kept in cases:
        row=(p.id,min(p.limit,maxcap or p.limit),len(inputs),len(roots),len(hints),ub,width,depth,*inputs,*roots,*hints)
        if partial:
            weights=ownership(graph,kept,roots)
            row=(*row,len(weights),*(v for r in weights.items() for v in r))
        wire.append(' '.join(map(str,row)))
    run=subprocess.run([str(exe),*(['partial'] if partial else [])],input='\n'.join(wire)+'\n',capture_output=True,encoding='ascii',check=True)
    lines=iter(run.stdout.splitlines());valid=[];stats=Counter();winners={}
    for roots,inputs,hints,ub,kept in cases:
        pid,cert,won,count=next(lines).split();assert pid==p.id
        stats['cases']+=1
        if int(cert)>=1:stats['full_one_helper_explored']+=1
        if int(won):stats['closure_solved']+=1
        for _ in range(int(count) if partial else int(won)):
            size,gain,mask=map(int,next(lines).split()) if partial else (int(count),0,(1<<len(roots))-1)
            patch={}
            for _ in range(size):
                v,op,a,b=next(lines).split();patch[int(v)]=(op,int(a),int(b))
            assert {v for i,v in enumerate(roots) if mask>>i&1}<=set(patch)|set(inputs)
            # Removed nodes can be outputs to a kept branch, so apply the
            # replacement to the original graph and release unused ancestors.
            try:active=active_graph(p,graph|patch)
            except (ValueError,KeyError):continue
            if len(active)<len(graph):
                valid.append((len(active),patch));stats['graph_improved']+=1
    def materialize(graph,pg):
        trial=schedule_like(p,pg,graph)
        if trial is None or len(trial)>len(graph):
            alt=compile_graph(p,graph,recompute=True,schedule_width=7)
            if alt is not None and (trial is None or len(alt)<len(trial)):trial=alt
        return trial
    best=pg;base=graph
    for _,patch in sorted(valid,key=lambda x:x[0]):
        try:active=active_graph(p,base|patch)
        except (ValueError,KeyError):continue
        if len(active)>=len(best):continue
        alt=materialize(active,best)
        if alt is not None and len(alt)<len(best):
            check(p,alt);best=alt;base=active;winners.update(patch)
    stats['wins']=int(len(best)<len(pg));stats['saved']=len(pg)-len(best)
    return p.id,best,dict(stats),winners


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for a in ('input','output'):ap.add_argument(a,type=Path)
    ap.add_argument('--jobs',type=int,default=3);ap.add_argument('--rows',type=int,default=0)
    ap.add_argument('--ids',type=Path);ap.add_argument('--seed',type=int,default=79241)
    ap.add_argument('--width',type=int,default=5);ap.add_argument('--depth',type=int,default=3)
    ap.add_argument('--cases',type=int,default=19);ap.add_argument('--cap',type=int,default=0)
    ap.add_argument('--partial',action='store_true')
    ap.add_argument('--exe',type=Path,default=Path('work/gpu/offset-closure.exe'))
    a=ap.parse_args();pg=read_submission(a.input);puzzles=read_puzzles('data/puzzles.csv')
    ids=set(pg) if not a.ids else set(a.ids.read_text().split())
    pick=[p for p in puzzles if p.id in ids];random.Random(a.seed).shuffle(pick)
    if a.rows:pick=pick[:a.rows]
    cfg=(a.seed,a.width,a.depth,a.cases,a.cap,a.partial,sha256(a.exe.read_bytes()).hexdigest(),sha256(Path(__file__).read_bytes()).hexdigest())
    out={};stats=Counter();t0=time.monotonic();todo=[]
    db=sqlite3.connect(a.output.with_suffix('.sqlite'))
    db.execute('create table if not exists rows (digest text primary key, id text, result text, stats text)')
    for p in pick:
        d=sha256(repr((p,pg[p.id],cfg)).encode()).hexdigest()
        old=db.execute('select result,stats from rows where digest=?',(d,)).fetchone()
        if old:
            r,counts=map(json.loads,old);out[p.id]=tuple(map(tuple,r));stats.update(counts)
        else:todo.append((p,d))
    from concurrent.futures import as_completed
    def save():
        if not out:return
        write_submission(a.output,[p for p in puzzles if p.id in out],out)
        report=dict(stats,rows=len(out),input=str(a.input),input_sha=sha256(a.input.read_bytes()).hexdigest(),
                    seconds=round(time.monotonic()-t0,3),config=cfg)
        a.output.with_suffix('.json').write_text(json.dumps(report,indent=2))
        print(len(out),len(pick),stats['saved'],flush=True)
    with ThreadPoolExecutor(a.jobs) as pool:
        jobs={pool.submit(row,p,pg[p.id],a.exe.resolve(),a.width,a.depth,a.cases,a.seed,a.cap,a.partial):d for p,d in todo}
        for job in as_completed(jobs):
            k,best,st,_=job.result();out[k]=best;stats.update(st)
            db.execute('insert or replace into rows values(?,?,?,?)',(jobs[job],k,json.dumps(best),json.dumps(st)));db.commit()
            if len(out)%12==0:save()
    save();db.close()


if __name__=='__main__':main()
