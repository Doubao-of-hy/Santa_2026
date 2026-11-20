"""Certify a lower bound after relaxing all possible first k helpers to free values."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import csv
from itertools import permutations
import json
from math import isqrt
from pathlib import Path

from elf import read_puzzles, read_submission, score, sha256
from lower_bounds import certificate, double_witnesses, values
from prefix_bounds import lower as prefix_lower


def operands(t,b,limit):
    possible=(t-b,b-t,b+t,b*t,t//b if t%b==0 else 0,b//t if b%t==0 else 0)
    return {a for a in possible if 0<a<=limit and a!=t and b!=t}


def close(known,goals,limit):
    while True:
        new={t for t in goals-known if any(operands(t,b,limit)&known for b in known)}
        if not new:return known
        known=known|new


def domains(p,depth,max_values):
    goals=set(p.targets)
    current=close(set(p.seeds),goals,p.limit)
    older=current
    for k in range(1,depth+1):
        # Before the k-th helper is created there is at most one operand
        # outside the (k-2)-helper envelope and the intervening target values.
        # Squaring/doubling that same operand is allowed as well.
        partners=older|(current&goals)
        new=set(current)
        for a in current:
            new.update(values(a,a,p.limit))
            for b in partners:new.update(values(a,b,p.limit))
            if len(new)>max_values:return
        expanded=close(new,goals,p.limit)
        if len(expanded)>max_values:return
        yield k,expanded
        older,current=current,expanded


def unary_capacity(h, targets, base, limit):
    """Bound how many of these first target occurrences can use h and one base operand."""
    if len(targets) == 1:
        return 1
    # For fixed h all four operators are reversible. Thus internal one-step
    # links between target integers are undirected. Without a first value
    # from outside the component, h alone cannot start producing its members.
    pending = set(targets)
    bound = len(pending)
    generated_without_target = values(h, h, limit)
    while pending:
        stack = [pending.pop()]
        rooted = False
        while stack:
            t = stack.pop()
            partners = operands(t, h, limit) & base
            rooted |= t in generated_without_target or bool(partners - targets)
            newly_reached = partners & pending
            pending.difference_update(newly_reached)
            stack.extend(newly_reached)
        if not rooted:
            bound -= 1
    return bound


def missing_capacity(p,allowed,rooted=False):
    required=set(p.targets)-allowed
    base=allowed|set(p.targets)
    incidence=Counter();members={};unsupported=set()
    for t in required:
        candidates={t//2} if t%2==0 else set()
        root=isqrt(t)
        if root*root==t:candidates.add(root)
        for b in base:
            if b==t:continue
            options=operands(t,b,p.limit)
            if options&base:break
            candidates.update(options)
        else:
            unsupported.add(t)
            for h in candidates-base:
                if rooted:
                    old=members.get(h)
                    if old is None:members[h]=t
                    elif isinstance(old,int):members[h]={old,t}
                    else:old.add(t)
                incidence[h]+=1
    if not unsupported:return 0
    if rooted:
        for h,group in members.items():
            if isinstance(group,set):
                incidence[h]=unary_capacity(h,group,base,p.limit)
    pairs=set()
    for x,y in permutations(unsupported,2):
        pairs.update((a,b) for a,b in double_witnesses(x,y) if 1<=b<a<=p.limit and a not in base and b not in base)
    degree=Counter();bonuses=[]
    for a,b in pairs:
        bonus=len(values(a,b,p.limit)&unsupported)-1
        if bonus>0:degree.update({a:bonus,b:bonus});bonuses.append(bonus)
    def cumulative(weights):
        out=[0]
        for w in sorted(weights,reverse=True)[:len(unsupported)+1]:out.append(out[-1]+w)
        return out
    u=cumulative(incidence.values());d=cumulative(degree.values())
    mixed=cumulative(2*incidence[v]+degree[v] for v in incidence.keys()|degree.keys())
    bonuses.sort(reverse=True)
    for h in range(len(unsupported)+2):
        n=h*(h-1)//2
        extra=min(sum(bonuses[:n]),d[min(h,len(d)-1)]//2)
        allowed_hits=n+min(u[min(h,len(u)-1)]+extra,mixed[min(h,len(mixed)-1)]//2)
        if allowed_hits>=len(unsupported):return h
    raise AssertionError("No sufficient helper count")


def bound(entry):
    p,depth,cap,rooted=entry
    original,_,helper_lb,_=certificate(p)
    prior=prefix_lower(p)
    best=max(prior,original+missing_capacity(p,set(p.seeds),True)) if rooted else prior;best_k=0
    for k,domain in domains(p,min(depth,helper_lb),cap):
        # At least k distinct non-target helpers are required by the original
        # incidence bound. Grant every possible value of that prefix for free.
        h=missing_capacity(p,domain,rooted)
        trial=original+k+h
        if trial>best:best=trial;best_k=k
    return p.id,prior,best,best_k


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('puzzles',type=Path);ap.add_argument('upper',type=Path);ap.add_argument('out',type=Path)
    ap.add_argument('--depth',type=int,default=3);ap.add_argument('--cap',type=int,default=2200)
    ap.add_argument('--rows',type=int,default=0);ap.add_argument('--jobs',type=int,default=4)
    ap.add_argument('--prior',type=Path,help="Optional previously certified per-row lower bounds")
    ap.add_argument('--rooted',action='store_true',help="Require an entry to each fixed-helper target component")
    args=ap.parse_args();ps=read_puzzles(args.puzzles);programs=read_submission(args.upper)
    score(ps,programs)
    if args.rows:ps=ps[:args.rows]
    prior={}
    if args.prior:
        with args.prior.open(encoding='utf-8-sig',newline='') as f:
            prior={r['id']:int(r['certified_lower']) for r in csv.DictReader(f)}
    records=[]
    with ProcessPoolExecutor(args.jobs) as pool:
        for pid,old,current,k in pool.map(bound,((p,args.depth,args.cap,args.rooted) for p in ps),chunksize=4):
            joint=max(current,prior.get(pid,0));upper=len(programs[pid])
            if joint>upper:raise AssertionError((pid,joint,upper))
            records.append((pid,old,current,k,joint,upper))
    with args.out.open('w',encoding='utf8',newline='') as f:
        w=csv.writer(f,lineterminator='\n');w.writerow(('id','prefix_lower','domain_lower','first_helpers','certified_lower','verified_upper'))
        w.writerows(records)
    totals={'rows':len(records),'domain_total':sum(r[2] for r in records),'certified_lower':sum(r[4] for r in records),
            'upper':sum(r[5] for r in records),'proved_optimal':sum(r[4]==r[5] for r in records),
            'improved_rows':sum(r[2]>r[1] for r in records),'max_domain':args.cap,'depth':args.depth,
            'puzzles_sha256':sha256(args.puzzles),'upper_sha256':sha256(args.upper),'certificate_sha256':sha256(args.out),
            'previous_certificate_sha256':sha256(args.prior) if args.prior else None,
            'rooted_helper_components':args.rooted}
    args.out.with_suffix('.json').write_text(json.dumps(totals,indent=2)+'\n',encoding='utf8')
    print(totals)


if __name__=='__main__':main()
