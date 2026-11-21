"""Fit shared integer scales to near-rational pairs of targets, with held-out controls."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import csv
from itertools import combinations
import json
from math import log2
from pathlib import Path
import random

from elf import read_puzzles
from solvers.arithmetic.rational_links import convergents


def match(t,h):
    k=(t+h//2)//h
    if not 1<=k<=65536:return None
    r=t-k*h
    d=(2*r+k)//(2*k)
    e=r-k*d
    if abs(d)>192 or abs(e)>96:return None
    # The union of all accepted offsets covers at most 385*193 residues
    # modulo h, with additional overlap for small multipliers.
    window=min(385*k+193,385*193,h)
    surprise=log2(h/window)-.14*log2(k)-.10*log2(1+abs(r))
    if surprise<6:return None
    return {'t':t,'a':1,'b':h,'k':k,'r':r,'d':d,'e':e,'weight':round(surprise,3)}


def fit(ts):
    votes=Counter()
    for x,y in combinations(sorted(ts),2):
        for n,d in convergents(y,x,65536):
            a=(x+d//2)//d;b=(y+n//2)//n
            if min(a,b)<max(8192,n*24) or abs(a-b)>280:continue
            # Each of the two observations proposes a center. Neighboring
            # pairs vote together before individual offsets are considered.
            for h in {a,b,(a+b)//2}:votes[h]+=1
    if not votes:return []
    bins=Counter()
    for h,v in votes.items():bins[h//96]+=v
    chosen=sorted(votes,key=lambda h:-(bins[h//96]+.25*(bins[h//96-1]+bins[h//96+1])))[:90]
    tested=set();offers=[]
    for h in chosen:
        for delta in (0,-1,1,-2,2,-4,4,-8,8):
            c=h+delta
            if c in tested:continue
            tested.add(c)
            support=[r for t in ts if (r:=match(t,c)) is not None]
            if len(support)<3 or len({r['k'] for r in support})<2:continue
            # Disfavor an arbitrary small divisor of the actual common scale.
            merit=sum(min(22,r['weight']) for r in support)-.12*c.bit_length()
            merit-=sum(.16*abs(r['d']).bit_length()+.12*abs(r['e']).bit_length() for r in support)
            offers.append((merit,c,support))
    seen=set();out=[]
    for m,c,group in sorted(offers,key=lambda a:-a[0]):
        sig=frozenset(r['t'] for r in group)
        if sig in seen:continue
        if any(len(sig&s)>=.85*max(len(sig),len(s)) for s in seen):continue
        seen.add(sig);out.append((c,group))
        if len(out)>=6:break
    return out


def run(entry):
    p,holdout=entry
    ids=list(p.targets);rng=random.Random(p.id+'-rational')
    rng.shuffle(ids)
    train=ids[len(ids)//3:] if holdout else ids
    held=ids[:len(ids)//3]
    result=fit(train)
    groups=[g for h,g in result]
    if holdout:
        null=[]
        for t in held:
            jitter=max(1,t//43)
            delta=rng.randint(max(1,jitter//2),jitter)*rng.choice((-1,1))
            null.append(max(1,min(p.limit,t+delta)))
        return p.id,(len(held),sum(any(match(t,h) for h,_ in result) for t in held),
                     sum(any(match(t,h) for h,_ in result) for t in null),len(result))
    best={}
    for group in groups:
        for r in group:
            if r['t'] not in best or r['weight']>best[r['t']]['weight']:best[r['t']]=r
    rest=[r for group in groups for r in group if r!=best[r['t']]]
    return p.id,{'id':p.id,'targets':list(best.values()),'alternatives':rest,'hubs':[h for h,_ in result],'derived':[]}


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('input',type=Path)
    ap.add_argument('output',type=Path);ap.add_argument('--holdout',action='store_true')
    ap.add_argument('--jobs',type=int,default=4);a=ap.parse_args()
    ps=read_puzzles(a.input)
    with ProcessPoolExecutor(a.jobs) as pool:result=dict(pool.map(run,((p,a.holdout) for p in ps),chunksize=4))
    if a.holdout:
        with a.input.open(encoding='utf-8-sig',newline='') as f:families={r['id']:r.get('family','') for r in csv.DictReader(f)}
        summary={}
        for pid,vals in result.items():
            family=families[pid]
            prior=summary.setdefault(family,[0]*4)
            for i,v in enumerate(vals):prior[i]+=v
        print(summary)
        a.output.write_text(json.dumps({'columns':['held_out','matched','perturbed_matched','models'],'families':summary},indent=2)+'\n')
    else:
        models=[x for x in result.values() if x['targets']]
        a.output.write_text(''.join(json.dumps(m,separators=(',',':'))+'\n' for m in models),encoding='utf8')
        print(len(models),'puzzles',sum(len(m['targets']) for m in models),'targets')


if __name__=='__main__':main()
