"""Subdivide unfinished two-level decisions while retaining completed sibling proofs."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import sqlite3

from checkpoint import atomic_text
from elf import check, read_puzzles, sha256, write_submission
from shard_decision import decide


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for key in ("exe","parent","output"):
        ap.add_argument(key,type=Path)
    ap.add_argument("--parts",type=int,default=12)
    ap.add_argument("--nodes",type=int,default=70000000)
    ap.add_argument("--retry-nodes",type=int,
                    help="Raise the cap only on cached third-level partitions that returned UNKNOWN")
    ap.add_argument("--cache",type=Path,help="Reuse this refinement SQLite cache for a new report")
    ap.add_argument("--jobs",type=int,default=2)
    ap.add_argument("--pair-bound",action="store_true")
    a=ap.parse_args()
    if a.parts<2 or a.nodes<1 or a.jobs<1:ap.error("Invalid refinement sizes")
    if a.retry_nodes is not None and a.retry_nodes<=a.nodes:ap.error("Retry cap must increase")
    parent_bytes=a.parent.read_bytes()
    parent=json.loads(parent_bytes)
    data=Path("data/puzzles.csv"); puzzles={p.id:p for p in read_puzzles(data)}
    if sha256(data)!=parent["puzzles_sha256"]:raise ValueError("Input mismatch")
    binary=a.exe.resolve(); binary_hash=sha256(binary)
    n,m=parent["shards"],parent["subshards"]
    report={"parent_sha256":hashlib.sha256(parent_bytes).hexdigest(),
            "puzzles_sha256":parent["puzzles_sha256"],"binary_sha256":binary_hash,
            "shards":n,"subshards":m,"third_shards":a.parts,"node_limit_per_shard":a.nodes,
            "pair_bound":a.pair_bound,"instances":{}}
    if a.retry_nodes:report["retry_node_limit"]=a.retry_nodes
    db=sqlite3.connect(a.cache or a.output.with_suffix(".sqlite"))
    db.execute("CREATE TABLE IF NOT EXISTS branches(key TEXT PRIMARY KEY,result TEXT)")
    results={}; queue={}; witnesses={}; retried=set()
    def publish():
        for pid,before in parent["instances"].items():
            p=puzzles[pid];h=before["helpers"]
            branches=[]
            for row in before["branches"]:
                r=dict(row);key=(pid,row["first"],row["second"])
                if row["status"]=="UNKNOWN":
                    children=results.get(key,{})
                    r["children"]=[{"third":k,"status":res[0],"nodes":res[1],"terminals":res[2]}
                                   for k,res in sorted(children.items())]
                    for child in r["children"]:
                        if (*key,child["third"]) in retried:
                            child["node_limit"]=a.retry_nodes
                    if len(children)==a.parts and all(v[0]=="UNSAT" for v in children.values()):
                        r["status"]="UNSAT"
                        r["nodes"]=sum(v[1] for v in children.values())
                        r["terminals"]=sum(v[2] for v in children.values())
                    for res in children.values():
                        if res[0]=="FOUND":
                            r["status"]="FOUND";candidate=tuple(map(tuple,res[3]))
                            check(p,candidate)
                            if pid not in witnesses or len(candidate)<len(witnesses[pid]):witnesses[pid]=candidate
                branches.append(r)
            joined={(r["first"],r["second"]) for r in branches if r["status"]=="UNSAT"}
            complete=joined=={(i,j) for i in range(n) for j in range(m)}
            status="UNSAT" if complete else "FOUND" if any(r["status"]=="FOUND" for r in branches) else "INCOMPLETE"
            report["instances"][pid]={"helpers":h,"status":status,"branches":branches,
                "nodes":sum(r["nodes"] for r in branches),
                "certified_lower":len(set(p.targets)-set(p.seeds))+h+1 if complete else None}
        if witnesses:
            write_submission(a.output.with_suffix(".csv"),[puzzles[k] for k in sorted(witnesses)],witnesses)
        atomic_text(a.output,json.dumps(report,indent=2)+"\n")
    with ThreadPoolExecutor(a.jobs) as pool:
        for pid,r in parent["instances"].items():
            p=puzzles[pid];h=r["helpers"]
            for b in r["branches"]:
                if b["status"]!="UNKNOWN":continue
                i,j=b["first"],b["second"];group=(pid,i,j)
                for k in range(a.parts):
                    cap=a.nodes
                    while True:
                        settings=(binary_hash,p,h,n,m,i,j,k,a.parts,cap)
                        if a.pair_bound:settings+=("pair-bound",)
                        key=hashlib.sha256(repr(settings).encode()).hexdigest()
                        saved=db.execute("SELECT result FROM branches WHERE key=?",(key,)).fetchone()
                        if not saved:break
                        result=json.loads(saved[0])
                        if result[0]=="UNKNOWN" and a.retry_nodes and cap==a.nodes:
                            cap=a.retry_nodes
                            retried.add((*group,k))
                            continue
                        results.setdefault(group,{})[k]=result
                        break
                    if saved:continue
                    fut=pool.submit(decide,binary,p,h,cap,i,n,j,m,True,k,a.parts,a.pair_bound)
                    queue[fut]=(key,group,k)
        for fut in as_completed(queue):
            key,group,k=queue[fut];res=fut.result()
            results.setdefault(group,{})[k]=res
            db.execute("INSERT OR REPLACE INTO branches VALUES(?,?)",(key,json.dumps(res)));db.commit()
            publish()
    publish();db.close()
    print({pid:r["status"] for pid,r in report["instances"].items()})


if __name__=="__main__":main()
