"""Extract a short program from several graphs using independent Boolean components."""
import argparse
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor,as_completed
import hashlib
import heapq
import json
from pathlib import Path
import random
import sqlite3
import sys
import time

from run_source import ROOT
from parallel_solve import arithmetic,compile_best
from crossover_lns import load_solver
from elf import check,read_puzzles,read_submission,sha256,write_submission
from graph import active_graph,first_recipes


def canonical(recipe):
    op,a,b=recipe
    if op in "+*" and a>b:a,b=b,a
    return op,a,b


def bank(p,programs):
    graphs=[active_graph(p,first_recipes(p,program)) for program in programs]
    primary=graphs[0]
    population=defaultdict(int)
    for graph in graphs:
        for v in graph:population[v]+=1
    values=list(dict.fromkeys((*p.seeds,*primary,*sorted(population,key=lambda x:-population[x]))))[:650]
    present=set(values)
    ways={v:set() for v in values if v not in p.seeds}
    for graph in graphs:
        for v,r in graph.items():
            if v in ways and r[1] in present and r[2] in present:ways[v].add(canonical(r))
    for i,a in enumerate(values):
        for b in values[:i+1]:
            for v,r in arithmetic(a,b,p.limit):
                if v in ways and v not in (a,b) and len(ways[v])<45:ways[v].add(canonical(r))
    return primary,ways


def ordered(p,primary,ways,seed):
    rng=random.Random(seed)
    roots=set(p.seeds)
    order_index={v:i for i,v in enumerate(primary)}
    waiting=defaultdict(list);remain=[];outputs=[];queue=[]
    priority={}
    for v,rs in ways.items():
        # Primary edges constrain ordering only. Every existing primary
        # solution stays feasible for every alternative topological order.
        if v in primary:
            allowed=(canonical(primary[v]),)
            priority[v]=(order_index[v] if seed==0 else rng.random()*len(primary),v)
        else:
            allowed=rs
            priority[v]=(-1.0-rng.random() if seed%2==0 else rng.random()*len(primary)*.25,v)
        for r in allowed:
            ix=len(remain);parents=set(r[1:])-roots
            outputs.append(v);remain.append(len(parents))
            if not parents:heapq.heappush(queue,priority[v])
            for x in parents:waiting[x].append(ix)
    positions={v:-1 for v in roots}
    sequence=[]
    while queue:
        _,v=heapq.heappop(queue)
        if v in positions:continue
        positions[v]=len(sequence);sequence.append(v)
        for ix in waiting[v]:
            remain[ix]-=1
            if not remain[ix]:heapq.heappush(queue,priority[outputs[ix]])
    if set(primary)-positions.keys():raise RuntimeError("primary graph unavailable")
    return {v:[r for r in sorted(ways[v]) if all(positions.get(z,10**8)<positions[v] for z in r[1:])]
            for v in sequence}


def components(p,allowed,primary):
    fixed=set(p.seeds)|set(p.targets)
    while True:
        before=len(fixed)
        for v in tuple(fixed-set(p.seeds)):
            choices=[set(r[1:])-fixed for r in allowed[v]]
            if all(choices):fixed.update(set.intersection(*choices))
        if len(fixed)==before:break
    if fixed-set(p.seeds)-primary.keys():raise RuntimeError("forced value absent from feasible incumbent")
    constraints={};todo=list(fixed-set(p.seeds));seen=set()
    while todo:
        v=todo.pop()
        if v in seen:continue
        seen.add(v)
        options={tuple(sorted(set(r[1:])-fixed)) for r in allowed[v]}
        if () in options:continue
        singles={q[0] for q in options if len(q)==1}
        options=tuple(sorted(q for q in options if len(q)==1 or not set(q)&singles))
        if not options:raise RuntimeError("unreachable arithmetic value")
        constraints[v]=options
        for choice in options:todo.extend(choice)
    parent={}
    def root(v):
        parent.setdefault(v,v)
        while v!=parent[v]:
            parent[v]=parent[parent[v]];v=parent[v]
        return v
    for v,options in constraints.items():
        connected={x for q in options for x in q}
        if v not in fixed:connected.add(v)
        it=iter(connected);first=next(it)
        for x in it:parent[root(x)]=root(first)
        root(first)
    group=defaultdict(list)
    for v,options in constraints.items():group[root(options[0][0])].append((v,options))
    return fixed,list(group.values())


def select_component(rules,fixed,primary,seconds):
    cp=load_solver()
    model=cp.CpModel()
    values={x for _,choices in rules for option in choices for x in option}
    values.update(v for v,_ in rules if v not in fixed)
    active={x:model.new_bool_var("") for x in sorted(values)}
    pair={}
    for v,options in rules:
        clause=[] if v in fixed else [~active[v]]
        for opt in options:
            if len(opt)==1:clause.append(active[opt[0]])
            else:
                if opt not in pair:
                    both=model.new_bool_var("");pair[opt]=both
                    for x in opt:model.add_implication(both,active[x])
                clause.append(pair[opt])
        model.add_bool_or(clause)
    feasible=values&primary.keys()
    for x,b in active.items():model.add_hint(b,int(x in feasible))
    for (a,b),use in pair.items():model.add_hint(use,int(a in feasible and b in feasible))
    total=sum(active.values());model.add(total<=len(feasible));model.minimize(total)
    solver=cp.CpSolver();solver.parameters.num_search_workers=1
    solver.parameters.max_time_in_seconds=seconds
    status=solver.solve(model)
    if status in (cp.FEASIBLE,cp.OPTIMAL):
        return {x for x,b in active.items() if solver.value(b)},status==cp.OPTIMAL
    return feasible,False


