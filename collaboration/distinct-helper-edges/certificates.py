"""Build compact per-puzzle certificates; independently rebuild each claim from the official puzzle."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import csv
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys

from cliques import resolve
from sorted_quads import audit
from screen import capacities


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def stamp(values):
    return digest((",".join(map(str,sorted(values)))+"\n").encode())


def make(args):
    rows={}
    def select(screen,checks):
        lookup={r["k"]:r for r in screen["states"]}
        for test in checks["cases"]:
            if test["status"]!="ABSENT" or test["independent_status"]!="ABSENT" or test["established"]<=checks["previous"]:
                continue
            key=screen["id"]; state=lookup[test["k"]]
            item=dict(prior=checks["previous"],lower=test["established"],missing=screen["missing"],
                      k=test["k"],residual_helpers=state["optimistic"],plain_helpers=state["classic"],
                      allowed_count=state["allowed_count"],allowed_sha256=state["allowed_sha256"],
                      labels=test["unsupported"],labels_sha256=state.get("labels_sha256") or stamp(state["labels"]),
                      mobius=test["statistics"],mobius_status=test["status"],ordered_status=test["independent_status"])
            if "independent_statistics" in test:
                item["ordered"]=test["independent_statistics"]
            if key not in rows or item["lower"]>rows[key]["lower"]:
                rows[key]=item
    for name in ("screen","replicate"):
        s={r["id"]:r for r in json.loads((args.inputs/(name+".json")).read_bytes())}
        for v in json.loads((args.inputs/(name+"-dual.json")).read_bytes()):
            select(s[v["id"]],v)
    if args.full:
        for filename in sorted(args.full.glob("batch-*.json")):
            for rec in json.loads(filename.read_bytes())["rows"]:
                select(rec["screen"],rec["evidence"])
    ordered=dict(sorted(rows.items()))
    meta=json.loads((Path(__file__).with_name("extension-design.json")).read_bytes())
    out=dict(method="rainbow-k4-turan-two-integer-oracles-v1",base_commit=meta["snapshot"],
             base_table_sha256=meta["bound_table_sha256"],official_sha256=meta["official_sha256"],
             count=len(rows),sum_gain=sum(r["lower"]-r["prior"] for r in rows.values()),rows=ordered)
    args.output.write_bytes((json.dumps(out,indent=1)+"\n").encode())
    print("claims",len(rows),"strict gain",out["sum_gain"])


def verify_one(arg):
    repo,p,claim=arg
    sys.path.insert(0,str(repo))
    from solvers.proofs.domain_bounds import domains,missing_capacity
    from lower_bounds import certificate
    missing,_,minimum,_=certificate(p)
    k=claim["k"]
    assert 0<=k<=min(4,minimum) and missing==claim["missing"]
    base=set(p.seeds) if k==0 else dict(domains(p,k,3500))[k]
    assert len(base)==claim["allowed_count"] and stamp(base)==claim["allowed_sha256"]
    labels,ordinary,improved=capacities(p,base)
    assert ordinary==missing_capacity(p,base,True)==claim["plain_helpers"]
    assert len(labels)==claim["labels"] and stamp(labels)==claim["labels_sha256"]
    assert improved==claim["residual_helpers"] and missing+k+improved==claim["lower"]
    forbid=base|set(p.targets)
    m,counts,w=resolve(labels,forbid,p.limit)
    stats={}
    l,w2=audit(labels,forbid,p.limit,stats)
    assert m==l==claim["ordered_status"]==claim["mobius_status"]=="ABSENT" and w is None and w2 is None
    assert counts==claim["mobius"]
    if "ordered" in claim:
        assert stats==claim["ordered"]
    return p.id,claim["lower"]


def verify(args):
    sys.path.insert(0,str(args.repo))
    from elf import read_puzzles
    doc=json.loads(args.receipt.read_bytes())
    blob=subprocess.check_output(["git","-C",str(args.repo),"show",doc["base_commit"]+":collaboration/puzzle-bounds.csv"])
    assert digest(blob)==doc["base_table_sha256"] and digest(args.puzzles.read_bytes())==doc["official_sha256"]
    table={r["id"]:r for r in csv.DictReader(io.StringIO(blob.decode()))}
    puzzles={p.id:p for p in read_puzzles(args.puzzles)}
    assert len(table)==len(puzzles)==1000 and set(table)==set(puzzles)
    lower={pid:int(r["certified_lower"]) for pid,r in table.items()}
    previous=sum(lower.values())
    cases=[]
    for pid,c in doc["rows"].items():
        assert c["prior"]==lower[pid]<c["lower"]<=int(table[pid]["best_verified_upper"])
        cases.append((args.repo,puzzles[pid],c))
    with ProcessPoolExecutor(args.jobs) as pool:
        for pid,lb in pool.map(verify_one,cases):
            lower[pid]=lb
    assert len(cases)==doc["count"] and sum(lower.values())-previous==doc["sum_gain"]
    print("verified",len(cases),"previous",previous,"new",sum(lower.values()),"strict gain",doc["sum_gain"])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    commands=p.add_subparsers(dest="action",required=True)
    c=commands.add_parser("make")
    c.add_argument("--inputs",type=Path,required=True)
    c.add_argument("--full",type=Path)
    c.add_argument("--output",type=Path,required=True)
    v=commands.add_parser("verify")
    v.add_argument("--puzzles",type=Path,required=True)
    v.add_argument("--repo",type=Path,required=True)
    v.add_argument("--receipt",type=Path,required=True)
    v.add_argument("--jobs",type=int,default=4)
    args=p.parse_args()
    (make if args.action=="make" else verify)(args)


if __name__=="__main__":
    main()
