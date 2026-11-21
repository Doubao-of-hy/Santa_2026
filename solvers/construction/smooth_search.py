"""Rebuild private arithmetic cones around a complete interval of candidate products."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
import json
from pathlib import Path
import random
import subprocess
import time

from elf import check, read_puzzles, read_submission, sha256
from graph import active_graph, compile_graph, first_recipes


def cones(puzzle, original, count, order="size", skip=0):
    graph=active_graph(puzzle,original)
    users=Counter(arg for _,a,b in graph.values() for arg in {a,b})
    goals=set(puzzle.targets)
    cases=[]
    for pivot in graph:
        if pivot<32: continue
        retained=set()
        stack=list(goals)
        while stack:
            v=stack.pop()
            if v==pivot or v in retained or v not in graph:continue
            retained.add(v)
            stack.extend(graph[v][1:])
        removed=len(graph)-len(retained)
        if removed<3:continue
        free=set(puzzle.seeds)
        for v,(_,a,b) in graph.items():
            if v in retained and a in free and b in free:free.add(v)
        # Prefer externally reused inputs when a one-operation value has many recipes.
        atoms=sorted(free,key=lambda x:(x not in puzzle.seeds,-users[x],x))
        merit=removed + 1.0*(pivot in goals)+min(2,users[pivot]*0.3)
        cases.append((merit,pivot,removed,atoms))
    ranked=sorted(cases,reverse=True)[skip:]
    if order=="density":
        # A large removable branch helps, and exact matches become more likely
        # when a candidate integer occupies fewer bits.
        ranked.sort(key=lambda x: (12*x[2]-max(24,x[1].bit_length()),x[0]),reverse=True)
    return ranked[:count]


def apply_patches(p,baseline,raw,patches):
    working=raw
    best=baseline
    for gain,pivot,patch in sorted(patches,key=lambda x:-x[0]):
        try:
            new=active_graph(p,working|patch)
        except (KeyError,ValueError):
            continue
        if len(new)>=len(best):continue
        # Preserve the incumbent's relative order whenever the new dependencies allow it.
        order=tuple(x for x in raw if x in new)+p.targets
        timed=active_graph(p,new,order)
        for dag in (timed,new):
            prog=compile_graph(p,dag,recompute=True,schedule_width=6)
            if prog is not None and len(prog)<len(best):
                best=prog
                working=dag
                if len(prog)==len(new):break
    check(p,best)
    return best


def optimize(p,baseline,exe,radius,bound,centers,cuts,hubs=False,cut_order="size",skip_cuts=0,
             bank_exe=None,alternatives=12,slack=1,connect=False,component_seconds=0):
    raw=first_recipes(p,baseline)
    regions=cones(p,raw,cuts,cut_order,skip_cuts)
    if not regions: return p.id,baseline,0,0
    if hubs:
        live=active_graph(p,raw)
        roots=list(dict.fromkeys((*p.targets,*(v for _,v,_,_ in regions[:14]))))
        roots=[v for v in roots if v>=4096][:60]
        if len(roots)<2:return p.id,baseline,0,0
        lines=[" ".join(map(str,(p.limit,len(p.seeds),len(p.targets),len(roots),len(live),
                                *p.seeds,*p.targets,*roots)))]
        lines.extend(f"{v} {op} {a} {b}" for v,(op,a,b) in raw.items() if v in live)
        inp="\n".join(lines)+"\n"
        options=[str(radius),str(cuts)]
    else:
        extra_budget=slack+1 if bank_exe else 0
        inp="".join(" ".join(map(str,(p.limit,pivot,budget+extra_budget,len(atoms),*atoms)))+"\n"
                    for _,pivot,budget,atoms in regions)
        options=[str(radius),str(bound),str(centers)]
        if bank_exe:options.append(str(alternatives))
    result=subprocess.run([exe,*options],input=inp,capture_output=True,encoding="ascii")
    if result.returncode: raise RuntimeError(f"{p.id}: {result.returncode} {result.stderr}")
    stream=iter(result.stdout.splitlines())
    def read_graph(n):
        graph={}
        for _ in range(n):
            v,op,a,b=next(stream).split()
            graph[int(v)]=op,int(a),int(b)
        return graph
    patches=[]
    if hubs:
        tested,count=map(int,next(stream).split())
        for _ in range(count):
            gain,n=map(int,next(stream).split())
            patches.append((gain,0,read_graph(n)))
    else:
        tested=len(regions)
        for _,pivot,budget,_ in regions:
            root,count=map(int,next(stream).split())
            if root!=pivot:raise ValueError("misaligned pivot")
            for _ in range(count):
                n=int(next(stream))
                patches.append((budget-n,pivot,read_graph(n)))
    if next(stream,None) is not None:raise ValueError("trailing patch")
    if bank_exe and patches:
        import sys
        sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"generative"))
        from shrink_select import run_one
        strict=apply_patches(p,baseline,raw,[q for q in patches if q[0]>0])
        _,result,_=run_one(p,[baseline,strict],None,bank_exe,85,0,[q[2] for q in patches],
                          connect,component_seconds)
        return p.id,result,tested,len(patches)
    return p.id,apply_patches(p,baseline,raw,patches),tested,len(patches)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for key in ("puzzles","input","output"):ap.add_argument(key,type=Path)
    ap.add_argument("--exe",type=Path,default=Path("work/creative/smooth.exe"))
    ap.add_argument("--ids",type=Path)
    ap.add_argument("--structured",action="store_true")
    ap.add_argument("--hubs",action="store_true")
    ap.add_argument("--cut-order",choices=("size","density"),default="size")
    ap.add_argument("--skip-cuts",type=int,default=0)
    ap.add_argument("--bank-exe",type=Path)
    ap.add_argument("--alternatives",type=int,default=12)
    ap.add_argument("--slack",type=int,default=1)
    ap.add_argument("--connect-helpers",action="store_true")
    ap.add_argument("--component-seconds",type=float,default=0)
    for k,d in (("radius",1536),("bound",541),("centers",48),("cuts",20),
                ("rows",0),("jobs",2),("seed",105)):
        ap.add_argument("--"+k,type=int,default=d)
    a=ap.parse_args()
    data=read_puzzles(a.puzzles)
    incumbent=read_submission(a.input)
    if a.structured:data=[p for p in data if max(p.seeds)<=35 and len(p.targets)>=6]
    random.Random(a.seed).shuffle(data)
    if a.ids:
        ids=set(a.ids.read_text().split())
        data=[p for p in data if p.id in ids]
    if a.rows:data=data[:a.rows]
    if not data:raise ValueError("no input rows")
    stored=read_submission(a.output) if a.output.exists() else {}
    sig=a.output.with_suffix(".settings.json")
    config=dict(input=sha256(a.input),exe=sha256(a.exe),radius=a.radius,bound=a.bound,
                centers=a.centers,cuts=a.cuts)
    if a.hubs:config["hubs"]=True
    if a.cut_order!="size":config["cut_order"]=a.cut_order
    if a.skip_cuts:config["skip_cuts"]=a.skip_cuts
    if a.bank_exe:
        if a.hubs or a.slack<0 or a.alternatives<1:raise ValueError("invalid patch bank options")
        config.update(bank=sha256(a.bank_exe),alternatives=a.alternatives,slack=a.slack)
        if a.connect_helpers:
            config.update(connect_helpers=sha256(Path(__file__).parents[2]/"generative"/"shrink_select.py"))
        if a.component_seconds:
            config.update(component_seconds=a.component_seconds)
    elif a.connect_helpers or a.component_seconds:raise ValueError("joint solving requires --bank-exe")
    if stored and config!=json.loads(sig.read_text()):raise ValueError("checkpoint mismatch")
    sig.write_text(json.dumps(config),encoding="utf8")
    rows={p.id:p for p in data}
    for pid,program in stored.items():check(rows[pid],program)
    tasks=[p for p in data if p.id not in stored]
    before=time.monotonic()
    gain=sum(len(incumbent[pid])-len(program) for pid,program in stored.items())
    tested=patches=0
    with a.output.open("a",encoding="utf8",newline="") as stream,ProcessPoolExecutor(a.jobs) as pool:
        out=csv.writer(stream,lineterminator="\n")
        if not stream.tell():out.writerow(("id","program"))
        futures=[pool.submit(optimize,p,incumbent[p.id],str(a.exe.resolve()),a.radius,
                             a.bound,a.centers,a.cuts,a.hubs,a.cut_order,a.skip_cuts,
                             str(a.bank_exe.resolve()) if a.bank_exe else None,
                             a.alternatives,a.slack,a.connect_helpers,a.component_seconds) for p in tasks]
        for i,job in enumerate(as_completed(futures),len(stored)+1):
            pid,program,regions,variants=job.result()
            gain+=len(incumbent[pid])-len(program)
            out.writerow((pid,json.dumps(program,separators=(",",":"))));stream.flush()
            tested+=regions;patches+=variants
            if i%8==0 or i==len(data):
                print(f"{i}/{len(data)} gain {gain}, {patches} variants/{tested} cuts, "
                      f"{time.monotonic()-before:.1f}s",flush=True)


if __name__=="__main__":main()
