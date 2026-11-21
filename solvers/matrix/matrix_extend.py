"""Test a finite grammar of compound centers against targets missing from a recovered table."""
import argparse
from collections import Counter
import csv
from itertools import combinations_with_replacement
import json
from math import log2
from pathlib import Path
import random

from elf import read_puzzles


def library(p,hubs):
    prim=set(hubs)
    expressions={}
    def put(op,a,b):
        if op=="-" and a<b:a,b=b,a
        v=a+b if op=="+" else (a-b if op=="-" else a*b)
        if 1<v<=p.limit and v not in prim and v not in (a,b):
            expressions.setdefault(v,(op,a,b))
            return v
        return None
    pairs=set()
    shifts=set()
    for a,b in combinations_with_replacement(hubs,2):
        v=put("*",a,b)
        if v:pairs.add(v)
        for op in ("+","-"):
            v=put(op,a,b)
            if v:shifts.add(v)
    centers={}
    def accept(v,family,extra):
        if v and v>=4096 and (v not in centers or centers[v][1]>extra):
            centers[v]=family,extra
    for x in pairs:
        for y in hubs:
            for op in "+-":accept(put(op,x,y),"product with hub correction",1)
            accept(put("*",x,y),"triple product",1)
        for y in shifts:
            for op in "+-":accept(put(op,x,y),"product with two hub corrections",2)
    for x in shifts:
        for y in hubs:accept(put("*",x,y),"product of hub and sum or difference",1)
    for x,y in combinations_with_replacement(sorted(pairs),2):
        for op in "+-":accept(put(op,x,y),"sum or difference of two products",2)
    for x,y in combinations_with_replacement(sorted(shifts),2):
        accept(put("*",x,y),"product of two sums or differences",3)
    return expressions,centers


def matches(ts,centers,hubs):
    offers={}
    radius=min(800,max(12,min(hubs)//100))
    complexity=log2(max(1,len(centers)))
    for t in ts:
        best=None
        for base,(family,extra) in centers.items():
            k=(t+base//2)//base
            if not 1<=k<=200000:continue
            r=t-k*base
            d=(1 if r>=0 else -1)*((abs(r)+k//2)//k)
            e=r-k*d
            if abs(r)>radius and (abs(d)>radius or abs(e)>radius):continue
            # Bonferroni-style penalty for the whole center catalogue. The
            # number of eligible integer residuals is bounded under either
            # one direct correction or two bounded corrections.
            margin=max(1,min(abs(r),max(abs(d),abs(e))))
            intensity=min((2*margin+1)*(k+1),(2*margin+1)**2)+2*margin+1
            information=log2(base/intensity)-complexity
            if information<6.5:continue
            quality=information-.8*extra-.11*k.bit_length()+int(k==1)
            entry=(quality,-extra,base,k,r,d,e,family)
            if best is None or entry>best:best=entry
        if best is not None:offers[t]=best
    return offers


def extend(p,m):
    if not m["hubs"]:return None,{}
    old={r["t"] for r in m["targets"]}
    ts=set(p.targets)-old
    fixed,centers=library(p,m["hubs"])
    found=matches(ts,centers,m["hubs"])
    pruned={}
    def trace(x):
        if x in pruned or x not in fixed:return
        op,a,b=fixed[x];trace(a);trace(b);pruned[x]=(op,a,b)
    extra=[]
    for t,(q,_,v,k,r,d,e,kind) in sorted(found.items()):
        trace(v)
        extra.append(dict(t=t,a=v,b=1,k=k,r=r,d=d,e=e,weight=round(q,4),shape=kind))
    if not extra:return None,centers
    result=dict(m,targets=m["targets"]+extra,
                derived=[[v,*recipe] for v,recipe in pruned.items()],extra=len(extra))
    return result,centers


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for k in ("puzzles","models","output"):ap.add_argument(k,type=Path)
    ap.add_argument("--control",action="store_true")
    args=ap.parse_args()
    puzzles={p.id:p for p in read_puzzles(args.puzzles)}
    counts=Counter();null=Counter();considered=Counter()
    families={r["id"]:r.get("family","scored") for r in csv.DictReader(args.puzzles.open())}
    rng=random.Random(6650)
    with args.output.open("w",encoding="utf8") as f:
        for line in args.models.read_text().splitlines():
            if not line:continue
            m=json.loads(line);p=puzzles[m["id"]];group=families[p.id]
            result,centers=extend(p,m)
            remain=set(p.targets)-{t["t"] for t in m["targets"]}
            if result:
                f.write(json.dumps(result,separators=(",",":"))+"\n");counts[group]+=result["extra"]
            if centers and remain:
                considered[group]+=len(remain)
                if args.control:
                    decoy=[max(1,min(p.limit,t+rng.randint(-max(1,t//5),max(1,t//5)))) for t in sorted(remain)]
                    null[group]+=len(matches(decoy,centers,m["hubs"]))
    print("unexplained targets",dict(considered),"new fits",dict(counts),"perturbed fits",dict(null))


if __name__=="__main__":main()
