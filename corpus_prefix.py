"""Rebuild several required small intermediate values together using arithmetic seen on other puzzles."""
import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from heapq import heappush, heappop
import json
from pathlib import Path
import sys
from time import perf_counter

from checkpoint import atomic_text
from elf import Puzzle, check, read_puzzles, read_submission, sha256, write_submission
from graph import active_graph, compile_graph, first_recipes
from gpu_schedule import schedule_like
ROOT=Path(__file__).resolve().parent
for directory in (ROOT/'work/crossover/deps', ROOT/'work/creative/frontier-135161/arsen',ROOT/'generative/arsen_v15'):
    if directory.is_dir():sys.path.insert(0,str(directory))


def arithmetic_edges(a,b,cap):
    if a+b<=cap:yield a+b,('+',min(a,b),max(a,b))
    if a!=b:yield abs(a-b),('-',max(a,b),min(a,b))
    if a<=cap//b:yield a*b,('*',min(a,b),max(a,b))
    u,v=max(a,b),min(a,b)
    if u%v==0:yield u//v,('/',u,v)


def build_corpus(data,bank):
    global CORPUS,FREQUENCY,SORTED,SEEN_BY_ID
    raw=defaultdict(dict);FREQUENCY=Counter();SEEN_BY_ID={}
    tapes=read_submission(bank)
    for p in read_puzzles(data):
        graph=active_graph(p,first_recipes(p,tapes[p.id]))
        SEEN_BY_ID[p.id]=set(graph)|set(p.seeds)
        FREQUENCY.update(SEEN_BY_ID[p.id])
        for v,(op,a,b) in graph.items():
            if max(v,a,b)>65536:continue
            e=(op,min(a,b),max(a,b)) if op in '+*' else (op,a,b)
            previous=raw[v].get(e)
            if previous is None:raw[v][e]=p.id
            elif previous!=p.id:raw[v][e]='multiple'
    CORPUS={v:tuple(recipes.items()) for v,recipes in raw.items()}
    SORTED=sorted(v for v in CORPUS if FREQUENCY[v]>=2)


def gather(p,head,wanted,limit,width):
    seeds=set(p.seeds);seen=seeds|head.keys()
    universe=seen|{v for v in SORTED[:bisect_right(SORTED,min(p.limit,65536,2*limit))] if FREQUENCY[v]-int(v in SEEN_BY_ID[p.id])>=2}
    recipes=defaultdict(set)
    for v in universe-seeds:
        for e,pid in CORPUS.get(v,()):
            if pid!=p.id and e[1] in universe and e[2] in universe:recipes[v].add(e)
    for v,e in head.items():recipes[v].add(e)
    atoms=tuple(seen)
    for ix,a in enumerate(atoms):
        for b in atoms[:ix+1]:
            for v,e in arithmetic_edges(a,b,p.limit):
                if v in universe and v not in seeds and v not in (a,b):recipes[v].add(e)
    use=defaultdict(list)
    for v,es in recipes.items():
        for e in es:
            a,b=e[1:];use[a].append((v,e))
            if b!=a:use[b].append((v,e))
    dist={};first={};queue=[(0,v) for v in sorted(seeds)]
    while queue:
        cost,v=heappop(queue)
        if v in dist:continue
        dist[v]=cost
        for out,e in use[v]:
            if out in dist:continue
            a,b=e[1:]
            if a in dist and b in dist:
                n=1+dist[a]+(dist[b] if b!=a else 0)
                if out not in first or n<first[out][0] or (n==first[out][0] and e<first[out][1]):
                    first[out]=(n,e);heappush(queue,(n,out))
    def birth(v,memo):
        if v in seen or v in memo:return
        e=first[v][1];birth(e[1],memo);birth(e[2],memo);memo[v]=e
    rank=Counter();requests=[]
    for v in head:
        if v not in dist:continue
        options=[]
        for e in recipes[v]:
            a,b=e[1:]
            if a not in dist or b not in dist or (a in seen and b in seen):continue
            plan={};birth(a,plan);birth(b,plan)
            if not plan or len(plan)>8:continue
            price=1+dist[a]+(dist[b] if b!=a else 0)
            options.append((price,len(plan),e,plan))
        options.sort(key=lambda row:row[:3])
        for k,(price,n,e,plan) in enumerate(options[:10]):
            strength=(2 if v in wanted else 1)/(1+n+max(0,price-dist[v]))/(1+k/3)
            for z in plan:rank[z]+=strength
            requests.append((strength,v,e,plan))
    requests.sort(key=lambda r:(-r[0]-sum(rank[z] for z in r[3])/len(r[3]),r[1],r[2]))
    chosen={};offered=set()
    for _,v,e,plan in requests:
        if len(chosen.keys()|plan.keys())<=width:
            chosen.update(plan);offered.add((*e,v))
    for v,e in chosen.items():offered.add((*e,v))
    return sorted(offered),len(chosen)


