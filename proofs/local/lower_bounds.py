"""Certified instruction bounds from possible operand pairs in the final arithmetic DAG."""
import argparse
from collections import Counter
import csv
from itertools import permutations
import json
from math import isqrt
from pathlib import Path

from elf import read_puzzles, read_submission, score, sha256
from tiny import solve_tiny


def values(a,b,limit):
    large,small=max(a,b),min(a,b)
    result={a+b,large-small,a*b}
    if large%small==0:
        result.add(large//small)
    return {v for v in result if 0<v<=limit}


def double_witnesses(x,y):
    """All positive distinct operand pairs with two specified distinct outputs.

    For a >= b the four possible output functions are a+b, a-b, a*b, a/b.
    Choosing two functions gives six systems, each solved in integers below.
    Call this routine with both orders of the observed outputs.
    """
    # x = sum, y = difference
    if x>y and (x-y)%2==0:
        yield (x+y)//2,(x-y)//2
    # x = sum or difference, y = product
    d=x*x-4*y
    if d>=0:
        r=isqrt(d)
        if r*r==d and (x-r)%2==0 and x>r:
            yield (x+r)//2,(x-r)//2
    d=x*x+4*y
    r=isqrt(d)
    if r*r==d and (r-x)%2==0:
        yield (r+x)//2,(r-x)//2
    # x = sum or difference, y = quotient
    if x%(y+1)==0:
        b=x//(y+1)
        yield b*y,b
    if y>1 and x%(y-1)==0:
        b=x//(y-1)
        yield b*y,b
    # x = product, y = quotient
    if x%y==0:
        b=isqrt(x//y)
        if b*b*y==x:
            yield b*y,b


def incidence(puzzle):
    base=set(puzzle.targets)|set(puzzle.seeds)
    required=set(puzzle.targets)-set(puzzle.seeds)
    unsupported=required.copy()
    for a in base:
        for b in base:
            if b<=a:
                unsupported.difference_update(values(a,b,puzzle.limit)-{a,b})
    # A helper is a distinct generated value outside the relaxed base.
    # Unary coverage allows one helper with any base operand, or itself.
    unary=Counter()
    for t in unsupported:
        helpers=set()
        if t%2==0: helpers.add(t//2)
        r=isqrt(t)
        if r*r==t: helpers.add(r)
        for b in base:
            if b==t: continue
            helpers.update((t-b,b-t,b+t,b*t))
            if t%b==0: helpers.add(t//b)
            if b%t==0: helpers.add(b//t)
        for h in helpers-base:
            if 1<=h<=puzzle.limit: unary[h]+=1
    # An unordered pair of different helpers usually gives at most one of
    # these targets. Enumerate *all* exceptions and bound the extra coverage
    # that a set of h vertices can collect in their weighted graph.
    pairs=set()
    for x,y in permutations(unsupported,2):
        for a,b in double_witnesses(x,y):
            if 1<=b<a<=puzzle.limit and a not in base and b not in base:
                pairs.add((a,b))
    degree=Counter()
    edges=[]
    for a,b in pairs:
        extra=len(values(a,b,puzzle.limit)&unsupported)-1
        if extra>0:
            degree[a]+=extra
            degree[b]+=extra
            edges.append(extra)
    return required,unsupported,unary,degree,edges


def certificate(p):
    required,unsupported,unary,degree,weights=incidence(p)
    def sums(items):
        result=[0]
        for x in sorted(items,reverse=True)[:2*len(required)+10]: result.append(result[-1]+x)
        return result
    def top(s,k):return s[min(k,len(s)-1)]
    unary_s=sums(unary.values())
    degree_s=sums(degree.values())
    mixed_s=sums(2*unary[h]+degree[h] for h in unary.keys()|degree.keys())
    # h never needs to exceed |unsupported|: the universal pair-count bound
    # alone exceeds |unsupported| earlier, except for a singleton.
    edges_sorted=sorted(weights,reverse=True)
    h=0
    while True:
        pairs=h*(h-1)//2
        extra=min(sum(edges_sorted[:pairs]),top(degree_s,h)//2)
        maximum=pairs+min(top(unary_s,h)+extra,top(mixed_s,h)//2)
        if maximum>=len(unsupported):break
        h+=1
    # Before the first missing target occurs each instruction has produced
    # a helper. Upper bound the maximum integer reachable after each step.
    first=0
    if required:
        peak=max(p.seeds)
        while peak<min(required):
            peak=max(peak+peak,peak*peak)
            first+=1
    assists=max(h,first-1,0)
    return len(required),len(unsupported),h,assists+len(required)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("puzzles",type=Path)
    ap.add_argument("upper",type=Path)
    ap.add_argument("output",type=Path)
    args=ap.parse_args()
    puzzles=read_puzzles(args.puzzles)
    feasible=read_submission(args.upper)
    score(puzzles,feasible)
    rows=[]
    for p in puzzles:
        missing,unsupported,assists,bound=certificate(p)
        exact=solve_tiny(p) if p.limit<=128 else None
        if exact is not None: bound=max(bound,len(exact))
        upper=len(feasible[p.id])
        if bound>upper or (exact is not None and bound!=len(exact)):
            raise AssertionError((p.id,bound,upper))
        rows.append((p.id,missing,unsupported,assists,bound,upper,int(bound==upper)))
    with args.output.open("w",newline="",encoding="utf8") as f:
        writer=csv.writer(f)
        writer.writerow(("id","missing_targets","unsupported_targets","incidence_helper_bound",
                         "certified_lower_bound","verified_upper_bound","proved_optimal"))
        writer.writerows(rows)
    stats={"puzzles_sha256":sha256(args.puzzles),"tested_upper_sha256":sha256(args.upper),
           "certificate_csv_sha256":sha256(args.output),"rows":len(rows),
           "target_count_bound":sum(r[1] for r in rows),"certified_instruction_bound":sum(r[4] for r in rows),
           "proved_optimal":sum(r[-1] for r in rows)}
    args.output.with_suffix(".json").write_text(json.dumps(stats,indent=2)+"\n",encoding="utf8")
    print(stats)


if __name__=="__main__":
    main()
