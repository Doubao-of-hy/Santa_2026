"""Rechoose all inferred template routes using actual overlap of their ingredient programs."""
from collections import defaultdict
import random

from gpu_conditioned import normalized
from graph import active_graph


def inverses(y, x):
    yield y-x, '+', True
    yield y+x, '-', True
    yield x-y, '-', False
    if y%x==0: yield y//x, '*', True
    yield y*x, '/', True
    if x%y==0: yield x//y, '/', False


def exchange(p, options, ingredients, seed):
    # Represent every distinct computed number once. Overlap between two
    # ingredient programs then amounts to shared bits in their union.
    ids={}
    def bit(v):
        if v not in ids:ids[v]=1<<len(ids)
        return ids[v]
    raw={v:0 for v in p.seeds}
    for v,(_,a,b) in active_graph(p,ingredients,ingredients).items():
        raw[v]=bit(v)|raw[a]|raw[b]
    wanted={x for routes in options.values() for r in routes for x in r.leaves}
    for routes in options.values():
        for r in routes:
            for v in r.graph:bit(v)
    vals=sorted(raw)
    # Track the cheapest realizable one-step expression of every result in
    # the neighbourhood, without allocating a new bit for each trial value.
    step={}
    for i,a in enumerate(vals):
        for b in vals[i:]:
            sources=raw[a]|raw[b];cost=sources.bit_count()
            recipes=((a+b,'+',a,b),(b-a,'-',b,a),(a*b,'*',a,b),
                     (b//a if b%a==0 else 0,'/',b,a))
            for v,op,x,y in recipes:
                if v not in raw and 0<v<=p.limit and (v not in step or cost<step[v][0]):
                    step[v]=(cost,sources,normalized(op,x,y))
    costs=dict(raw); extra=defaultdict(set);num_targets=set(p.targets)
    for v in sorted(wanted-raw.keys()):
        if v in step:
            _,used,r=step[v];costs[v]=bit(v)|used;extra[v].add(r)
        best=None
        for x in vals:
            for h,op,left in inverses(v,x):
                if h not in step or h==v:continue
                _,sources,recipe=step[h]
                if (v in recipe[1:]) or (h in num_targets and h not in ingredients):continue
                predecessor=sources|raw[x]
                cost=predecessor.bit_count()+2
                if best is None or cost<best[0]:best=(cost,predecessor,h,x,op,left)
        if best is not None and (v not in costs or best[0]<costs[v].bit_count()):
            _,sources,h,x,op,left=best
            costs[v]=sources|bit(v)|bit(h)
            extra[h].add(step[h][2]);extra[v].add(normalized(op,h,x) if left else normalized(op,x,h))
        if v not in costs:
            # No two-step witness. Its one-off construction cost is estimated
            # with private bits, shared by every route requesting this value.
            costly=bit(v)
            for j in range(min(11,1+v.bit_length()//4)):costly|=bit((v,j))
            costs[v]=costly
    choices={}
    for t,routes in options.items():
        pairs=[]
        for r in routes:
            use=0
            for v in r.graph:use|=bit(v)
            for v in r.leaves:use|=costs[v]
            pairs.append((use,r))
        if pairs:choices[t]=pairs
    targets=list(choices);rng=random.Random(seed)
    best_counts=10**12; best={}
    for trial in range(4):
        current={}
        for sweep in range(9):
            changed=False;rng.shuffle(targets)
            for t in targets:
                paid=0
                for x,(footprint,_) in current.items():
                    if x!=t:paid|=footprint
                pick=min(choices[t],key=lambda pair:(pair[0]&~paid).bit_count()+rng.random()*.48)
                if t not in current or current[t][0]!=pick[0]:changed=True
                current[t]=pick
            if not changed:break
        used=0
        for footprint,_ in current.values():used|=footprint
        if used.bit_count()<best_counts:best_counts=used.bit_count();best=current
    graph={};leaves=set()
    for t in sorted(best):
        r=best[t][1];leaves.update(r.leaves)
        for v,e in r.graph.items():graph.setdefault(v,e)
    return graph,leaves-graph.keys(),extra
