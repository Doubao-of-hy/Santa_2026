"""Change the targets of a subproblem to a joint dictionary of signed residuals."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from math import log2
from pathlib import Path
import random

from elf import check, read_puzzles, read_submission, write_submission
from gpu_schedule import schedule_like
from graph import active_graph, compile_graph, first_recipes
from matrix_construct import native


def available(p, free):
    direct = {}
    vals = sorted(free)
    for i,a in enumerate(vals):
        for b in vals[:i+1]:
            if a+b<=p.limit:direct.setdefault(a+b,("+",a,b))
            if a>b:direct.setdefault(a-b,("-",a,b))
            if a*b<=p.limit:direct.setdefault(a*b,("*",a,b))
            if a%b==0:direct.setdefault(a//b,("/",a,b))
    return direct


def menus(y, sources, free, direct, limit):
    result = {}
    def offer(x,k,r,reverse):
        if k<=0 or k>65536 or r==0 or abs(r) in (x,y):
            return
        middle=y*k if reverse else x*k
        if middle>limit or middle==y and k!=1 and not reverse:
            return
        literals=frozenset(({k} if k!=1 else set()) | {abs(r)})
        if y in literals or x in literals:
            return
        edges={}
        if reverse:
            edges[middle]=("+" if r>0 else "-",x,abs(r))
            if k!=1: edges[y]=("/",middle,k)
        else:
            if k!=1: edges[middle]=("*",x,k)
            edges[y]=("+" if r>0 else "-",middle,abs(r))
        if any(v in e[1:] for v,e in edges.items()):
            return
        score=len(edges)
        for v in literals-free:
            if v in direct:
                score+=1
            else:
                n=v.bit_length()
                score+=1.8+max(0,n-8)*.12
        key=tuple(sorted(edges.items()))
        if key not in result:result[key]=(score,edges,literals)
    for x in sources:
        if x==y or x<16:
            continue
        k=(y+x//2)//x
        if 1<=k<=65536:
            offer(x,k,y-x*k,False)
            if k>1 and k-1 in free:offer(x,k-1,y-x*(k-1),False)
            if k+1 in free:offer(x,k+1,y-x*(k+1),False)
        q=(x+y//2)//y
        if 2<=q<=65536:offer(x,q,y*q-x,True)
    return sorted(result.values(),key=lambda r:r[0])[:10]


def transform(p, pg, exe, rounds, random_seed):
    rng=random.Random(p.id+str(random_seed));best=pg;attempts=0
    for trial in range(rounds):
        graph=active_graph(p,first_recipes(p,best))
        ts=list(p.targets);rng.shuffle(ts)
        group=set(ts[:min(len(ts),max(6,int(len(ts)*(.4,.65,.9)[trial%3])))])
        fixed=active_graph(p,graph,set(ts)-group)
        free=set(fixed)|set(p.seeds)
        order=[x for x in ts if x in group and x not in free]
        if len(order)<3:continue
        if trial%2:order.sort(key=lambda t:t.bit_length())
        direct=available(p,free)
        # Targets earlier in this order may anchor later ones. Residuals from
        # all chosen relations will be synthesized in one shared subproblem.
        options={};prior=set(free);prices={}
        for y in order:
            cone=active_graph(p,graph,(y,))
            prices[y]=len(cone.keys()-free)
            options[y]=menus(y,prior,free,direct,p.limit)
            prior.add(y)
        frequency=Counter(v for choices in options.values()
                          for v in {v for _,_,ls in choices for v in ls if v not in free})
        picked={};required=set()
        for y in order:
            ranked=[]
            for cost,edges,ls in options[y]:
                sharing=sum(.55*log2(1+frequency[v]) for v in ls-free)
                sharing+=sum(1.35 for v in ls&required-free)
                ranked.append((cost-sharing+rng.random()*.45,edges,ls))
            if not ranked:continue
            c,edges,ls=min(ranked,key=lambda x:x[0])
            if c<=prices[y]+(.1 if trial%2 else -1.0):
                picked[y]=edges;required.update(ls)
        if not picked:continue
        # Keep the full original ancestry of the unswitched targets. This
        # frequently pays for part of the new payload before planning begins.
        retained=active_graph(p,graph,set(p.targets)-picked.keys())
        paid=set(p.seeds)|set(retained)
        rest=set(required)-paid
        if rest & picked.keys():continue
        raw=dict(retained)
        for v in rest & direct.keys():raw.setdefault(v,direct[v])
        todo=sorted(rest-raw.keys())
        if todo:
            popularity=Counter(x for op,a,b in retained.values() for x in (a,b))
            seeds=list(dict.fromkeys((*p.seeds,*sorted(paid-set(p.seeds),
                       key=lambda x:(x not in rest,-popularity[x],x))[:85],*(v for v in rest if v in raw))))
            # These residuals are new targets. An incumbent for the original
            # puzzle cannot supply a complete warm trace for this subproblem.
            generated=native(p,seeds,todo,exe,77,4,rng.randrange(1<<25))
            for v,e in generated.items():raw.setdefault(v,e)
        for t in order:
            if t in picked:
                for v,e in picked[t].items():raw.setdefault(v,e)
        attempts+=1
        try:cut=active_graph(p,raw)
        except (KeyError,ValueError):continue
        if len(cut)>=len(best):continue
        physical=schedule_like(p,best,cut)
        if physical is None or len(physical)>len(cut):
            other=compile_graph(p,cut,attempts=2,recompute=True,schedule_width=6)
            if other and (physical is None or len(other)<len(physical)):physical=other
        if physical and len(physical)<len(best):
            check(p,physical);best=physical
    return p.id,best,attempts


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ("base","output","exe"):ap.add_argument(name,type=Path)
    for name,default in (("rounds",4),("rows",48),("jobs",3),("seed",192)):
        ap.add_argument("--"+name,type=int,default=default)
    a=ap.parse_args();ps=read_puzzles("data/puzzles.csv");base=read_submission(a.base)
    selected=[p for p in ps if len(p.targets)>=8];random.Random(a.seed).shuffle(selected)
    if a.rows:selected=selected[:a.rows]
    done={};attempts=0
    def run(p):return transform(p,base[p.id],a.exe.resolve(),a.rounds,a.seed)
    with ThreadPoolExecutor(a.jobs) as pool:
        for pid,pg,n in pool.map(run,selected):
            check(next(p for p in selected if p.id==pid),pg)
            done[pid]=pg;attempts+=n
            if len(done)%25==0:write_submission(a.output,[p for p in ps if p.id in done],done)
    write_submission(a.output,[p for p in ps if p.id in done],done)
    print(len(done),attempts,sum(len(base[k])-len(v) for k,v in done.items()))


if __name__=="__main__":main()
