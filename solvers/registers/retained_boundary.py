"""Require most historical helper values while searching for cheaper large program sections."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations
from pathlib import Path
import hashlib
import json
import random
import subprocess
from time import perf_counter
from checkpoint import atomic_text
from solvers.graphs.corpus_prefix import windows
from elf import check,read_puzzles,read_submission,sha256,write_submission
from solvers.proofs.exact_boundary import generate
from solvers.gpu.gpu_schedule import schedule_like
from graph import active_graph,first_recipes,compile_graph


def subsets(p,head,required,remove,quantity):
    helpers=sorted(head.keys()-set(required));choices=list(combinations(helpers,remove))
    old=set(helpers)
    dep={v:{v} for v in helpers}
    for v,(_,a,b) in head.items():dep[v]=({v} if v in old else set())|dep.get(a,set())|dep.get(b,set())
    consumers={h:{v for v,e in head.items() if h in e[1:]} for h in helpers}
    def score(c):
        pairs=combinations(c,2)
        return sum(2*bool(consumers[a]&consumers[b])+int(a in dep[b] or b in dep[a]) for a,b in pairs)
    rng=random.Random(3705+int(p.id[-4:])+len(head)*53+remove*31)
    rng.shuffle(choices);ordered=sorted(choices,key=score,reverse=True)
    chosen=list(dict.fromkeys(ordered[:quantity//2]+choices[:quantity]))[:quantity]
    return chosen

def search(args):
    p,old,exe,fringe,remove,quantity,cap=args;g=active_graph(p,first_recipes(p,old))
    plans=[];inputs=[];best=old;counts=Counter();witnesses=[]
    for hi,head,required in windows(p,g,fringe):
        auxiliaries=set(head)-set(required)
        if len(auxiliaries)<max(5,remove) or len(required)<8:continue
        for omitted in subsets(p,head,required,remove,quantity):
            needed=tuple(sorted(set(required)|(auxiliaries-set(omitted))))
            if len(needed)>64:continue
            i=len(plans);plans.append((hi,required,needed,omitted,len(head)))
            inputs.append(' '.join(map(str,[i,p.limit,len(p.seeds),len(needed),remove-1,cap,*p.seeds,*needed])))
    if inputs:
        q=subprocess.run([str(exe)],input='\n'.join(inputs)+'\n',capture_output=True,text=True,check=True,creationflags=getattr(subprocess,'BELOW_NORMAL_PRIORITY_CLASS',0))
        lines=q.stdout.splitlines();assert len(lines)==len(plans)
        for i,(line,(hi,required,needed,omitted,oldsize)) in enumerate(zip(lines,plans)):
            idx,st,n,terminal,*seq=line.split();assert int(idx)==i;counts[st]+=1
            if st!='FOUND':continue
            seq=tuple(map(int,seq));patch=generate(p.seeds,p.limit,seq,needed);assert len(patch)<oldsize
            w=dict(ceiling=hi,required=required,augmented=needed,omitted=omitted,old=oldsize,nodes=int(n),sequence=seq)
            witnesses.append(w)
            try:graph=active_graph(p,g|patch)
            except (KeyError,ValueError):continue
            if len(graph)>=len(best):continue
            t=schedule_like(p,old,graph)
            if t is None or len(t)>len(graph):
                other=compile_graph(p,graph,attempts=4,recompute=True,schedule_width=5)
                if other is not None and (t is None or len(other)<len(t)):t=other
            if t is not None and len(t)<len(best):check(p,t);best=t
    return p.id,best,dict(before=len(old),best=len(best),counts=dict(counts),witnesses=witnesses)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for n in ('parent','ids','output'):ap.add_argument(n,type=Path)
    ap.add_argument('--puzzles',type=Path,default=Path('data/puzzles.csv'))
    ap.add_argument('--exe',type=Path,required=True)
    ap.add_argument('--fringe',type=int,default=0);ap.add_argument('--remove',type=int,default=3,choices=(2,3,4))
    ap.add_argument('--per-window',type=int,default=20);ap.add_argument('--nodes',type=int,default=18000);ap.add_argument('--jobs',type=int,default=3)
    a=ap.parse_args();base=read_submission(a.parent);ids=set(a.ids.read_text().split());ps=[p for p in read_puzzles(a.puzzles) if p.id in ids]
    assert len(ps)==len(ids);rows={};wins={};start=perf_counter()
    def save():
        write_submission(a.output,[p for p in ps if p.id in wins],wins)
        atomic_text(a.output.with_suffix('.json'),json.dumps(dict(complete=len(rows)==len(ps),parent=sha256(a.parent),ids=sha256(a.ids),exe=sha256(a.exe),
          source=sha256(Path(__file__)),fringe=a.fringe,remove=a.remove,per_window=a.per_window,cap=a.nodes,seconds=perf_counter()-start,rows=rows),separators=(',',':')))
    with ThreadPoolExecutor(a.jobs) as pool:
        for i,t,r in pool.map(search,[(p,base[p.id],a.exe.resolve(),a.fringe,a.remove,a.per_window,a.nodes) for p in ps]):
            rows[i]=r
            if len(t)<r['before']:wins[i]=t
            if len(rows)%32==0:save()
    save();print(len(rows),sum(r['before']-r['best'] for r in rows.values()),sum((Counter(r['counts']) for r in rows.values()),Counter()))
if __name__=='__main__':main()