def windows(p,g,fringe=0):
    setups=[];seeds=set(p.seeds);done=set()
    for cap in (48,192,1024,8192,32768):
        kept=set(seeds);head={}
        for v,e in g.items():
            if v<=cap and e[1] in kept and e[2] in kept:
                head[v]=e;kept.add(v)
        if fringe:
            usage=Counter(x for e in g.values() for x in set(e[1:]))
            for level in range(fringe):
                candidates=[v for v,e in g.items() if v not in kept and e[1] in kept and e[2] in kept]
                candidates.sort(key=lambda v:(-sum(x in head and usage[x]<=2 for x in set(g[v][1:])),v not in p.targets,v))
                layer=candidates[:min(12,max(0,56-len(head)))]
                if not layer:break
                for v in layer:head[v]=g[v];kept.add(v)
            head={v:e for v,e in g.items() if v in head}
        needed=tuple(sorted((set(p.targets)&head.keys())|{a for v,e in g.items() if v not in head for a in e[1:] if a in head}))
        if needed in done or len(head)-len(needed)<1 or len(needed)<2 or len(head)>60:continue
        done.add(needed);setups.append((cap,head,needed))
    return setups

def put_back(p,graph,old,local,program):
    patch=first_recipes(local,program)
    try:candidate=active_graph(p,graph|patch)
    except (KeyError,ValueError):return old
    if len(candidate)>=len(old):return old
    new=schedule_like(p,old,candidate)
    if new is None or len(new)>len(candidate):
        other=compile_graph(p,candidate,attempts=4,recompute=True,schedule_width=4)
        if other is not None and (new is None or len(other)<len(new)):new=other
    if new is not None and len(new)<len(old):check(p,new);return new
    return old


def worker(case):
    from recombine2026 import solve
    p,initial,width,budget,fringe=case
    graph=active_graph(p,first_recipes(p,initial));reports=[];choices={name:initial for name in ('simple','local','corpus')}
    for cap,head,required in windows(p,graph,fringe):
        local=Puzzle(p.id,p.seeds,required,p.limit,p.registers)
        base=compile_graph(local,head)
        if base is None or len(base)>len(head):continue
        extra,n=gather(p,head,set(required),cap,width)
        d={'limit':cap,'nodes':len(head),'required':len(required),'new_values':n}
        row={'id':p.id,'starting_values':json.dumps(p.seeds),'targets':json.dumps(required),'value_limit':p.limit,'registers':p.registers}
        cached={}
        for name,helpers,add in [('simple',0,None),('local',n,None),('corpus',0,extra)]:
            key=(helpers,tuple(add or []))
            if key not in cached:
                prog,stat=solve(row,[[list(s) for s in base]],helpers=helpers,extra=add,budget=budget)
                check(local,prog);cached[key]=tuple(tuple(op) for op in prog)
            prog=cached[key];d[name]=len(prog)
            if len(prog)<len(head):
                t=put_back(p,graph,initial,local,prog)
                if len(t)<len(choices[name]):choices[name]=t
        reports.append(d)
    winner=min(choices,key=lambda k:len(choices[k]));best=choices[winner]
    return p.id,best,dict(parent=len(initial),best=len(best),winner=winner,
        arms={k:len(v) for k,v in choices.items()},windows=reports)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('parent','training','ids','output'):ap.add_argument(name,type=Path)
    ap.add_argument('--puzzles',type=Path,default=Path('data/puzzles.csv'))
    ap.add_argument('--fringe',type=int,default=0)
    ap.add_argument('--width',type=int,default=20)
    ap.add_argument('--budget',type=float,default=.16)
    ap.add_argument('--jobs',type=int,default=3)
    a=ap.parse_args();data=read_puzzles(a.puzzles);ids=set(a.ids.read_text().split());base=read_submission(a.parent)
    ps=[p for p in data if p.id in ids];assert len(ps)==len(ids)
    start=perf_counter();rows={};wins={}
    def save():
        write_submission(a.output,[p for p in ps if p.id in wins],wins)
        atomic_text(a.output.with_suffix('.json'),json.dumps(dict(parent=sha256(a.parent),training=sha256(a.training),source=sha256(Path(__file__)),
          ids=sha256(a.ids),complete=len(rows)==len(ps),width=a.width,budget=a.budget,fringe=a.fringe,seconds=perf_counter()-start,rows=rows),indent=1))
    with ProcessPoolExecutor(a.jobs,initializer=build_corpus,initargs=(a.puzzles,a.training)) as pool:
        for i,t,r in pool.map(worker,[(p,base[p.id],a.width,a.budget,a.fringe) for p in ps]):
            rows[i]=r
            if len(t)<len(base[i]):wins[i]=t
            if len(rows)%8==0:save()
    save();print(len(rows),'saved',sum(r['parent']-r['best'] for r in rows.values()),flush=True)
if __name__=='__main__':main()
