"""Replace a program region by a factored nearby value and synthesize both factors."""
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
from pathlib import Path
from time import perf_counter
import argparse
import json
import subprocess
import sys

from checkpoint import atomic_text
from elf import arithmetic, check, read_puzzles, read_submission, sha256, write_submission
from graph import active_graph, compile_graph, first_recipes
from solvers.gpu.gpu_join import cut_many
from solvers.gpu.gpu_schedule import schedule_like
from solvers.gpu.pooled_joins import inverse

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'work/lattice/deps'))
from flint import fmpz


@lru_cache(maxsize=16000)
def factors(n):
    if n<4:return ()
    divisors=[1]
    for prime,power in fmpz(n).factor():
        prior=divisors.copy()
        for j in range(1,int(power)+1):
            scale=int(prime)**j
            divisors.extend(d*scale for d in prior)
    return tuple((d,n//d) for d in sorted(divisors) if 1<d<=n//d)


def cuts(p,graph,count):
    uses=Counter(x for _,a,b in graph.values() for x in {a,b})
    targets=set(p.targets)
    regions=[]
    for root in graph:
        kept,free=cut_many(p,graph,{root})
        cost=len(graph)-len(kept)
        if cost<3:continue
        paid=set(p.seeds)|free.keys()
        if not paid:continue
        regions.append((cost,root,paid))
    groups=([r for r in regions if r[1] in targets],
            [r for r in regions if r[1] not in targets and uses[r[1]]>1],
            [r for r in regions if r[1] not in targets and uses[r[1]]==1])
    for group in groups:
        group.sort(key=lambda r:(-min(r[0],14),-min(uses[r[1]],6),-r[1].bit_length(),r[1]))
    chosen=[]
    for index in range(max(map(len,groups),default=0)):
        for group in groups:
            if index<len(group):chosen.append(group[index])
            if len(chosen)==count:return chosen
    return chosen


def residuals(p,graph,root,paid,limit):
    if not limit:return [(root,('=',0,0))]
    uses=Counter(x for _,a,b in graph.values() for x in {a,b})
    priority={};old=graph[root][1:]
    for a in sorted(paid):
        for n,e in inverse(root,a,p.limit):
            if n in paid or n==root or n<4:continue
            # Small factors and smooth residuals have more possible products.
            key=(a not in old, -sum(n%q==0 for q in (2,3,5,7,11,13)),
                 n.bit_length()//4,-min(5,uses[a]),n,e)
            if n not in priority or key<priority[n][0]:priority[n]=(key,e)
    best=sorted(priority.items(),key=lambda item:item[1][0])
    return [(root,('=',0,0))]+[(n,e) for n,(_,e) in best[:limit]]


def optimize(p,tape,exe,ncuts,offsets,linked,nout,select):
    base=active_graph(p,first_recipes(p,tape))
    regions=cuts(p,base,ncuts)
    lines=[str(len(regions))]
    stats=Counter(cuts=len(regions))
    for cost,root,paid in regions:
        rows=[]
        for n,(op,a,b) in residuals(p,base,root,paid,offsets):
            for f,g in factors(n):
                rows.append(f'{n} {f} {g} {op} {a} {b}')
        stats['factor_pairs']+=len(rows)
        lines.append(f'{p.limit} {root} {len(paid)} {len(rows)} {min(cost+1,8)} {int(linked)} {nout}')
        lines.append(' '.join(map(str,sorted(paid))))
        lines.extend(rows)
    raw=subprocess.run([str(exe)],input='\n'.join(lines)+'\n',capture_output=True,text=True,check=True)
    stream=iter(raw.stdout.splitlines());offers=[];witness=defaultdict(set)
    for cost,root,paid in regions:
        count,joint,found=map(int,next(stream).split())
        stats.update(generated=found,linked=joint,retained=count)
        for _ in range(count):
            steps,common=map(int,next(stream).split());patch={};available=set(paid)
            for _ in range(steps):
                out,op,a,b=next(stream).split()
                out,a,b=int(out),int(a),int(b)
                if a not in available or b not in available or arithmetic(op,a,b)!=out or not 1<=out<=p.limit:
                    raise ValueError('Invalid native factorization')
                available.add(out);patch[out]=(op,a,b)
                witness[out].add((op,min(a,b),max(a,b)) if op in '+*' else (op,a,b))
            if list(patch)[-1]!=root:raise ValueError('Wrong output')
            try:new=active_graph(p,base|patch)
            except (KeyError,ValueError):continue
            if len(new)<len(base):offers.append((len(new),patch))
    if next(stream,None) is not None:raise ValueError('Unexpected native output')
    best=tape;graph=base
    for _,patch in sorted(offers,key=lambda x:x[0]):
        try:g=active_graph(p,graph|patch)
        except (KeyError,ValueError):continue
        if len(g)>=len(best):continue
        prog=schedule_like(p,best,g)
        if prog is None or len(prog)>len(g):
            second=compile_graph(p,g,attempts=3,schedule_width=4,recompute=True)
            if second is not None and (prog is None or len(second)<len(prog)):prog=second
        if prog is not None and len(prog)<len(best):best=prog;graph=g
    stats['greedy']=len(best)
    if select and witness:
        from solvers.graphs.witness_portfolio import candidates,extract
        menu=candidates(p,best,witness,90)
        other=extract(p,best,menu,2,.16,False)
        if len(other)<len(best):best=other
    check(p,best)
    return p.id,best,dict(stats,parent=len(tape),best=len(best))


def job(args):
    return optimize(*args)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('parent',type=Path);ap.add_argument('output',type=Path)
    ap.add_argument('--exe',type=Path,required=True)
    ap.add_argument('--ids',type=Path,required=True)
    ap.add_argument('--puzzles',type=Path,default=Path('data/puzzles.csv'))
    ap.add_argument('--cuts',type=int,default=14)
    ap.add_argument('--offsets',type=int,default=24)
    ap.add_argument('--nout',type=int,default=25)
    ap.add_argument('--jobs',type=int,default=3)
    ap.add_argument('--linked',action='store_true')
    ap.add_argument('--select',action='store_true')
    a=ap.parse_args()
    ids=set(a.ids.read_text().split());puzzles=[p for p in read_puzzles(a.puzzles) if p.id in ids]
    assert len(ids)==len(puzzles)
    base=read_submission(a.parent)
    rows={};wins={};start=perf_counter()
    def save():
        write_submission(a.output,[p for p in puzzles if p.id in wins],wins)
        atomic_text(a.output.with_suffix('.json'),json.dumps(dict(
            complete=len(rows)==len(puzzles),elapsed=perf_counter()-start,source=sha256(Path(__file__)),
            native_source=sha256(ROOT/'solvers/native/factor_resynthesis.cpp'),native=sha256(a.exe),ids=sha256(a.ids),
            parent=sha256(a.parent),parameters=dict(cuts=a.cuts,offsets=a.offsets,nout=a.nout,
            linked=a.linked,select=a.select),rows=rows),indent=1))
    tasks=[(p,base[p.id],a.exe.resolve(),a.cuts,a.offsets,a.linked,a.nout,a.select) for p in puzzles]
    with ProcessPoolExecutor(a.jobs) as pool:
        for i,t,r in pool.map(job,tasks):
            rows[i]=r
            if len(t)<len(base[i]):
                wins[i]=t;print(i,len(base[i]),len(t),flush=True)
            if len(rows)%32==0:save()
    save()
    print('rows',len(rows),'saved',sum(v['parent']-v['best'] for v in rows.values()),flush=True)

if __name__=='__main__':main()
