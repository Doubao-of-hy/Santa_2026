"""Replay whole-puzzle forward synthesis on small finite value domains."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import subprocess
import time

from checkpoint import atomic_text
from elf import check, read_puzzles, read_submission, sha256, write_submission
from tiny import encode
from graph import active_graph, compile_graph, first_recipes
from solvers.proofs.prefix_exact import add_value


def run(p,tape,exe,width,variant,seed,extra,lookahead=False,warm=False,separate_goals=False):
    budget=len(tape)-len(set(p.targets)-set(p.seeds))-1+extra
    entry=(p.limit,len(p.seeds),len(p.targets),budget,*p.seeds,*p.targets)
    start=time.monotonic()
    command=[str(exe),str(width),str(variant),str(seed)]
    if lookahead:command.append('--lookahead')
    if separate_goals:command.append('--separate-goals')
    text=' '.join(map(str,entry))+'\n'
    if warm:
        g=active_graph(p,first_recipes(p,tape));command.append('--warm')
        text+=str(len(g))+'\n'+''.join(f'{v} {op} {a} {b}\n' for v,(op,a,b) in g.items())
    proc=subprocess.run(command,
                         input=text,capture_output=True,text=True,check=True)
    rows=proc.stdout.splitlines()
    status,expanded=rows[0].split();winner=None
    if status=='FOUND':
        seq=tuple(map(int,rows[1].split()))
        if seq[:len(p.seeds)]!=p.seeds:raise ValueError('missing seeds')
        if len(seq)<=p.registers:
            winner=encode(p,seq[len(p.seeds):])
            if warm:
                g=active_graph(p,first_recipes(p,winner))
                if len(g)<len(winner):
                    other=compile_graph(p,g,attempts=2)
                    if other is not None and len(other)<len(winner):winner=other
        else:
            known=set();offers={};graph={}
            for s in p.seeds:add_value(s,known,offers,p.limit)
            for x in seq[len(p.seeds):]:
                graph[x]=offers[x];add_value(x,known,offers,p.limit)
            winner=compile_graph(p,graph,attempts=3,recompute=True,schedule_width=8)
        if winner is not None:check(p,winner)
        if len(seq)-len(p.seeds)>budget+len(set(p.targets)-set(p.seeds)):raise ValueError('invalid witness')
    elif status!='NO_WITNESS':raise ValueError(status)
    return winner,dict(id=p.id,variant=variant,seed=seed,width=width,budget=budget,lookahead=lookahead,warm=warm,
                       separate_goals=separate_goals,
                       expanded=int(expanded),seconds=round(time.monotonic()-start,4),
                       before=len(tape),after=len(winner) if winner is not None else None)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for k in ('base','exe','out'):ap.add_argument(k,type=Path)
    ap.add_argument('--ids',nargs='*');ap.add_argument('--variants',default='0,1,2')
    ap.add_argument('--width',type=int,default=320);ap.add_argument('--jobs',type=int,default=3)
    ap.add_argument('--seed',type=int,default=3177);ap.add_argument('--extra',type=int,default=0)
    ap.add_argument('--min',type=int,default=16);ap.add_argument('--max',type=int,default=27)
    ap.add_argument('--domain',type=int,default=10**18)
    ap.add_argument('--lookahead',action='store_true')
    ap.add_argument('--warm',action='store_true')
    ap.add_argument('--separate-goals',action='store_true')
    a=ap.parse_args();ps=read_puzzles('data/puzzles.csv');base=read_submission(a.base)
    selected=[p for p in ps if (not a.ids or p.id in a.ids) and p.limit<=a.domain
              and len(p.targets)<=16 and a.min<=len(base[p.id])<=a.max]
    best={};stats=[]
    def save():
        if best:write_submission(a.out,[p for p in ps if p.id in best],best)
        atomic_text(a.out.with_suffix('.json'),json.dumps({'parent_sha256':parent_hash,'binary_sha256':exe_hash,
                    'wins':{i:len(r) for i,r in best.items()},'trials':stats},indent=2)+'\n')
    parent_hash=sha256(a.base);exe_hash=sha256(a.exe)
    with ThreadPoolExecutor(a.jobs) as pool:
        todo=[]
        for variant in map(int,a.variants.split(',')):
            for p in selected:
                seed=a.seed+variant*171+int(p.id.split('_')[-1])
                todo.append(pool.submit(run,p,base[p.id],a.exe.resolve(),a.width,variant,seed,a.extra,
                                        a.lookahead,a.warm,a.separate_goals))
        for task in as_completed(todo):
            prog,row=task.result();pid=row['id'];stats.append(row)
            if prog is not None and len(prog)<len(best.get(pid,base[pid])):
                best[pid]=prog;print(pid,row['before'],len(prog),flush=True);save()
    save();print('trials',len(stats),'expanded',sum(r['expanded'] for r in stats),'wins',len(best),flush=True)

if __name__=='__main__':main()
