"""Independent finite checker for projected rooted capacity; uses Python's exact integers."""
import argparse
import csv
import hashlib
import io
import itertools
import json
import math
import os
import subprocess
from collections import Counter,defaultdict
from pathlib import Path
HERE=Path(__file__).resolve().parent
GIT=Path(os.getenv('SANTA_CHECKOUT',HERE.parents[1]))
PUZZLES=Path(os.getenv('SANTA_PUZZLES',GIT/'data/puzzles.csv'))

def outcomes(a,b,cap):
    hi,lo=sorted((a,b),reverse=True);z={hi+lo,hi-lo,hi*lo}
    if hi%lo==0:z.add(hi//lo)
    return {x for x in z if 1<=x<=cap}

def other(t,known,cap):
    if t==known:return set()
    x={t-known, known-t,known+t,t*known}
    if not t%known:x.add(t//known)
    if not known%t:x.add(known//t)
    return {v for v in x if 1<=v<=cap and v!=t}

def close_once_stable(start,goals,cap):
    avail=set(start)
    while True:
        nxt={t for t in goals-avail if any(other(t,b,cap)&avail for b in avail)}
        if not nxt:return avail
        avail|=nxt

def envelope(seeds,goals,cap,k):
    if k==0:return set(seeds),None
    current=close_once_stable(seeds,goals,cap);earlier=current
    for depth in range(1,k+1):
        new=set(current);partners=earlier|(current&goals)
        for a in current:
            new.update(outcomes(a,a,cap))
            for b in partners:new.update(outcomes(a,b,cap))
        earlier,current=current,close_once_stable(new,goals,cap)
    return current,earlier

def solve_pair(t,q,cap):
    """Possible two distinct positive inputs having both outputs (enumerate six law pairs)."""
    solved=set()
    def add(a,b):
        if 1<=b<a<=cap and {t,q}<=outcomes(a,b,cap):solved.add((a,b))
    for x,y in [(t,q),(q,t)]:
        # Sum and difference. Sum or difference with product.
        if (x+y)%2==0:add((x+y)//2,(x-y)//2)
        for sign in [-1,1]:
            disc=x*x+sign*4*y
            if disc>=0:
                root=math.isqrt(disc)
                if root*root==disc and not (x+root)%2:
                    a=(x+root)//2;add(a,abs(x-a))
        # Sum or difference with quotient.
        for denominator in (y+1,y-1):
            if denominator>0 and x%denominator==0:
                b=x//denominator;add(b*y,b)
        # Product and quotient.
        if x%y==0:
            b=math.isqrt(x//y)
            if b*b*y==x:add(b*y,b)
    return solved

def choose_targets(base,goals,cap):
    u=set()
    for t in goals-base[0]:
        if all(not other(t,b,cap)&base[1] for b in base[1]):u.add(t)
    return u

def capacity(allowed,all_targets,chosen,cap,h,brute=False,pair_limit=None,excluded=frozenset()):
    base=set(allowed)|all_targets
    if brute:
        helpers=set(range(1,cap+1))-base-excluded
    else:
        helpers=set()
        for t in chosen:
            for b in base:helpers.update(other(t,b,cap))
            rt=math.isqrt(t)
            if rt*rt==t:helpers.add(rt)
            if t%2==0:helpers.add(t//2)
        helpers-=base
    if brute:
        groups={v:{t for t in chosen if t in outcomes(v,v,cap) or any(t in outcomes(v,b,cap) and t!=b for b in base)} for v in helpers}
    else:
        groups=defaultdict(set)
        for t in chosen:
            g=set()
            for b in base:g.update(other(t,b,cap))
            rt=math.isqrt(t)
            if rt*rt==t:g.add(rt)
            if t%2==0:g.add(t//2)
            for v in g-base-excluded:groups[v].add(t)
    cap1={}
    for v,group in groups.items():
        if not group:continue
        if len(group)==1:
            cap1[v]=1;continue
        remaining=set(group);lost=0
        while remaining:
            component={remaining.pop()};todo=list(component);entry=False
            while todo:
                t=todo.pop()
                if brute:partners={b for b in base if b!=t and t in outcomes(v,b,cap)}
                else:partners=other(t,v,cap)&base
                if partners-group or t in outcomes(v,v,cap):entry=True
                adjacent=partners&remaining;remaining-=adjacent;todo.extend(adjacent);component|=adjacent
            lost+=not entry
        cap1[v]=len(group)-lost
    if brute:
        pairs=itertools.combinations(helpers,2)
    else:
        candidates=set()
        for t,q in itertools.combinations(chosen,2):candidates.update(solve_pair(t,q,cap))
        pairs=((a,b) for a,b in candidates if a not in base and b not in base and a not in excluded and b not in excluded)
    degrees=Counter();bonuses=[]
    for a,b in pairs:
        v=len(outcomes(a,b,cap)&chosen)-1
        if v>0:
            degrees[a]+=v;degrees[b]+=v;bonuses.append(v)
    def top(xs,n):return sum(sorted(xs,reverse=True)[:n])
    pairs=h*(h-1)//2
    if pair_limit is not None:
        pairs=min(pairs,pair_limit)
    u=top(cap1.values(),h);d=top(degrees.values(),h)
    ab=top(bonuses,pairs);mix=top([2*cap1.get(v,0)+degrees[v] for v in cap1.keys()|degrees.keys()],h)
    maximum=pairs+min(u+min(ab,d//2),mix//2)
    return maximum,{'helper_pairs':pairs,'top_unary':u,'top_degrees':d,'top_pair_bonuses':ab,'top_mixed':mix}

def rows_from(blob):
    return {r['id']:r for r in csv.DictReader(io.StringIO(blob.decode('utf-8-sig')))}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--puzzles',type=Path,default=PUZZLES);ap.add_argument('--output', type=Path);args=ap.parse_args()
    setup=json.loads((HERE/'design.json').read_bytes())
    blob=subprocess.check_output(['git','-C',str(GIT),'show',setup['frozen']+':collaboration/puzzle-bounds.csv'])
    official=args.puzzles.read_bytes()
    assert hashlib.sha256(blob).hexdigest()==setup['current_sha256'] and hashlib.sha256(official).hexdigest()==setup['puzzles_sha256']
    bounds=rows_from(blob);puzzles=rows_from(official);improved={}
    candidates=json.loads((HERE/'witnesses.json').read_bytes())
    for i,w in candidates.items():
        p=puzzles[i];seeds=set(json.loads(p['starting_values']));goals=set(json.loads(p['targets']));cap=int(p['value_limit'])
        k=w['k'];allowed,prior=envelope(seeds,goals,cap,k)
        assert not k or goals-prior,'The relaxed (k-1)-helper envelope must miss an actual target.'
        base=allowed|goals;u=choose_targets((allowed,base),goals,cap)
        deleted=set(w['deleted']);assert deleted<=u
        s=u-deleted;old=int(bounds[i]['certified_lower']);m=len(goals-seeds);h=w.get('remaining_helpers',old-m-k)
        assert k>=0 and h>=0 and m+k+h>=old
        cut,terms=capacity(allowed,goals,s,cap,h)
        assert cut<len(s)
        improved[i]={'old':old,'new':m+k+h+1,'required':m,'witness_first_helpers':k,'remaining_helper_budget':h,'original_free_envelope_size':len(allowed),'unsupported':len(u),'deleted':sorted(deleted),'counted':len(s),'capacity':cut,'terms':terms}
    baseline=sum(int(r['certified_lower']) for r in bounds.values())
    assert baseline==36768
    doc={'frozen':setup['frozen'],'puzzles_sha256':setup['puzzles_sha256'],'published_table_sha256':setup['current_sha256'],'baseline':baseline,'proposed_new_total':baseline+sum(v['new']-v['old'] for v in improved.values()),'rows':improved}
    if args.output is None:
        if doc != json.loads((HERE/'verified.json').read_bytes()):
            raise ValueError('The rebuilt certificate differs from the published one.')
    else:
        args.output.write_bytes((json.dumps(doc,indent=1)+'\n').encode())
    print([(i,v['old'],v['new'],v['counted'],v['capacity']) for i,v in improved.items()],doc['proposed_new_total'])
if __name__=='__main__':main()
