"""Replace only a shared fitted component, pricing the rest of the incumbent as available."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sqlite3
from statistics import median
from time import perf_counter

from elf import Puzzle,check,read_puzzles,read_submission,write_submission
from gpu_join import cut_many
from gpu_templates import settings,stitch
from gpu_wave import WaveEngine,solve
from graph import active_graph,first_recipes
from matrix_construct import choose,routes


def cuts(p,m,baseline):
    graph=active_graph(p,first_recipes(p,baseline))
    groups=defaultdict(list)
    for item in m['targets']:groups[item['a']*item['b']].append(item)
    cases=[]
    for center,desc in groups.items():
        if len(desc)<3 or median(row.get('weight',0) for row in desc)<7:continue
        goals={row['t'] for row in desc};kept,free=cut_many(p,graph,goals)
        removed=len(graph)-len(kept)
        if removed<3+len(goals):continue
        model=dict(m);model['targets']=desc;model['alternatives']=[];model['multi_stage']=False
        opts=routes(p,model)
        available=set(p.seeds)|free.keys()
        template,leaves=choose(opts,p,available,int(p.id[-4:])+center)
        if not template:continue
        requires=({v for e in template.values() for v in e[1:] if v not in template}|leaves)-available
        # Estimate gain from only this cut, including operands required to
        # rebuild the component from the still attainable part of the graph.
        demand=sum(.9+max(0,v.bit_length()-4)*.065 for v in requires)
        cost=len(template.keys()-available)+demand
        score=removed-cost+.1*len(goals)
        cases.append((score,removed,center,opts,template,requires,free,goals))
    cases.sort(reverse=True,key=lambda row:row[:3])
    return cases


def repair(p,m,old,engine,amount,seconds):
    best=old
    for score,removed,center,opts,template,requires,free,goals in cuts(p,m,old)[:amount]:
        ingredients={}
        if requires:
            task=Puzzle(p.id,p.seeds,tuple(sorted(requires)),p.limit,p.registers)
            pg,_=solve(task,engine,settings(4),prepared=free)
            ingredients=first_recipes(task,pg)
        current=stitch(p,best,template,ingredients,opts,best,seconds,True)
        if len(current)<len(best):best=current
    return best


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('data','models','base','output'):ap.add_argument(name,type=Path)
    ap.add_argument('--rows',type=int,default=30);ap.add_argument('--cuts',type=int,default=2)
    ap.add_argument('--seconds',type=float,default=1.25);ap.add_argument('--ids',type=Path)
    a=ap.parse_args();rows=read_puzzles(a.data);ps={p.id:p for p in rows};base=read_submission(a.base)
    models={m['id']:m for m in map(json.loads,a.models.read_text().splitlines()) if m['hubs']}
    if a.ids:
        eligible=set(a.ids.read_text().split());models={k:m for k,m in models.items() if k in eligible}
    ranked=[]
    for k,m in models.items():
        choices=cuts(ps[k],m,base[k]);
        if choices:ranked.append((choices[0][0],k))
    ranked.sort(reverse=True)
    if a.rows:ranked=ranked[:a.rows]
    db=sqlite3.connect(a.output.with_suffix('.sqlite'))
    db.execute('CREATE TABLE IF NOT EXISTS result (id TEXT, signature TEXT, program TEXT, PRIMARY KEY(id,signature))')
    engine=WaveEngine(Path(__file__).resolve().parent/'work/gpu',True);answers={};t0=perf_counter()
    code=hashlib.sha256()
    for path in [__file__,Path(__file__).with_name('gpu_templates.py'),Path(__file__).with_name('matrix_construct.py')]:
        code.update(Path(path).read_bytes())
    for _,k in ranked:
        p=ps[k];m=models[k]
        sig=hashlib.sha256(repr((p,m,base[k],a.cuts,a.seconds,code.hexdigest())).encode()).hexdigest()
        stored=db.execute('SELECT program FROM result WHERE id=? AND signature=?',(k,sig)).fetchone()
        if stored:pg=tuple(map(tuple,json.loads(stored[0])))
        else:
            pg=repair(p,m,base[k],engine,a.cuts,a.seconds);check(p,pg)
            db.execute('INSERT INTO result VALUES (?,?,?)',(k,sig,json.dumps(pg)));db.commit()
        answers[k]=pg
        if len(answers)==1 or len(answers)%4==0 or len(answers)==len(ranked):
            write_submission(a.output,[ps[x] for x in answers],answers)
        print(k,len(base[k])-len(pg),round(perf_counter()-t0,1),flush=True)


if __name__=='__main__':main()
