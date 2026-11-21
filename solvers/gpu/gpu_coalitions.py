"""Synthesize several cut outputs jointly as signed affine uses of one new helper."""
import argparse
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from time import perf_counter

import numpy as np

from elf import check, read_puzzles, read_submission, write_submission
from solvers.gpu.gpu_join import anchors_for, cut_many
from solvers.gpu.gpu_schedule import schedule_like
from solvers.gpu.gpu_wave import NativeTable, atom_graph
from graph import active_graph, compile_graph, first_recipes


def neighborhoods(puzzle,graph,count):
    users=defaultdict(set)
    for v,(_,a,b) in graph.items():
        users[a].add(v); users[b].add(v)
    found=set(); options=[]
    for v,targets in users.items():
        if v not in graph: continue
        candidates=[]
        if 2<=len(targets)<=6:
            candidates.append(tuple(sorted(targets)))
            if len(targets)>2: candidates.extend(combinations(sorted(targets),2))
        _,a,b=graph[v]
        if a in graph and b in graph and a!=b:
            candidates.append(tuple(sorted((a,b))))
        for roots in candidates:
            if roots in found: continue
            found.add(roots)
            kept,free=cut_many(puzzle,graph,set(roots))
            freed=len(graph)-len(kept)
            if freed<=len(roots)+1 or len(free)<3: continue
            options.append((freed-len(roots),roots,kept,free))
    options.sort(key=lambda case:(-case[0],len(case[1]),case[1]))
    return options[:count]


def possibilities(table,target,limit,filter_keys=None):
    # Index all q such that t = m*q +/- r or t = r - m*q. A one-step
    # remainder may itself be shared by two ports and is only charged once.
    offsets=table.values[:table.n1]
    result={}
    def keep(q,score,scale,remainder,sign):
        if filter_keys is not None and q not in filter_keys: return
        before=result.get(q)
        if before is None or score<before[0]:
            result[q]=(score,scale,remainder,sign)
    for j,d in enumerate(table.values[:table.n0]):
        m=int(d)
        if m!=1 and target%m==0 and target//m>1:
            keep(target//m,1,j,-1,0)
        for sign in (1,-1,2):
            if sign==1:
                sel=np.flatnonzero(offsets<target)
                nums=np.uint64(target)-offsets[sel]
            elif sign==-1:
                sel=np.flatnonzero(offsets<=limit-target)
                nums=np.uint64(target)+offsets[sel]
            else:
                sel=np.flatnonzero(offsets>target)
                nums=offsets[sel]-np.uint64(target)
            good=np.flatnonzero((nums % d == 0)&(nums>d))
            for pos,q in zip(sel[good].tolist(),(nums[good]//d).tolist()):
                if q==target: continue
                keep(q,1+(m!=1)+(pos>=table.n0),j,pos,sign)
    return result


def instantiate(puzzle,table,chosen,byvalue,helper,uses,roots,available):
    bridge={}
    if helper not in available:
        atom_graph(table,byvalue[helper],bridge)
    for target,(cost,mi,ri,sign) in zip(roots,uses):
        m=int(table.values[mi])
        product=helper*m
        if m!=1: bridge.setdefault(product,("*",m,helper))
        if ri>=0:
            r=atom_graph(table,ri,bridge)
            if sign==1: bridge[target]=("+",product,r)
            elif sign==-1: bridge[target]=("-",product,r)
            else: bridge[target]=("-",r,product)
    return bridge


def optimize(puzzle,old,native,windows,width,tries):
    graph=active_graph(puzzle,first_recipes(puzzle,old))
    best=old
    stats=Counter()
    for _,roots,kept,free in neighborhoods(puzzle,graph,windows):
        stats["cuts"]+=1
        anchors=anchors_for(puzzle,kept,free,max(roots),width)
        available=set(free)|set(puzzle.seeds)
        table=native.build(anchors,puzzle.limit,{})
        byvalue={int(v):i for i,v in enumerate(table.values)}
        # Cheap reachable helper filters avoid materializing maps of irrelevant
        # arbitrary quotients. Preserve free values that lie outside the bank.
        keys=byvalue.keys()|available
        keys.difference_update(roots)
        matches=[]
        for t in roots:
            hits=possibilities(table,t,puzzle.limit,keys)
            matches.append(hits); keys=hits.keys()
            if not keys: break
        if not keys: continue
        stats["meetings"]+=len(keys)
        def rank(h):
            idx=byvalue.get(h,0)
            cost=0 if h in available else 1+(idx>=table.n1)
            return cost+sum(options[h][0] for options in matches),h
        for h in sorted(keys,key=rank)[:tries]:
            routes=[m[h] for m in matches]
            bridge=instantiate(puzzle,table,anchors,byvalue,h,routes,roots,available)
            candidate=bridge|kept
            try: active=active_graph(puzzle,candidate)
            except (KeyError,ValueError): continue
            if len(active)>=len(best): continue
            stats["logical"]+=1
            physical=schedule_like(puzzle,old,active)
            if physical is None or len(physical)>len(active):
                other=compile_graph(puzzle,active,recompute=True,schedule_width=12)
                if other is not None and (physical is None or len(other)<len(physical)): physical=other
            if physical is not None and len(physical)<len(best):
                check(puzzle,physical); best=physical
    return best,stats


def main():
    import random
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("data",type=Path); ap.add_argument("base",type=Path); ap.add_argument("output",type=Path)
    for name,default in (("rows",20),("cuts",8),("width",42),("tries",30),("seed",843)):
        ap.add_argument("--"+name,type=int,default=default)
    args=ap.parse_args()
    puzzles=read_puzzles(args.data); old=read_submission(args.base)
    random.Random(args.seed).shuffle(puzzles)
    native=NativeTable(Path(__file__).resolve().parents[2]/"work/gpu/gpu_table.dll")
    results={}; total=Counter(); t0=perf_counter()
    subset=puzzles[:args.rows] if args.rows else puzzles
    for p in subset:
        fresh,stats=optimize(p,old[p.id],native,args.cuts,args.width,args.tries)
        total.update(stats)
        results[p.id]=fresh
        write_submission(args.output,[x for x in subset if x.id in results],results)
        print(p.id,len(old[p.id]),len(fresh),dict(stats),round(perf_counter()-t0,1),flush=True)
    print(dict(total),flush=True)


if __name__=="__main__": main()
