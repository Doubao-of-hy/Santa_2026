"""Count a chosen subset of required targets while retaining every target as an operand."""
import argparse
import csv
import gzip
import hashlib
import io
import itertools
import json
import math
import os
import subprocess
import sys
from collections import Counter,defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=Path(os.getenv('SANTA_PROJECT',HERE.parents[1]))
GIT=Path(os.getenv('SANTA_CHECKOUT',HERE.parents[1]))
OFFICIAL=Path(os.getenv('SANTA_PUZZLES',ROOT/'data/puzzles.csv'))
sys.path.insert(0,str(ROOT))
from domain_bounds import domains,operands
from lower_bounds import certificate,double_witnesses,values
from elf import read_puzzles
def pop(x):return x.bit_count()
def supported(p,allowed):
    """A required target has a base/base realization, with all official targets retained."""
    base=allowed|set(p.targets);uncovered={}
    for t in sorted(set(p.targets)-allowed):
        cand={t//2} if t%2==0 else set()
        rt=math.isqrt(t)
        if rt*rt==t:cand.add(rt)
        for b in base:
            if b==t:continue
            opts=operands(t,b,p.limit)
            if opts&base:break
            cand.update(opts)
        else:uncovered[t]=cand-base
    return base,uncovered

def root_model(h,members,base,cap,bits):
    mask=sum(bits[t] for t in members)
    if len(members)<2:return mask,()
    rest=set(members);unrooted=[];own=values(h,h,cap)
    while rest:
        start=rest.pop();queue=[start];rooted=False;component=0
        while queue:
            t=queue.pop();component|=bits[t]
            partners=operands(t,h,cap)&base
            if t in own or partners-members:rooted=True
            near=partners&rest
            rest-=near;queue.extend(near)
        if not rooted:unrooted.append(component)
    return mask,tuple(unrooted)

def unary(pattern,s):
    m,cc=pattern
    return pop(m&s)-sum(c&s==c for c in cc)
def top_sum(a,k):
    return sum(sorted(a,reverse=True)[:k])

class Capacity:
    def __init__(self,p,base,incid):
        self.bits={t:1<<i for i,t in enumerate(incid)};bits=self.bits
        rawpairs=set()
        for t,q in itertools.permutations(incid,2):
            rawpairs.update((a,b) for a,b in double_witnesses(t,q) if 1<=b<a<=p.limit and a not in base and b not in base)
        self.pairs=[]
        mixing=set()
        for a,b in rawpairs:
            output=sum(bits[t] for t in values(a,b,p.limit) if t in bits)
            if pop(output)>1:self.pairs.append((a,b,output));mixing.update((a,b))
        groups=defaultdict(set)
        for t,neighbors in incid.items():
            for h in neighbors:groups[h].add(t)
        patterns=Counter();mixed={}
        for h,group in groups.items():
            if len(group)==1 and h not in mixing:continue
            pattern=root_model(h,group,base,p.limit,bits)
            if h in mixing:mixed[h]=pattern
            elif pop(pattern[0])-len(pattern[1])>1:patterns[pattern]+=1
        self.mixed={h:mixed.get(h,(0,())) for h in mixing}
        self.patterns=patterns
    def ceiling(self,s,h):
        # h artificial unary-only singletons safely cover all omitted helpers whose
        # full-set unary capacity is <=1. Their added capacity can only weaken the proof.
        n=h*(h-1)//2;single=[1]*h;both=[2]*h;degree=Counter();extra=[]
        for pattern,count in self.patterns.items():
            v=unary(pattern,s)
            if v>1:single.extend([v]*min(count,h));both.extend([2*v]*min(count,h))
        for a,b,outs in self.pairs:
            v=pop(outs&s)-1
            if v>0:degree[a]+=v;degree[b]+=v;extra.append(v)
        for helper,pat in self.mixed.items():
            v=unary(pat,s);d=degree[helper];single.append(v);both.append(2*v+d)
        bonus=min(top_sum(extra,n),top_sum(degree.values(),h)//2)
        return n+min(top_sum(single,h)+bonus,top_sum(both,h)//2)

def maximum_deleted(U,small,h):
    n=h*(h-1)//2
    return max((d for d in range(1,U) if U-d>n+min(h,max(0,U-d-small))),default=0)

def search(arg):
    p,k,h,M=arg
    allowed=set(p.seeds)
    if k:
        for step,domain in domains(p,k,3500):
            if step==k:allowed=domain;break
        else:raise ValueError(p.id+' no recorded envelope')
    assert certificate(p)[2]>=k
    base,incid=supported(p,allowed);U=len(incid);small=sum(t<=min(p.seeds) for t in incid)
    maxdrop=maximum_deleted(U,small,h)
    out={'id':p.id,'k':k,'h':h,'missing':M,'unsupported':U,'envelope_count':len(allowed),'maxdrop_after_envelope':maxdrop,'trial_counts':{},'verified':[]}
    if not maxdrop:return out
    cap=Capacity(p,base,incid)
    full=(1<<U)-1
    old=cap.ceiling(full,h);out['uncut_capacity']=old
    Ulist=list(incid)
    for j in range(1,min(maxdrop,3)+1):
        # No need to test more choices if this row already has its one-step strict lower bound.
        count=0;lowest=None
        for deleted in itertools.combinations(Ulist,j):
            s=full^sum(cap.bits[x] for x in deleted)
            c=cap.ceiling(s,h);count+=1
            if lowest is None or c<lowest:lowest=c
            if c<pop(s):
                out['verified'].append({'deleted':deleted,'counted':pop(s),'capacity':c,'new_lower':M+k+h+1})
                break
        out['trial_counts'][str(j)]={'subsets':count,'smallest_capacity':lowest}
        if out['verified']:break
    return out

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--jobs',type=int,default=4);args=ap.parse_args()
    design=json.loads((HERE/'design.json').read_bytes())
    puzzles={p.id:p for p in read_puzzles(OFFICIAL)}
    entries=[(puzzles[i],k,h,m) for i,k,h,m,j in design['initial_candidates'] if j]
    with ProcessPoolExecutor(args.jobs) as pool:
        records=[]
        for r in pool.map(search,entries,chunksize=1):
            records.append(r)
            if r['verified']:print('candidate',r['id'],r['verified'],flush=True)
            if len(records)%10==0:print('progress',len(records),'/',len(entries),flush=True)
            (HERE/'results.json').write_text(json.dumps(records,indent=1)+'\n',encoding='utf8')
if __name__=='__main__':main()
