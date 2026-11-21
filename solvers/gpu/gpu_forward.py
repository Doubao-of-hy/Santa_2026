"""Keep competing multi-target construction orders and score entire provisional completions."""
import argparse
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import random
from time import perf_counter

from solvers.construction.construct import Constructor
from elf import check, read_puzzles, read_submission, write_submission
from solvers.gpu.gpu_join import anchors_for
from solvers.gpu.gpu_schedule import schedule_like
from solvers.gpu.gpu_wave import WaveEngine, scaffolding
from graph import active_graph, compile_graph, first_recipes


@dataclass
class Route:
    goal:int
    graph:dict
    mask:int=0
    hits:int=0


def expansions(p,graph,oldgraph,engine,args,stats):
    targets=tuple(t for t in p.targets if t not in p.seeds)
    pending=[t for t in targets if t not in graph]
    solved=[t for t in targets if t in graph]
    if not pending:return [],[graph]
    backbone=scaffolding(p,args.ladder)
    base=backbone|graph
    possible=anchors_for(p,base,base,max(pending),args.quantity)
    core=anchors_for(p,base,{v:base[v] for v in possible if v in base},max(pending),args.core)
    debt={}
    def mask_for(v):
        if v in graph or v in p.seeds:return 0
        if v not in debt:
            _,a,b=base[v]
            inherited=mask_for(a)|mask_for(b)
            debt[v]=(1<<len(debt))|inherited
        return debt[v]
    for v in backbone:mask_for(v)
    families=engine.solutions(possible,p,pending,args.search_width,args.depth,stats,
                              core,debt,args.pricing,0,0,args.sweep,1,args.landmarks)
    groups=[]; numbers={};roots={t:1<<i for i,t in enumerate(pending)}
    for t in pending:
        candidates=list(families.get(t,()))
        if oldgraph is not None:candidates.append(oldgraph)
        routes=[]
        for proposal in candidates:
            try:r=active_graph(p,(base|proposal)|graph,targets=(*solved,t))
            except (KeyError,ValueError):continue
            delta={v:r[v] for v in r.keys()-graph.keys()}
            routes.append(delta)
        if not routes:
            new=Constructor(p,32,True,True);new.synthesize(t)
            r=active_graph(p,(base|new.graph)|graph,targets=(*solved,t))
            routes.append({v:r[v] for v in r.keys()-graph.keys()})
        unique={}
        for delta in routes:
            key=tuple(sorted(delta))
            unique.setdefault(key,delta)
        options=[]
        for delta in sorted(unique.values(),key=len):
            bits=hits=0
            for v in delta:
                if v not in numbers:numbers[v]=1<<len(numbers)
                bits|=numbers[v];hits|=roots.get(v,0)
            options.append(Route(t,delta,bits,hits))
        groups.append(options)
    allgoals=(1<<len(pending))-1
    for_group=[j for j,options in enumerate(groups) for _ in options]
    flat=[r for options in groups for r in options]
    # The provisional graph union prices shared intermediates once. Evaluate
    # different first commitments against the same complete family of goals.
    scarcity={}
    frequency=Counter(v for options in groups for v in options[0].graph)
    for j,r in enumerate(flat):
        scarcity[j]=sum(min(5,frequency[v]-1) for v in r.graph if frequency[v]>1)
    starts=[]
    rankindex=0
    for options in groups:
        if not options:continue
        selected=[0]
        if len(options)>1:
            # Keep a distinct trajectory, including a slightly longer route
            # when its intermediates can be shared with later work.
            best=min(range(1,len(options)),key=lambda j:(
                len(options[j].graph)-.32*scarcity[rankindex+j],
                (options[0].mask & options[j].mask).bit_count()))
            selected.append(best)
        starts.extend(rankindex+j for j in selected)
        rankindex+=len(options)
    estimates=[]
    for j in starts:
        r=flat[j];order=[j];known=r.mask;covered=r.hits
        future_bias=0.12 if len(starts)%3 else 0.25
        while covered!=allgoals:
            winner=-1;quality=1e20
            for index,route in enumerate(flat):
                if covered&(1<<for_group[index]):continue
                gain=(route.mask&~known).bit_count()
                added=(route.hits&~covered).bit_count()
                cost=(gain-future_bias*min(8,scarcity[index]))/max(1,added)
                if cost<quality:
                    quality=cost;winner=index
            if winner<0:break
            r=flat[winner];known|=r.mask;covered|=r.hits
            order.append(winner)
        actual=len(graph)+known.bit_count()
        prefix=0
        for k in order[:args.commit]:prefix|=flat[k].mask
        estimates.append((actual,order,prefix))
    estimates.sort(key=lambda z:(z[0],z[2].bit_count(),z[1]))
    def assemble(order):
        g=graph.copy()
        for i in order:
            for v,recipe in flat[i].graph.items():g.setdefault(v,recipe)
        included=tuple(t for t in targets if t in g)
        try:return active_graph(p,g,targets=included)
        except (KeyError,ValueError):return None
    nextstates=[];complete=[]
    accepted=[]
    for estimate,order,prefix in estimates:
        if len(complete)<3:
            proposal=assemble(order)
            if proposal is not None:complete.append(proposal)
        if any((prefix^prev).bit_count()<max(2,min(prefix.bit_count(),prev.bit_count())//4)
               for prev in accepted):continue
        partial=assemble(order[:args.commit])
        if partial is None:continue
        accepted.append(prefix)
        nextstates.append((estimate,partial))
        if len(nextstates)>=args.beam+1 and len(complete)>=3:break
    return nextstates,complete


def solve(p,previous,engine,args):
    stats=Counter()
    oldgraph=first_recipes(p,previous) if args.warm else None
    if args.warm:
        goalset=set(p.targets)-set(p.seeds)
        order=[v for v in oldgraph if v in goalset]
        rng=random.Random(f"{p.id}-{args.seed}")
        if args.tail<len(order):
            rng.shuffle(order)
        start=active_graph(p,oldgraph,targets=order[args.tail:])
        best=previous
    else:
        start={}; best=None
    if set(p.targets)<=set(p.seeds)|start.keys():return previous if args.warm else (),stats
    states=[start];examined=set()
    for _ in range((len(p.targets)+args.commit-1)//args.commit+1):
        if not states:break
        nxt=[]
        for g in states:
            sig=frozenset(g.items())
            if sig in examined:continue
            examined.add(sig)
            proposals,final=expansions(p,g,oldgraph,engine,args,stats)
            for candidate in sorted(final,key=len):
                if best is not None and len(candidate)>=len(best):continue
                if set(p.targets)-set(p.seeds)-candidate.keys():continue
                physical=schedule_like(p,previous,candidate) if args.warm else None
                if physical is None or len(physical)>len(candidate):
                    extra=compile_graph(p,candidate,recompute=True,schedule_width=10)
                    if extra is not None and (physical is None or len(extra)<len(physical)):physical=extra
                if physical is not None and (best is None or len(physical)<len(best)):
                    check(p,physical);best=physical
            nxt.extend(proposals)
        nxt.sort(key=lambda z:(z[0],len(z[1])))
        states=[]
        for _,g in nxt:
            if set(p.targets)-set(p.seeds)-g.keys() and all(g!=old for old in states):
                states.append(g)
            if len(states)==args.beam:break
    if best is None:raise RuntimeError(f"no physical solution for {p.id}")
    return best,stats


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ("data","input","output"):ap.add_argument(name,type=Path)
    for name,value in (("rows",14),("seed",710),("quantity",92),("core",41),("beam",2),
             ("search-width",8),("depth",4),("pricing",65),("sweep",0),("ladder",0),
             ("landmarks",8),("commit",4),("tail",10)):
        ap.add_argument("--"+name,type=int,default=value)
    ap.add_argument("--warm",action="store_true")
    a=ap.parse_args(); ps=read_puzzles(a.data); base=read_submission(a.input)
    random.Random(a.seed).shuffle(ps); ps=ps[:a.rows] if a.rows else ps
    engine=WaveEngine(Path(__file__).resolve().parents[2]/"work/gpu",True)
    raw={};t0=perf_counter()
    for p in ps:
        answer,stats=solve(p,base[p.id],engine,a); raw[p.id]=answer
        write_submission(a.output,[q for q in ps if q.id in raw],raw)
        print(p.id,len(base[p.id]),len(answer),stats["states"],round(perf_counter()-t0,1),flush=True)


if __name__=="__main__":main()
