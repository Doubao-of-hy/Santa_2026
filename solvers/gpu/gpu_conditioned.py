"""Generate conditional recipes on the GPU, then choose a compatible global dependency graph."""
import argparse
from collections import Counter, defaultdict
import heapq
import hashlib
import json
from pathlib import Path
import random
import sqlite3
from time import perf_counter

from solvers.graphs.crossover_lns import load_solver
from elf import check, read_puzzles, read_submission, write_submission
from solvers.gpu.gpu_join import anchors_for, cut_many
from solvers.gpu.gpu_schedule import schedule_like
from solvers.gpu.gpu_wave import WaveEngine
from graph import active_graph, compile_graph, first_recipes


def normalized(op,a,b):
    if op in "+*" and a>b: a,b=b,a
    return op,a,b


def components(bank):
    number={}; low={}; stack=[]; active=set(); group={}
    def visit(v):
        number[v]=low[v]=len(number); active.add(v); stack.append(v)
        for _,a,b in bank[v]:
            for w in {a,b}:
                if w not in bank: continue
                if w not in number:
                    visit(w); low[v]=min(low[v],low[w])
                elif w in active:
                    low[v]=min(low[v],number[w])
        if number[v]==low[v]:
            while True:
                w=stack.pop(); active.remove(w); group[w]=v
                if w==v: break
    for v in bank:
        if v not in number: visit(v)
    return group


def local_search(p,old,bank,count,stats):
    # Re-price all conditional recipes after releasing a cone: a precursor that
    # survives in the incumbent really is free, including expensive later goals.
    edges=[]
    users=defaultdict(list)
    for v,choices in bank.items():
        for op,a,b in choices:
            index=len(edges)
            edges.append((v,op,a,b))
            users[a].append(index)
            if b!=a: users[b].append(index)
    ids={v:1<<i for i,v in enumerate(bank)}
    seeds=set(p.seeds);best=old
    for _ in range(2):
        warm=first_recipes(p,best)
        graph=active_graph(p,warm)
        uses=defaultdict(set)
        for v,(_,a,b) in graph.items(): uses[a].add(v);uses[b].add(v)
        cases=[]
        for v in graph:
            groups=[(v,)] if len(bank[v])>1 else []
            if 2<=len(uses[v])<=5 and any(len(bank[w])>1 for w in uses[v]):
                groups.append(tuple(sorted(uses[v])))
            for roots in groups:
                kept,free=cut_many(p,graph,set(roots))
                freed=len(graph)-len(kept)
                if freed>len(roots):
                    cases.append((freed/len(roots),roots,kept,free,freed))
        cases.sort(key=lambda x:(-x[0],x[1]))
        before=len(best)
        for _,roots,kept,free,freed in cases[:count]:
            known=seeds|free.keys()
            blocked=kept.keys()-known
            # Seeds and every surviving, non-cyclic node settle at cost zero.
            chosen={}
            final=set(known);bits={x:0 for x in known}
            moves=[]
            def relax(i):
                v,op,a,b=edges[i]
                if v in final or v in blocked or a not in final or b not in final: return
                path=bits[a]|bits[b]|ids[v]
                price=path.bit_count()
                if price>=freed or (v in bits and bits[v].bit_count()<=price):return
                bits[v]=path; chosen[v]=(op,a,b)
                heapq.heappush(moves,(price,v))
            for x in known:
                for edge in users[x]:relax(edge)
            while moves and any(v not in final for v in roots):
                price,x=heapq.heappop(moves)
                if x in final or price!=bits[x].bit_count():continue
                final.add(x)
                for edge in users[x]: relax(edge)
            if any(v not in final for v in roots):continue
            graph2=kept|chosen
            try: recovered=active_graph(p,graph2)
            except (KeyError,ValueError):continue
            if len(recovered)>=len(best):continue
            stats["local_arithmetic"]+=1
            lifted=schedule_like(p,best,recovered)
            if lifted is None or len(lifted)>len(recovered):
                other=compile_graph(p,recovered,recompute=True,schedule_width=8)
                if other is not None and (lifted is None or len(other)<len(lifted)): lifted=other
            if lifted is not None and len(lifted)<len(best):
                check(p,lifted);best=lifted
        if len(best)==before:break
    return best


