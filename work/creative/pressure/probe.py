"""Sample baseline pressure strata and preserve the rejected exact value DAGs."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
import os
from pathlib import Path
import random
import re
import subprocess
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];sys.path.insert(0,str(ROOT))
from elf import arithmetic,check,read_puzzles,read_submission,sha256,write_submission
from graph import compile_graph,first_recipes

def peak(p,graph):
    remaining=Counter(value for recipe in graph.values() for value in set(recipe[1:]))
    live={s for s in p.seeds if remaining[s]};maximum=len(live)
    for v,r in graph.items():
        for a in set(r[1:]):
            remaining[a]-=1
            if not remaining[a]:live.discard(a)
        maximum=max(maximum,len(live)+1)
        if remaining[v]:live.add(v)
    return maximum

def recover(p,logical,old):
    ways=[('greedy',dict(attempts=16)),('target ordering',dict(schedule_width=24)),
          ('operation beam',dict(operation_width=96)),('paid recomputation',dict(recompute=True,schedule_width=12))]
    for method,args in ways:
        prog=compile_graph(p,logical,**args)
        if prog is not None and check(p,prog)<old:return prog,method
    return None,None

def trial(p,old,duration,relax,seed):
    path=HERE/f'rejected-{p.id}.txt';env=os.environ.copy();env.update(ELF_PRESSURE_FILE=str(path),ELF_PRESSURE_EXTRA=str(relax))
    head=['P',p.id,len(p.seeds),*p.seeds,len(p.targets),*p.targets,p.limit,p.registers,len(old)]
    payload='\n'.join([' '.join(map(str,head)),*(' '.join(map(str,s)) for s in old)])+'\n'
    cmd=[str(HERE/'probe.exe'),'--time',str(duration),'--seed',str(seed+int(p.id.split('_')[-1])),'--kicks','25','--kslack','3','--helpers','1']
    r=subprocess.run(cmd,input=payload,encoding='ascii',capture_output=True,check=True,env=env)
    best=old;direct=0;details=[]
    if r.stdout.strip():
        h,*ops=r.stdout.splitlines();who,i,prior,n=h.split()
        draft=tuple((op,int(a),int(b),int(c)) for op,a,b,c in (s.split() for s in ops))
        if who!='R' or i!=p.id or int(prior)!=len(old) or int(n)!=check(p,draft):raise ValueError(h)
        best=draft;direct=len(old)-len(best)
    if path.exists():
        content=iter(path.read_text(encoding='ascii').splitlines())
        for h in content:
            mark,i,n,orig,reorder=h.split();n,orig,reorder=map(int,(n,orig,reorder));graph={};known=set(p.seeds)
            if mark!='R' or i!=p.id or n>=len(old) or min(orig,reorder)<=48:raise ValueError(h)
            for _ in range(n):
                vs,op,a,b=next(content).split();v,a,b=map(int,(vs,a,b))
                if a not in known or b not in known or v in known or arithmetic(op,a,b)!=v or not 0<v<=p.limit:raise ValueError((p.id,v))
                graph[v]=(op,a,b);known.add(v)
            if peak(p,graph)!=orig or not set(p.targets)<=known:raise ValueError(h)
            program,method=recover(p,graph,len(old));details.append([n,orig,reorder,method,len(program) if program else None])
            if program is not None and len(program)<len(best):best=program
    found=re.search(r'rejP (\d+) rejPs (\d+)',r.stderr)
    return p.id,best,{'initial':len(old),'initial_peak':peak(p,first_recipes(p,old)),'direct_saved':direct,
                      'minimum_physical':len(best),'rejected_candidates':details,'native_rejection_events':list(map(int,found.groups())) if found else None}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--top',type=int,default=115);ap.add_argument('--controls',type=int,default=35)
    ap.add_argument('--time',type=float,default=1.15);ap.add_argument('--relax',type=int,default=5);ap.add_argument('--jobs',type=int,default=4)
    ap.add_argument('--offset-high',type=int,default=0);ap.add_argument('--offset-controls',type=int,default=0);ap.add_argument('--label',default='')
    a=ap.parse_args();suffix='-'+a.label if a.label else ''
    base=next(HERE.glob('public-????????????.csv'));ps=read_puzzles(ROOT/'data/puzzles.csv');known=read_submission(base)
    peaks={p.id:peak(p,first_recipes(p,known[p.id])) for p in ps};rng=random.Random(49182)
    high=[p for p in ps if peaks[p.id]>=47];controls=[p for p in ps if 20<=peaks[p.id]<=44]
    rng.shuffle(high);rng.shuffle(controls);selected=high[a.offset_high:a.top]+controls[a.offset_controls:a.controls];rng.shuffle(selected)
    allstats={};wins={}
    def save():
        (HERE/f'search-report{suffix}.json').write_text(json.dumps({'baseline':base.name,'baseline_sha256':sha256(base),'parameters':vars(a),'rows':allstats}),encoding='ascii')
        if wins:write_submission(HERE/f'pressure-recovery{suffix}.csv',[p for p in ps if p.id in wins],wins)
        print(len(allstats),'strict rejected',sum(len(r['rejected_candidates']) for r in allstats.values()),'net',sum(x['initial']-x['minimum_physical'] for x in allstats.values()),flush=True)
    with ThreadPoolExecutor(a.jobs) as ex:
        jobs=[ex.submit(trial,p,known[p.id],a.time,a.relax,49182) for p in selected]
        for f in as_completed(jobs):
            i,prog,stats=f.result();allstats[i]=stats
            if len(prog)<len(known[i]):wins[i]=prog
            if len(allstats)%12==0:save()
    save()

if __name__=='__main__':main()
