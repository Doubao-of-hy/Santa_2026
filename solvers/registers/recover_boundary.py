"""Compile exact boundary value witnesses using incumbent recipes and register-aware alternatives."""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import random
import sys
from checkpoint import atomic_text
from elf import check,read_puzzles,read_submission,write_submission,sha256
from graph import active_graph,compile_graph,first_recipes
from solvers.graphs.corpus_prefix import arithmetic_edges
from solvers.gpu.gpu_schedule import schedule_like
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'work/creative/pressure'))
from reorder import peak,schedule
from operand_allocation import synthesize


def variants(p,old,anchors,seq):
    current=active_graph(p,first_recipes(p,old));pos={v:i for i,v in enumerate((*p.seeds,*current))}
    seen=list(anchors);allowed=defaultdict(list)
    for v in seq[len(anchors):]:
        if v in seen:continue
        for j,a in enumerate(seen):
            for b in seen[:j+1]:
                for w,e in arithmetic_edges(a,b,p.limit):
                    if w==v:allowed[v].append(e)
        assert allowed[v]
        seen.append(v)
    rng=random.Random(9844+int(p.id[-4:]));graphs=set()
    for mode in range(9):
        patch={}
        for v,es in allowed.items():
            original=current.get(v)
            def rank(e):
                equal=original and e[0]==original[0] and (e[1:]==original[1:] or e[0] in '+*' and e[:0:-1]==original[1:])
                return (int(bool(equal)) if mode%3!=2 else 0,
                    rng.random() if mode>=3 else -sum(abs(pos.get(v,30)-pos.get(u,15)) for u in set(e[1:])) if mode else -es.index(e))
            patch[v]=max(es,key=rank)
        try:g=active_graph(p,current|patch)
        except (ValueError,KeyError):continue
        signature=frozenset(g.items())
        if signature not in graphs:graphs.add(signature);yield g


def repair(case):
    p,old,record,prior=case;best=old;logs=[];lowest=len(old)
    for anchors,seq in record:
        for g in variants(p,old,anchors,seq):
            lowest=min(lowest,len(g))
            if len(g)>=min(len(best),prior):continue
            direct=schedule_like(p,old,g)
            if direct is None or len(direct)>len(g):
                other=compile_graph(p,g,attempts=8,recompute=True,schedule_width=8,operation_width=4)
                if other is not None and (direct is None or len(other)<len(direct)):direct=other
            best_here=direct
            top=peak(p,g);order=[]
            if direct is None or len(direct)>len(g):
                for seed in [4201,871]:
                    _,t,layout=schedule((p.id,p,old,top,top,g,.8,seed))
                    if t is None or len(t)>len(g):
                        vs=list(g);alt={vs[j]:g[vs[j]] for j in layout['ordered_node_indices']}
                        opt,*_=synthesize(p,alt,.55)
                        if opt is not None and (t is None or len(opt)<len(t)):t=opt
                    if t is not None and (best_here is None or len(t)<len(best_here)):best_here=t
                    order.append(None if t is None else len(t))
                    if best_here is not None and len(best_here)==len(g):break
            logs.append([len(g),top,None if direct is None else len(direct),order])
            if best_here is not None and len(best_here)<len(best):check(p,best_here);best=best_here
    return p.id,best,dict(before=len(old),best=len(best),lowest_graph=lowest,prior=prior,tests=logs)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('parent',type=Path);ap.add_argument('incumbent',type=Path)
    ap.add_argument('output',type=Path);ap.add_argument('reports',type=Path,nargs='+')
    ap.add_argument('--puzzles',type=Path,default=Path('data/puzzles.csv'));ap.add_argument('--jobs',type=int,default=3)
    a=ap.parse_args();bank=read_submission(a.parent);now=read_submission(a.incumbent);ps=read_puzzles(a.puzzles);pm={p.id:p for p in ps};records=defaultdict(set)
    for f in a.reports:
        j=json.loads(f.read_bytes());assert j['complete'] and j['parent']==sha256(a.parent)
        for i,r in j['rows'].items():
            for w in r.get('windows',r.get('witnesses',[])):
                if w.get('status','FOUND')=='FOUND':records[i].add((tuple(w.get('anchors',pm[i].seeds)),tuple(w['sequence'])))
    rows={};out={}
    with ThreadPoolExecutor(a.jobs) as pool:
        for i,t,r in pool.map(repair,[(pm[i],bank[i],sorted(recs),len(now[i])) for i,recs in records.items()]):
            rows[i]=r
            if len(t)<r['prior']:out[i]=t
    write_submission(a.output,[p for p in ps if p.id in out],out)
    atomic_text(a.output.with_suffix('.json'),json.dumps(dict(complete=True,parent=sha256(a.parent),incumbent=sha256(a.incumbent),
         reports={f.name:sha256(f) for f in a.reports},rows=rows),indent=1))
    print('rows',len(rows),'further wins',len(out))
if __name__=='__main__':main()
