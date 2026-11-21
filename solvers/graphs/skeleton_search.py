"""Solve the shared constants of a program as separate multi-target puzzles."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from hashlib import sha256
import json
from pathlib import Path
import random
import sqlite3

from elf import Puzzle,check,read_puzzles,read_submission,write_submission
from generative.run_source import solve_stream
from graph import active_graph,compile_graph,first_recipes
from solvers.gpu.gpu_schedule import schedule_like
from solvers.matrix.matrix_construct import native,routes,choose
from solvers.graphs.hypergraph_search import optimize


def boundary(p,graph,cut,ingredients):
    needed=set()
    suffix={}
    seen=set(p.seeds)
    visiting=set()
    def visit(v):
        if v in seen:return
        if v in visiting:raise ValueError("cycle")
        if v<=cut or v in ingredients or v not in graph:
            needed.add(v)
        else:
            visiting.add(v)
            op,a,b=graph[v]
            visit(a);visit(b)
            visiting.remove(v)
            suffix[v]=(op,a,b)
        seen.add(v)
    for t in p.targets:visit(t)
    return tuple(sorted(needed)),suffix


def specifications(p,old,model,n):
    usage=Counter(x for _,a,b in old.values() for x in (a,b))
    relevant=set(p.targets)-set(p.seeds)
    if not relevant:return []
    cases=[]
    options=routes(p,model) if model else {}
    for choice in range(3 if options else 1):
        macro={};ingredients=set()
        if choice:
            costs={v:1+1/(1+usage[v]) for v in old}
            selected=options
            if choice==2:
                # Keep some of the incumbent branches. The resulting boundary
                # rewards constants with uses on both sides of the rewrite.
                rng=random.Random(p.id)
                selected={v:rs for v,rs in options.items() if rng.randrange(4)!=0}
            macro,ingredients=choose(selected,p,p.seeds,choice*31,costs)
        graph=old|macro
        limits=(256,4096,1<<16,1<<20,1<<24,1<<29,1<<34)
        seen=set()
        ranked=[]
        for limit in limits:
            try: needs,suffix=boundary(p,graph,limit,ingredients)
            except ValueError:continue
            if needs in seen or not 5<=len(needs)<=47 or not suffix:continue
            seen.add(needs)
            if max(needs)>max(1<<35,max(p.seeds)):continue
            private=[v for v in old if v<=limit and v not in needs and v not in suffix]
            # Prefer boundaries with a meaningful number of shared small
            # targets and some private steps to replace.
            score=min(28,len(private))+.6*min(28,len(needs))-.25*max(0,len(needs)-28)
            ranked.append((score,needs,suffix))
        ranked.sort(key=lambda item:-item[0])
        cases.extend((choice,i,needs,suffix) for i,(_,needs,suffix) in enumerate(ranked[:n]))
    return cases


def apply_header(p,suffix,header,old):
    graph=dict(header)
    for v,r in suffix.items():graph.setdefault(v,r)
    try: graph=active_graph(p,graph)
    except (KeyError,ValueError):return None
    if len(graph)>=len(old):return None
    candidate=schedule_like(p,old,graph)
    if candidate is None or len(candidate)>len(graph):
        alternate=compile_graph(p,graph,attempts=5,recompute=True,schedule_width=7)
        if alternate is not None and (candidate is None or len(alternate)<len(candidate)):
            candidate=alternate
    return candidate


def row(p,original,model,paths,variants):
    planner,rudolph,merger=paths
    best=original
    old=first_recipes(p,original)
    tested=0
    for choice,i,needs,suffix in specifications(p,old,model,variants):
        bound=min(p.limit,max((*needs,*p.seeds))*3+37)
        sub=Puzzle(p.id,p.seeds,needs,bound,p.registers)
        pool=[]
        def consider(g):
            nonlocal best
            c=apply_header(p,suffix,g,best)
            if c is not None and len(c)<len(best):
                check(p,c);best=c
        start=41*i+773*choice+int(p.id.split('_')[-1])
        warm={}
        known=set(p.seeds)
        for v,(op,a,b) in old.items():
            if a in known and b in known and v<=bound:
                warm[v]=(op,a,b);known.add(v)
        if set(needs)<=known:
            prev=compile_graph(sub,active_graph(sub,warm),attempts=2,recompute=True)
            if prev is not None:pool.append(prev)
        # The native planner uses its warm trace as a complete fallback for
        # each goal. Close the truncated trace using always-valid doubling.
        def supply(v):
            if v in known:return
            if v==1:recipe=('/',p.seeds[0],p.seeds[0])
            elif v%2:
                supply(v-1);supply(1);recipe=('+',v-1,1)
            else:
                supply(v//2);recipe=('+',v//2,v//2)
            warm[v]=recipe;known.add(v)
        for v in needs:supply(v)
        g=native(sub,p.seeds,needs,planner,77,7,start,warm)
        consider(g)
        pg=compile_graph(sub,g,attempts=3,recompute=True)
        if pg is not None:pool.append(pg)
        result=solve_stream(rudolph,("14",".18","48","64","16","36","1","0","0","0","1","1"),
                            [sub],None,"shuffled",start)[p.id]
        consider(first_recipes(sub,result));pool.append(result)
        unique=sorted(set(pool),key=len)
        if len(unique)>1:
            _,mixed,_=optimize(merger,(12,36,8,2,8,0),sub,unique,start)
            consider(first_recipes(sub,mixed))
        tested+=1
    return p.id,best,tested


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("incumbent",type=Path)
    parser.add_argument("output",type=Path)
    parser.add_argument("--models",type=Path)
    parser.add_argument("--rows",type=int,default=50)
    parser.add_argument("--variants",type=int,default=1)
    parser.add_argument("--jobs",type=int,default=3)
    parser.add_argument("--seed",type=int,default=83279)
    args=parser.parse_args()
    paths=[Path(s).resolve() for s in ("work/virtual/planner-powers.exe","work/gen/rudolph-fe2ce780df2b3821b4.exe","work/virtual/hyper-model.exe")]
    puzzles=read_puzzles("data/puzzles.csv");base=read_submission(args.incumbent)
    models={}
    if args.models:
        models={m["id"]:m for line in args.models.read_text().splitlines() if (m:=json.loads(line))}
    selected=[p for p in puzzles if (not models or p.id in models) and len(p.targets)>6]
    random.Random(args.seed).shuffle(selected)
    if args.rows:selected=selected[:args.rows]
    out={};wins=0;cases=0
    config=(sha256(Path(__file__).read_bytes()).hexdigest(),args.variants)
    db=sqlite3.connect(args.output.with_suffix(".sqlite"))
    db.execute("CREATE TABLE IF NOT EXISTS solved (digest TEXT PRIMARY KEY, program TEXT, cases INTEGER)")
    def record(p,program,count):
        nonlocal wins,cases
        check(p,program);out[p.id]=program;wins+=len(base[p.id])-len(program);cases+=count
    def checkpoint():
        write_submission(args.output,[p for p in puzzles if p.id in out],out)
        print(f"{len(out)}/{len(selected)} rows, {cases} subpuzzles, {wins} steps saved",flush=True)
    with ProcessPoolExecutor(args.jobs) as executor:
        jobs={}
        for p in selected:
            m=models.get(p.id)
            digest=sha256(repr((config,p,base[p.id],m)).encode()).hexdigest()
            hit=db.execute("SELECT program,cases FROM solved WHERE digest=?",(digest,)).fetchone()
            if hit:
                record(p,tuple(map(tuple,json.loads(hit[0]))),hit[1]);continue
            jobs[executor.submit(row,p,base[p.id],m,paths,args.variants)]=(p,digest)
        for job in as_completed(jobs):
            p,key=jobs[job];_,program,count=job.result()
            record(p,program,count)
            db.execute("INSERT OR REPLACE INTO solved VALUES (?,?,?)",(key,json.dumps(program),count));db.commit()
            if len(out)%5==0:checkpoint()
    if out:checkpoint()
    db.close()


if __name__=="__main__":
    main()
