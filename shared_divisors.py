"""Recover large common factors of noisy targets using a batched product/remainder tree."""
import argparse
from collections import Counter,defaultdict
from concurrent.futures import ProcessPoolExecutor,as_completed
from functools import lru_cache
from itertools import combinations
import json
from math import gcd,log2,prod
from pathlib import Path
import sys
import time

from elf import read_puzzles

DEPS=Path(__file__).resolve().parent/"work/lattice/deps"
if DEPS.is_dir():sys.path.insert(0,str(DEPS))
from flint import fmpz

PRIMES=(2,3,5,7,11,13,17,19,23,29,31,37,41,43,47,53,59,61,67,71,
        73,79,83,89,97,101,103,107,109,113,127)
SMALL=prod(PRIMES)


def strip(x):
    while (g:=gcd(x,SMALL))>1:x//=g
    return x


def overlaps(raw):
    level=list(map(fmpz,raw)); levels=[level]
    while len(level)>1:
        level=[level[i]*level[i+1] if i+1<len(level) else level[i] for i in range(0,len(level),2)]
        levels.append(level)
    remainder=level
    for layer in reversed(levels[:-1]):
        remainder=[remainder[i//2]%(v*v) for i,v in enumerate(layer)]
    return [(a,int(gcd(a,int(r//a)))) for a,r in zip(raw,remainder)]


@lru_cache(maxsize=16000)
def factor_pairs(g):
    primes=[(int(p),int(e)) for p,e in fmpz(g).factor()]
    divs=[1]
    for p,e in primes:
        old=divs.copy()
        for i in range(1,e+1): divs.extend(v*p**i for v in old)
    result={}
    for c in divs:
        if c<=127:continue
        a=max((v for v in divs if c%v==0 and v<=c//v),default=1)
        result[c]=a,c//a
    return result


def find_bases(points,radius,extra):
    owners={}
    for i,t in enumerate(points):
        bit=1<<i
        for delta in extra:
            n=t+delta
            if n<=max(128,radius*3):continue
            c=strip(n)
            if c>127:owners[c]=owners.get(c,0)|bit
    if not owners:return {}
    bases={}
    for c,g in overlaps(list(owners)):
        candidates=[]
        if g>127:candidates.append(g)
        if owners[c].bit_count()>1:candidates.append(c)
        for x in candidates:
            for d,f in factor_pairs(x).items():
                if d<max(384,radius*2):continue
                previous=bases.get(d,(0,f))
                bases[d]=previous[0]|owners[c],f
    return bases


def local_cost(v,seeds):
    if not v or v==1:return 0
    if v in seeds:return .25
    rem=strip(v)
    return min(.6+.16*log2(v),1.3+.07*log2(v)+.14*log2(rem))


def recover(p,radius,difference=False):
    ts=p.targets
    small={1,2,3,4,*p.seeds}
    for a in p.seeds:
        for b in p.seeds:
            small.update((a+b,abs(a-b),a*b))
    shifts=set(range(-radius,radius+1))
    shifts.update(s*d for d in small for s in (-1,1) if d<=4096)
    factors=find_bases(ts,radius,shifts)
    if difference:
        # Adjacent and short-range differences reveal a common offset that is
        # too large to appear among the small perturbations themselves.
        dpoints=sorted({b-a for i,a in enumerate(ts) for b in ts[i+1:i+5] if b-a>=8192})
        diff=find_bases(dpoints,min(24,radius),range(-min(24,radius),min(24,radius)+1))
        for d,(mask,f) in diff.items():
            if mask.bit_count()>=3 and d>=4096:factors.setdefault(d,(0,f))
    offers=[]
    for c,(mask,(a,b)) in factors.items():
        if mask and mask.bit_count()<2:continue
        shifts=[0]
        if not mask:
            residues=sorted(t%c for t in ts)
            clusters=[]
            for v in residues:
                if clusters and v-clusters[-1][-1]<=radius*2:clusters[-1].append(v)
                else:clusters.append([v])
            shifts.extend(group[len(group)//2] for group in clusters if len(group)>=3)
        for bias in shifts:
            rows={}
            for t in ts:
                k=(t-bias+c//2)//c
                if not 1<=k<=10**12:continue
                r=t-k*c;delta=r-bias
                d=(2*delta+k)//(2*k);e=delta-k*d
                if min(abs(delta),max(abs(d),abs(e)))>max(512,4*radius):continue
                mass=min(2*abs(delta)+1,(2*abs(d)+1)*(2*abs(e)+1))
                info=log2(c/mass)
                if info<7.5:continue
                coeff=local_cost(k,small);res=min(local_cost(abs(delta),small),local_cost(abs(d),small)+local_cost(abs(e),small)+1)
                value=1+.19*log2(t)-coeff-res-(k!=1)-(delta!=0)-bool(bias)+.24*min(24.,info)
                if value<2.3:continue
                d0=(2*r+k)//(2*k);row=dict(t=t,a=a,b=b,k=k,r=r,d=d0,e=r-k*d0,weight=round(value,3))
                if bias:row["bias"]=bias
                rows[t]=(value,row)
            if len(rows)<2:continue
            cost=min(local_cost(c,small),local_cost(a,small)+local_cost(b,small)+1)+.15*log2(1+abs(bias))+2
            offers.append((c,bias,cost,rows))
    best={};selected=[];chosen=set()
    for stage in range(10):
        win=None;price=1.5
        for i,(c,bias,cost,rows) in enumerate(offers):
            if i in chosen:continue
            differences=[val-best.get(t,(0,None))[0] for t,(val,row) in rows.items()]
            gain=sum(max(0,g) for g in differences)-cost
            if sum(g>.5 for g in differences)>=2 and gain>price:win=i;price=gain
        if win is None:break
        chosen.add(win);c,bias,cost,rows=offers[win];selected.append((c,bias))
        for t,z in rows.items():
            if z[0]>best.get(t,(0,None))[0]:best[t]=z
    main=[row for _,row in best.values()]
    ranked=sorted(((sum(v for v,r in rows.values())-cost,i) for i,(c,bias,cost,rows) in enumerate(offers)),reverse=True)
    seen=defaultdict(set);alts=[]
    for row in main:seen[row["t"]].add(row["a"]*row["b"])
    for _,i in ranked[:22]:
        for t,(val,row) in offers[i][3].items():
            c=row["a"]*row["b"];covered=seen[t]
            if len(covered)<4 and c not in covered and val+1.5>=best.get(t,(0,None))[0]:
                covered.add(c);alts.append(row)
    derived={}
    for row in (*main,*alts):
        if (bias:=row.get("bias")):
            r=row["r"];correction=r-bias
            if r>0 and bias>0 and correction:
                derived[r]=("+" if correction>0 else "-",bias,abs(correction))
    hubs=sorted({q for row in (*main,*alts) for q in (row["a"],row["b"])})
    return dict(id=p.id,hubs=hubs,targets=main,alternatives=alts,total=len(ts),
                fit=round(sum(v for v,r in best.values()),3),multi_stage=True,
                derived=[[v,*e] for v,e in derived.items()])


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ("data","output"):ap.add_argument(name,type=Path)
    ap.add_argument("--radius",type=int,default=64)
    ap.add_argument("--jobs",type=int,default=2)
    ap.add_argument("--rows",type=int,default=0)
    ap.add_argument("--difference",action="store_true")
    args=ap.parse_args()
    data=[p for p in read_puzzles(args.data) if max(p.seeds)<=35 and len(p.targets)>=6]
    if args.rows:data=data[:args.rows]
    done={json.loads(s)["id"] for s in args.output.read_text().splitlines()} if args.output.exists() else set()
    start=time.monotonic()
    with args.output.open("a",encoding="utf8") as f,ProcessPoolExecutor(args.jobs) as pool:
        futures=[pool.submit(recover,p,args.radius,args.difference) for p in data if p.id not in done]
        for n,v in enumerate(as_completed(futures),1):
            info=v.result();f.write(json.dumps(info,separators=(",",":"))+"\n");f.flush()
            if n%40==0 or n==len(futures):print(f"{n}/{len(futures)} {time.monotonic()-start:.1f}s",flush=True)


if __name__=="__main__":main()
