"""Replace two live intermediates while preserving every arithmetic target."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from itertools import combinations, combinations_with_replacement
import json
from pathlib import Path
import random
import time

from checkpoint import atomic_text
from domain_bounds import operands
from elf import arithmetic, check, read_puzzles, read_submission, sha256, write_submission
from gpu_schedule import schedule_like
from graph import active_graph, compile_graph, first_recipes
from whole_pools import arithmetic as legal_equations

PRIME=1000000007


def sensitivities(p,graph,spare):
    # A modular derivative proposes substitutions. Only full integer replay
    # can accept a substitution or verify its behavior under exact division.
    vs=list(dict.fromkeys((*p.seeds,*graph)));bit={v:1<<j for j,v in enumerate(vs)}
    deps={v:bit[v] for v in p.seeds};up={v:[] for v in vs}
    for v,(op,a,b) in graph.items():
        deps[v]=deps[a]|deps[b]|bit[v]
        if op=='+':ma,mb=1,1
        elif op=='-':ma,mb=1,-1
        elif op=='*':ma,mb=b,a
        else:
            if b%PRIME==0:return None
            ma=pow(b,-1,PRIME);mb=-v*ma
        up[v]=((a,ma%PRIME),(b,mb%PRIME))
    gradients={v:[] for v in graph}
    for t in p.targets:
        adj=defaultdict(int);adj[t]=1
        for v in reversed(graph):
            k=adj[v]
            gradients[v].append(k)
            if k:
                for w,f in up[v]:adj[w]=(adj[w]+k*f)%PRIME
    groups=defaultdict(list)
    for v,g in gradients.items():
        if v in p.targets:continue
        drops=[-1]+(list(range(len(g))) if spare else [])
        for j in drops:
            projected=tuple(0 if n==j else k for n,k in enumerate(g))
            lead=next((k for k in projected if k),None)
            if lead is None:continue
            inv=pow(lead,-1,PRIME)
            key=tuple(k*inv%PRIME for k in projected)
            groups[j,key].append((v,lead))
    return bit,deps,groups,up


def rebuild(p,graph,pair,replacements,keep,altered,optional):
    # Stable input subgraphs may be scheduled before the severed nodes.
    # A replacement can use a new, single arithmetic instruction over these inputs.
    g={};values={}
    for x in keep:g[x]=graph[x]
    for old,(new,recipe) in zip(pair,replacements):
        values[old]=new
        if recipe is not None:g.setdefault(new,recipe)
    for x in altered:
        if x in values:continue
        op,a,b=graph[x];a=values.get(a,a);b=values.get(b,b)
        if op=='/' and a%b:return None
        y=arithmetic(op,a,b)
        if not 0<y<=p.limit:return None
        if x in p.targets and x!=y and x!=optional:return None
        values[x]=y
        if y not in (a,b) and y not in p.seeds:g.setdefault(y,(op,a,b))
    if optional is not None and values.get(optional,optional)!=optional and optional not in g:
        available=set(g)|set(p.seeds)
        choices=[]
        for a in sorted(available):
            for b in operands(optional,a,p.limit)&available:
                if b<a:continue
                for w,r in legal_equations(a,b,p.limit):
                    if w==optional:choices.append(r)
        if not choices:return None
        # Materialize the cheapest reconstruction under the proposed graph.
        try:
            return min((active_graph(p,{**g,optional:r}) for r in choices),key=len)
        except (ValueError,KeyError):return None
    try:return active_graph(p,g)
    except (ValueError,KeyError):return None


def trial(entry):
    p,old,howmany,anchors,seed,spare=entry
    graph=active_graph(p,first_recipes(p,old));data=sensitivities(p,graph,spare)
    best=old;stats=Counter()
    if data is None:return p.id,best,stats
    bit,deps,groups,up=data;rng=random.Random(seed)
    use=Counter(v for _,a,b in graph.values() for v in {a,b})
    pairs=[];used=set()
    def partial(source,v,cache):
        if v==source:return 1
        if not deps[v]&bit[source]:return 0
        if v not in cache:cache[v]=sum(f*partial(source,w,cache) for w,f in up[v])%PRIME
        return cache[v]
    for (drop,key),group in sorted(groups.items(),key=lambda item:item[0][0]):
        for (a,da),(b,db) in combinations(group,2):
            if (a,b) in used:continue
            if deps[b]&bit[a]:
                if not spare:continue
                da=(da-db*partial(a,b,{}))%PRIME
            if not da:continue
            used.add((a,b))
            # A substitution must jointly preserve every target reachable
            # through either value. Shared internal consumers increase its scope.
            rank=(min(5,use[a])+min(5,use[b])+.13*min(30,(deps[a]^deps[b]).bit_count())
                  +rng.random()*2)
            pairs.append((rank,a,b,da*pow(db,-1,PRIME)%PRIME,drop))
    stats['compatible_pairs']=len(pairs)
    for _,x,y,ratio,drop in sorted(pairs,reverse=True)[:howmany]:
        ban=bit[x]|bit[y];stable=[v for v in graph if not deps[v]&ban]
        known=set(p.seeds)|set(stable)
        core=sorted(known,key=lambda v:(v not in p.seeds,-use[v],v))[:anchors]
        pool={v:None for v in known}
        for a,b in combinations_with_replacement(core,2):
            for v,r in legal_equations(a,b,p.limit):
                if v not in (x,y):pool.setdefault(v,r)
        bymod=defaultdict(list)
        for v in pool:bymod[v%PRIME].append(v)
        # Find exactly which old nodes' operations survive after severing x,y.
        required=set();stack=list(p.targets)
        while stack:
            v=stack.pop()
            if v in required or v in p.seeds:continue
            required.add(v)
            if v not in (x,y):stack.extend(graph[v][1:])
        altered=[v for v in graph if v in required and deps[v]&ban]
        attempts=set()
        for u in pool:
            for v in bymod.get((y-(u-x)*ratio)%PRIME,()):
                attempts.add((u,v))
            if x*y%u==0 and x*y//u in pool:attempts.add((u,x*y//u))
            if u*y%x==0 and u*y//x in pool:attempts.add((u,u*y//x))
        stats['numeric_matches']+=len(attempts)
        stats['evaluated_pairs']+=1
        for u,v in attempts:
            g=rebuild(p,graph,(x,y),((u,pool[u]),(v,pool[v])),stable,altered,
                      None if drop<0 else p.targets[drop])
            if g is None:continue
            stats['unchanged_targets']+=1
            if len(g)>=len(best):continue
            tape=schedule_like(p,old,g)
            if tape is None or len(tape)>len(g):
                other=compile_graph(p,g,attempts=3,recompute=True,schedule_width=6)
                if other is not None and (tape is None or len(other)<len(tape)):tape=other
            if tape is not None and len(tape)<len(best):check(p,tape);best=tape
    stats['saved']=len(old)-len(best)
    return p.id,best,stats


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('base',type=Path);ap.add_argument('out',type=Path)
    for k,n in [('rows',56),('pairs',110),('anchors',18),('jobs',3),('seed',39016)]:
        ap.add_argument('--'+k,type=int,default=n)
    ap.add_argument('--repair-one',action='store_true')
    a=ap.parse_args();base=read_submission(a.base);ps=read_puzzles('data/puzzles.csv')
    rows=[p for p in ps if p.id in base];random.Random(a.seed).shuffle(rows)
    if a.rows:rows=rows[:a.rows]
    start=time.monotonic();stats=Counter();wins={}
    with ProcessPoolExecutor(a.jobs) as ex:
        for i,t,s in ex.map(trial,((p,base[p.id],a.pairs,a.anchors,a.seed+int(p.id.split('_')[-1]),a.repair_one) for p in rows)):
            stats.update(s)
            if len(t)<len(base[i]):wins[i]=t
    if wins:write_submission(a.out,[p for p in ps if p.id in wins],wins)
    report={'parent_sha256':sha256(a.base),'rows':[p.id for p in rows],'totals':dict(stats),
            'wins':{k:len(v) for k,v in wins.items()},'seconds':round(time.monotonic()-start,3)}
    atomic_text(a.out.with_suffix('.json'),json.dumps(report,indent=2)+'\n')
    print(dict(stats),len(wins),'wins',report['seconds'],'s',flush=True)

if __name__=='__main__':main()
