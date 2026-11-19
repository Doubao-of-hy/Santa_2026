"""Use short integer relations among several large values to rewrite a target."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from itertools import combinations
from math import gcd
from pathlib import Path
import random
import sys
import time

from elf import read_puzzles, read_submission, write_submission
from graph import active_graph, compile_graph, first_recipes


def identities(values, rng, samples):
    # The final coordinate is the exact signed residual of a linear combination.
    from flint import fmpz_mat
    for a, b in combinations(values, 2):
        u, v, p, q, r, s = a, b, 1, 0, 0, 1
        while v:
            k = u // v
            u, v, p, q, r, s = v, u % v, r, s, p-k*r, q-k*s
            if max(abs(p), abs(q)) > 65536:
                break
            if p and q:
                yield (a, b), (p, q)
    for dimension in (3, 4):
        if len(values) < dimension:
            continue
        groups = set()
        amount = min(samples, len(values) * (len(values)-1) *
                     (len(values)-2)//6) if dimension==3 else samples//3
        if dimension==3 and len(values)<16:
            groups.update(combinations(values, dimension))
        else:
            for _ in range(amount):
                groups.add(tuple(sorted(rng.sample(values, dimension))))
        for group in sorted(groups):
            for scale in (1, 4096, 1<<21):
                matrix = [[int(i==j)*scale for j in range(dimension)]+[x]
                          for i,x in enumerate(group)]
                for row in fmpz_mat(matrix).lll().tolist():
                    coeff = tuple(int(v)//scale for v in row[:-1])
                    if all(coeff) and max(map(abs, coeff)) <= 4096:
                        yield group, coeff


class Literals:
    def __init__(self, puzzle, graph):
        self.known = set(puzzle.seeds) | set(graph)
        self.table = {}
        values = sorted(self.known)
        for i, a in enumerate(values):
            for b in values[:i+1]:
                if a <= puzzle.limit-b:
                    self.table.setdefault(a+b, ('+',a,b))
                if a>b:
                    self.table.setdefault(a-b, ('-',a,b))
                if a <= puzzle.limit//b:
                    self.table.setdefault(a*b, ('*',a,b))
                if a%b==0:
                    self.table.setdefault(a//b, ('/',a,b))

    def supply(self, value, draft, pivot):
        if value==pivot:
            return False
        if value in self.known or value in draft:
            return True
        recipe = self.table.get(value)
        if recipe is None or pivot in recipe[1:]:
            return False
        draft[value] = recipe
        return True


def expression(puzzle, y, denominator, others, mode, literals):
    steps = {}
    terms = []
    for factor, x in others:
        divisor = gcd(abs(factor), denominator)
        coefficient = abs(factor)//divisor
        d = denominator//divisor
        if mode=='direct':
            d = 1
        base, residual = divmod(x, d)
        if residual and (mode=='up' or (mode=='center' and residual*2>d)):
            base += 1
            residual -= d
        if base < 1 or base*d>puzzle.limit or base*coefficient>puzzle.limit:
            return None
        if d>1:
            if not literals.supply(d, steps, y):
                return None
            multiple=base*d
            if residual:
                if not literals.supply(abs(residual), steps, y):
                    return None
                steps[multiple]=('-',x,residual) if residual>0 else ('+',x,-residual)
            steps[base]=('/',multiple,d)
        if coefficient>1:
            if not literals.supply(coefficient, steps, y):
                return None
            steps[base*coefficient]=('*',base,coefficient)
        terms.append(base * coefficient * (1 if factor>0 else -1))
    dest = y * denominator if mode=='direct' else y
    if not 1<=dest<=puzzle.limit:
        return None
    correction = dest-sum(terms)
    if correction:
        if not literals.supply(abs(correction), steps, y):
            return None
        terms.append(correction)
    # Try subtraction before addition when positive terms might overflow.
    def join(pending, value, draft):
        if not pending:
            return draft if value==dest else None
        for idx, term in enumerate(pending):
            output=value+term
            if not 1<=output<=puzzle.limit:
                continue
            trial = draft.copy()
            if value:
                trial[output]=('+', value, term) if term>0 else ('-', value, -term)
            chosen=join(pending[:idx]+pending[idx+1:],output,trial)
            if chosen is not None:
                return chosen
        return None
    steps=join(sorted(terms, key=lambda v:-abs(v)),0,steps)
    if not steps:
        return None
    if mode=='direct' and denominator!=1:
        if not literals.supply(denominator, steps, y):
            return None
        steps[y]=('/',dest,denominator)
    return steps if y in steps else None


def improve(puzzle, program, samples, seed):
    graph=active_graph(puzzle,first_recipes(puzzle,program))
    targets=set(puzzle.targets)-set(puzzle.seeds)
    if len(targets)<2:
        return puzzle.id,program,0
    rng=random.Random(seed)
    shared=Counter(x for edge in graph.values() for x in set(edge[1:]))
    extra=[v for v in shared if v>=65536 and shared[v]>=2 and v not in targets]
    extra.sort(key=lambda v:(-shared[v],-v))
    values=sorted(set(v for v in targets if v>=100) | set(extra[:12]))
    literals=Literals(puzzle,graph)
    alternatives=defaultdict(dict)
    for group, coefficients in identities(values,rng,samples):
        for i, (y, cy) in enumerate(zip(group,coefficients)):
            if y not in targets:
                continue
            sign=1 if cy>0 else -1
            others=tuple((-c*sign,x) for j,(x,c) in enumerate(zip(group,coefficients)) if i!=j)
            d=abs(cy)
            # Both forms reduce the rational coefficients. The direct form multiplies
            # by d at the end, so it requires the original, unscaled numerators.
            modes=('down','up','center') if d>1 else ('down',)
            if d>1 and y*d<=puzzle.limit and all(gcd(abs(c),d)==1 for c,_ in others):
                modes+=('direct',)
            for mode in modes:
                steps=expression(puzzle,y,d,others,mode,literals)
                if not steps:
                    continue
                projected={v:e for v,e in steps.items() if v==y or v not in literals.known}
                signature=tuple(projected.items())
                alternatives[y][signature]=projected
    initial=len(graph)
    proposals=[]
    for pivot, options in alternatives.items():
        for new in sorted(options.values(),key=len)[:150]:
            try:
                draft=active_graph(puzzle,graph|new)
            except (ValueError,KeyError):
                continue
            if len(draft)<initial:
                proposals.append((initial-len(draft),pivot,new))
    best=program
    history=[]
    for _, pivot, new in sorted(proposals,key=lambda item:-item[0]):
        if pivot not in graph:
            continue
        try:
            draft=active_graph(puzzle,graph|new)
        except (ValueError,KeyError):
            continue
        if len(draft)<len(graph):
            graph=draft
            history.append(graph)
    for draft in reversed(history):
        candidate=compile_graph(puzzle,draft,recompute=True,schedule_width=8)
        if candidate is not None and len(candidate)<len(best):
            best=candidate
        if len(best)<=len(draft):
            break
    return puzzle.id,best,len(proposals)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("puzzles", type=Path)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--samples",type=int,default=300)
    parser.add_argument("--rows",type=int,default=0)
    parser.add_argument("--jobs",type=int,default=3)
    parser.add_argument("--seed",type=int,default=132)
    args=parser.parse_args()
    puzzles=read_puzzles(args.puzzles)
    programs=read_submission(args.input)
    rows=puzzles.copy()
    random.Random(args.seed).shuffle(rows)
    rows=rows[:args.rows] if args.rows else rows
    t0=time.monotonic()
    gain=matches=0
    with ProcessPoolExecutor(args.jobs) as pool:
        futures=[pool.submit(improve,p,programs[p.id],args.samples,args.seed+i)
                 for i,p in enumerate(rows)]
        for count,future in enumerate(as_completed(futures),1):
            pid,candidate,n=future.result()
            gain+=len(programs[pid])-len(candidate)
            matches+=n
            programs[pid]=candidate
            if count%50==0 or count==len(rows):
                result=write_submission(args.output,puzzles,programs)
                print(f"{count}/{len(rows)} score {result} gain {gain} "
                      f"shorter candidates {matches} {time.monotonic()-t0:.1f}s",flush=True)


if __name__=="__main__":
    main()
