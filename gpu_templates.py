"""Construct inferred numerical ingredients on the GPU and jointly re-use their valid recipes."""
import argparse
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
from time import perf_counter
from types import SimpleNamespace

from elf import Puzzle,check,read_puzzles,read_submission,write_submission
from gpu_conditioned import local_search,normalized,select
from gpu_affine_tree import expand as affine_ancestors
from gpu_exchange import exchange
from gpu_factor_graph import augment
from gpu_schedule import schedule_like
from gpu_wave import WaveEngine,solve
from graph import active_graph,compile_graph,first_recipes
from matrix_construct import choose,routes


def settings(commit):
    return SimpleNamespace(ladder=0,tail=0,warm_schedule=False,warm_macros=0,quantity=90,core=39,
                           width=8,depth=4,pricing=80,neighbor_bits=0,mod_banks=0,sweep=0,sweep_levels=1,
                           landmarks=7,exact_routes=0,cluster=False,bridge=False,commit=commit,credit=.18)


def small_closure(p,ingredients,leaves):
    # In the inferred templates dozens of offsets are compulsory. Computing
    # them together prices each shared auxiliary only once.
    exe=Path(__file__).resolve().parent/"work/virtual/closure-portable.exe"
    best=active_graph(p,ingredients,leaves)
    for ceiling in (2048,65536):
        mandatory=sorted(v for v in leaves if v<=ceiling and v not in p.seeds)
        if len(mandatory)>56:mandatory=mandatory[:56]
        if len(mandatory)<6:continue
        warm=active_graph(p,best,mandatory)
        if len(warm)<=len(mandatory):continue
        lines=[" ".join(map(str,(p.id,p.limit,len(p.seeds),len(mandatory),len(warm),len(warm),
                                 *p.seeds,*mandatory)))]
        lines.extend(f"{v} {s} {a} {b}" for v,(s,a,b) in warm.items())
        run=subprocess.run([str(exe),"14","5"],input="\n".join(lines)+"\n",capture_output=True,
                           encoding="ascii",check=True)
        records=iter(run.stdout.splitlines());key,n=next(records).split()
        if key!=p.id:raise ValueError(key)
        patch={}
        for _ in range(int(n)):
            v,op,a,b=next(records).split();patch[int(v)]=(op,int(a),int(b))
        if patch:
            try:g=active_graph(p,best|patch,leaves)
            except (ValueError,KeyError):continue
            if len(g)<len(best):best=g
    return best