def select(puzzle,old,bank,seconds,stats,lazy=False):
    warm=first_recipes(puzzle,old)
    cp=load_solver()
    group=components(bank)
    model=cp.CpModel()
    present={v:model.new_bool_var("") for v in bank}
    clock={}
    choices={}
    for v,options in bank.items():
        flags=[]
        for recipe in sorted(options):
            op,a,b=recipe
            flag=present[v] if len(options)==1 else model.new_bool_var("")
            if len(options)>1:
                flags.append(flag)
                model.add_hint(flag,int(v in warm and normalized(*warm[v])==recipe))
            choices[v,recipe]=flag
            for x in {a,b}-set(puzzle.seeds):
                model.add_implication(flag,present[x])
                if not lazy and group[x]==group[v]:
                    for z in (x,v):
                        if z not in clock: clock[z]=model.new_int_var(0,len(old),"")
                    model.add(clock[x]<clock[v]).only_enforce_if(flag)
        if flags: model.add(sum(flags)==present[v])
        model.add_hint(present[v],int(v in warm))
    for t in set(puzzle.targets)-set(puzzle.seeds): model.add(present[t]==1)
    total=sum(present.values())
    model.add(total<=len(old)-int(lazy))
    if lazy:
        # Inverse arithmetic commonly creates two-node cycles. Remove them
        # once, then discover larger traps from the actual solver selections.
        direct=defaultdict(list)
        for (v,r),flag in choices.items():
            for x in set(r[1:]):direct[v,x].append(flag)
        for (v,x),flags in direct.items():
            if v<x and (x,v) in direct:
                model.add(sum(flags)+sum(direct[x,v])<=1)
    model.minimize(total)
    best=old
    deadline=perf_counter()+seconds
    for _ in range(20 if lazy else 3):
        if perf_counter()>=deadline: break
        solver=cp.CpSolver()
        solver.parameters.num_search_workers=1
        solver.parameters.max_time_in_seconds=deadline-perf_counter()
        status=solver.solve(model)
        stats[solver.status_name(status)]+=1
        if status not in (cp.OPTIMAL,cp.FEASIBLE):break
        graph={v:recipe for (v,recipe),flag in choices.items() if solver.value(flag)}
        if len(graph)>=len(best): break
        if lazy:
            # Every nonempty set of constructed values contains a first
            # instruction whose operands both came from outside that set.
            groups=components({v:(r,) for v,r in graph.items()})
            bygroup=defaultdict(set)
            for v,head in groups.items(): bygroup[head].add(v)
            invalid=[g for g in bygroup.values() if len(g)>1]
            if invalid:
                for nodes in invalid:
                    roots=[flag for (v,recipe),flag in choices.items()
                           if v in nodes and not (nodes & set(recipe[1:]))]
                    for v in nodes:
                        model.add(sum(roots)>=present[v])
                stats["cycle_cuts"]+=len(invalid)
                continue
        stats["virtual_saved"]+=len(old)-len(graph)
        phys=schedule_like(puzzle,old,graph)
        if phys is None or len(phys)>len(graph):
            other=compile_graph(puzzle,graph,recompute=True,schedule_width=12)
            if other is not None and (phys is None or len(other)<len(phys)): phys=other
        if phys is not None and len(phys)<len(best):
            check(puzzle,phys); best=phys
        if len(best)==len(graph): break
        selected=[choices[v,r] for v,r in graph.items()]
        model.add(sum(selected)<len(selected))
    return best


