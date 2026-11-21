"""Resynthesize original target branches in the presence of a recovered arithmetic scaffold."""
from collections import Counter
from math import log2
import random

from elf import check
from solvers.gpu.gpu_schedule import schedule_like
from graph import active_graph,compile_graph,first_recipes
from solvers.matrix.matrix_construct import native


def addition(root,trace,known):
    if root not in trace:return {}
    out={}
    def visit(v):
        if v in known or v in out:return
        symbol,a,b=trace[v]
        visit(a);visit(b);out[v]=(symbol,a,b)
    visit(root)
    return out


def solve_anchor(p,m,exe,trials,old,donors):
    sources=[first_recipes(p,q) for q in (old,*donors)]
    current=sources[0]
    interest=Counter();support=Counter();products={}
    for row in m["targets"]:
        a,b,k,d,e,r=(row[x] for x in ("a","b","k","d","e","r"))
        support[a]+=1;support[b]+=1
        if a*b<=p.limit and a*b not in (a,b):products[a*b]=('*',a,b)
        for v,w in ((a,3),(b,3),(a*b,2),(k,1.8),(abs(d),1),(abs(e),1),(abs(r),.5)):
            if 0<v<=p.limit:interest[v]+=w
    usage=Counter(v for _,a,b in current.values() for v in {a,b})
    best=None;records=[]
    for rep in range(trials):
        rng=random.Random(int(p.id.split('_')[-1])*257+rep)
        mode=(77,2125,4173,2637,77,2125)[rep%6]
        primary=sources[rep%len(sources)] if rep%3==2 else current
        trace_list=[primary]+[g for g in sources if g is not primary]
        rank=interest.copy()
        for v,n in usage.items():
            if n>=3 and v not in p.targets:rank[v]+=(1.3+.3*(rep%4))*log2(n+1)
        graph={};known=set(p.seeds)
        cap=(32,48,26,62,38,22)[rep%6]
        pool=[(v,rank[v]+rng.random()*.8) for v in rank if v not in p.targets and v not in known]
        for _ in range(28):
            winning=None;quality=0
            for v,priority in pool:
                if v in known:continue
                paths=[addition(v,g,known) for g in trace_list if v in g]
                if not paths:continue
                branch=min(paths,key=len)
                if not branch or len(graph)+len(branch)>cap:continue
                rating=priority/(1+len(branch))**.75
                if rating>quality:quality=rating;winning=branch
            if winning is None:break
            graph.update(winning);known.update(winning)
        ordered=sorted((x for x in m["hubs"] if x>1),key=lambda x:-support[x])
        useful=[x for x in ordered if support[x]>=max(2,len(m["targets"])//12)][:8]
        missing=[x for x in useful if x not in known]
        if missing:
            header=native(p,(*p.seeds,*graph),missing,exe,77,7,rng.randrange(1<<24))
            for x in missing:
                patch=addition(x,header,known);graph.update(patch);known.update(patch)
        for v,recipe in products.items():
            if recipe[1] in known and recipe[2] in known and v not in known:
                graph[v]=recipe;known.add(v)
        # Prefer true table anchors over unrelated earlier values if the
        # 98-leaf working dictionary cannot hold the entire provisional graph.
        extra=sorted(graph,key=lambda v:(-interest[v],-usage[v],v))
        body=native(p,(*p.seeds,*extra),p.targets,exe,mode,7+rep%3,rng.randrange(1<<24),primary)
        for v,recipe in body.items():graph.setdefault(v,recipe)
        active=active_graph(p,graph)
        if best is not None and len(active)>=len(best):
            records.append(len(active));continue
        candidate=schedule_like(p,old,active)
        if candidate is None or len(candidate)>len(active):
            alternate=compile_graph(p,graph,attempts=6,recompute=True,schedule_width=10)
            if alternate is not None and (candidate is None or len(alternate)<len(candidate)):candidate=alternate
        records.append(len(candidate) if candidate is not None else None)
        if candidate is not None and (best is None or len(candidate)<len(best)):
            check(p,candidate);best=candidate
    return p.id,(best if best is not None and len(best)<len(old) else old),best,records
