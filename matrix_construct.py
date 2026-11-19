"""Construct a complete scored program using recovered integer multiplication tables."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
from math import isqrt,log2
from pathlib import Path
import random
import sqlite3
import subprocess

from elf import check, read_puzzles, read_submission, sha256, write_submission
from graph import active_graph, compile_graph


def native(p,seeds,targets,exe,mode,width,seed,warm=None):
    seeds=tuple(dict.fromkeys(seeds))
    targets=tuple(dict.fromkeys(x for x in targets if x not in seeds))
    if not targets: return {}
    trace=warm or {}
    data=" ".join(map(str,(p.id,p.limit,len(seeds),len(targets),*seeds,*targets,len(trace))))+"\n"
    data+="".join(f"{v} {op} {a} {b}\n" for v,(op,a,b) in trace.items())
    command=[str(exe),"98","1",str(width),".19",".34","0","0",str(seed),str(mode)]
    run=subprocess.run(command,input=data,text=True,capture_output=True)
    if run.returncode:raise RuntimeError(f"{p.id}: native exit {run.returncode}: {run.stderr[:300]}")
    lines=iter(run.stdout.splitlines())
    pid,n=next(lines).split()
    if pid!=p.id:raise ValueError("unexpected planner header")
    g={}
    for _ in range(int(n)):
        v,op,a,b=next(lines).split()
        g[int(v)]=(op,int(a),int(b))
    if next(lines,None) is not None:raise ValueError("trailing planner data")
    return g


@dataclass
class Route:
    graph: dict
    leaves: set


@lru_cache(maxsize=4096)
def factors(value):
    small=[i for i in range(2,min(isqrt(value),512)+1) if value%i==0]
    return tuple(sorted(set(small[:9]+[value//i for i in small[:9]])))


def routes(p,model):
    derived={v:(op,a,b) for v,op,a,b in model.get("derived",())}
    grouped=defaultdict(list)
    items=(*model["targets"],*model.get("alternatives",()))
    expanded=model.get("multi_stage",False)
    for item in items:
        t,a,b,k,r=(item[x] for x in ("t","a","b","k","r"))
        if t!=a*b*k+r or t not in p.targets: raise ValueError((p.id,item))
        grouped[a*b].append((k,r,t))
    result={}
    for item in items:
        t,a,b,k,r=(item[x] for x in ("t","a","b","k","r"))
        prod=a*b
        if prod>p.limit:continue
        origins=[(1,0,prod)]
        origins.extend((q,d,x) for q,d,x in grouped[prod] if x<t and k%q==0)
        options=result.setdefault(t,{})
        for q,d,x in origins:
            m=k//q
            gap=t-m*x
            if m<1:continue
            rounded=(2*gap+m)//(2*m)
            shifts={0,rounded,rounded-1,rounded+1,gap//m}
            if abs(gap)<8192:shifts.update((-2,-1,1,2))
            for k2,r2,t2 in grouped[prod]:
                if k2==q and abs(r2-d)<4096:shifts.add(r2-d)
                elif expanded and k2%q==0:
                    ratio=k2//q
                    other=(2*r2+ratio)//(2*ratio)-d
                    if abs(other-rounded)<=64:shifts.add(other)
            for s in shifts:
                shifted=x+s
                multiple=shifted*m
                if min(shifted,multiple)<=0 or max(shifted,multiple)>p.limit:continue
                error=t-multiple
                if max(abs(s),abs(error),m)>p.limit:continue
                g={}
                leaves=set()
                if x==prod:
                    def build(v):
                        if v in g:return
                        if v not in derived:
                            leaves.add(v);return
                        symbol,left,right=derived[v]
                        build(left);build(right);g[v]=(symbol,left,right)
                    if prod in derived or prod in (a,b):build(prod)
                    else:
                        build(a);build(b)
                        g[prod]=('*',a,b)
                if s:
                    if shifted==t and m!=1:continue
                    g[shifted]=('+' if s>0 else '-',x,abs(s));leaves.add(abs(s))
                if expanded and m>=4 and abs(s-rounded)<=1 and x==prod:
                    # Insert a correction between consecutive multiplications.
                    for outer in factors(m):
                        inner=m//outer
                        mid0=shifted*inner
                        if not 0<mid0<=p.limit:continue
                        adjust=(2*error+outer)//(2*outer)
                        for u in (adjust,adjust-1,adjust+1):
                            mid=mid0+u
                            last=mid*outer;tail=t-last
                            if u==0 or not 0<mid<=p.limit or not 0<last<=p.limit:continue
                            temp=g.copy();uses=leaves|{inner,outer,abs(u)}
                            temp[mid0]=('*',shifted,inner)
                            temp[mid]=('+' if u>0 else '-',mid0,abs(u))
                            temp[last]=('*',mid,outer)
                            if tail:
                                temp[t]=('+' if tail>0 else '-',last,abs(tail));uses.add(abs(tail))
                            if any(v in e[1:] for v,e in temp.items()):continue
                            key=tuple(sorted(temp.items()))
                            options[key]=Route(temp,uses)
                if m!=1:
                    g[multiple]=('*',shifted,m);leaves.add(m)
                if error:
                    g[t]=('+' if error>0 else '-',multiple,abs(error));leaves.add(abs(error))
                if t not in g and x!=t:continue
                if any(v in e[1:] for v,e in g.items()):continue
                signature=tuple(sorted(g.items()))
                options[signature]=Route(g,leaves)
    if not expanded:return {t:list(choices.values()) for t,choices in result.items()}
    popularity=Counter()
    for choices in result.values():
        members=set()
        for route in choices.values():members.update(route.graph);members.update(route.leaves)
        popularity.update(members)
    output={}
    for t,choices in result.items():
        def rank(route):
            fixed=sum(1/(min(8,popularity[v])**.33) for v in route.graph)
            ingredients=sum((1.0+max(0,log2(v)-2)/5)/min(8,popularity[v])**.42
                            for v in route.leaves if v not in p.seeds)
            return fixed+ingredients
        output[t]=sorted(choices.values(),key=rank)[:140]
    return output


def choose(options,p,seeds,trial,cost_hint=None,integer_choices=False):
    # Prefer shared centers and constants. Values in a table cell are distinct
    # from their small multipliers and errors, which have to be built as well.
    rng=random.Random(trial)
    cost={}
    seeds=set(seeds)
    for t,opts in options.items():
        for route in opts:
            for v in route.leaves:
                cost[v]=0 if v in seeds else (cost_hint or {}).get(v,1.0+max(0,log2(v)-3)/6)
            for v in route.graph:
                if v not in cost:cost[v]=0.0 if v in seeds else 1.0
    opts={t:[(route,set(route.graph)|route.leaves) for route in rs] for t,rs in options.items() if rs}
    counts=Counter()
    selected={}
    targets=list(opts)
    for _ in range(8):
        rng.shuffle(targets)
        changed=False
        for t in targets:
            old=selected.get(t)
            if old is not None:counts.subtract(old[1])
            winner=min(opts[t],key=lambda pair:sum(cost[x] for x in pair[1] if not counts[x])
                       +rng.random()*0.045)
            counts.update(winner[1]);selected[t]=winner
            if winner!=old:changed=True
        if not changed:break
    if integer_choices and selected:
        from matrix_menu import coordinate
        selected=coordinate(opts,selected,cost,trial)
    graph={};leaves=set()
    for t in sorted(selected):
        route=selected[t][0]
        for v,e in route.graph.items():graph.setdefault(v,e)
        leaves.update(route.leaves)
    return graph,leaves-set(graph)


def solve(p,model,exe,variants,starting):
    rng=random.Random(int(p.id.split("_")[-1]))
    all_hubs=tuple(model["hubs"])
    options=routes(p,model)
    products={v:(op,a,b) for v,op,a,b in model.get("derived",())}
    for e in (*model["targets"],*model.get("alternatives",())):
        v=e["a"]*e["b"]
        if v<=p.limit and v not in (e["a"],e["b"]):products.setdefault(v,('*',e["a"],e["b"]))
    best=starting
    fresh=None
    outcomes=[]
    for i in range(variants):
        mode=(77,2637,13,589,2125,77)[i%6]
        if model.get("multi_stage"):
            _,provisional=choose(options,p,p.seeds,i)
            hubs=tuple(h for h in all_hubs if h in provisional)
        else:hubs=all_hubs
        header=native(p,p.seeds,hubs,exe,mode,7+i%3,rng.randrange(1<<20))
        header=active_graph(p,header,hubs)
        def evaluate(g):
            nonlocal best,fresh
            try: selected=active_graph(p,g)
            except (KeyError,ValueError):return None
            if fresh is not None and len(selected)>=len(fresh):return len(selected)
            candidate=compile_graph(p,g,attempts=6,recompute=True,schedule_width=12)
            if candidate is None:return None
            check(p,candidate)
            if fresh is None or len(candidate)<len(fresh):fresh=candidate
            if len(candidate)<len(best):best=candidate
            return len(candidate)
        small=(*p.seeds,*header)
        macro,required=choose(options,p,small,i+len(header),integer_choices=model.get("integer_choices",False))
        # Make the paid ingredients available to a new search over the complete
        # target set. Unused prospective helpers are removed after synthesis.
        ingredient_set=set(required)|set(hubs)
        if i%3==0:
            g=dict(header)
            corrections=native(p,small,sorted(required),exe,mode,6,rng.randrange(1<<20))
        elif i%3==1:
            g={}
            corrections=native(p,p.seeds,sorted(ingredient_set),exe,mode,8,rng.randrange(1<<20))
        else:
            # Coefficients learned from target offsets can also occur in the
            # construction of the hidden bases. Let them be computed first.
            g=native(p,p.seeds,sorted(required-set(hubs)),exe,mode,7,rng.randrange(1<<20))
            g=active_graph(p,g,required-set(hubs))
            corrections=native(p,(*p.seeds,*g),hubs,exe,mode,8,rng.randrange(1<<20))
        for v,e in corrections.items():g.setdefault(v,e)
        # The subproblem used a virtual collection of starting values. Trace the
        # actually required part on the original seeds before pooling helpers.
        g=active_graph(p,g,ingredient_set)
        for v,e in macro.items():g.setdefault(v,e)
        missing=[t for t in p.targets if t not in g and t not in p.seeds]
        if missing:
            extra=native(p,(*p.seeds,*g),missing,exe,mode,6,rng.randrange(1<<20))
            for v,e in extra.items():g.setdefault(v,e)
        canonical=evaluate(g)
        if i%2==0 and not model.get("multi_stage"):
            scaffold=dict(header)
            for v,e in products.items():scaffold.setdefault(v,e)
        else:
            scaffold=active_graph(p,g,ingredient_set)
            available=set(scaffold)|set(p.seeds)
            for v,e in products.items():
                if e[1] in available and e[2] in available:
                    scaffold.setdefault(v,e);available.add(v)
            if model.get("multi_stage"):
                usage=Counter(w for _,a,b in macro.values() for w in {a,b})
                for v,e in g.items():
                    if v not in p.targets and e[1] in available and e[2] in available and usage[v]>=2:
                        scaffold.setdefault(v,e);available.add(v)
        # Include the previous pass's best small constants, then synthesize all
        # target branches with no fixed choice of matrix cell or multiplier.
        body=native(p,(*p.seeds,*scaffold),p.targets,exe,mode,7,rng.randrange(1<<20))
        for v,e in body.items():scaffold.setdefault(v,e)
        virtual=evaluate(scaffold)
        outcomes.append((canonical,virtual))
    return p.id,best,fresh,outcomes


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("models",type=Path)
    ap.add_argument("output",type=Path)
    ap.add_argument("--incumbent",type=Path,default=Path("submission.csv"))
    ap.add_argument("--exe",type=Path,default=Path("work/virtual/planner-powers.exe"))
    ap.add_argument("--rows",type=int,default=0)
    ap.add_argument("--variants",type=int,default=4)
    ap.add_argument("--workers",type=int,default=3)
    ap.add_argument("--coverage",type=float,default=0)
    ap.add_argument("--minimum",type=int,default=2)
    ap.add_argument("--anchored",action="store_true")
    ap.add_argument("--donor",type=Path,action="append",default=[])
    a=ap.parse_args()
    puzzles=read_puzzles(Path("data/puzzles.csv"));byid={p.id:p for p in puzzles}
    orig=read_submission(a.incumbent)
    extra_donors=[read_submission(path) for path in a.donor]
    models=[json.loads(line) for line in a.models.read_text(encoding="utf8").splitlines() if line.strip()]
    models=[m for m in models if len(m["targets"])>=a.minimum and m["hubs"] and
            len(m["targets"])>=a.coverage*len(byid[m["id"]].targets)]
    models.sort(key=lambda m:(-len(m["targets"])/len(byid[m["id"]].targets),-len(m["targets"]),m["id"]))
    if a.rows:models=models[:a.rows]
    if not models:raise ValueError("no model rows")
    raw={};gains=0
    db=sqlite3.connect(a.output.with_suffix(".sqlite"))
    db.execute("CREATE TABLE IF NOT EXISTS rows (id TEXT, digest TEXT, candidate TEXT, PRIMARY KEY(id,digest))")
    config=sha256(a.exe)+sha256(Path(__file__))+str(a.variants)
    if a.anchored:
        from matrix_anchor import solve_anchor
        config+=sha256(Path(__file__).with_name("matrix_anchor.py"))
    with ProcessPoolExecutor(a.workers) as pool:
        tasks={}
        for m in models:
            pid=m["id"]
            extra=tuple(z[pid] for z in extra_donors if pid in z)
            context=repr((orig[pid],extra)) if a.anchored else ""
            digest=hashlib.sha256((json.dumps(m,sort_keys=True)+config+context).encode()).hexdigest()
            prior=db.execute("SELECT candidate FROM rows WHERE id=? AND digest=?",(pid,digest)).fetchone()
            if prior:
                candidate=tuple(map(tuple,json.loads(prior[0])))
                check(byid[pid],candidate);raw[pid]=candidate
                gains+=max(0,len(orig[pid])-len(candidate));continue
            if a.anchored:task=pool.submit(solve_anchor,byid[pid],m,a.exe.resolve(),a.variants,orig[pid],extra)
            else:task=pool.submit(solve,byid[pid],m,a.exe.resolve(),a.variants,orig[pid])
            tasks[task]=digest
        for task in as_completed(tasks):
            pid,best,candidate,info=task.result()
            if candidate is None:continue
            raw[pid]=candidate;gains+=len(orig[pid])-len(best)
            db.execute("INSERT OR REPLACE INTO rows VALUES (?,?,?)",(pid,tasks[task],json.dumps(candidate,separators=(",",":"))))
            db.commit()
            if len(models)<=8:print(pid,len(orig[pid]),len(candidate),info,flush=True)
            if len(raw)%10==0 or len(models)<=8:
                write_submission(a.output,[p for p in puzzles if p.id in raw],raw)
                print(f"{len(raw)}/{len(models)}, portfolio saves {gains}",flush=True)
    if raw:write_submission(a.output,[p for p in puzzles if p.id in raw],raw)
    db.close()
    print(f"{len(raw)} raw rows, {gains} fewer instructions than the incumbent on winning rows")


if __name__=="__main__":
    main()
