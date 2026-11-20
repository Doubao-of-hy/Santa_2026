"""Rebuild small integer portions using the full admissible arithmetic universe up to each ceiling."""
import argparse
from collections import Counter,defaultdict
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
from time import perf_counter

from elf import check,read_puzzles,read_submission,write_submission
from gpu_join import cut_many
from gpu_schedule import schedule_like
from graph import active_graph,compile_graph,first_recipes


def regions(p,graph,wide_goals=False):
    users=defaultdict(set)
    for v,(_,a,b) in graph.items():users[a].add(v);users[b].add(v)
    plans={}
    for cap in ((64,128,256,512,1024,2048) if wide_goals else (64,128,256,512)):
        cap=min(cap,p.limit)
        available=set(p.seeds);small=[]
        for v,(_,a,b) in graph.items():
            if v<=cap and a in available and b in available:small.append(v);available.add(v)
        for keep in (0,3):
            block=set(small[keep:])
            goals={v for v in block if v in p.targets or users[v]-block}
            if len(goals)<2 or len(goals)>=len(block):continue
            kept,free=cut_many(p,graph,goals)
            upper=len(graph)-len(kept)-len(goals)
            if upper<1:continue
            inputs=set(p.seeds)|free.keys();tag=(frozenset(inputs),frozenset(goals))
            plans[tag]=(cap,tuple(sorted(inputs)),tuple(sorted(goals)),upper,kept)
    return list(plans.values())


def optimize(p,pg,exe,budget,ceiling=0,wide_goals=False):
    graph=active_graph(p,first_recipes(p,pg));cases=regions(p,graph,wide_goals);stat=Counter()
    if not cases:return pg,stat
    lines=[]
    for cap,inputs,goals,ub,_ in cases:
        cap=min(p.limit,max(cap,ceiling))
        lines.append(' '.join(map(str,(p.id,cap,len(inputs),len(goals),ub,budget,*inputs,*goals))))
    finished=subprocess.run([str(exe)],input='\n'.join(lines)+'\n',text=True,capture_output=True,check=True)
    stream=iter(finished.stdout.splitlines());choices=[]
    for cap,inputs,goals,ub,kept in cases:
        pid,depth,cutoff,count=next(stream).split();assert pid==p.id
        depth=int(depth);count=int(count);stat['subproblems']+=1
        if int(cutoff):stat['limit_reached']+=1
        elif depth>=ub-1 or count:stat['optimum_certified_in_domain']+=1
        replacement={}
        for _ in range(count):
            value,op,a,b=next(stream).split();replacement[int(value)]=(op,int(a),int(b))
        if not replacement:continue
        stat['smaller_closure']+=1
        for g in (kept|replacement,replacement|kept):
            try:sealed=active_graph(p,g)
            except (KeyError,ValueError):continue
            if len(sealed)<len(pg):choices.append(sealed)
    best=pg
    for g in sorted(choices,key=len):
        if len(g)>=len(best):break
        proposal=schedule_like(p,best,g)
        if proposal is None or len(proposal)>len(g):
            other=compile_graph(p,g,recompute=True,schedule_width=10)
            if other is not None and (proposal is None or len(other)<len(proposal)):proposal=other
        if proposal is not None and len(proposal)<len(best):check(p,proposal);best=proposal
    stat['steps_saved']=len(pg)-len(best);stat['rows_improved']=int(len(pg)>len(best))
    return best,stat


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('data','base','output'):ap.add_argument(name,type=Path)
    ap.add_argument('--jobs',type=int,default=2);ap.add_argument('--budget',type=int,default=15000)
    ap.add_argument('--rows',type=int,default=0);ap.add_argument('--ids',type=Path)
    ap.add_argument('--exe',type=Path,default=Path('work/gpu/small-domain.exe'))
    ap.add_argument('--helper-ceiling',type=int,default=0,choices=(0,512,1024,2048))
    ap.add_argument('--wide-goals',action='store_true')
    a=ap.parse_args();pg=read_submission(a.base);ps=read_puzzles(a.data);exe=a.exe.resolve()
    ids=set(pg) if not a.ids else set(a.ids.read_text().split())&set(pg)
    cases=[]
    for p in ps:
        if p.id not in ids:continue
        choices=regions(p,active_graph(p,first_recipes(p,pg[p.id])),a.wide_goals)
        if choices:cases.append((max(z[3] for z in choices),p))
    cases.sort(key=lambda z:(-z[0],z[1].id));ps=[p for _,p in cases];
    if a.rows:ps=ps[:a.rows]
    out={};t0=perf_counter();stats=Counter()
    with ThreadPoolExecutor(a.jobs) as pool:
        for p,(best,stat) in zip(ps,pool.map(lambda row:optimize(row,pg[row.id],exe,a.budget,a.helper_ceiling,a.wide_goals),ps)):
            out[p.id]=best;stats.update(stat)
            if len(out)==1 or len(out)%16==0 or len(out)==len(ps):
                write_submission(a.output,[x for x in ps if x.id in out],out)
                summary=dict(stats,rows=len(out),total_rows=len(ps),seconds=round(perf_counter()-t0,1))
                a.output.with_suffix('.json').write_text(json.dumps(summary,indent=2),encoding='ascii')
                print(summary,flush=True)


if __name__=='__main__':main()