def solve(p,programs,trials,seconds,candidate_bank=None):
    programs=sorted(dict.fromkeys(programs),key=len)
    best=programs[0]
    primary,ways=candidate_bank if candidate_bank is not None else bank(p,programs)
    original=first_recipes(p,best)
    rng=random.Random(871+int(p.id.rsplit("_",1)[-1]))
    stats=[0,0,0,0]
    for trial in range(trials):
        allowed=ordered(p,primary,ways,trial)
        fixed,blocks=components(p,allowed,primary)
        chosen=fixed.copy()
        for rules in blocks:
            used,opt=select_component(rules,fixed,primary,seconds)
            chosen.update(used);stats[0]+=1;stats[1]+=int(opt)
        if len(chosen-set(p.seeds))>=len(best):continue
        stats[2]+=1
        for attempt in range(3):
            graph={}
            for v,choices in allowed.items():
                if v not in chosen:continue
                viable=[r for r in choices if r[1] in chosen and r[2] in chosen]
                if not viable:raise RuntimeError("invalid selected operands")
                old=canonical(primary[v]) if v in primary else None
                if attempt==0 and old in viable:r=old
                else:r=min(viable,key=lambda e:(int(e[1] not in fixed)+int(e[2] not in fixed),rng.random()))
                graph[v]=r
            graph=active_graph(p,graph)
            if len(graph)>=len(best):continue
            tape=compile_best(p,original,graph)
            if tape is not None and len(tape)<len(best):
                best=tape;stats[3]+=1
    check(p,best);return p.id,best,stats


def delete_values(p,programs,rounds,helpers):
    sys.path.insert(0,str(Path(__file__).resolve().parent/"arsen_v7"))
    from eliminate_values import improve
    row={"id":p.id,"starting_values":json.dumps(p.seeds),"targets":json.dumps(p.targets),
         "value_limit":str(p.limit),"registers":str(p.registers)}
    tapes=[[list(step) for step in program] for program in sorted(programs,key=len)]
    pid,tape,wins=improve((row,tapes,helpers,rounds,20261120))
    tape=tuple(map(tuple,tape));check(p,tape)
    return pid,tape,[1,0,wins,int(len(tape)<min(map(len,programs)))]


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("puzzles",type=Path);ap.add_argument("output",type=Path)
    ap.add_argument("donors",nargs="+",type=Path)
    ap.add_argument("--ids",type=Path)
    ap.add_argument("--seconds",type=float,default=.55)
    ap.add_argument("--method",choices=("component","free","delete"),default="component")
    ap.add_argument("--helpers",type=int,default=240)
    for key,value in (("rows",0),("trials",3),("jobs",2),("checkpoint",8)):
        ap.add_argument("--"+key,type=int,default=value)
    a=ap.parse_args();puzzles=read_puzzles(a.puzzles)
    sources=[read_submission(path) for path in a.donors]
    selection=puzzles.copy()
    if a.ids:
        allowed=set(a.ids.read_text().split());selection=[p for p in selection if p.id in allowed]
    random.Random(8631).shuffle(selection)
    if a.rows:selection=selection[:a.rows]
    database=sqlite3.connect(a.output.with_suffix(".sqlite"))
    database.execute("CREATE TABLE IF NOT EXISTS rows (id TEXT,hash TEXT,tape TEXT,stats TEXT,PRIMARY KEY(id,hash))")
    model=sha256(Path(__file__));base={};done={};summary=[0]*4
    if a.method=="free":model+=sha256(Path(__file__).with_name("reachability_select.py"))
    def save():
        write_submission(a.output,[p for p in puzzles if p.id in done],done)
        print(f"{len(done)}/{len(selection)} saved {sum(base[i]-len(v) for i,v in done.items())}, "
              f"components {summary}",flush=True)
    with ProcessPoolExecutor(a.jobs) as pool:
        tasks={}
        for p in selection:
            tapes=tuple(dict.fromkeys(s[p.id] for s in sources if p.id in s))
            if not tapes:continue
            base[p.id]=min(map(len,tapes))
            h=hashlib.sha256(repr((model,a.method,a.helpers,a.seconds,a.trials,tapes)).encode("ascii")).hexdigest()
            saved=database.execute("SELECT tape,stats FROM rows WHERE id=? AND hash=?",(p.id,h)).fetchone()
            if saved:
                done[p.id]=tuple(map(tuple,json.loads(saved[0])));check(p,done[p.id])
                summary=[x+y for x,y in zip(summary,json.loads(saved[1]))];continue
            if a.method=="delete":task=pool.submit(delete_values,p,tapes,a.trials,a.helpers)
            elif a.method=="free":
                from reachability_select import solve_free
                task=pool.submit(solve_free,p,tapes,a.trials,a.seconds)
            else:task=pool.submit(solve,p,tapes,a.trials,a.seconds)
            tasks[task]=h
        for task in as_completed(tasks):
            pid,program,stats=task.result();done[pid]=program
            summary=[x+y for x,y in zip(summary,stats)]
            database.execute("INSERT OR REPLACE INTO rows VALUES(?,?,?,?)",(pid,tasks[task],
                json.dumps(program,separators=(",",":")),json.dumps(stats)));database.commit()
            if len(done)%a.checkpoint==0:save()
    save();database.close()


if __name__=="__main__":
    main()
