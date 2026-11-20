"""Test complete signed three-term neighborhoods on expensive private expressions."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import csv
from pathlib import Path
import random
import subprocess

from elf import check, read_puzzles, read_submission, write_submission
from gpu_join import cut_many
from gpu_schedule import schedule_like
from graph import active_graph, compile_graph, first_recipes


def solve(p, old, exe, anchors, cuts):
    graph=active_graph(p,first_recipes(p,old))
    use=Counter(x for _,a,b in graph.values() for x in {a,b})
    cases=[]
    for t in graph:
        if t<256 or (t not in p.targets and use[t]<2):continue
        kept,free=cut_many(p,graph,{t})
        budget=len(graph)-len(kept)
        if budget<5:continue
        values=set(p.seeds)|free.keys()
        material=sorted(values,key=lambda x:(x not in p.seeds,x not in p.targets,
                                -use[x],abs(x.bit_length()-t.bit_length()//2),x))
        # Keep actual input values, popular constants, and a sample of the
        # larger magnitudes that a constant-only roster would otherwise omit.
        popular=sorted(values,key=lambda x:(x not in p.seeds,-use[x],x))
        large=sorted(values,key=lambda x:(abs(x.bit_length()-t.bit_length()),-use[x],x))
        roster=list(dict.fromkeys((*p.seeds,*popular[:anchors//2],*large[:anchors//4],*material)))[:anchors]
        cases.append((budget,t,kept,roster))
    cases.sort(key=lambda item:(-item[0],item[1]))
    cases=cases[:cuts]
    data="".join(" ".join(map(str,(p.limit,t,len(free),budget,18,*free)))+"\n"
                 for budget,t,kept,free in cases)
    stream=iter(subprocess.run([str(exe)],input=data,text=True,capture_output=True,check=True).stdout.splitlines())
    found=[];inspected=0
    for budget,t,kept,free in cases:
        n,work=map(int,next(stream).split());inspected+=work
        for _ in range(n):
            patch={}
            for _ in range(int(next(stream))):
                v,op,a,b=next(stream).split()
                patch[int(v)]=(op,int(a),int(b))
            try:g=active_graph(p,graph|patch)
            except (KeyError,ValueError):continue
            if len(g)<len(old):found.append((len(g),patch))
    if next(stream,None) is not None:raise ValueError("Unconsumed search output")
    best=old
    for _,patch in sorted(found,key=lambda pair:pair[0]):
        try:g=active_graph(p,graph|patch)
        except (KeyError,ValueError):continue
        if len(g)>=len(best):continue
        feasible=schedule_like(p,best,g)
        if feasible is None or len(feasible)>len(g):
            other=compile_graph(p,g,recompute=True,schedule_width=6)
            if other and (feasible is None or len(other)<len(feasible)):feasible=other
        if feasible and len(feasible)<len(best):
            check(p,feasible);best=feasible;graph=active_graph(p,first_recipes(p,best))
    return p.id,best,len(cases),inspected


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for k in ("base","output","exe"):ap.add_argument(k,type=Path)
    ap.add_argument("--families",type=Path)
    ap.add_argument("--family",default="independent")
    for k,v in (("rows",40),("cuts",9),("anchors",74),("jobs",3),("seed",846)):
        ap.add_argument("--"+k,type=int,default=v)
    a=ap.parse_args();ps=read_puzzles("data/puzzles.csv");base=read_submission(a.base)
    selected=[p for p in ps if len(base[p.id])>50]
    if a.families:
        with a.families.open(encoding="utf-8-sig",newline="") as f:
            ids={r["id"] for r in csv.DictReader(f) if r["assigned"]==a.family}
        selected=[p for p in selected if p.id in ids]
    random.Random(a.seed).shuffle(selected)
    if a.rows:selected=selected[:a.rows]
    def work(p):return solve(p,base[p.id],a.exe.resolve(),a.anchors,a.cuts)
    done={};total=checks=0
    with ThreadPoolExecutor(a.jobs) as pool:
        for pid,pg,n,inspected in pool.map(work,selected):
            done[pid]=pg;total+=n;checks+=inspected
            if len(done)%20==0:write_submission(a.output,[p for p in ps if p.id in done],done)
    write_submission(a.output,[p for p in ps if p.id in done],done)
    print(len(done),total,checks,sum(len(base[k])-len(v) for k,v in done.items()))


if __name__=="__main__":main()
