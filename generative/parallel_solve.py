"""Build and schedule local solutions using scaled differences between four targets."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from itertools import combinations_with_replacement
import json
from pathlib import Path
import sqlite3
import subprocess
import time

from run_source import ROOT,compile_engine,compiler_path
from parallel_probe import puzzle_line
from elf import check,read_puzzles,read_submission,sha256,write_submission
from graph import active_graph,compile_graph,first_recipes


def rules_for(exe,puzzles,keep):
    data="\n".join(map(puzzle_line,puzzles))+"\n"
    run=subprocess.run([str(exe),str(keep)],input=data,capture_output=True,text=True,check=True)
    groups={}
    for line in run.stdout.splitlines():
        pid,*fields=line.split()
        groups.setdefault(pid,[]).append(tuple(map(int,fields)))
    return groups


def arithmetic(a,b,limit):
    if a+b<=limit:yield a+b,("+",a,b)
    if a!=b:yield abs(a-b),("-",max(a,b),min(a,b))
    if a<=limit//b:yield a*b,("*",a,b)
    u,v=max(a,b),min(a,b)
    if u%v==0:yield u//v,("/",u,v)


def inverses(t,a,limit):
    if t>a:yield t-a,"+",False
    if t+a<=limit:yield t+a,"-",False
    if a>t:yield a-t,"-",True
    if t%a==0:yield t//a,"*",False
    if t<=limit//a:yield t*a,"/",False
    if a%t==0:yield a//t,"/",True


class Helpers:
    def __init__(self,puzzle,base):
        self.puzzle=puzzle
        self.parents=list(dict.fromkeys((*puzzle.seeds,*base)))
        self.known=set(self.parents)
        self.one={}
        self.cache={}
        # Early anchors have the broadest legal range in the parent schedule.
        for a,b in combinations_with_replacement(self.parents,2):
            for x,recipe in arithmetic(a,b,puzzle.limit):
                if x not in self.known:self.one.setdefault(x,recipe)

    def choices(self,x):
        if x in self.known:return [{}]
        if x in self.cache:return self.cache[x]
        out=[]
        if x in self.one:out.append({x:self.one[x]})
        for a in self.parents:
            for y,op,flip in inverses(x,a,self.puzzle.limit):
                if y==x or y not in self.one:continue
                rec=(op,a,y) if flip else (op,y,a)
                out.append({y:self.one[y],x:rec})
                if len(out)>=4:break
            if len(out)>=4:break
        self.cache[x]=out
        return out


def macro(rule):
    target,a,b,c,k,error,divide=rule
    diff=b-c
    if divide and diff%k:raise ValueError("inexact scaled difference")
    scaled=diff//k if divide else diff*k
    expected=target-error
    positive=expected>a
    if expected!=a+(scaled if positive else -scaled):raise ValueError("bad native identity")
    steps=[(diff,("-",b,c))]
    if k!=1:steps.append((scaled,("/" if divide else "*",diff,k)))
    if expected!=a:steps.append((expected,("+" if positive else "-",a,scaled)))
    if error:steps.append((target,("+" if error>0 else "-",expected,abs(error))))
    return target,steps


def compile_best(p,baseline,proposed):
    # Preserve original physical order wherever the altered dependency graph permits.
    original_order=tuple(v for v in baseline if v in proposed)+p.targets
    best=None
    for graph in (active_graph(p,proposed,original_order),proposed):
        tape=compile_graph(p,graph,attempts=6,recompute=True,schedule_width=10)
        if tape is not None and (best is None or len(tape)<len(best)):best=tape
        if best is not None and len(best)==len(proposed):break
    return best


def optimize(p,incumbent,rules,rounds):
    original=first_recipes(p,incumbent)
    baseline=active_graph(p,original)
    graph=baseline
    best=incumbent
    used=0
    rules=[r for r in rules if abs(r[5])<=min(2**29,max(8192,r[0]//200))]
    if not rules:return p.id,best,0
    helpers=Helpers(p,{v:recipe for v,recipe in original.items() if v in baseline})
    patches=[]
    for rule in rules:
        target,steps=macro(rule)
        k,error=rule[4],abs(rule[5])
        multipliers=[{}] if k==1 else helpers.choices(k)
        errors=[{}] if error==0 else helpers.choices(error)
        for multiple in multipliers[:2]:
            for offset in errors:
                patch=multiple|offset
                for v,recipe in steps:
                    if v not in helpers.known or v==target:patch[v]=recipe
                if target in patch and target!=patch[target][1] and target!=patch[target][2]:
                    patches.append(patch)
    for _ in range(rounds):
        options=[]
        for patch in patches:
            if all(graph.get(v)==r for v,r in patch.items()):continue
            try:new=active_graph(p,graph|patch)
            except (ValueError,KeyError):continue
            if len(new)<len(best):options.append((len(new),patch,new))
        if not options:break
        prior=len(best)
        for _,patch,new in sorted(options,key=lambda s:s[0])[:8]:
            if len(new)>=len(best):continue
            tape=compile_best(p,original,new)
            if tape is not None and len(tape)<len(best):best=tape;graph=new
        if len(best)==prior:break
        used+=1
    check(p,best);return p.id,best,used


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for key in ("puzzles","base","output"):ap.add_argument(key,type=Path)
    for key,default in (("jobs",2),("rows",0),("keep",8),("rounds",4),("checkpoint",20)):
        ap.add_argument("--"+key,type=int,default=default)
    args=ap.parse_args()
    puzzles=read_puzzles(args.puzzles);all_programs=read_submission(args.base)
    selected=[p for p in puzzles if max(p.seeds)<=64 and len(p.targets)>=6]
    exe,_,_=compile_engine("parallels",compiler_path(None))
    rules=rules_for(exe,selected,args.keep)
    # Prioritize strongest absolute matches and likely savings on large goals.
    def strength(p):
        high=[r for r in rules.get(p.id,()) if r[0]>=10**7]
        return sum((r[0].bit_length()-12)/(3+abs(r[5]).bit_length()) for r in high)
    selected.sort(key=strength,reverse=True)
    if args.rows:selected=selected[:args.rows]
    db=sqlite3.connect(args.output.with_suffix(".sqlite"))
    db.execute("CREATE TABLE IF NOT EXISTS outcomes (run TEXT,id TEXT,program TEXT,PRIMARY KEY(run,id))")
    key=":".join((sha256(args.base),sha256(exe),sha256(Path(__file__)),str(args.rounds),str(args.keep)))
    cached={k:tuple(map(tuple,json.loads(v))) for k,v in db.execute(
        "SELECT id,program FROM outcomes WHERE run=?",(key,))}
    completed={p.id:cached[p.id] for p in selected if p.id in cached}
    started=time.monotonic()
    def save():
        write_submission(args.output,[p for p in puzzles if p.id in completed],completed)
        differences=[len(all_programs[k])-len(v) for k,v in completed.items()]
        print(f"{len(completed)}/{len(selected)} rows, {sum(x>0 for x in differences)} improved, "
              f"saved {sum(differences)}, {time.monotonic()-started:.1f}s",flush=True)
    with ProcessPoolExecutor(args.jobs) as pool:
        tasks=[pool.submit(optimize,p,all_programs[p.id],rules.get(p.id,[]),args.rounds)
               for p in selected if p.id not in completed]
        for job in as_completed(tasks):
            pid,program,_=job.result();completed[pid]=program
            db.execute("INSERT OR REPLACE INTO outcomes VALUES(?,?,?)",(key,pid,json.dumps(program,separators=(",",":"))))
            db.commit()
            if len(completed)%args.checkpoint==0:save()
    save();db.close()


if __name__=="__main__":
    main()
