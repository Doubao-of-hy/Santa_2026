"""Rebuild small shared computations using sets of rooted intermediate values."""
from collections import defaultdict, deque
from itertools import combinations, combinations_with_replacement
import random
from solver import ROOT
from elf import check
from graph import active_graph, compile_graph, first_recipes
from solvers.graphs.corpus_prefix import arithmetic_edges


def rooted_bank(p, parents):
    ways=defaultdict(dict)
    valid=set(p.seeds)
    for tape in parents:
        g=first_recipes(p,tape)
        valid.update(g)
    for x,y in combinations_with_replacement(sorted(valid),2):
        for v,recipe in arithmetic_edges(x,y,p.limit):
            if v in valid and v not in (x,y) and v not in p.seeds:
                ways[v].setdefault(tuple(sorted({x,y})),recipe)
    return ways


def cut(p, g, roots):
    need=set(); todo=list(p.targets)
    while todo:
        v=todo.pop()
        if v not in g or v in need:continue
        need.add(v)
        if v not in roots:todo.extend(g[v][1:])
    goals=roots&need
    fixed=need-goals
    free=set(p.seeds)
    for v,e in g.items():
        if v in fixed and e[1] in free and e[2] in free:free.add(v)
    return goals,free,len(g)-len(fixed)


def supports(p,ways,free,goals,cost,width):
    # Positive-cost values in a state are a set. Any two rooted derivations may
    # be executed in sequence, skipping already computed values.
    values=sorted(ways.keys()-free)
    index={v:i for i,v in enumerate(values)}
    if not goals<=index.keys():return [],0
    edges=[]
    for v in values:
        choices=[]
        for operands in ways[v]:
            if all(a in index or a in free for a in operands):
                choices.append(tuple(index[a] for a in operands if a not in free))
        edges.append(choices)
    states=[[] for _ in values];candidate_count=0
    for _ in range(cost):
        changed=False
        for i,options in enumerate(edges):
            bit=1<<i; pool=set(states[i])
            for args in options:
                if not args:
                    pool={bit}
                    break
                if len(args)==1:
                    pool.update(s|bit for s in states[args[0]] if s.bit_count()<cost and not s&bit)
                else:
                    for a in states[args[0]]:
                        for b in states[args[1]]:
                            c=a|b
                            if c.bit_count()<cost and not c&bit:pool.add(c|bit)
            if not pool:continue
            ordered=sorted(pool,key=lambda m:(m.bit_count(),m));keep=[]
            for m in ordered:
                if any((z&m)==z for z in keep):continue
                keep.append(m)
                if len(keep)>=width:break
            if keep!=states[i]:
                states[i]=keep;changed=True
        if not changed:break
    combined=[0]
    for t in sorted(goals):
        products={a|b for a in combined for b in states[index[t]] if (a|b).bit_count()<=cost}
        combined=sorted(products,key=lambda m:(m.bit_count(),m))[:width*2]
    out=[]
    for m in combined:
        chosen=[v for v in values if (1<<index[v])&m]
        bank=set(free);path={}
        while not goals<=bank:
            before=len(bank)
            for v in chosen:
                if v in bank:continue
                for recipe in ways[v].values():
                    if recipe[1] in bank and recipe[2] in bank:
                        bank.add(v);path[v]=recipe;break
            if len(bank)==before:raise ValueError('non-rooted set returned by propagation')
        out.append(path)
    return out,len(combined)


def optimize(p,parents,windows=24,width=3):
    current=parents[0];g=active_graph(p,first_recipes(p,current))
    ways=rooted_bank(p,parents)
    ranked=[];singles=[]
    for v in g:
        goals,free,old=cut(p,g,{v})
        if 2<=old<=10 and goals:
            singles.append(v)
            ranked.append((old,0,tuple(goals),free))
    # Pair roots close to each other in the supplied program and pairs sharing an operand.
    pos={v:i for i,v in enumerate(g)}
    for a,b in combinations(singles,2):
        common=set(g[a][1:])&set(g[b][1:])
        if abs(pos[a]-pos[b])>4 and not common:continue
        goals,free,old=cut(p,g,{a,b})
        if len(goals)==2 and 3<=old<=10:ranked.append((old,1,tuple(sorted(goals)),free))
    rng=random.Random(9137+int(p.id.split('_')[-1]))
    rng.shuffle(ranked)
    a=[r for r in ranked if r[1]==0];b=[r for r in ranked if r[1]==1]
    cases=a[:windows//2]+b[:windows//2]
    if len(cases)<windows:cases+=(a[windows//2:]+b[windows//2:])[:windows-len(cases)]
    best=current;recovered=total=0;detail=[]
    for old,_,targets,free in cases:
        variants,count=supports(p,ways,free,set(targets),min(8,old-1),width)
        total+=count;recovered+=bool(variants)
        for path in variants:
            patch=g|path
            try:active=active_graph(p,patch)
            except (KeyError,ValueError):continue
            if len(active)>=len(best):continue
            tape=compile_graph(p,active,attempts=5)
            if tape is not None and check(p,tape)<len(best):
                best=tape;detail.append(dict(targets=targets,old=old,anchors=len(free),new=len(path),physical=len(tape)))
    return best,dict(before=len(current),after=len(best),cases=len(cases),rooted=recovered,variants=total,wins=detail)
