"""Minimize a fixed set of live boundary values starting at the official seeds."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import perf_counter
import json
import subprocess
from checkpoint import atomic_text
from corpus_prefix import windows, arithmetic_edges
from elf import check,read_submission,read_puzzles,write_submission,sha256
from graph import compile_graph,active_graph,first_recipes
from gpu_schedule import schedule_like


def generate(p,seq,targets):
    order=list(p.seeds);graph={}
    assert list(seq[:len(order)])==order
    for v in seq[len(order):]:
        if v in order:continue
        options=(e for i,a in enumerate(order) for b in order[:i+1] for w,e in arithmetic_edges(a,b,p.limit) if w==v)
        graph[v]=next(options);order.append(v)
    assert set(targets)<=set(order)
    return graph


def run(args):
    p,old,exe,cap,depth,fringe=args
    graph=active_graph(p,first_recipes(p,old));records=[];best=old
    for ceiling,head,required in windows(p,graph,fringe):
        n=len(head)-len(required)
        if not 1<=n<=depth or p.limit>10**18 or len(required)>64:continue
        budget=n-1
        while budget>=0:
            payload=[p.limit,len(p.seeds),len(required),budget,cap,*p.seeds,*required]
            process=subprocess.run([str(exe),'pair','0','1','0','1','0','1'],text=True,input=' '.join(map(str,payload))+'\n',
                capture_output=True,check=True,creationflags=getattr(subprocess,'BELOW_NORMAL_PRIORITY_CLASS',0))
            lines=process.stdout.splitlines();status,nodes,*_=lines[0].split()
            r=dict(ceiling=ceiling,required=required,old=len(head),helpers=budget,status=status,nodes=int(nodes));records.append(r)
            if status!='FOUND':break
            seq=tuple(map(int,lines[1].split()));g=generate(p,seq,required)
            assert len(g)<=len(required)+budget
            r['sequence']=seq
            try:combined=active_graph(p,graph|g)
            except (ValueError,KeyError):combined=None
            if combined is not None and len(combined)<len(best):
                t=schedule_like(p,old,combined)
                if t is None or len(t)>len(combined):
                    other=compile_graph(p,combined,attempts=4,recompute=True,schedule_width=4)
                    if other is not None and (t is None or len(other)<len(t)):t=other
                if t is not None and len(t)<len(best):check(p,t);best=t
            budget=len(g)-len(required)-1
    return p.id,best,dict(before=len(old),best=len(best),windows=records)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for k in ('parent','ids','output'):ap.add_argument(k,type=Path)
    ap.add_argument('--puzzles',type=Path,default=Path('data/puzzles.csv'))
    ap.add_argument('--exe',type=Path,required=True)
    ap.add_argument('--depth',type=int,default=3)
    ap.add_argument('--nodes',type=int,default=25000)
    ap.add_argument('--fringe',type=int,default=0)
    ap.add_argument('--jobs',type=int,default=5)
    a=ap.parse_args();start=perf_counter();base=read_submission(a.parent);ids=set(a.ids.read_text().split())
    ps=[p for p in read_puzzles(a.puzzles) if p.id in ids];assert len(ps)==len(ids)
    rows={};wins={}
    def save():
        write_submission(a.output,[p for p in ps if p.id in wins],wins)
        atomic_text(a.output.with_suffix('.json'),json.dumps(dict(complete=len(rows)==len(ps),parent=sha256(a.parent),source=sha256(Path(__file__)),
            exe=sha256(a.exe),official=sha256(a.puzzles),ids=sha256(a.ids),depth=a.depth,nodes=a.nodes,fringe=a.fringe,seconds=perf_counter()-start,rows=rows),separators=(',',':')))
    with ThreadPoolExecutor(a.jobs) as pool:
        for i,t,r in pool.map(run,[(p,base[p.id],a.exe.resolve(),a.nodes,a.depth,a.fringe) for p in ps]):
            rows[i]=r
            if len(t)<r['before']:wins[i]=t
            if len(rows)%64==0:save()
    save();print(len(rows),sum(r['before']-r['best'] for r in rows.values()),dict(Counter(z['status'] for r in rows.values() for z in r['windows'])))
if __name__=='__main__':main()
