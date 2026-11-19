"""Factor the relationships between recovered centers, including scaled near matches."""
import argparse
from collections import Counter,defaultdict
from itertools import combinations
import json
from math import gcd,log2
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor

from elf import read_puzzles
from projection_models import build


def neighbors(p):
    def pairs(values):
        items=list(values);out=set()
        for i,a in enumerate(items):
            for b in items[:i+1]:
                out.update((a+b,abs(a-b),a*b))
                if a%b==0:out.add(a//b)
                if b%a==0:out.add(b//a)
        return {v for v in out if 0<v<=p.limit}
    seeds=set(p.seeds);one=pairs(seeds)|seeds;two=pairs(one)|one
    def price(v):
        if v in seeds:return 0.
        if v in one:return 1.
        if v in two:return 2.
        return 1.0+log2(max(2,v))*.22
    return price


def evaluate(required,graph,price):
    seen=set();active=set()
    def visit(v):
        if v in active:raise ValueError("cycle")
        if v in seen:return 0
        seen.add(v)
        if v not in graph:return price(v)
        op,a,b=graph[v];active.add(v)
        amount=1+visit(a)+visit(b)
        active.remove(v)
        return amount
    try:return sum(visit(v) for v in required),seen
    except ValueError:return 1e10,set()


def segment(out,h,k,p):
    residual=out-k*h
    recipes={}
    if k<1 or not 1<=k*h<=p.limit:return None
    if k!=1:recipes[k*h]=("*",k,h)
    if residual:recipes[out]=("+" if residual>0 else "-",k*h,abs(residual))
    return recipes


def model(p,proposals):
    # Include alternate facility assignments selected by the divisibility search.
    record=build([dict(m,targets=[*m["targets"],*m.get("alternatives",())]) for m in proposals])
    primary=record["targets"];alts=record["alternatives"]
    if not primary:return None
    centers={};frequency=Counter()
    for s in primary+alts:
        a,b=s["a"],s["b"];v=a*b
        frequency[v]+=2 if s in primary else 1
        if v!=a and v!=b:centers[v]=("*",a,b)
    known={}
    for m in proposals:
        for v,op,a,b in m.get("derived",[]):known.setdefault(v,(op,a,b))
    dag=known|centers
    required=sorted(frequency)
    price=neighbors(p)
    old,used=evaluate(required,dag,price)
    weights={v:frequency.get(v,0) for v in used}
    for v in required:
        if v in centers:
            _,a,b=centers[v]
            weights[a]=weights.get(a,0)+frequency[v]
            weights[b]=weights.get(b,0)+frequency[v]
    items=sorted((v for v in used if v>=2048 and weights.get(v,0)>=2),
                 key=lambda v:(-weights[v],v))[:55]
    bases=defaultdict(dict)
    for x,y in combinations(sorted(items),2):
        # x/m and y/n coincide up to a few units when two centers share a base.
        for m in range(1,35):
            n=(2*y*m+x)//(2*x)
            if not 1<=n<=2048:continue
            if gcd(n,m)!=1:continue
            num=abs(y*m-x*n)
            if num>20*(m+n):continue
            left=(2*x+m)//(2*m);right=(2*y+n)//(2*n)
            for h in {left,right,(left+right)//2,left-1,left+1,right-1,right+1}:
                if h<128 or h in (m,n):continue
                bases[h][x]=m;bases[h][y]=n
    pool=[]
    for h,members in bases.items():
        if len(members)<2:continue
        rough=sum(max(0,price(x)-.8-(k!=1)-bool(x-h*k)-.45*price(abs(x-h*k)))
                  for x,k in members.items())-price(h)
        pool.append((rough,h,members))
    pool.sort(reverse=True,key=lambda row:row[0]);pool=pool[:100]
    steps=0
    for epoch in range(5):
        best=old;choice=None
        for _,h,members in pool:
            forward={x:z for x,k in members.items() if x!=h and (z:=segment(x,h,k,p)) is not None}
            if not forward:continue
            anchors=[None]
            if h not in dag:anchors.extend(sorted(forward,key=lambda x:-weights.get(x,0))[:3])
            for anchor in anchors:
                trial=dag.copy()
                for x,edges in forward.items():
                    if x!=anchor:trial.update(edges)
                if anchor is not None:
                    k=members[anchor];r=anchor-k*h
                    if r:trial[k*h]=("-" if r>0 else "+",anchor,abs(r))
                    if k!=1:trial[h]=("/",k*h,k)
                cost,_=evaluate(required,trial,price)
                if cost+.02<best:best=cost;choice=trial
        if choice is None:break
        old=best;dag=choice;steps+=1
    _,live=evaluate(required,dag,price)
    record["derived"]=[[v,*dag[v]] for v in sorted(live) if v in dag]
    primitive=set(record["hubs"])|set(bases)
    record["hubs"]=sorted(v for v in live if v in primitive and v not in dag and price(v)>0)
    record["hierarchy_changes"]=steps
    return record


def worker(args):
    p,items=args
    return model(p,items)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("data",type=Path);ap.add_argument("output",type=Path)
    ap.add_argument("inputs",nargs="+",type=Path);ap.add_argument("--jobs",type=int,default=2)
    a=ap.parse_args()
    pp={p.id:p for p in read_puzzles(a.data)};bank=defaultdict(list)
    for path in a.inputs:
        for line in path.read_text().splitlines():
            row=json.loads(line)
            if row["targets"]:bank[row["id"]].append(row)
    seen={json.loads(line)["id"] for line in a.output.read_text().splitlines()} if a.output.exists() else set()
    tasks=[(pp[k],v) for k,v in bank.items() if k not in seen]
    with a.output.open("a",encoding="utf8") as file,ProcessPoolExecutor(a.jobs) as pool:
        for i,row in enumerate(pool.map(worker,tasks,chunksize=2),1):
            if row:file.write(json.dumps(row,separators=(",",":"))+"\n");file.flush()
            if i%60==0 or i==len(tasks):print(f"{i}/{len(tasks)}",flush=True)


if __name__=="__main__":main()
