"""Use recovered multiplication tables to reconstruct complete register programs."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
import json
from pathlib import Path
import subprocess
import time

from elf import check, read_puzzles, read_submission, sha256
from graph import active_graph, compile_graph, first_recipes


def solve(p,incumbent,model,exe,attempts,donors=()):
    raw=first_recipes(p,incumbent)
    targets=[*model["targets"],*model.get("alternatives",())]
    lines=[" ".join(map(str,(p.limit,len(p.seeds),len(p.targets),len(targets),*p.seeds,*p.targets))),str(len(raw))]
    lines.extend(f"{v} {op} {a} {b}" for v,(op,a,b) in raw.items())
    derived=model.get("derived",())
    lines.append(str(len(donors)+bool(derived)))
    for other in donors:
        trace=first_recipes(p,other)
        lines.append(str(len(trace)))
        lines.extend(f"{v} {op} {a} {b}" for v,(op,a,b) in trace.items())
    if derived:
        lines.append(str(len(derived)))
        lines.extend(f"{v} {op} {a} {b}" for v,op,a,b in derived)
    lines.extend(" ".join(str(z[k]) for k in ("t","a","b","k","r","d","e")) for z in targets)
    hubs=model.get("hubs",[])
    lines.append(" ".join(map(str,(len(hubs),*hubs))))
    proc=subprocess.run([exe,str(attempts),str(491+int(p.id.split("_")[-1]))],
                        input="\n".join(lines)+"\n",capture_output=True,text=True)
    if proc.returncode:raise RuntimeError(f"{p.id}: {proc.returncode} {proc.stderr}")
    it=iter(proc.stdout.splitlines())
    variants=int(next(it))
    best=incumbent
    for _ in range(variants):
        graph={}
        for _ in range(int(next(it))):
            v,op,a,b=next(it).split()
            graph[int(v)]=op,int(a),int(b)
        if len(graph)>=len(best):continue
        timeline=active_graph(p,graph,tuple(x for x in raw if x in graph)+p.targets)
        for candidate in (timeline,graph):
            physical=compile_graph(p,candidate,attempts=6,recompute=True,schedule_width=12)
            if physical is not None and len(physical)<len(best):best=physical
            if len(best)==len(graph):break
    if next(it,None) is not None:raise ValueError("extra matrix plans")
    check(p,best)
    return p.id,best,variants


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for key in ("puzzles","input","models","output"):ap.add_argument(key,type=Path)
    ap.add_argument("--exe",type=Path,default=Path("work/creative/matrix-network.exe"))
    ap.add_argument("--ids",type=Path)
    ap.add_argument("--donor",type=Path,action="append",default=[])
    ap.add_argument("--extra-model",type=Path,action="append",default=[])
    for key,default in (("rows",0),("attempts",4),("jobs",2)):
        ap.add_argument("--"+key,type=int,default=default)
    a=ap.parse_args()
    puzzles={p.id:p for p in read_puzzles(a.puzzles)}
    baseline=read_submission(a.input)
    models=[m for m in (json.loads(l) for l in a.models.read_text().splitlines()) if m["hubs"]]
    merged={m["id"]:m for m in models}
    for path in a.extra_model:
        for line in path.read_text().splitlines():
            m=json.loads(line)
            if not m["hubs"]:continue
            if m["id"] not in merged:merged[m["id"]]=m;continue
            base=merged[m["id"]]
            existing={(z["t"],z["a"],z["b"],z["k"]) for z in base["targets"]}
            base["targets"].extend(z for z in m["targets"] if (z["t"],z["a"],z["b"],z["k"]) not in existing)
    models=list(merged.values())
    models.sort(key=lambda m:(len(m["targets"])/m["total"],m.get("fit",0)),reverse=True)
    if a.ids:
        ids=set(a.ids.read_text().split());models=[m for m in models if m["id"] in ids]
    if a.rows:models=models[:a.rows]
    sig=a.output.with_suffix(".settings.json")
    settings=dict(exe=sha256(a.exe),input=sha256(a.input),models=sha256(a.models),attempts=a.attempts,
                  donors=[sha256(d) for d in a.donor],extra=[sha256(v) for v in a.extra_model])
    pools=[read_submission(d) for d in a.donor]
    stored=read_submission(a.output) if a.output.exists() else {}
    if stored and json.loads(sig.read_text())!=settings:raise ValueError("incompatible checkpoint")
    sig.write_text(json.dumps(settings),encoding="utf8")
    todo=[m for m in models if m["id"] not in stored]
    start=time.monotonic()
    length=sum(len(baseline[k])-len(v) for k,v in stored.items())
    winning=sum(len(baseline[k])>len(v) for k,v in stored.items())
    with a.output.open("a",newline="",encoding="utf8") as f,ProcessPoolExecutor(a.jobs) as pool:
        out=csv.writer(f,lineterminator="\n")
        if not f.tell():out.writerow(("id","program"))
        pending=[pool.submit(solve,puzzles[m["id"]],baseline[m["id"]],m,
                             str(a.exe.resolve()),a.attempts,
                             tuple(dict.fromkeys(d[m["id"]] for d in pools if m["id"] in d and
                                                 d[m["id"]]!=baseline[m["id"]]))) for m in todo]
        for i,task in enumerate(as_completed(pending),len(stored)+1):
            k,program,_=task.result()
            gain=len(baseline[k])-len(program);length+=gain;winning+=gain>0
            out.writerow((k,json.dumps(program,separators=(",",":"))));f.flush()
            if i%15==0 or i==len(models):print(f"{i}/{len(models)} saved {length} on {winning}, "
                                                f"{time.monotonic()-start:.1f}s",flush=True)


if __name__=="__main__":main()
