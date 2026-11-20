"""Search for a shorter completion after preserving selected helpers of an incumbent."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import random
import subprocess

from elf import check, read_puzzles, read_submission, write_submission
from graph import active_graph, compile_graph, first_recipes


def add_value(value, known, choices, cap):
    # Keep a witness for every possible next value from the current dictionary.
    for x in (*known, value):
        a,b=max(value,x),min(value,x)
        if a+b<=cap:choices.setdefault(a+b,("+",a,b))
        if a>b:choices.setdefault(a-b,("-",a,b))
        if a*b<=cap:choices.setdefault(a*b,("*",a,b))
        if a%b==0:choices.setdefault(a//b,("/",a,b))
    known.add(value)


def prefixes(p, old, trials, depths):
    g=active_graph(p,first_recipes(p,old))
    goals=set(p.targets);external=goals-set(p.seeds)
    max_helpers=len(old)-len(external)-1
    helpers=set(g)-goals
    order={v:i for i,v in enumerate(g)}
    use=Counter(x for _,a,b in g.values() for x in (a,b))
    rng=random.Random(p.id+"-suffix")
    seen=set()
    for trial in range(trials):
        known=set();choices={};prefix={}
        for s in p.seeds:add_value(s,known,choices,p.limit)
        used=0
        while True:
            ready=(goals-known)&choices.keys()
            while ready:
                t=min(ready)
                prefix[t]=choices[t];add_value(t,known,choices,p.limit)
                ready=(goals-known)&choices.keys()
            h=max_helpers-used
            key=frozenset(known)
            if h in depths and key not in seen:
                seen.add(key)
                yield dict(prefix),tuple(sorted(known)),tuple(sorted(goals-known)),h
            if h<=min(depths) or not goals-known:break
            eligible=sorted((helpers-known)&choices.keys())
            if not eligible:break
            if trial==0:v=min(eligible,key=order.get)
            elif trial==1:v=max(eligible,key=lambda x:(use[x],-order[x]))
            else:v=min(eligible,key=lambda x:rng.random()*3+order[x]/max(1,len(g))-.15*use[x])
            prefix[v]=choices[v];add_value(v,known,choices,p.limit);used+=1


def search(p, old, exe, trials, depths, limit):
    best=old;counts=Counter()
    for prefix,known,missing,budget in prefixes(p,old,trials,depths):
        if len(prefix)+len(missing)>=len(best):
            continue
        if missing:
            data=" ".join(map(str,(p.limit,len(known),len(missing),budget,limit,*known,*missing)))+"\n"
            run=subprocess.run([str(exe),"--incremental"],input=data,text=True,capture_output=True,check=True)
            rows=run.stdout.splitlines()
            status=rows[0].split()[0];counts[status]+=1
            if status!="FOUND":continue
            values=tuple(map(int,rows[1].split()))
            if values[:len(known)]!=known:raise ValueError("native witness prefix differs")
            active=set();offers={}
            for s in known:add_value(s,active,offers,p.limit)
            for t in values[len(known):]:
                prefix[t]=offers[t];add_value(t,active,offers,p.limit)
        proposed=compile_graph(p,prefix,attempts=4,schedule_width=10,recompute=True)
        if proposed is not None and len(proposed)<len(best):
            check(p,proposed);best=proposed
    return p.id,best,counts


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for k in ("base","output","exe"):ap.add_argument(k,type=Path)
    ap.add_argument("--ids",nargs="*")
    ap.add_argument("--depths",default="2,3,4")
    for k,v in (("trials",8),("steps",31),("nodes",2000),("jobs",3)):
        ap.add_argument("--"+k,type=int,default=v)
    a=ap.parse_args();ps=read_puzzles("data/puzzles.csv");base=read_submission(a.base)
    ds={int(s) for s in a.depths.split(",")}
    if min(ds)<0:ap.error("Require nonnegative suffix budgets")
    selected=[p for p in ps if (p.id in a.ids if a.ids else p.limit>128 and len(base[p.id])<=a.steps)]
    def solve(p):return search(p,base[p.id],a.exe.resolve(),a.trials,ds,a.nodes)
    done={};counts=Counter()
    with ThreadPoolExecutor(a.jobs) as pool:
        for pid,pg,stats in pool.map(solve,selected):
            done[pid]=pg;counts.update(stats)
            if len(done)%10==0:write_submission(a.output,[p for p in ps if p.id in done],done)
    write_submission(a.output,[p for p in ps if p.id in done],done)
    print(len(done),dict(counts),"saved",sum(len(base[k])-len(v) for k,v in done.items()))


if __name__=="__main__":main()
