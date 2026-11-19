"""Rebuild early arithmetic frontiers jointly while retaining every outside use."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
import random
import subprocess
import time

from elf import read_puzzles, read_submission, write_submission
from graph import active_graph, compile_graph, first_recipes


def regions(puzzle, program, count, rng):
    recipes=first_recipes(puzzle,program)
    graph=active_graph(puzzle,recipes)
    order=[v for v in recipes if v in graph]
    users=defaultdict(set)
    for v,(_,a,b) in graph.items():
        users[a].add(v)
        users[b].add(v)
    targets=set(puzzle.targets)
    candidates=[]
    for length in (9,14,22,32,48,72,96):
        if length>len(order):
            continue
        ends={length,min(len(order),length+rng.randrange(1,max(2,len(order)-length+1)))}
        if length<=32:
            ends.add(min(len(order),length+len(order)//3))
        for end in ends:
            span=set(order[end-length:end])
            goals=tuple(v for v in order[end-length:end] if v in targets or users[v]-span)
            if not 2<=len(goals)<=38:
                continue
            fixed=set()
            boundary=set(goals)
            stack=list(targets-boundary)
            while stack:
                v=stack.pop()
                if v in fixed or v in boundary or v not in graph:
                    continue
                fixed.add(v)
                stack.extend(graph[v][1:])
            removed=set(graph)-fixed
            helpers=len(removed)-len(goals)
            if helpers<1: continue
            free=set(puzzle.seeds)
            for v,(op,a,b) in graph.items():
                if v in fixed and a in free and b in free: free.add(v)
            needed={x for v in removed for x in graph[v][1:] if x in free}
            needed.update(puzzle.seeds)
            extras=sorted(free-needed,key=lambda v:(-len(users[v]),v))
            inputs=sorted(needed)+extras[:max(0,75-len(needed))]
            # Prefer cuts with several helper instructions and small enough
            # boundary values to permit short newly synthesized definitions.
            average_bits=sum(t.bit_length() for t in goals)/len(goals)
            priority=min(10,helpers)*1.1 + min(5,len(goals)/3)-average_bits*.10+rng.random()*8
            candidates.append((priority,goals,removed,inputs))
    selected=[]
    for _,goals,removed,inputs in sorted(candidates,key=lambda x:-x[0]):
        if any(len(removed&prev)>min(len(removed),len(prev))*.70 for _,prev,_ in selected):
            continue
        selected.append((goals,removed,inputs))
        if len(selected)>=count: break
    return graph,selected


def foundations(puzzle,original,count,rng):
    ordered=first_recipes(puzzle,original)
    selected=active_graph(puzzle,ordered)
    graph={v:e for v,e in ordered.items() if v in selected}
    users=defaultdict(set)
    for v,(_,a,b) in graph.items():
        users[a].add(v);users[b].add(v)
    seeds=set(puzzle.seeds);targets=set(puzzle.targets)
    cases={}
    for threshold in (64,256,1024,8192,65536,1048576,4000000,1<<27,1<<33):
        for keep in (0,4,9):
            known=set(seeds)
            small=[]
            for v,(_,a,b) in graph.items():
                if v<=threshold and a in known and b in known:
                    known.add(v);small.append(v)
            removed=frozenset(small[keep:])
            if len(removed)<4 or removed in cases:continue
            goals=tuple(v for v in small[keep:] if v in targets or users[v]-removed)
            if not 2<=len(goals)<=55:continue
            extra=len(removed)-len(goals)
            if extra<=0:continue
            base=sorted(seeds|set(small[:keep]))
            score=min(15,extra)+3*extra/len(removed)+rng.random()*2
            cases[removed]=(score,goals,removed,base)
    found=[]
    for _,out,removed,base in sorted(cases.values(),key=lambda e:-e[0]):
        if any(len(removed^old)<3 and len(inputs)==len(base) for _,old,inputs in found):continue
        found.append((out,removed,base))
        if len(found)>=count:break
    return graph,found


def optimize(exe,puzzle,original,count,width,depth,seed,scope="windows"):
    chooser=foundations if scope=="foundation" else regions
    graph,cases=chooser(puzzle,original,count,random.Random(seed))
    if not cases:
        return puzzle.id,original,0,0
    data=[]
    for goals,removed,inputs in cases:
        data.append(f"{puzzle.id} {puzzle.limit} {len(inputs)} {len(goals)} {len(graph)} {len(removed)}")
        data.append(" ".join(map(str,inputs)))
        data.append(" ".join(map(str,goals)))
        data.extend(f"{v} {op} {a} {b}" for v,(op,a,b) in graph.items())
    wire="\n".join(data)+"\n"
    runner=subprocess.run([exe,str(width),str(depth)],input=wire,
                          capture_output=True,encoding="ascii")
    if runner.returncode:
        diagnostic=Path(exe).parent/f"closure-failure-{puzzle.id}.txt"
        diagnostic.write_text(wire,encoding="ascii")
        raise RuntimeError(f"{puzzle.id}: {runner.returncode} {runner.stderr[:400]} ({diagnostic})")
    lines=iter(runner.stdout.splitlines())
    blocks=[]
    for goals,removed,_ in cases:
        pid,n=next(lines).split()
        if pid!=puzzle.id: raise ValueError(pid)
        new={}
        for _ in range(int(n)):
            v,op,a,b=next(lines).split()
            v=int(v)
            if v in removed or v not in graph:
                new[v]=(op,int(a),int(b))
        if not new: continue
        try: candidate=active_graph(puzzle,graph|new)
        except (KeyError,ValueError): continue
        if len(candidate)<len(graph):
            blocks.append((len(graph)-len(candidate),new))
    if next(lines,None) is not None: raise ValueError("trailing data")
    best=original
    for _,new in sorted(blocks,key=lambda x:-x[0]):
        try: candidate=active_graph(puzzle,graph|new)
        except (KeyError,ValueError): continue
        if len(candidate)>=len(graph): continue
        physical=compile_graph(puzzle,candidate,recompute=True,schedule_width=12)
        if physical is not None and len(physical)<len(best):
            graph=candidate
            best=physical
    return puzzle.id,best,len(cases),len(blocks)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ("puzzles","input","output","exe"): ap.add_argument(name,type=Path)
    for name,value in (("rows",0),("cuts",4),("width",8),("depth",4),("jobs",3),("seed",925)):
        ap.add_argument("--"+name,type=int,default=value)
    ap.add_argument("--scope",choices=("windows","foundation"),default="windows")
    args=ap.parse_args()
    puzzles=read_puzzles(args.puzzles); programs=read_submission(args.input)
    rows=puzzles.copy();random.Random(args.seed).shuffle(rows)
    if args.rows: rows=rows[:args.rows]
    start=time.monotonic(); saved=regions_tested=winning=0
    with ProcessPoolExecutor(args.jobs) as pool:
        tasks=[pool.submit(optimize,str(args.exe.resolve()),p,programs[p.id],args.cuts,
                           args.width,args.depth,args.seed+i,args.scope) for i,p in enumerate(rows)]
        for i,task in enumerate(as_completed(tasks),1):
            pid,candidate,n,w=task.result()
            saved+=len(programs[pid])-len(candidate)
            programs[pid]=candidate;regions_tested+=n;winning+=w
            if i%25==0 or i==len(rows):
                result=write_submission(args.output,puzzles,programs)
                print(f"{i}/{len(rows)} total {result}, saved {saved}, "
                      f"{winning}/{regions_tested} shorter regions, {time.monotonic()-start:.1f}s",flush=True)


if __name__=="__main__":
    main()
