"""Verify rejected graphs and try rescheduling or rematerialization under 48 registers."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import subprocess

from probe import HERE,ROOT,peak
from elf import arithmetic,check,read_puzzles,read_submission,write_submission
from graph import _allocate,_rematerialize,first_recipes

def rejected(path):
    it=iter(path.read_text(encoding='ascii').splitlines())
    for header in it:
        marker,i,n,initial,greedy=header.split();n=int(n);nodes={}
        for _ in range(n):
            v,operator,a,b=next(it).split();v,a,b=map(int,(v,a,b))
            if arithmetic(operator,a,b)!=v:raise ValueError(v)
            nodes[v]=(operator,a,b)
        if marker!='R' or n!=len(nodes):raise ValueError(header)
        yield i,int(initial),int(greedy),nodes

def schedule(task):
    source,p,old,initial,greedy,graph,seconds,seed=task
    n=len(graph);values=list(graph);indexed={v:i for i,v in enumerate(values)}
    indexed.update({v:n+i for i,v in enumerate(p.seeds)})
    parent_positions={v:i for i,v in enumerate(first_recipes(p,old))}
    hints={};new=[]
    for i,v in enumerate(values):
        if v in parent_positions:hints[v]=parent_positions[v]
        else:new.append(v)
    for v in reversed(new):
        use=min((hints.get(y,n) for y,r in graph.items() if v in r[1:]),default=n)
        hints[v]=max(0,use-1)
    lines=[' '.join(map(str,(n,len(p.seeds),p.registers,seconds,seed)))]
    for v,(_,a,b) in graph.items():lines.append(' '.join(map(str,(indexed[a],indexed[b],hints[v]))))
    r=subprocess.run([str(HERE/'order-search.exe')],input='\n'.join(lines)+'\n',encoding='ascii',capture_output=True,check=True)
    h,order=r.stdout.splitlines();final,attempts=map(int,h.split());seq=[int(s) for s in order.split()]
    if len(seq)!=len(set(seq)) or len(seq)!=n or not set(p.targets)<=indexed.keys():raise ValueError(p.id)
    ordered={values[i]:graph[values[i]] for i in seq};live=set(p.seeds)
    for v,(opp,a,b) in ordered.items():
        if v in live or a not in live or b not in live or not 0<v<=p.limit:raise ValueError((p.id,v))
        live.add(v)
    if peak(p,ordered)!=final or peak(p,graph)!=initial:raise ValueError('pressure')
    exact=_allocate(p,ordered,False,0,fixed_order=True)
    if final<=48 and exact is None:raise ValueError('failed exact allocation')
    outputs=[(exact,'order')] if exact is not None else []
    if not outputs:
        for mode in ('dynamic','static','literal'):
            candidate=_rematerialize(p,ordered,mode)
            if candidate is not None:outputs.append((candidate,'recompute-'+mode))
    for physical,_ in outputs:check(p,physical)
    best,method=min(outputs,key=lambda q:len(q[0]),default=(None,None))
    key=sha256(json.dumps(sorted(graph.items())).encode()).hexdigest()
    return p.id,best,dict(logical=n,original_peak=initial,greedy_peak=greedy,reordered_peak=final,moves=attempts,physical=len(best) if best else None,method=method,source=source,graph_sha256=key,ordered_node_indices=seq)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--seconds',default=4,type=float);ap.add_argument('--jobs',default=3,type=int);a=ap.parse_args()
    puzzles=read_puzzles(ROOT/'data/puzzles.csv');by={p.id:p for p in puzzles};base=next(HERE.glob('public-????????????.csv'));old=read_submission(base)
    jobs=[];seen=set()
    for path in sorted(HERE.glob('rejected-*.txt')):
        for k,(i,initial,greedy,g) in enumerate(rejected(path)):
            key=(i,frozenset(g.items()))
            if key in seen:continue
            seen.add(key);jobs.append((path.name,by[i],old[i],initial,greedy,g,a.seconds,493+17*k))
    wins={};report={}
    with ThreadPoolExecutor(a.jobs) as ex:
        for i,new,stats in ex.map(schedule,jobs):
            report.setdefault(i,[]).append(stats)
            if new is not None and len(new)<len(wins.get(i,old[i])):wins[i]=new
            print(i,stats['logical'],stats['original_peak'],stats['greedy_peak'],stats['reordered_peak'],stats['physical'],stats['method'],flush=True)
    (HERE/'order-report.json').write_text(json.dumps(report),encoding='ascii')
    if wins:write_submission(HERE/'order-recovery.csv',[p for p in puzzles if p.id in wins],wins)

if __name__=='__main__':main()
