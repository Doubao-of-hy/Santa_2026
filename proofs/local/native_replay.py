"""Recompute recorded exhaustive exclusions on a fresh canonical grid, or try an open helper budget."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import subprocess

from elf import check, read_puzzles, sha256
from tiny import encode
from verify import HERE, PROOFS, require


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--puzzles",type=Path,required=True)
    ap.add_argument("--binary",type=Path,required=True)
    ap.add_argument("--save",type=Path,required=True,help="folder for per-cell receipts and physical witnesses")
    ap.add_argument("--engine",choices=("star","generic","hot","pair"),default="star")
    ap.add_argument("--task",action="append",help="e.g. 0882:9; defaults to each puzzle's strongest archived exhaustive exclusion")
    ap.add_argument("--shards",type=int,default=12);ap.add_argument("--subshards",type=int,default=8)
    ap.add_argument("--cell",help="run only FIRST:SECOND; 0-based")
    ap.add_argument("--nodes",type=int,default=3000000000);ap.add_argument("--jobs",type=int,default=4)
    ap.add_argument("--width",type=int,default=16)
    a=ap.parse_args()
    require(min(a.shards,a.subshards,a.nodes,a.jobs,a.width)>0,"positive budgets required")
    puzzles={p.id:p for p in read_puzzles(a.puzzles)}
    official=sha256(a.puzzles)
    require(official==json.loads((PROOFS/"domain-bounds.json").read_bytes())["puzzles_sha256"],"official data mismatch")
    tasks={}
    for row in json.loads((PROOFS/"decisions.json").read_bytes())["decisions"]:
        if row["status"]=="UNSAT":tasks[row["id"]]=row["helpers"]
    for wave in PROOFS.glob("helper-wave*.json"):
        for pid,row in json.loads(wave.read_bytes())["instances"].items():
            if row["status"]=="UNSAT":tasks[pid]=max(tasks.get(pid,-1),row["helpers"])
    expected=dict(tasks)
    if a.task:
        tasks={f"scored_{int(pid):04}":int(h) for pid,h in (t.split(":") for t in a.task)}
    engine_hash=sha256(a.binary)
    env={**os.environ,"SANTA_GROUP_WIDTH":str(a.width)}
    a.save.mkdir(exist_ok=True,parents=True)
    chosen=tuple(map(int,a.cell.split(":"))) if a.cell else None
    cells=[]
    for pid,h in sorted(tasks.items()):
        p=puzzles[pid]
        require(0<=h<=4096 and (a.engine!="hot" or p.limit<=2000000),"engine or helper count not supported")
        n=a.shards;m=a.subshards if h>=4 else 1
        require(not chosen or 0<=chosen[0]<n and 0<=chosen[1]<m,"cell out of grid")
        cells.extend((p,h,n,m,i,j) for j in range(m) for i in range(n) if not chosen or chosen==(i,j))
    def run(cell):
        p,h,n,m,i,j=cell
        path=a.save/f"{p.id}-h{h}-{a.engine}-{engine_hash[:12]}-{n}x{m}-w{a.width}-{i}-{j}.json"
        header=dict(id=p.id,helpers=h,first=i,second=j,shards=n,subshards=m,
                    engine_sha256=engine_hash,puzzles_sha256=official,mode=a.engine,width=a.width)
        if path.exists():
            previous=json.loads(path.read_bytes())
            require(all(previous.get(k)==v for k,v in header.items()),"incompatible resume")
            if previous["status"] in ("FOUND","UNSAT") or previous["node_limit"]>=a.nodes:
                return previous
        args=[str(a.binary.resolve())]
        if a.engine in ("star","hot"):args+=["star",str(i),str(n),str(j),str(m),"0","1"]
        else:
            args+=["--original" if a.engine=="generic" else "--pair-bound",str(i),str(n)]
            if m>1:args.extend([str(j),str(m)])
        payload=" ".join(map(str,[p.limit,len(p.seeds),len(p.targets),h,a.nodes,*p.seeds,*p.targets]))+"\n"
        raw=subprocess.run(args,input=payload,env=env,text=True,capture_output=True,check=True).stdout.splitlines()
        status,*counters=raw[0].split()
        require(status in ("FOUND","UNSAT","UNKNOWN"),"unexpected native result")
        record={**header,"status":status,"node_limit":a.nodes,"counters":list(map(int,counters))}
        if status=="FOUND":
            values=tuple(map(int,raw[1].split()))
            require(values[:len(p.seeds)]==p.seeds,"invalid witness prefix")
            witness=encode(p,values[len(p.seeds):])
            require(check(p,witness)<=len(set(p.targets)-set(p.seeds))+h,"invalid witness")
            record["program"]=witness
            require(expected.get(p.id,-1)<h,"witness contradicts a published lower bound")
        temp=path.with_suffix(f".{os.getpid()}.tmp")
        temp.write_text(json.dumps(record)+"\n",encoding="utf-8")
        os.replace(temp,path)
        return record
    done={}
    with ThreadPoolExecutor(a.jobs) as pool:
        pending=[pool.submit(run,c) for c in cells]
        for future in as_completed(pending):
            result=future.result()
            done.setdefault(result["id"],[]).append(result)
    for pid,records in sorted(done.items()):
        n=records[0]["shards"];m=records[0]["subshards"]
        statuses=[r["status"] for r in records]
        verdict="FOUND" if "FOUND" in statuses else "UNSAT" if len(records)==n*m and set(statuses)=={"UNSAT"} else "INCOMPLETE"
        print(pid,tasks[pid],verdict,f"{len(records)}/{n*m}",f"unknown={statuses.count('UNKNOWN')}",flush=True)


if __name__=="__main__":
    main()
