"""Synthesize a whole small puzzle over a seed-reachable and goal-directed vocabulary."""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations_with_replacement
import json
from pathlib import Path
import random
import subprocess
import time

from solvers.proofs.domain_bounds import operands
from elf import check, read_puzzles, read_submission, sha256, write_submission
from graph import active_graph, compile_graph, first_recipes


def arithmetic(a,b,cap):
    a,b=sorted((a,b))
    if a+b<=cap: yield a+b,('+',a,b)
    if a!=b: yield b-a,('-',b,a)
    if a*b<=cap: yield a*b,('*',a,b)
    if b%a==0: yield b//a,('/',b,a)


def dictionaries(p,graph):
    seeds=set(p.seeds)
    known=seeds|set(graph)
    forward={}
    by_depth=[sorted(seeds)]
    # Save acyclic paths to each prospective helper. A shared branch can be
    # used twice, e.g. x*x, without paying to construct x twice.
    for depth in range(1,4):
        added={}
        for d in range(depth):
            for a in by_depth[-1]:
                for b in by_depth[d]:
                    if d==depth-1 and b>a:continue
                    for v,r in arithmetic(a,b,p.limit):
                        if v in seeds or v in forward or v in added:continue
                        added[v]=r
            # At depth three unrestricted F2 x F2 can swamp a small vocabulary.
            if depth==3 and d==1:break
        by_depth.append(sorted(added));forward.update(added)
    hops={v:i for i,f in enumerate(by_depth) for v in f}
    direct={}
    for a,b in combinations_with_replacement(sorted(known),2):
        for v,r in arithmetic(a,b,p.limit):
            if v not in known: direct.setdefault(v,r)
    # Each bit denotes a distinct puzzle target which the helper can produce
    # with an existing value or with another inexpensive, seed-reachable value.
    anchor=sorted(known|set(by_depth[1])|set(by_depth[2][:72]))
    support=defaultdict(int);strong=defaultdict(int)
    for j,t in enumerate(p.targets):
        for b in anchor:
            for x in operands(t,b,p.limit):
                if x in known or (x not in direct and x not in forward):continue
                support[x]|=1<<j
                if b in known:strong[x]|=1<<j
    return forward,direct,hops,support,strong


def choose(p,graph,data,width,variant):
    known=set(p.seeds)|set(graph)
    if width==0:return known
    forward,direct,hops,support,strong=data
    rng=random.Random(p.id+'-'+str(variant))
    rank=[]
    for v,mask in sorted(support.items()):
        many=mask.bit_count()
        priority=(many+strong[v].bit_count()*.6)*(1+(.3 if v in direct else 0))
        priority/=1+.17*hops.get(v,3)
        priority*=rng.uniform(.70,1.30) if variant else 1
        rank.append((priority, -v if not variant else rng.random(),v))
    pool=set(known)
    def path(v,out):
        if v in pool or v in out:return
        if v not in direct:
            _,a,b=forward[v];path(a,out);path(b,out)
        out.add(v)
    for _,_,v in sorted(rank,reverse=True):
        extra=set();path(v,extra)
        if len(pool)-len(known)+len(extra)<=width:pool.update(extra)
        if len(pool)>=len(known)+width:break
    return pool


def attempt(p,old,pool,exe,visits):
    graph=active_graph(p,first_recipes(p,old));vs=sorted(pool);ids={v:i for i,v in enumerate(vs)}
    edges=[]
    def edge(t,op,a,b):return (t,op,min(a,b),max(a,b)) if op in '+*' else (t,op,a,b)
    for a,b in combinations_with_replacement(vs,2):
        for t,r in arithmetic(a,b,p.limit):
            if t in ids and t not in (a,b) and t not in p.seeds:edges.append(edge(t,*r))
    codes={e:i for i,e in enumerate(edges)}
    source=[codes[edge(t,*r)] for t,r in graph.items()]
    args=(len(vs),len(edges),len(p.seeds),len(p.targets),1,9319)
    rows=[' '.join(map(str,args)),' '.join(str(ids[s]) for s in p.seeds),
          ' '.join(str(ids[t]) for t in p.targets)]
    rows.extend(f'{ids[t]} {ids[a]} {ids[b]}' for t,_,a,b in edges)
    rows.append(' '.join(map(str,[len(source),*source])))
    result=subprocess.run([str(exe),'1','--whole',str(visits),str(len(graph))],
                          input='\n'.join(rows)+'\n',capture_output=True,text=True,check=True)
    outputs=iter(result.stdout.splitlines());count=int(next(outputs));best=old
    for _ in range(count):
        n,*chosen=map(int,next(outputs).split());assert len(chosen)==n
        g={v:(op,a,b) for v,op,a,b in (edges[j] for j in chosen)}
        g=active_graph(p,g)
        candidate=compile_graph(p,g,attempts=3,recompute=True,schedule_width=6)
        if candidate is not None and len(candidate)<len(best):check(p,candidate);best=candidate
    assert next(outputs,None) is None
    return best,len(edges)


def search(task):
    p,old,widths,visits,exe=task;graph=active_graph(p,first_recipes(p,old))
    data=dictionaries(p,graph);records=[];best=old
    for n,width in enumerate(widths):
        pool=choose(p,graph,data,width,max(0,n-1))
        candidate,size=attempt(p,old,pool,exe,visits)
        records.append([width,len(pool),size,len(candidate)])
        if len(candidate)<len(best):best=candidate
    check(p,best)
    return p.id,best,records


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('base',type=Path);ap.add_argument('out',type=Path);ap.add_argument('exe',type=Path)
    ap.add_argument('--widths',default='0,18,28,44')
    ap.add_argument('--min',type=int,default=16);ap.add_argument('--max',type=int,default=27)
    ap.add_argument('--visits',type=int,default=4000);ap.add_argument('--jobs',type=int,default=3)
    ap.add_argument('--ids',nargs='*');a=ap.parse_args()
    ps=read_puzzles('data/puzzles.csv');base=read_submission(a.base)
    rows=[p for p in ps if p.id in base and a.min<=len(base[p.id])<=a.max and (not a.ids or p.id in a.ids)]
    widths=list(map(int,a.widths.split(',')));out={};stats={};start=time.monotonic()
    with ThreadPoolExecutor(a.jobs) as pool:
        for pid,tape,configs in pool.map(search,[(p,base[p.id],widths,a.visits,a.exe.resolve()) for p in rows]):
            stats[pid]={'before':len(base[pid]),'tested':configs}
            if len(tape)<len(base[pid]):out[pid]=tape
    if out:write_submission(a.out,[p for p in ps if p.id in out],out)
    report={'baseline_sha256':sha256(a.base),'solver_sha256':sha256(a.exe),'visits':a.visits,
            'seconds':round(time.monotonic()-start,3),'rows':stats,'wins':{k:len(v) for k,v in out.items()}}
    a.out.with_suffix('.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(len(stats),'rows',sum(len(base[i])-len(t) for i,t in out.items()),'saved',report['seconds'],'s',flush=True)

if __name__=='__main__':main()
