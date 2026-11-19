"""Evaluate a product of two independently shifted recovered bases on held-out targets."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import csv
from dataclasses import replace
import json
from pathlib import Path
import random
import subprocess

from elf import read_puzzles
from matrix_scan import recover


def original_fit(t,hubs):
    best=0
    for i,a in enumerate(hubs):
        for b in hubs[i:]:
            center=a*b;k=(t+center//2)//center
            if not 1<=k<=100000000:continue
            r=t-k*center;d=(2*r+k)//(2*k);e=r-k*d
            if abs(r)<=128 or max(abs(d),abs(e))<=64:
                mass=min(2*abs(r)+1,(2*abs(d)+1)*(2*abs(e)+1))
                best=max(best,(center/mass))
    return best>=2**11


def detect(p,hubs,goals,exe):
    if not goals or not hubs:return []
    run=subprocess.run([exe],input=" ".join(map(str,(p.limit,len(hubs),len(goals),len(p.seeds),*hubs,*goals,*p.seeds)))+"\n",text=True,capture_output=True,check=True)
    matches=[]
    for target,line in zip(goals,run.stdout.splitlines(),strict=True):
        f=line.split();t,a,u,b,v,k,r,d,e=map(int,f[:9]);q,ev=map(float,f[9:])
        if t!=target:raise ValueError("mismatched target")
        if not a:continue
        if t!=(a+u)*(b+v)*k+r or r!=k*d+e:raise ValueError("bad identity")
        row=dict(t=t,a=a+u,b=b+v,k=k,r=r,d=d,e=e,weight=ev,offsets=[a,u,b,v],quality=q)
        matches.append(row)
    return matches


def worker(args):
    p,model,exe,recovery,control=args
    rng=random.Random(32119+int(p.id.split("_")[-1]))
    if control:
        shuffled=list(p.targets);rng.shuffle(shuffled)
        goals=shuffled[:max(1,len(shuffled)//4)]
        train=sorted(shuffled[len(goals):])
        model=recover(replace(p,targets=tuple(train)),recovery,wide=True)
        controls=[max(1,min(p.limit,t+rng.randint(-max(1,t//7),max(1,t//7)))) for t in goals]
    else:
        goals=list(p.targets);controls=[]
    h=model["hubs"]
    remaining=[t for t in goals if not original_fit(t,h)]
    neg=[t for t in controls if not original_fit(t,h)]
    scores=detect(p,h,remaining+neg,exe)
    stats=Counter()
    for tag,values in (("target",remaining),("random",neg)):
        stats[tag,"attempted"]+=len(values)
        for level in (3,5,7,9,12):
            stats[tag,level]+=sum(row["t"] in values and row["quality"]>=level for row in scores)
    if control:return p.id,None,stats
    extra=[r for r in scores if r["quality"]>=5 and r["weight"]>=8]
    if not extra:return p.id,None,stats
    bytarget={r["t"]:r for r in model["targets"]}
    alternatives=[];derived={};primitives=set(h)
    for row in extra:
        a,u,b,v=row["offsets"]
        for x,shift in ((a,u),(b,v)):
            n=x+shift
            if shift and n not in primitives and n not in derived:
                derived[n]=("+" if shift>0 else "-",x,abs(shift))
        if row["t"] in bytarget:alternatives.append(row)
        else:bytarget[row["t"]]=row
    out=dict(model,targets=list(bytarget.values()),alternatives=alternatives,derived=[[v,*e] for v,e in derived.items()],shifted=len(extra),multi_stage=True)
    return p.id,out,stats


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ("puzzles","models","output"):parser.add_argument(key,type=Path)
    parser.add_argument("--control",action="store_true")
    parser.add_argument("--jobs",type=int,default=2)
    parser.add_argument("--rows",type=int,default=0)
    a=parser.parse_args()
    data={p.id:p for p in read_puzzles(a.puzzles)}
    tags={r["id"]:r.get("family","scored") for r in csv.DictReader(a.puzzles.open())}
    models=[json.loads(s) for s in a.models.read_text().splitlines()]
    if a.rows:models=models[:a.rows]
    totals=Counter();nout=nnew=0
    exe=str(Path("work/creative/shifted-factors.exe").resolve())
    recovery=str(Path("work/creative/matrix-wide.exe").resolve())
    with ProcessPoolExecutor(a.jobs) as pool,a.output.open("w",encoding="utf8") as out:
        tasks=((data[m["id"]],m,exe,recovery,a.control) for m in models)
        for pid,row,stats in pool.map(worker,tasks,chunksize=1):
            for key,n in stats.items():totals[(tags[pid],*key)]+=n
            if row:
                out.write(json.dumps(row,separators=(",",":"))+"\n");out.flush()
                nout+=1;nnew+=row["shifted"]
        if a.control:json.dump({str(k):v for k,v in sorted(totals.items(),key=lambda t:str(t[0]))},out,indent=2)
    print("output rows",nout,"shifted options",nnew)


if __name__=="__main__":main()
