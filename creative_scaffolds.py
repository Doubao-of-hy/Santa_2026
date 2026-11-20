"""Propose speculative constructor anchors from arithmetic puzzle inputs and fitted models.

Fitted model observations are accepted only if they exactly reproduce an actual
target. The output contains values only; the constructor builds them from the
true seeds and accounts for all instructions it ultimately uses.
"""
import argparse
import collections
import json
from math import gcd
from pathlib import Path

from elf import read_puzzles


def observations(puzzles, paths):
    bank=collections.defaultdict(list)
    by={p.id:p for p in puzzles}
    for path in paths:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                m=json.loads(line)
                p=by.get(m["id"])
                if p is None:
                    continue
                for row in m["targets"]:
                    a,b,k,r,t=(row[x] for x in ("a","b","k","r","t"))
                    if a>=1 and b>=1 and k>=1 and a*b*k+r==t and t in p.targets:
                        bank[p.id].append((a,b,k,r,t))
    return bank


def scaffold(p, fitted, mode=0):
    tars=tuple(sorted(p.targets))
    uses=collections.defaultdict(set)
    importance=collections.Counter()
    for a,b,k,r,t in fitted:
        for x,w in [(a,6),(b,6),(a*b,2),(k,3),(abs(r),1)]:
            if 1 < x < p.limit and (t,x) not in uses[x]:
                uses[x].add((t,x)); importance[x] += w
    # Nearby target differences that independently reveal repeated common-factor groups.
    ds=[b-a for i,a in enumerate(tars) for b in tars[i+1:min(i+7,len(tars))]]
    for i,a in enumerate(ds):
        for b in ds[:i]:
            g=gcd(a,b)
            if 128 < g <= p.limit and g not in tars:
                importance[g]+=.6
    selected=sorted(importance,key=lambda x:(-importance[x]/(1+x.bit_length()/21),x))[:12]
    core=[x for x in selected if x not in p.seeds and x not in p.targets]
    if mode==1 and fitted:
        # Search shifted products whose residuals are expressible in seed-like
        # values, then present both factors before the promising center.
        familiar={1,2,3,4,8,16,32,*p.seeds}
        for a in p.seeds:
            for b in p.seeds:
                familiar.update(x for x in (a+b,abs(a-b),a*b,a//b if a%b==0 else 0) if x>0)
        groups=collections.defaultdict(dict)
        for a,b,k,r,t in fitted:
            groups[a*b][t]=(a,b,k,r)
        def price(v):
            v=abs(v)
            if v==0:return 0
            if v in familiar:return 1
            return 1.8+.10*v.bit_length()
        shifted=[]
        for center,rows in groups.items():
            if len(rows)<3:continue
            variations=set()
            for a,b,k,r in rows.values():
                d=(2*r+k)//(2*k)
                variations.update((d,d-1,d+1))
            for d in variations:
                if not d or not 0<center+d<=p.limit:continue
                if any((center+d)*k>p.limit for a,b,k,r in rows.values()):continue
                value=sum(price(r)-price(r-k*d) for a,b,k,r in rows.values())-1-price(d)
                a,b,*_=next(iter(rows.values()))
                if value>1.0:
                    shifted.append((value,a,b,center+d))
        shifted.sort(key=lambda x:(-x[0],x[-1]))

        # Long shared factors become cheap if several nearby hubs are powers,
        # multiples or quotients of a single latent affine base. Sweep exact
        # signed perturbations at the hub level, independently of programs.
        pool=set()
        hubs=[a for a in core if a>=100][:5]
        for i,x in enumerate(hubs):
            for y in hubs[:i]:
                for e in range(-5,6):
                    for f in range(-5,6):
                        g=gcd(x+e,y+f)
                        if 64<=g<=min(x,y):pool.add(g)
                pool.add(abs(x-y))
        def supporting(g):
            if g<2 or g in hubs:return -1
            score=0; n=0
            for h in hubs:
                q=max(1,(h+g//2)//g)
                delta=abs(h-g*q)
                if q>96 or delta>12:continue
                score+=6 if q==1 or delta==0 else 5
                score-=max(q.bit_length()-3,0)*.4
                score-=delta.bit_length()*.42
                n+=1
            if n<2:return -1
            return score-.12*g.bit_length()
        gs=sorted([g for g in pool if supporting(g)>2],key=lambda g:(-supporting(g),g))[:3]
        anchors=gs[:2]
        if shifted:
            _,a,b,c=shifted[0]
            anchors+= [a,b,c]
        return list(dict.fromkeys([x for x in anchors+core[:8] if x not in p.seeds and x>=2]))
    return core

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("puzzles",type=Path)
    ap.add_argument("output",type=Path)
    ap.add_argument("models",type=Path,nargs="+")
    ap.add_argument("--alternate",action="store_true",help="prefer affine and signed-shift anchors")
    ap.add_argument("--ids",type=Path,help="optional whitespace-separated subset")
    args=ap.parse_args()
    puzzles=read_puzzles(args.puzzles)
    bank=observations(puzzles,args.models)
    selected=set(args.ids.read_text().split()) if args.ids else None
    if selected is not None and selected - {p.id for p in puzzles}:
        raise ValueError("unknown selected puzzle ID")
    out={}
    for p in puzzles:
        if selected is None or p.id in selected:
            values=scaffold(p,bank[p.id],mode=int(args.alternate))
            if args.alternate:
                values=values[:8]
            if values:
                out[p.id]=values
    args.output.write_text(json.dumps(out,sort_keys=True,separators=(",",":"))+"\n",encoding="utf-8")


if __name__=="__main__":
    main()
