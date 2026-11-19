"""Test short seed- and peer-derived arithmetic for recovered matrix hubs."""
import argparse
from collections import Counter,defaultdict
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import random
import subprocess

from run_source import ROOT
from elf import read_puzzles


def neighbors(value,excluded,rng):
    radius=max(4,value//12);matches=[]
    while len(matches)<3:
        x=rng.randint(max(2,value-radius),value+radius)
        if x not in excluded and x not in matches:matches.append(x)
    return matches


def calculate(exe,p,queries):
    lines=[];metadata=[]
    for label,roots,depth,wanted in queries:
        distinct=tuple(dict.fromkeys(v for v,_,_ in wanted))
        lines.append(" ".join(map(str,(p.limit,len(roots),len(distinct),depth,*roots,*distinct))))
        metadata.append((label,set(roots),wanted,distinct))
    run=subprocess.run([str(exe)],input="\n".join(lines)+"\n",capture_output=True,text=True,check=True)
    stream=iter(run.stdout.splitlines());output=[]
    for label,roots,requested,distinct in metadata:
        solutions={}
        for t in distinct:
            value,length,*other=next(stream).split()
            if int(value)!=t or len(other)!=4*max(0,int(length)):raise ValueError("invalid native output")
            available=set(roots);tape=[]
            for i in range(0,len(other),4):
                w,op,a,b=other[i:i+4];w,a,b=int(w),int(a),int(b)
                expect=a+b if op=="+" else a-b if op=="-" else a*b if op=="*" else a//b
                if min(w,a,b)<=0 or max(w,a,b)>p.limit or a not in available or b not in available or expect!=w or (op=="/" and a%b):raise ValueError("invalid recovered route")
                available.add(w);tape.append((w,op,a,b))
            if int(length)>=0 and t not in available:raise ValueError("unreached hub")
            solutions[t]=(int(length),tape)
        output.extend((label,t,real,h,*solutions[t]) for t,real,h in requested)
    if next(stream,None) is not None:raise ValueError("unexpected extra output")
    return output


def job(arg):
    p,model,foreign,exe,peer_depth=arg
    uses=Counter()
    for row in model["targets"]:
        uses.update({row["a"],row["b"]})
    hubs=[v for v in model["hubs"] if v>=32 and uses[v]>=2 and v not in p.seeds]
    rng=random.Random(31011+int(p.id.rsplit("_",1)[-1]))
    exclude=set(hubs)|set(p.seeds)
    query={h:[(h,True,h)]+[(c,False,h) for c in neighbors(h,exclude,rng)] for h in hubs}
    all_items=[x for values in query.values() for x in values]
    queries=[("seeds",p.seeds,4,all_items),("matched_seeds",foreign,4,all_items)]
    for h in hubs:
        others=sorted((v for v in hubs if v!=h),key=lambda v:(abs(v.bit_length()-h.bit_length()),-uses[v],v))
        if others:queries.append(("peers",(*p.seeds,*others[:3]),peer_depth,query[h]))
    return p.id,calculate(exe,p,queries)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("puzzles",type=Path);ap.add_argument("models",type=Path)
    ap.add_argument("output",type=Path);ap.add_argument("--exe",required=True,type=Path)
    ap.add_argument("--jobs",type=int,default=2);ap.add_argument("--peer-depth",type=int,default=3)
    ap.add_argument("--rows",type=int,default=0)
    args=ap.parse_args();ps=read_puzzles(args.puzzles);pset={p.id:p for p in ps}
    models=[m for line in args.models.read_text().splitlines() if (m:=json.loads(line))["total"]>=8
            and len(m["hubs"])<=11 and len(m["targets"])>=max(8,.65*m["total"])]
    random.Random(54).shuffle(models)
    if args.rows:models=models[:args.rows]
    tasks=[]
    for model in models:
        p=pset[model["id"]]
        candidates=[q for q in ps if len(q.seeds)==len(p.seeds) and q.seeds!=p.seeds]
        if not candidates:continue
        candidates.sort(key=lambda q:sum(abs(a-b) for a,b in zip(sorted(p.seeds),sorted(q.seeds))))
        foreign=random.Random(int(p.id.rsplit("_",1)[-1])).choice(candidates[:min(7,len(candidates))]).seeds
        tasks.append((p,model,foreign,args.exe.resolve(),args.peer_depth))
    counters=defaultdict(Counter);scales=defaultdict(Counter);details=[]
    with ProcessPoolExecutor(args.jobs) as worker:
        for pid,out in worker.map(job,tasks):
            found=[]
            for label,t,real,h,cost,recipe in out:
                counters[(label,real)][cost]+=1
                scales[(label,real,h.bit_length()//4)][cost]+=1
                if real and cost>=0:found.append(dict(query=label,hub=h,cost=cost,recipe=recipe))
            details.append(dict(id=pid,found=found))
    report={"rows":len(tasks),"peer_depth":args.peer_depth,"histograms":{f"{label} {'real' if real else 'null'}":dict(sorted(counts.items())) for (label,real),counts in counters.items()},"by_4_bit_bins":{f"{label} {'real' if real else 'null'} {group}":dict(sorted(counts.items())) for (label,real,group),counts in scales.items()},"routes":details}
    args.output.write_text(json.dumps(report,separators=(",",":"))+"\n",encoding="utf8")
    print(json.dumps({k:v for k,v in report.items() if k in ("rows","peer_depth","histograms")},indent=2))


if __name__=="__main__":
    main()
