"""Select compatible matrix recipes by solving local integer constraints."""
import argparse
from collections import Counter,defaultdict
from concurrent.futures import ProcessPoolExecutor,as_completed
import csv
import json
from pathlib import Path
import subprocess
import time

from crossover_lns import build_model_bank,load_solver
from elf import check,read_puzzles,read_submission,sha256
from graph import active_graph,compile_graph,first_recipes


def select(p,graph,bank,available,retained,wanted,incumbent,seconds):
    ceiling=len(incumbent)-1-len(retained)
    if ceiling<len(wanted):return incumbent
    cp=load_solver();model=cp.CpModel()
    use={x:model.new_bool_var("") for x in bank}
    when={x:model.new_int_var(0,ceiling,"") for x in bank}
    edges=[]
    prior=set(graph)-set(retained)
    for v,recipes in bank.items():
        pick=[]
        model.add_hint(use[v],int(v in prior))
        for r in recipes:
            y=model.new_bool_var("");pick.append(y);edges.append((y,v,r))
            model.add_hint(y,int(v in prior and graph[v]==r))
            for u in set(r[1:])-available:
                model.add_implication(y,use[u])
                model.add(when[u]<when[v]).only_enforce_if(y)
        model.add(sum(pick)==use[v])
    for x in wanted:model.add(use[x]==1)
    cost=sum(use.values());model.add(cost<=ceiling);model.minimize(cost)
    solver=cp.CpSolver();solver.parameters.num_search_workers=1
    solver.parameters.max_time_in_seconds=seconds
    solver.parameters.max_presolve_iterations=2
    status=solver.solve(model)
    if status not in (cp.OPTIMAL,cp.FEASIBLE):return incumbent
    fresh=dict(retained)
    for bit,v,r in edges:
        if solver.value(bit):fresh[v]=r
    active=active_graph(p,fresh)
    order=tuple(x for x in graph if x in active)+p.targets
    original=active_graph(p,active,order)
    best=incumbent
    for variant in (original,active):
        physical=compile_graph(p,variant,recompute=True,schedule_width=12)
        if physical is not None and len(physical)<len(best):best=physical
        if len(best)==len(active):break
    return best


def optimize(p,original,models,exe,windows,seconds,cap):
    src=first_recipes(p,original)
    lines=[" ".join(map(str,(p.limit,len(p.seeds),len(p.targets),len(models),*p.seeds,*p.targets))),str(len(src))]
    lines.extend(f"{v} {op} {a} {b}" for v,(op,a,b) in src.items());lines.append("0")
    lines.extend(" ".join(str(z[k]) for k in ("t","a","b","k","r","d","e")) for z in models)
    proc=subprocess.run([exe,"-1","13"],input="\n".join(lines)+"\n",capture_output=True,text=True)
    if proc.returncode:raise RuntimeError(f"{p.id}: {proc.returncode} {proc.stderr}")
    it=iter(proc.stdout.splitlines());ne,ng=map(int,next(it).split());bank=defaultdict(set)
    for _ in range(ne):
        v,op,a,b=next(it).split();bank[int(v)].add((op,int(a),int(b)))
    groups=[]
    for _ in range(ng):
        _,*wanted=map(int,next(it).split());group=frozenset(wanted)
        if group:groups.append(group)
    if next(it,None) is not None:raise ValueError("trailing data")
    goals=set(p.targets);seeds=set(p.seeds);live=active_graph(p,src)
    def window(group):
        fixed=active_graph(p,live,goals-group)
        wanted=group-fixed.keys()-seeds
        return fixed,wanted
    candidate=[]
    for group in set(groups):
        fixed,want=window(group)
        if not want:continue
        slack=len(live)-len(fixed)-len(want)
        if slack<1:continue
        # Most small windows solve in presolve. Reserve space for a whole-table trial.
        priority=(slack/(1+len(want))**.4)*(1.16 if 2<=len(want)<=8 else 1)
        candidate.append((priority,group))
    candidate.sort(key=lambda c:-c[0])
    choices=[]
    for _,group in candidate:
        if len(choices)>=windows:break
        if any(len(group&v)>.85*max(len(group),len(v)) for v in choices):continue
        choices.append(group)
    best=original;done=0
    for group in choices:
        fixed,wanted=window(group)
        if not wanted:continue
        local,available=build_model_bank(p,bank,live,tuple(wanted),set(fixed),set(),0,cap,False)
        if wanted-local.keys():continue
        prog=select(p,live,local,available,fixed,wanted,best,seconds)
        done+=1
        if len(prog)<len(best):
            best=prog;live=active_graph(p,first_recipes(p,best))
    check(p,best)
    return p.id,best,done


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ("data","input","output","models"):ap.add_argument(name,type=Path)
    ap.add_argument("--extra",type=Path,action="append",default=[])
    ap.add_argument("--exe",type=Path,default=Path("work/creative/matrix-recipes.exe"))
    ap.add_argument("--seconds",type=float,default=.35)
    for key,d in (("windows",5),("limit",600),("jobs",2),("rows",0)):
        ap.add_argument("--"+key,type=int,default=d)
    a=ap.parse_args()
    pp=read_puzzles(a.data);base=read_submission(a.input);merged=defaultdict(dict);strength=Counter()
    for path in [a.models,*a.extra]:
        for line in path.read_text().splitlines():
            m=json.loads(line);pid=m["id"];strength[pid]=max(strength[pid],m["fit"])
            for z in m["targets"]:merged[pid][z["t"],z["a"],z["b"],z["k"]]=z
    pp=sorted((p for p in pp if merged.get(p.id)),key=lambda p:-strength[p.id])
    if a.rows:pp=pp[:a.rows]
    settings=dict(exe=sha256(a.exe),base=sha256(a.input),models=[sha256(x) for x in [a.models,*a.extra]],
                  seconds=a.seconds,windows=a.windows,limit=a.limit)
    sig=a.output.with_suffix(".settings.json");stored=read_submission(a.output) if a.output.exists() else {}
    if stored and settings!=json.loads(sig.read_text()):raise ValueError("settings mismatch")
    sig.write_text(json.dumps(settings),encoding="utf8")
    total=sum(len(base[k])-len(v) for k,v in stored.items());start=time.monotonic()
    with a.output.open("a",encoding="utf8",newline="") as stream,ProcessPoolExecutor(a.jobs) as pool:
        writer=csv.writer(stream,lineterminator="\n")
        if not stream.tell():writer.writerow(("id","program"))
        jobs=[pool.submit(optimize,p,base[p.id],list(merged[p.id].values()),str(a.exe.resolve()),
                          a.windows,a.seconds,a.limit) for p in pp if p.id not in stored]
        for i,j in enumerate(as_completed(jobs),len(stored)+1):
            k,new,_=j.result();total+=len(base[k])-len(new)
            writer.writerow((k,json.dumps(new,separators=(",",":"))));stream.flush()
            if i%10==0 or i==len(pp):print(f"{i}/{len(pp)} saved {total}, {time.monotonic()-start:.1f}s",flush=True)


if __name__=="__main__":main()
