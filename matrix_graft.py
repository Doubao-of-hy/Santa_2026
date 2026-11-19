"""Rebuild clusters on a recovered multiplication table with the rest of the program paid."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import random
import sqlite3

from elf import check, read_puzzles, read_submission, sha256, write_submission
from gpu_schedule import schedule_like
from graph import active_graph, compile_graph, first_recipes
from matrix_construct import Route, choose, native, routes


def trim(target,path,free,allowed):
    useful={};leaves=set();todo=[target]
    while todo:
        x=todo.pop()
        if x in free or x in useful:continue
        if x not in path:
            if x not in allowed:leaves.add(x)
            continue
        op,a,b=path[x];useful[x]=(op,a,b);todo.extend((a,b))
    return Route(useful,leaves)


def pool(p,free,literals):
    c={}
    vals=sorted(free)
    for i,a in enumerate(vals):
        for b in vals[:i+1]:
            if a+b<=p.limit:c.setdefault(a+b,('+',a,b))
            if a>b:c.setdefault(a-b,('-',a,b))
            if a*b<=p.limit:c.setdefault(a*b,('*',a,b))
            if a%b==0:c.setdefault(a//b,('/',a,b))
    hints={};new={}
    for x in sorted(literals-free):
        if x in c:
            new[x]=c[x];hints[x]=1;continue
        # Save the first complete two-step plan, preferring a shared helper.
        options=[]
        for b in vals:
            for v,op,flip in ((x-b,'+',0),(x+b,'-',0),(b-x,'-',1),
                              (x//b if x%b==0 else 0,'*',0),(x*b,'/',0),
                              (b//x if b%x==0 else 0,'/',1)):
                if v in c and v!=x and x not in c[v][1:]:
                    options.append((v not in new,v,op,b,flip))
        if options:
            _,v,op,b,flip=min(options)
            new.setdefault(v,c[v]);new[x]=(op,b,v) if flip else (op,v,b)
            hints[x]=1.8
    return hints,new


def optimize(p,m,old,exe,blocks,passes):
    original=first_recipes(p,old);best=old
    all_routes=routes(p,m)
    cells=defaultdict(set)
    for item in m["targets"]:
        t,a,b=item["t"],item["a"],item["b"]
        cells[a,b].add(t);cells[a].add(t);cells[b].add(t)
    pri={t:len(active_graph(p,original,(t,))) for t in all_routes}
    groups=[set(all_routes)]
    candidates=sorted(set(map(frozenset,cells.values())),key=lambda g:(-len(g),-sum(pri[x] for x in g)))
    for group in candidates:
        if group not in groups and len(group)>=2:groups.append(group)
    rng=random.Random(int(p.id.split('_')[-1]))
    if len(groups)>blocks:
        others=list(groups[2:]);rng.shuffle(others)
        groups=groups[:2]+others[:max(0,blocks-2)]
    for group in groups[:blocks]:
        kept=active_graph(p,original,set(p.targets)-group)
        free=set(kept)|set(p.seeds)
        wanted=group-free
        if not wanted:continue
        options={}
        for t in wanted:
            candidates=[trim(t,rt.graph,free,wanted) for rt in all_routes[t]]
            options[t]=candidates
        leafs=set().union(*(r.leaves for rr in options.values() for r in rr))
        hints,short=pool(p,free,leafs)
        # Model routes can be mixed with existing branches in a single cut.
        for t in wanted:options[t].append(trim(t,original,free,wanted-{t}))
        participation=Counter(v for g in kept.values() for v in set(g[1:]))
        ranked=sorted(free,key=lambda v:(v not in p.seeds,v not in leafs,-participation[v],v))
        # All small subproblems use a virtual dictionary. Every actual recipe
        # is merged back into the original DAG before physical replay.
        for i in range(passes):
            menu={t:(rs[:-1] if i==0 else rs) for t,rs in options.items()}
            net,required=choose(menu,p,free,rng.randrange(1<<24),hints)
            needed=required-free
            patch=dict(kept)
            def direct(x):
                if x in patch or x in free or x not in short:return
                op,a,b=short[x]
                direct(a);direct(b);patch[x]=(op,a,b)
            for x in sorted(needed):direct(x)
            missing=needed-set(patch)
            if missing:
                seeds=list(dict.fromkeys((*p.seeds,*(v for v in ranked if v in needed),
                                           *(v for v in patch if v not in free),*ranked[:70])))
                raw=native(p,seeds,sorted(missing),exe,77,5,rng.randrange(1<<24))
                for v,e in raw.items():patch.setdefault(v,e)
            for v,e in net.items():patch.setdefault(v,e)
            try:cut=active_graph(p,patch)
            except (KeyError,ValueError):continue
            if len(cut)>=len(best):continue
            physical=schedule_like(p,best,cut)
            if physical is None or len(physical)>len(cut):
                extra=compile_graph(p,cut,recompute=True,schedule_width=12)
                if extra is not None and (physical is None or len(extra)<len(physical)):physical=extra
            if physical is not None and len(physical)<len(best):
                check(p,physical);best=physical;original=first_recipes(p,best)
    return p.id,best


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for k in ("models","incumbent","output"):ap.add_argument(k,type=Path)
    ap.add_argument("--exe",type=Path,default=Path("work/virtual/planner-powers.exe"))
    for k,v in (("workers",3),("blocks",4),("passes",3),("rows",0),("minimum",5)):
        ap.add_argument("--"+k,type=int,default=v)
    a=ap.parse_args();puzzles=read_puzzles(Path("data/puzzles.csv"))
    byid={p.id:p for p in puzzles};base=read_submission(a.incumbent)
    models=[json.loads(s) for s in a.models.read_text().splitlines() if s]
    models=[m for m in models if len(m["targets"])>=a.minimum]
    models.sort(key=lambda m:-len(m["targets"])/len(byid[m["id"]].targets))
    if a.rows:models=models[:a.rows]
    db=sqlite3.connect(a.output.with_suffix(".sqlite"))
    db.execute("CREATE TABLE IF NOT EXISTS runs(id TEXT,digest TEXT,program TEXT,PRIMARY KEY(id,digest))")
    config=str((sha256(Path(__file__)),sha256(Path("matrix_construct.py")),sha256(a.exe),a.passes,a.blocks))
    out={};gains=0
    def save():
        write_submission(a.output,[p for p in puzzles if p.id in out],out)
        print(f"{len(out)}/{len(models)} completed, {gains} saved",flush=True)
    with ProcessPoolExecutor(a.workers) as workers:
        pending={}
        for m in models:
            t=m["id"]
            key=hashlib.sha256((repr(base[t])+json.dumps(m,sort_keys=True)+config).encode()).hexdigest()
            prior=db.execute("SELECT program FROM runs WHERE id=? AND digest=?",(t,key)).fetchone()
            if prior:
                pg=tuple(map(tuple,json.loads(prior[0])));check(byid[t],pg);out[t]=pg
                gains+=len(base[t])-len(pg);continue
            job=workers.submit(optimize,byid[t],m,base[t],a.exe.resolve(),a.blocks,a.passes)
            pending[job]=key
        for job in as_completed(pending):
            t,pg=job.result();out[t]=pg;gains+=len(base[t])-len(pg)
            db.execute("INSERT OR REPLACE INTO runs VALUES(?,?,?)",(t,pending[job],json.dumps(pg,separators=(",",":"))))
            db.commit()
            if len(out)%10==0:save()
    save();db.close()


if __name__=="__main__":main()
