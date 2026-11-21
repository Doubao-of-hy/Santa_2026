"""Recover shared operands of two existing results and price both replacement cones together."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
from itertools import combinations
from pathlib import Path
from time import perf_counter
import json

from checkpoint import atomic_text
from elf import arithmetic, check, read_puzzles, read_submission, sha256, write_submission
from graph import active_graph, compile_graph, first_recipes
from solvers.gpu.gpu_join import cut_many
from solvers.gpu.gpu_schedule import schedule_like
from lower_bounds import double_witnesses
from solvers.gpu.pooled_joins import inverse


def edges(a,b,cap):
    if a+b<=cap:yield a+b,('+',a,b)
    if a!=b:yield abs(a-b),('-',max(a,b),min(a,b))
    if a<=cap//b:yield a*b,('*',a,b)
    big,small=max(a,b),min(a,b)
    if big%small==0:yield big//small,('/',big,small)


def synthesis(p,tape,width,root_count,depth):
    g=active_graph(p,first_recipes(p,tape));old=tuple(dict.fromkeys((*p.seeds,*g)))
    bits={v:1<<i for i,v in enumerate(old)};closure={v:bits[v] for v in p.seeds}
    for v,(_,a,b) in g.items():closure[v]=bits[v]|closure[a]|closure[b]
    births=defaultdict(list)
    for ix,a in enumerate(old):
        for b in old[:ix+1]:
            m=closure[a]|closure[b]
            for v,edge in edges(a,b,p.limit):
                if v!=a and v!=b:births[v].append((m,edge))
    use=Counter(x for _,a,b in g.values() for x in {a,b})
    targets=set(p.targets)
    private={v:0 for v in p.seeds}
    for v,(_,a,b) in g.items():
        private[v]=bits[v]
        for val in {a,b}:
            if val not in targets and use[val]==1:private[v]|=private[val]
    pool=sorted(g,key=lambda v:(-private[v].bit_count(),-use[v],v))
    mandatory=[v for v in pool if v in targets]
    roots=list(dict.fromkeys(mandatory[:root_count]+pool[:root_count]))
    candidates=[];stats=Counter()
    for x,y in combinations(roots,2):
        for a,b in set((*double_witnesses(x,y),*double_witnesses(y,x))):
            if b<1 or a>p.limit or {x,y}&{a,b}:continue
            output=dict(edges(a,b,p.limit))
            if x not in output or y not in output:continue
            pair=[(x,output[x]),(y,output[y])]
            if all(g[v]==edge for v,edge in pair):continue
            cheap=sum(0 if h in bits else 1 if h in births else 2 for h in (a,b))
            if cheap>2 and depth<2:continue
            gain=(private[x]|private[y]).bit_count()-2-cheap
            priority=(int(any(h in bits or h in births for h in (a,b))),min(gain,7),sum(h in bits for h in (a,b)),sum(h in births for h in (a,b)),
                      int(x in targets)+int(y in targets),-a.bit_length(),-a)
            candidates.append((priority,x,y,a,b,tuple(pair)))
    candidates.sort(reverse=True);stats['equations']=len(candidates)
    @lru_cache(maxsize=None)
    def options(h):
        routes=[]
        if h in bits:routes.append((closure[h],()))
        for mask,recipe in births.get(h,()):
            routes.append((mask,((h,recipe),)))
        if depth>1:
            for a in old:
                for m,e in inverse(h,a,p.limit):
                    if m in (h,a) or h==a or m in bits:continue
                    for mask,r in births.get(m,()):
                        routes.append((mask|closure[a],((m,r),(h,e))))
        return routes
    offers={'single':{},'joint':{}}
    for _,x,y,a,b,pair in candidates[:width]:
        kept,_=cut_many(p,g,{x,y})
        removed=sum(bits[h] for h in g.keys()-kept.keys()-{x,y})
        forbidden=bits[x]|bits[y]
        def shortlist(routes):
            selected={}
            for mask,steps in routes:
                if mask&forbidden:continue
                debit=(mask&removed).bit_count()+len(steps)
                stamp=(mask&removed,tuple(i for i,_ in steps))
                if stamp not in selected:selected[stamp]=(debit,mask,steps)
            return sorted(selected.values(),key=lambda v:(v[0],len(v[2]),v[2]))[:5]
        aa=shortlist(options(a));bb=shortlist(options(b))
        ordinary=[(ra,rb) for ra in aa for rb in bb]
        # Permit the second operand to depend on the first, paying its birth once.
        for u,v,base in ((a,b,aa),(b,a,bb)):
            if not base:continue
            for needed,e in inverse(v,u,p.limit):
                if needed not in bits or needed==v or closure[needed]&forbidden:continue
                other=(0,closure[needed],((v,e),))
                ordinary.extend((first,other) for first in base)
        stats['buildable_pairs']+=int(bool(ordinary))
        stats['possible_constructions']+=len(ordinary)
        for (_,m,s),(_,n,t) in ordinary:
            patch=dict(s+t)
            if any(h in dict(s) and dict(s)[h]!=r for h,r in t):continue
            new_count=len(patch.keys()-g.keys())
            if new_count+(removed&(m|n)).bit_count()>=removed.bit_count():continue
            for action,rewrites in [('joint',pair),('single',pair[:1]),('single',pair[1:])]:
                delta=patch|dict(rewrites);key=tuple(sorted(delta.items()))
                if key in offers[action]:continue
                try:graph=active_graph(p,g|delta)
                except (ValueError,KeyError):continue
                if len(graph)<len(tape):offers[action][key]=(len(graph),delta)
    def install(proposals):
        best=tape;chosen=g
        for _,delta in sorted(proposals,key=lambda a:a[0]):
            try:graph=active_graph(p,chosen|delta)
            except (KeyError,ValueError):continue
            if len(graph)>=len(best):continue
            prog=schedule_like(p,best,graph)
            if prog is None or len(prog)>len(graph):
                other=compile_graph(p,graph,attempts=3,schedule_width=3,recompute=True)
                if other is not None and (prog is None or len(other)<len(prog)):prog=other
            if prog is not None and len(prog)<len(best):
                check(p,prog);best=prog;chosen=graph
        return best
    solo=install(offers['single'].values())
    joint=install([*offers['joint'].values(),*offers['single'].values()])
    best=min((solo,joint),key=len)
    stats.update(parent=len(tape),best=len(best),single=len(solo),joint=len(joint),
                 joint_offers=len(offers['joint']),solo_offers=len(offers['single']),tested=min(len(candidates),width))
    return p.id,best,dict(stats)


def work(args):return synthesis(*args)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for arg in ('parent','output','ids'):ap.add_argument(arg,type=Path)
    ap.add_argument('--puzzles',type=Path,default=Path('data/puzzles.csv'))
    ap.add_argument('--width',type=int,default=80)
    ap.add_argument('--roots',type=int,default=28)
    ap.add_argument('--depth',type=int,choices=(1,2),default=2)
    ap.add_argument('--jobs',type=int,default=3)
    a=ap.parse_args();base=read_submission(a.parent);ids=set(a.ids.read_text().split())
    ps=[p for p in read_puzzles(a.puzzles) if p.id in ids];assert len(ps)==len(ids)
    rows={};wins={};start=perf_counter()
    def save():
        write_submission(a.output,[p for p in ps if p.id in wins],wins)
        atomic_text(a.output.with_suffix('.json'),json.dumps(dict(parent=sha256(a.parent),source=sha256(Path(__file__)),
             ids=sha256(a.ids),width=a.width,roots=a.roots,depth=a.depth,seconds=perf_counter()-start,
             complete=len(ps)==len(rows),rows=rows),indent=1))
    with ProcessPoolExecutor(a.jobs) as pool:
        for pid,t,r in pool.map(work,[(p,base[p.id],a.width,a.roots,a.depth) for p in ps]):
            rows[pid]=r
            if len(t)<len(base[pid]):wins[pid]=t
            if len(rows)%8==0:save()
    save();print(len(rows),'savings',sum(r['parent']-r['best'] for r in rows.values()),flush=True)
if __name__=='__main__':main()
