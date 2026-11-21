"""Test several temporary starting values constructed from a single new shared intermediate."""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import csv
import gzip
import io
import json
from pathlib import Path
import subprocess

import compare as borrowed

ROOT=borrowed.ROOT
BASE="99b48016ec3c71d97569e8325e021797f5ac1737"
ROUNDS=400


def archive(name):
    return subprocess.check_output(["git","show",BASE+":"+name],cwd=ROOT)


def frozen(name):
    return {x["id"]:x for x in csv.DictReader(io.StringIO(archive(name).decode("utf-8-sig")))}


def family(p,graph):
    roots=set(p.seeds)
    closure={v:frozenset() for v in roots}
    for v,(_,a,b) in graph.items():
        closure[v]=closure[a]|closure[b]|{v}
    early=list(dict.fromkeys((*p.seeds,*sorted(graph,key=lambda v:(len(closure[v]),v))[:12])))
    universe=roots|set(graph)
    # Score a free value by the number and cost of old outputs that can use it directly.
    uses=defaultdict(dict)
    partners=list(dict.fromkeys((*early,*p.targets)))
    for t in graph:
        if len(closure[t])<3:
            continue
        for a in partners:
            if a==t or t in closure.get(a,()):
                continue
            for v,_ in borrowed.inverse(t,a,p.limit):
                if v not in universe and v!=t:
                    weight=1+min(8,len(closure[t]))+2*(t in p.targets)
                    uses[v][t]=max(uses[v].get(t,0),weight)
    birth={}
    for j,a in enumerate(early):
        for b in early[:j+1]:
            for h,e in borrowed.arithmetic_edges(a,b,p.limit):
                if h in universe:
                    continue
                cost=1+len(closure[a]|closure[b])
                if h not in birth or (cost,e)<birth[h]:
                    birth[h]=(cost,e)
    best=(-1,0,0);result={}
    for h,(cost,e) in birth.items():
        children={}
        for a in early:
            for v,edge in borrowed.arithmetic_edges(h,a,p.limit):
                if v!=h and v not in universe and uses.get(v):
                    children.setdefault(v,edge)
        if len(children)<2:
            continue
        picked={};covered=dict(uses.get(h,{}))
        for _ in range(3):
            remaining=[v for v in children if v not in picked]
            if not remaining:break
            def utility(v):
                gain=sum(max(0,weight-covered.get(t,0)) for t,weight in uses[v].items())
                return (gain,len(uses[v]),-v)
            v=max(remaining,key=utility)
            if utility(v)[0]==0:break
            picked[v]=children[v]
            for t,weight in uses[v].items():covered[t]=max(covered.get(t,0),weight)
        if len(picked)<2:continue
        score=(sum(covered.values())/(cost+len(picked)),len(covered),-h)
        if score>best:
            best=score;result={h:e,**picked}
    return result


def main():
    cp=argparse.ArgumentParser(description=__doc__)
    cp.add_argument("--puzzles",type=Path,required=True);cp.add_argument("--exe",type=Path,required=True)
    cp.add_argument("--out",type=Path,required=True);cp.add_argument("--jobs",type=int,default=6)
    args=cp.parse_args();args.out.mkdir(exist_ok=True,parents=True)
    ps=borrowed.read_puzzles(args.puzzles);pm={q.id:q for q in ps}
    own=frozen("submission.csv");pub=frozen("public-assisted/submission.csv")
    parents={lane:{i:tuple(map(tuple,json.loads(z["program"]))) for i,z in data.items()} for lane,data in [("own",own),("public",pub)]}
    credits={lane:frozen(path+"origins.csv") for lane,path in [("own",""),("public","public-assisted/")]}
    history={}
    for name in ["own-development","own-holdout",*[f"own-expand-{j:02}" for j in range(9)]]:
        history.update(json.loads(gzip.decompress(archive("collaboration/borrowed-starts/results/"+name+".json.gz"))))
    groups={"improved":[],"comparison":[]}
    for i,v in sorted(history.items(),key=lambda kv:borrowed.digest(["nested-starts-1",kv[0]])):
        if not 0<=len(parents["own"][i])-len(parents["public"][i])<=3:continue
        won=min(z["score"] for z in v["arms"].values())<v["arms"]["ordinary"]["before"]
        groups["improved" if won else "comparison"].append(i)
    groups={k:v[:20] for k,v in groups.items()}
    (args.out/"design.json").write_bytes((json.dumps(dict(base=BASE,groups=groups,rounds=ROUNDS),indent=2)+"\n").encode())
    def one(job):
        i,lane=job;q=pm[i];t=parents[lane][i];g=borrowed.active_graph(q,borrowed.first_recipes(q,t))
        _,fresh=borrowed.initial_values(q,g);nested=family(q,g)
        arms={};cache={}
        for name,values in [("direct",{}),("single",fresh),("shared",nested)]:
            arm="fresh" if values else "ordinary";key=(arm,tuple(values))
            if key not in cache:
                _,_,row=borrowed.trial((q,t,arm,[],values,args.exe.resolve()),seed_label="nested-starts-1",rounds=ROUNDS)
                cache[key]=row
            arms[name]=cache[key]
        return dict(id=i,lane=lane,parent=borrowed.digest(t),nested=nested,flat=fresh,arms=arms)
    tasks=[(i,lane) for group in groups.values() for i in group for lane in ("public","own")
           if lane=="public" or parents["public"][i]!=parents["own"][i]]
    with ThreadPoolExecutor(args.jobs) as pool:
        for rec in pool.map(one,tasks):
            dest=args.out/(rec["id"]+"-"+rec["lane"]+".json")
            dest.write_bytes((json.dumps(rec,separators=(",",":"))+"\n").encode())
    report={}
    for lane in ("own","public"):
        wins={};counts=defaultdict(int)
        for ids in groups.values():
            for i in ids:
                f=args.out/(i+"-"+lane+".json")
                if not f.exists():f=args.out/(i+"-public.json")
                row=json.loads(f.read_bytes());t=parents[lane][i];assert row["parent"]==borrowed.digest(t)
                for arm,value in row["arms"].items():
                    counts[arm]+=len(t)-value["score"]
                    if value["score"]<len(wins.get(i,t)):
                        result=tuple(map(tuple,value["program"]));assert borrowed.check(pm[i],result)==value["score"]
                        wins[i]=result
        borrowed.write_submission(args.out/(lane+".csv"),[q for q in ps if q.id in wins],wins)
        with (args.out/(lane+".origins.csv")).open("w",encoding="utf8",newline="") as stream:
            writer=csv.writer(stream);writer.writerow(["id","source","upstream_source","instructions"])
            for i,t in sorted(wins.items()):
                writer.writerow([i,"shared-prefix temporary starting values",credits[lane][i].get("upstream_source") or "Generated from official inputs",len(t)])
        report[lane]=dict(arms=dict(counts),wins={i:len(t) for i,t in wins.items()},combined=sum(len(parents[lane][i])-len(t) for i,t in wins.items()))
    (args.out/"results.json").write_bytes((json.dumps(report,indent=2)+"\n").encode())
    print(report,flush=True)


if __name__=="__main__":
    main()
