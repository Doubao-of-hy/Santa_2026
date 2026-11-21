"""Share exact factorizations of outputs and nearby values across an entire arithmetic program."""
from collections import Counter,defaultdict
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
from math import isqrt,log2
from pathlib import Path
from time import perf_counter
import argparse
import json

from checkpoint import atomic_text
from elf import check,read_puzzles,read_submission,sha256,write_submission
from solvers.arithmetic.factor_resynthesis import cuts,factors
from graph import active_graph,first_recipes
from solvers.gpu.pooled_joins import inverse
from solvers.graphs.witness_portfolio import canonical,candidates,extract
from solvers.graphs.whole_pools import arithmetic


def menus(p,tape,roots,offsets,width,recursive):
    primary=active_graph(p,first_recipes(p,tape))
    use=Counter(x for _,a,b in primary.values() for x in {a,b})
    known=set(p.seeds)|primary.keys()
    anchors=sorted(known,key=lambda a:(-use[a],a))
    one={}
    for i,a in enumerate(anchors):
        for b in anchors[:i+1]:
            for v,r in arithmetic(a,b,p.limit):
                if v not in known:one.setdefault(v,canonical(r))
    def basecost(v):
        if v in known:return 0.
        if v in one:return 1.
        return 2.5+.04*v.bit_length()
    routes=defaultdict(list);support=defaultdict(set)
    regions=cuts(p,primary,roots)
    for _,root,paid in regions:
        selected=[(root,None)];old=primary[root][1:];opts={}
        for a in sorted(paid):
            for v,r in inverse(root,a,p.limit):
                if v<4 or v in paid or v==root:continue
                merit=(a not in old,-sum(v%q==0 for q in (2,3,5,7,11)),v.bit_length()//4,-min(use[a],5),v)
                if v not in opts or merit<opts[v][0]:opts[v]=(merit,r)
        selected.extend((v,r) for v,(_,r) in sorted(opts.items(),key=lambda x:x[1][0])[:offsets])
        for n,r in selected:
            for a,b in factors(n):
                routes[root].append((n,r,a,b))
                support[a].add(root);support[b].add(root)
    def price(v):
        return basecost(v)-.55*min(4,log2(len(support.get(v,()))+1))
    ways=defaultdict(set);wanted=set()
    def add(v,r):
        if v not in p.seeds and v not in r[1:]:ways[v].add(canonical(r))
    for root,options in routes.items():
        # One quota per residual before filling the remaining places globally.
        ranked=sorted(options,key=lambda x:((x[1] is not None)+price(x[2])+(price(x[3]) if x[2]!=x[3] else 0),
                                           max(x[2].bit_length(),x[3].bit_length()),x[0],x[2]))
        seen=set();selected=[]
        for option in ranked:
            if option[0] in seen:continue
            selected.append(option);seen.add(option[0])
            if len(selected)>=max(2,width//3):break
        selected+=ranked[:width]
        for n,r,a,b in selected:
            wanted.update((a,b));add(n,('*',a,b))
            if r:add(root,r)
    main=set(wanted)
    if recursive:
        # Smaller factors found inside several first-layer factors are eligible
        # even when no such value occurs anywhere in the original program.
        second=defaultdict(set)
        for v in main-known:
            for a,b in factors(v):
                second[a].add(v);second[b].add(v)
        for v in sorted(main-known):
            terms=sorted(factors(v),key=lambda ab:sum(basecost(a)-.65*min(4,log2(1+len(second[a]))) for a in set(ab)))
            for a,b in terms[:3]:
                wanted.update((a,b));add(v,('*',a,b))
    # Supply factor leaves from the entire original graph. Cross-leaf recipes
    # can later be selected together, subject to an actual acyclic execution.
    for v in sorted(wanted-known):
        if v in one:add(v,one[v])
        count=0
        for a in anchors:
            for h,r in inverse(v,a,p.limit):
                if h==v:continue
                if h in known or h in wanted:add(v,r)
                elif h in one and count<5:
                    add(h,one[h]);add(v,r);count+=1
        for h,op in [(v//2,'+'),(isqrt(v),'*')]:
            if (op=='+' and h+h!=v) or (op=='*' and h*h!=v):continue
            if h in one:add(h,one[h])
            if h in wanted or h in known or h in one:add(v,(op,h,h))
    menu=candidates(p,tape,ways,48)
    return menu,dict(roots=len(regions),factor_pairs=sum(map(len,routes.values())),factor_leaves=len(main),
                     wanted=len(wanted),total_values=len(menu[1]),total_edges=sum(map(len,menu[1].values())))


def task(args):
    p,tape,roots,offsets,width,recursive,control=args
    menu,stats=menus(p,tape,roots,offsets,width,recursive)
    best=extract(p,tape,menu,3,.18,False)
    if control:
        baseline=extract(p,tape,candidates(p,tape,{},48),3,.18,False)
        stats['control']=len(baseline)
        if len(baseline)<len(best):best=baseline
    stats.update(parent=len(tape),best=check(p,best))
    return p.id,best,stats


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('parent',type=Path);ap.add_argument('output',type=Path)
    ap.add_argument('--ids',type=Path,required=True);ap.add_argument('--roots',type=int,default=28)
    ap.add_argument('--offsets',type=int,default=12);ap.add_argument('--width',type=int,default=12)
    ap.add_argument('--jobs',type=int,default=3);ap.add_argument('--recursive',action='store_true')
    ap.add_argument('--control',action='store_true')
    a=ap.parse_args();ids=set(a.ids.read_text().split())
    puzzles=[p for p in read_puzzles('data/puzzles.csv') if p.id in ids];assert len(puzzles)==len(ids)
    base=read_submission(a.parent);wins={};rows={};start=perf_counter()
    def save():
        write_submission(a.output,[p for p in puzzles if p.id in wins],wins)
        atomic_text(a.output.with_suffix('.json'),json.dumps(dict(complete=len(rows)==len(puzzles),
            seconds=perf_counter()-start,parent=sha256(a.parent),ids=sha256(a.ids),source=sha256(Path(__file__)),
            settings=dict(roots=a.roots,offsets=a.offsets,width=a.width,recursive=a.recursive),rows=rows),indent=1))
    with ProcessPoolExecutor(a.jobs) as pool:
        for i,prog,stats in pool.map(task,[(p,base[p.id],a.roots,a.offsets,a.width,a.recursive,a.control) for p in puzzles]):
            rows[i]=stats
            if len(prog)<len(base[i]):
                wins[i]=prog;print(i,len(base[i]),len(prog),flush=True)
            if len(rows)%32==0:save()
    save()
    print('count',len(rows),'gained',sum(r['parent']-r['best'] for r in rows.values()),flush=True)

if __name__=='__main__':main()