def supply(p,bank,base,desired):
    # Price missing offsets using real intermediates from the seed-only GPU
    # construction. A cheap alternative offset can unlock many template paths.
    vals=sorted(base)
    lookup={}
    for i,a in enumerate(vals):
        for b in vals[i:]:
            for v,s,x,y in ((a+b,'+',a,b),(b-a,'-',b,a),(a*b,'*',a,b),
                              (b//a if b%a==0 else 0,'/',b,a)):
                if 0<v<=p.limit and v not in (a,b) and v not in base:
                    lookup.setdefault(v,normalized(s,x,y))
    got=set(base)
    for h in sorted(desired-base,key=lambda x:x.bit_length()):
        if h in lookup:
            bank[h].add(lookup[h]);got.add(h);continue
        added=0
        for x in vals:
            candidates=((h-x,'+',True),(h+x,'-',True),(x-h,'-',False),
                        (h//x if h%x==0 else 0,'*',True),(h*x,'/',True),
                        (x//h if x%h==0 else 0,'/',False))
            for v,op,left in candidates:
                if v not in lookup or v==h:continue
                bank[v].add(lookup[v])
                bank[h].add(normalized(op,v,x) if left else normalized(op,x,v))
                got.add(h);added+=1
            if added>=4:break
    return got


def stitch(p,baseline,template,ingredients,options,output,seconds,extend=False,extra=None):
    original=first_recipes(p,baseline)
    starters=original.keys()|ingredients.keys()|set(p.seeds)
    bank=defaultdict(set)
    for g in (original,ingredients,template,first_recipes(p,output)):
        for v,r in g.items():
            if v not in p.seeds and v not in r[1:]:bank[v].add(normalized(*r))
    if extra:
        for v,r in extra.items(): bank[v].update(r)
    # Include multiple exact representations of the same modelled target. Only
    # admit options whose external operands can be supplied by the current bank.
    if extend:
        desired={v for opts in options.values() for r in opts for v in r.leaves}
        starters=supply(p,bank,starters,desired)
    for opts in options.values():
        for r in opts:
            if not r.leaves<=starters:continue
            for v,e in r.graph.items():
                if v not in p.seeds and v not in e[1:]:bank[v].add(normalized(*e))
    best=min((baseline,output),key=len)
    proposals=[original|ingredients|template,template|ingredients|original]
    for g in proposals:
        try:graph=active_graph(p,g)
        except (ValueError,KeyError):continue
        if len(graph)>=len(best):continue
        q=schedule_like(p,baseline,graph)
        if q is not None and len(q)<len(best):best=q
    stat=Counter()
    best=local_search(p,best,bank,60,stat)
    return select(p,best,bank,seconds,stat)


def run(p,m,independent,licensed,engine,seconds,refine,factors=False,exchange_routes=False,affine_tree=False):
    options=routes(p,m)
    if affine_tree:options,_=affine_ancestors(p,m,options)
    trial=int(p.id.split("_")[-1])
    template,leaves=choose(options,p,p.seeds,trial)
    if not template or not leaves:return independent,licensed,independent
    # Some modeled routes start with another observed output. Materialize that
    # required input here when this particular route portfolio lacks a recipe.
    needed={v for e in template.values() for v in e[1:] if v not in template}
    needed.update(leaves)
    needed-=set(p.seeds)
    task=Puzzle(p.id,p.seeds,tuple(sorted(needed)),p.limit,p.registers)
    ingredients=first_recipes(task,solve(task,engine,settings(7))[0])
    if refine:ingredients=small_closure(p,ingredients,needed)
    extra=defaultdict(set)
    if exchange_routes:
        replacement,leaves,available=exchange(p,options,ingredients,trial)
        replacement_needs={v for e in replacement.values() for v in e[1:] if v not in replacement}
        replacement_needs.update(leaves);replacement_needs-=set(p.seeds)
        for portfolio in (ingredients,template):
            for v,r in portfolio.items():
                if v not in p.seeds and v not in r[1:]:extra[v].add(normalized(*r))
        for v,recipes in available.items():extra[v].update(recipes)
        if replacement_needs!=needed:
            task=Puzzle(p.id,p.seeds,tuple(sorted(replacement_needs)),p.limit,p.registers)
            ingredients=first_recipes(task,solve(task,engine,settings(7))[0])
            if refine:ingredients=small_closure(p,ingredients,replacement_needs)
        template=replacement;needed=replacement_needs
    if factors:
        bank=defaultdict(set)
        program=compile_graph(task,ingredients,recompute=True,schedule_width=10)
        if program is not None:
            for v,r in ingredients.items():bank[v].add(normalized(*r))
            augment(p,bank,set(p.seeds)|ingredients.keys(),needed,supply)
            stat=Counter();local=local_search(task,program,bank,45,stat)
            better=select(task,local,bank,seconds,stat)
            ingredients=first_recipes(task,better)
            for v,recipes in bank.items():extra[v].update(recipes)
    merged=ingredients.copy()
    for v,e in template.items():merged.setdefault(v,e)
    roots=tuple(t for t in p.targets if t in merged)
    try:scaffold=active_graph(p,merged,roots)
    except (ValueError,KeyError):
        scaffold=ingredients
    raw,_=solve(p,engine,settings(4),prepared=scaffold)
    own=stitch(p,independent,template,ingredients,options,raw,seconds,refine,extra)
    trusted=stitch(p,licensed,template,ingredients,options,raw,seconds,refine,extra)
    return own,trusted,raw


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for key in ("data","models","independent","trusted","output"):ap.add_argument(key,type=Path)
    ap.add_argument("--rows",type=int,default=24)
    ap.add_argument("--seconds",type=float,default=2)
    ap.add_argument("--ids",type=Path)
    ap.add_argument("--refine",action="store_true")
    ap.add_argument("--factors",action="store_true")
    ap.add_argument("--exchange",action="store_true")
    ap.add_argument("--affine-tree",action="store_true")
    ap.add_argument("--checkpoint",type=int,default=4)
    a=ap.parse_args()
    puzzles={p.id:p for p in read_puzzles(a.data)}
    own=read_submission(a.independent);public=read_submission(a.trusted)
    models=[m for m in (json.loads(s) for s in a.models.read_text().splitlines()) if m["hubs"]]
    if a.ids:
        ids=set(a.ids.read_text().split());models=[m for m in models if m["id"] in ids]
    # Long rows with broad model coverage have the largest available gain.
    models.sort(key=lambda m:-(len(m["targets"])/max(1,m["total"]))**1.5 *
                len(public[m["id"]])*min(2,1+m.get("fit",0)/240))
    if a.rows:models=models[:a.rows]
    db=sqlite3.connect(a.output.with_suffix(".sqlite"))
    db.execute("CREATE TABLE IF NOT EXISTS portfolio (id TEXT, sig TEXT, own TEXT, trusted TEXT, raw TEXT, PRIMARY KEY(id,sig))")
    engine=WaveEngine(Path(__file__).resolve().parent/"work/gpu",True)
    raw={};trusted={};donors={};t0=perf_counter()
    code=hashlib.sha256()
    for filename in ("gpu_templates.py","gpu_wave.py","gpu_conditioned.py","gpu_wave.cl",
                     "gpu_join.py","matrix_construct.py","gpu_schedule.py","gpu_factor_graph.py","gpu_exchange.py","gpu_affine_tree.py"):
        code.update(Path(__file__).with_name(filename).read_bytes())
    outputs=[a.output.with_name(a.output.stem+"-"+s+".csv") for s in ("independent","trusted","raw")]
    for m in models:
        k=m["id"];p=puzzles[k]
        sig=hashlib.sha256(repr((p,m,own[k],public[k],a.seconds,a.refine,a.factors,a.exchange,a.affine_tree,code.hexdigest())).encode("ascii")).hexdigest()
        row=db.execute("SELECT own,trusted,raw FROM portfolio WHERE id=? AND sig=?",(k,sig)).fetchone()
        if row:aa,bb,cc=[tuple(map(tuple,json.loads(s))) for s in row]
        else:
            aa,bb,cc=run(p,m,own[k],public[k],engine,a.seconds,a.refine,a.factors,a.exchange,a.affine_tree)
            check(p,aa);check(p,bb);check(p,cc)
            db.execute("INSERT INTO portfolio VALUES (?,?,?,?,?)",(k,sig,json.dumps(aa),json.dumps(bb),json.dumps(cc)));db.commit()
        raw[k]=aa;trusted[k]=bb;donors[k]=cc
        if len(raw)%a.checkpoint==0 or len(raw)==len(models) or len(raw)==1:
            for path,answers in zip(outputs,(raw,trusted,donors)):
                write_submission(path,[puzzles[x] for x in answers],answers)
        print(k,len(own[k])-len(aa),len(public[k])-len(bb),round(perf_counter()-t0,1),flush=True)
    db.close()


if __name__=="__main__":main()
