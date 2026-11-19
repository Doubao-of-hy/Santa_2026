"""Jointly reconstruct the consumers of a shared helper under a fixed outer DAG."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
import random
import subprocess
import time

from elf import read_puzzles, read_submission, write_submission
from graph import active_graph, compile_graph, first_recipes


def cuts(puzzle, graph, number, rng):
    users=defaultdict(set)
    for v,(_,a,b) in graph.items():
        users[a].add(v)
        users[b].add(v)
    targets=set(puzzle.targets)
    options=[]
    for pivot in graph:
        n=len(users[pivot])
        if n<2 or n>9:
            continue
        region={pivot}|users[pivot]
        for depth in range(3):
            outgoing=tuple(sorted(v for v in region if v in targets or users[v]-region))
            if 2<=len(outgoing)<=12:
                boundary=set(outgoing)
                fixed=set()
                stack=list(targets-boundary)
                while stack:
                    v=stack.pop()
                    if v in fixed or v in boundary or v not in graph:
                        continue
                    fixed.add(v)
                    stack.extend(graph[v][1:])
                removed=set(graph)-fixed
                free=set(puzzle.seeds)
                for v,(op,a,b) in graph.items():
                    if v in fixed and a in free and b in free:
                        free.add(v)
                if pivot in removed and len(free)>=6 and len(removed)>len(outgoing)+2:
                    score=(min(18,len(removed)-len(outgoing)) /
                           (1+len(outgoing)/8) + rng.random()*5)
                    options.append((score,outgoing,removed,free))
            expand=[v for v in region if users[v]-region and v not in targets
                    and len(users[v]-region)<=5]
            if not expand:
                break
            rng.shuffle(expand)
            for v in expand[:max(1,len(expand)//2)]:
                region|=users[v]
    result=[]
    for weight,outgoing,removed,free in sorted(options,key=lambda x:-x[0]):
        if any(len(removed & prev)>min(len(removed),len(prev))*.7
               for _,prev,_,_ in result):
            continue
        inputs=Counter(x for v in removed for x in set(graph[v][1:]) if x in free)
        def useful(x):
            return (8*min(4,inputs[x]) + min(16,len(users[x])) + rng.random()*4)
        ordered=sorted(free,key=useful,reverse=True)
        result.append((outgoing,removed,free,ordered))
        if len(result)>=number:
            break
    return result


def one(exe, config, puzzle, program, number, seed):
    rng=random.Random(seed)
    original=active_graph(puzzle,first_recipes(puzzle,program))
    regions=cuts(puzzle,original,number,rng)
    if not regions:
        return puzzle.id,program,0,0
    request=[]
    for goals,_,_,anchors in regions:
        request.append(" ".join(map(str,(puzzle.id,puzzle.limit,len(anchors),len(goals),
                                         *anchors,*goals,len(original)))))
        request.extend(f"{v} {op} {a} {b}" for v,(op,a,b) in original.items())
    run=subprocess.run([exe,*config],input="\n".join(request)+"\n",capture_output=True,
                       encoding="ascii")
    if run.returncode:
        raise RuntimeError(f"{puzzle.id} returned {run.returncode}: {run.stderr}")
    stream=iter(run.stdout.splitlines())
    proposals=[]
    for goals,removed,free,anchors in regions:
        pid,n=next(stream).split()
        if pid!=puzzle.id:
            raise ValueError(pid)
        new={}
        for _ in range(int(n)):
            v,op,a,b=next(stream).split()
            v=int(v)
            if v in removed or v not in original:
                new[v]=op,int(a),int(b)
        try:
            draft=active_graph(puzzle,original|new)
        except (KeyError,ValueError):
            continue
        if len(draft)<len(original):
            proposals.append((len(original)-len(draft),new))
    graph=original
    best=program
    for _,new in sorted(proposals,key=lambda p:-p[0]):
        try:
            draft=active_graph(puzzle,graph|new)
        except (KeyError,ValueError):
            continue
        if len(draft)>=len(graph):
            continue
        candidate=compile_graph(puzzle,draft,recompute=True,schedule_width=12)
        if candidate is not None and len(candidate)<len(best):
            best=candidate
            graph=draft
    return puzzle.id,best,len(regions),len(proposals)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for arg in ("puzzles","input","output","exe"):
        ap.add_argument(arg,type=Path)
    ap.add_argument("--rows",type=int,default=0)
    ap.add_argument("--cuts",type=int,default=4)
    ap.add_argument("--jobs",type=int,default=3)
    ap.add_argument("--leaves",type=int,default=72)
    ap.add_argument("--seed",type=int,default=614)
    ap.add_argument("--joins",type=int,default=29)
    args=ap.parse_args()
    puzzles=read_puzzles(args.puzzles)
    programs=read_submission(args.input)
    rows=puzzles.copy()
    random.Random(args.seed).shuffle(rows)
    rows=rows[:args.rows] if args.rows else rows
    config=list(map(str,(args.leaves,1,5,.18,.30,0,1,args.seed,args.joins|16)))
    t0=time.monotonic()
    gain=regions=proposed=0
    with ProcessPoolExecutor(max_workers=args.jobs) as executor:
        futures=[executor.submit(one,str(args.exe.resolve()),config,p,programs[p.id],args.cuts,
                                 args.seed+i) for i,p in enumerate(rows)]
        for i,f in enumerate(as_completed(futures),1):
            pid,candidate,attempts,options=f.result()
            gain+=len(programs[pid])-len(candidate)
            programs[pid]=candidate
            regions+=attempts
            proposed+=options
            if i%25==0 or i==len(rows):
                result=write_submission(args.output,puzzles,programs)
                print(f"{i}/{len(rows)} score {result} gain {gain}, "
                      f"{proposed}/{regions} shorter graphs in {time.monotonic()-t0:.1f}s",flush=True)


if __name__=="__main__":
    main()
