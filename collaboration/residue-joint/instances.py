"""Choose registered two-private-branch instances without looking at solver outcomes."""
from itertools import combinations
from pathlib import Path
import hashlib,json,sys

HERE=Path(__file__).resolve().parent
ROOT=next(p for p in HERE.parents if (p/"elf.py").is_file() and (p/"graph.py").is_file())
sys.path[:0]=[str(ROOT),str(ROOT/"work/crossover/deps")]
from elf import read_puzzles,read_submission,sha256
from graph import active_graph,first_recipes
from solvers.gpu.gpu_join import cut_many

def case(p,program):
    g=active_graph(p,first_recipes(p,program))
    index={v:k for k,v in enumerate(g)};ancestors={s:0 for s in p.seeds}
    private={}
    for v,(_,a,b) in g.items():
        ancestors[v]=ancestors[a]|ancestors[b]|(1<<index[v])
        surviving,_=cut_many(p,g,{v})
        gone=g.keys()-surviving.keys()
        if 2<=len(gone)<=4:
            boundary={z for k in gone for z in g[k][1:] if z not in gone}
            private[v]=boundary
    best=None;result=None
    for a,b in combinations(private,2):
        if ancestors[b]&(1<<index[a]) or ancestors[a]&(1<<index[b]):continue
        overlap=len(private[a]&private[b])
        if best and -overlap>best[0]:continue
        surviving,free=cut_many(p,g,{a,b})
        removed=g.keys()-surviving.keys()
        if not 4<=len(removed)<=8:continue
        available=set(p.seeds)|free.keys()
        boundary={z for v in removed for z in g[v][1:] if z not in removed}
        if not 2<=len(boundary)<=5 or not boundary<=available:continue
        rank=(-overlap,-len(removed),len(boundary),index[a],index[b])
        if best is None or rank<best:
            extra=sorted(available-boundary,key=lambda v:(min(abs(a-v),abs(b-v)),v))[:1]
            result={"roots":[a,b],"boundary":sorted(boundary),"anchors":sorted(boundary)+extra,
                    "removed":sorted(removed,key=index.get),"private_sizes":[len(g.keys()-cut_many(p,g,{v})[0].keys()) for v in (a,b)],
                    "shared_input_boundary":overlap,"strict_lengths":list(range(3,min(5,len(removed)-1)+1))}
            best=rank
    return result