def optimize(p,old,engine,args,external=()):
    warm=first_recipes(p,old)
    base=active_graph(p,warm)
    if len(base)<8:return old,Counter()
    users=defaultdict(set)
    for v,(_,a,b) in base.items():
        users[a].add(v);users[b].add(v)
    targets=set(p.targets)-set(p.seeds)
    candidates=[x for x in base if x not in targets]
    rng=random.Random(f"{p.id}-{args.seed}")
    candidates.sort(key=lambda x:(-(min(len(users[x]),4)+rng.random()*3),-x.bit_length()))
    focus=sorted(targets|set(candidates[:args.extra]))
    bank=defaultdict(set)
    for v,r in base.items(): bank[v].add(normalized(*r))
    # Imported programs supply optional, unbuilt helpers. A hub can support
    # entirely new GPU routes even when none of its donor targets are adopted.
    foreign={}
    frequency=Counter()
    for donor in external:
        other=active_graph(p,first_recipes(p,donor))
        footprint={}
        bits={v:1<<i for i,v in enumerate(other)}
        for v,r in other.items():
            op,a,b=r
            bank[v].add(normalized(op,a,b))
            frequency.update({x:1 for x in {a,b}})
            footprint[v]=0 if v in base else bits[v]|footprint.get(a,0)|footprint.get(b,0)
            if v not in base:
                cost=footprint[v].bit_count()
                if v not in foreign or cost<foreign[v][0]: foreign[v]=(cost,r)
    stats=Counter()
    for _ in range(args.rounds):
        rng.shuffle(focus)
        for i in range(0,len(focus),args.batch):
            queries=focus[i:i+args.batch]
            banned=set(queries)
            banned.update(v for q in queries for v in users[q])
            other=list(set(focus)-banned)
            rng.shuffle(other)
            allowed={v:base[v] for v in base if v not in banned}
            optional_foreign=[]
            if foreign and args.foreign:
                ranked=sorted(foreign,key=lambda v:(foreign[v][0]-.7*min(9,frequency[v])
                              +rng.uniform(-2.5,2.5),v))
                bands=Counter()
                for v in ranked:
                    band=v.bit_length()//7
                    if bands[band]>=max(2,args.foreign//5):continue
                    optional_foreign.append(v);bands[band]+=1
                    if len(optional_foreign)>=args.foreign:break
            forced=other[:args.quantity//5]+optional_foreign
            anchors=anchors_for(p,base,allowed,max(queries),args.quantity,forced)
            core=anchors_for(p,base,{v:base[v] for v in anchors if v in base},max(queries),args.core)
            # Price optional large or weakly supported intermediates in the
            # provisional search. Their actual dependency is settled globally.
            optional=[v for v in anchors if (v in base and (v in focus or len(users[v])<3)) or v in foreign]
            optional.sort(key=lambda x:(x not in foreign,x not in focus,x))
            debt={};bit=0
            for v in optional:
                price=min(3,foreign[v][0]) if v in foreign else 1
                nbits=min(price,63-bit)
                if not nbits:break
                debt[v]=((1<<nbits)-1)<<bit
                bit+=nbits
            families=engine.solutions(anchors,p,queries,args.width,args.depth,stats,
                        core,debt,65,0,0,args.sweep,1,args.landmarks)
            for t,plans in families.items():
                for plan in plans:
                    for v,r in plan.items():
                        if v not in p.seeds and v not in r[1:]: bank[v].add(normalized(*r))
                    stats["routes"]+=1
    stats["new_recipes"]=sum(len(r) for r in bank.values())-len(base)
    if stats["new_recipes"]==0:return old,stats
    local=local_search(p,old,bank,args.cuts,stats) if args.cuts else old
    best=select(p,local,bank,args.seconds,stats,args.lazy)
    return best,stats


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ("data","base","output"): ap.add_argument(name,type=Path)
    for name,value in (("rows",20),("seed",843),("quantity",82),("core",41),
            ("width",8),("depth",4),("sweep",6),("landmarks",8),("rounds",2),
            ("extra",16),("batch",10),("cuts",45),("foreign",18)):
        ap.add_argument("--"+name,type=int,default=value)
    ap.add_argument("--seconds",type=float,default=1.5)
    ap.add_argument("--lazy",action="store_true")
    ap.add_argument("--donor",action="append",type=Path,default=[])
    ap.add_argument("--ids",type=Path)
    args=ap.parse_args()
    ps=read_puzzles(args.data); old=read_submission(args.base)
    external=[read_submission(d) for d in args.donor]
    random.Random(args.seed).shuffle(ps)
    if args.ids:
        ids=set(args.ids.read_text(encoding="utf8").split())
        ps=[p for p in ps if p.id in ids]
    chosen=ps[:args.rows] if args.rows else ps
    engine=WaveEngine(Path(__file__).resolve().parents[2]/"work/gpu",native=True)
    results={}; summary=Counter(); t0=perf_counter()
    database=sqlite3.connect(args.output.with_suffix(".sqlite"))
    database.execute("CREATE TABLE IF NOT EXISTS rows (id TEXT, signature TEXT, program TEXT, PRIMARY KEY(id,signature))")
    settings=tuple((k,v) for k,v in vars(args).items() if isinstance(v,(int,float)) and k!="rows")
    code=hashlib.sha256()
    for filename in ("solvers/gpu/gpu_conditioned.py","solvers/gpu/gpu_wave.py","solvers/gpu/gpu_wave.cl","solvers/gpu/gpu_schedule.py","solvers/gpu/gpu_table.cpp"):
        code.update((Path(__file__).resolve().parents[2]/filename).read_bytes())
    run=(settings,code.hexdigest())
    for p in chosen:
        row_donors=[d[p.id] for d in external if p.id in d]
        signature=hashlib.sha256(repr((p,run,old[p.id],row_donors)).encode("ascii")).hexdigest()
        prev=database.execute("SELECT program FROM rows WHERE id=? AND signature=?",(p.id,signature)).fetchone()
        if prev:
            program=tuple(map(tuple,json.loads(prev[0]))); check(p,program);results[p.id]=program
            continue
        program,stats=optimize(p,old[p.id],engine,args,row_donors)
        database.execute("INSERT INTO rows VALUES (?,?,?)",(p.id,signature,json.dumps(program,separators=(",",":"))))
        database.commit()
        results[p.id]=program;summary.update(stats)
        write_submission(args.output,[q for q in chosen if q.id in results],results)
        print(p.id,len(old[p.id]),len(program),stats["new_recipes"],stats["virtual_saved"],
              round(perf_counter()-t0,1),flush=True)
    print(dict(summary),flush=True)
    write_submission(args.output,[q for q in chosen if q.id in results],results)
    database.close()


if __name__=="__main__": main()
