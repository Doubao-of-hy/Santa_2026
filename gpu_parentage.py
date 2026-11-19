"""Find short two-parent dependencies between observed outputs, then select a full acyclic program."""
import argparse
from bisect import bisect_left
from collections import Counter, defaultdict
import csv
from itertools import combinations_with_replacement
from math import gcd,log2
from pathlib import Path
import random
from time import perf_counter

from elf import read_puzzles, read_submission, write_submission
from gpu_conditioned import local_search, normalized, select
from graph import active_graph, first_recipes


def terms(values,cap,scales):
    expanded=[]
    for i,x in enumerate(values):
        for k in scales:
            v=x*k
            if v>cap:break
            expanded.append((v,i,k))
    expanded.sort()
    return expanded,[entry[0] for entry in expanded]


def motifs(targets,cap,extra=()):
    # A catalogue of common scalar chains and any additional cheap scalars in
    # this puzzle. Coefficients need not divide each other or share one basis.
    scales=set(range(1,65))|{80,96,100,120,125,128,160,192,200,240,250,256,480,500,512,1000,1024}
    scales.update(k for k in extra if 2<=k<=2048)
    expanded,keys=terms(targets,cap,sorted(scales))
    rows={}
    for j,t in enumerate(targets):
        if t<10000:continue
        options={}
        for den in (1,2,3,4,5,7,8):
            goal=t*den
            if goal>cap:continue
            for left,ix,a in expanded:
                if ix==j:continue
                for wanted,sign1 in ((abs(goal-left),1),(goal+left,-1)):
                    if wanted<=0 or wanted>cap:continue
                    middle=bisect_left(keys,wanted)
                    # Adjacent nearly-coincident parent targets can share one
                    # scale. Probe both sides even if the first term cancels.
                    for k in range(max(0,middle-2),min(len(expanded),middle+2)):
                        right,iy,b=expanded[k]
                        if iy==j or iy==ix:continue
                        x,y=targets[ix],targets[iy]
                        sign2=1 if sign1<0 or goal>=left else -1
                        center=sign1*left+sign2*right
                        if center<=0 or center>cap:continue
                        r=goal-center
                        if abs(r)>3072:continue
                        # Suppress accidental identities where a tiny second
                        # term is merely another way to spell the offset.
                        if min(left,right)<max(8192,abs(r)*50):continue
                        gain=log2(min(t,left,right)/(1+abs(r)))
                        gain-=log2(1+a*b*den)*.80
                        if gain<9:continue
                        pair=tuple(sorted(((sign1*a,x),(sign2*b,y))))
                        key=(den,pair,r)
                        options[key]=gain
        if options:
            rows[t]=[(gain,key) for key,gain in sorted(options.items(),key=lambda z:-z[1])[:48]]
    return rows


def materialize(p,old,rows):
    base=active_graph(p,first_recipes(p,old))
    bank=defaultdict(set)
    for v,edge in base.items():bank[v].add(normalized(*edge))
    free=set(p.seeds)|base.keys()
    table=defaultdict(list)
    needed={v for row in rows.values() for _,(d,pair,r) in row
            for v in [d,abs(r),*(abs(m) for m,x in pair)] if 1<=v<=p.limit}
    for a,b in combinations_with_replacement(sorted(free),2):
        for v,op,x,y in ((a+b,'+',a,b),(b-a,'-',b,a),(a*b,'*',a,b),
                         (b//a if b%a==0 else 0,'/',b,a)):
            if v and v<=10000 and len(table[v])<12 and v not in (x,y):
                table[v].append(normalized(op,x,y))
    for v in needed:
        if v in table:
            bank[v].update(table[v])
        if v in free or bank.get(v):continue
        for a in sorted(free):
            choices=((v-a,'+',True),(v+a,'-',True),(a-v,'-',False),
                     (v//a if v%a==0 else 0,'*',True))
            for b,op,left in choices:
                if b not in table or b in (v,a):continue
                bank[b].update(table[b][:3])
                bank[v].add(normalized(op,b,a) if left else normalized(op,a,b))
            if len(bank.get(v,()))>=5:break
    valid=free|bank.keys()
    count=0
    for t,options in rows.items():
        for _,(d,pair,r) in options:
            if (d!=1 and d not in valid) or (r and abs(r) not in valid):continue
            (m,x),(n,y)=pair
            for common in {1,gcd(abs(m),abs(n))}:
                u,v=abs(m)//common,abs(n)//common
                if any(k!=1 and k not in valid for k in (u,v,common)):continue
                a,b=x*u,y*v
                c=(a if m>0 else -a)+(b if n>0 else -b)
                if c<=0 or max(a,b,c,c*common)>p.limit:continue
                new=[]
                if u>1:new.append((a,'*',x,u))
                if v>1:new.append((b,'*',y,v))
                if m>0 and n>0:new.append((c,'+',a,b))
                elif m<0:new.append((c,'-',b,a))
                else:new.append((c,'-',a,b))
                if common!=1:new.append((c*common,'*',c,common))
                total=c*common+r
                if r:new.append((total,'+' if r>0 else '-',c*common,abs(r)))
                if d!=1:new.append((t,'/',total,d))
                for value,s,a,b in new:
                    if value not in p.seeds and value not in (a,b):bank[value].add(normalized(s,a,b))
                count+=1
    return bank,count


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("data",type=Path)
    ap.add_argument("--base",type=Path);ap.add_argument("--output",type=Path)
    ap.add_argument("--rows",type=int,default=0);ap.add_argument("--cuts",type=int,default=80)
    ap.add_argument("--seconds",type=float,default=1);ap.add_argument("--seed",type=int,default=9917)
    ap.add_argument("--control",action="store_true")
    a=ap.parse_args();ps=read_puzzles(a.data);rng=random.Random(a.seed);rng.shuffle(ps)
    ps=[p for p in ps if max(p.seeds)<=35 and len(p.targets)>=6]
    if a.rows:ps=ps[:a.rows]
    with a.data.open(encoding="utf8") as f:labels={r["id"]:r.get("family","scored") for r in csv.DictReader(f)}
    base=read_submission(a.base) if a.base else {}
    counts=defaultdict(Counter);ans={};t0=perf_counter()
    for i,p in enumerate(ps,1):
        original=motifs(p.targets,p.limit)
        stats=counts[labels[p.id]]
        stats["puzzles"]+=1;stats["targets"]+=len(p.targets);stats["motifs"]+=len(original)
        stats["strong"]+=sum(max(score for score,_ in opts)>=20 for opts in original.values())
        if a.control:
            # Preserve each target's order of magnitude and number of terms.
            fake=tuple(min(p.limit,max(1,t+rng.randrange(-max(1,t//100),max(2,t//100)))) for t in p.targets)
            null=motifs(fake,p.limit)
            stats["control"]+=len(null)
            stats["control_strong"]+=sum(max(score for score,_ in opts)>=20 for opts in null.values())
        if base and original:
            old=base[p.id];bank,n=materialize(p,old,original)
            if n:
                local=local_search(p,old,bank,a.cuts,stats)
                pg=select(p,local,bank,a.seconds,stats)
                ans[p.id]=pg;stats["saved"]+=len(old)-len(pg)
                if len(pg)<len(old): print(p.id,len(old),len(pg),flush=True)
        if i%10==0 or i==len(ps):
            if a.output and ans:write_submission(a.output,[p for p in ps if p.id in ans],ans)
            print(i,dict((k,dict(x)) for k,x in counts.items()),round(perf_counter()-t0,1),flush=True)


if __name__=="__main__":main()
