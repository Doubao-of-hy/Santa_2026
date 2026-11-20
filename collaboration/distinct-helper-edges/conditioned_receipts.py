"""Package or independently replay improved per-ID claims from the frozen partition trees."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import gzip
import json
from pathlib import Path
import sys

from conditioned import canonical, load, sha, solve


def summarize(result):
    detail=[]
    for tree in result["trees"]:
        if tree["closed"]!=result["lower"]:
            continue
        proof=tree.get("leaf_proofs",[])
        summary=dict(pack=tree["pack"],tree_sha256=tree["tree_sha256"],leaves=tree["leaves"],
                     ordinary=sum(x["uses"]=="ordinary" for x in proof),
                     inherited=sum(x["uses"]=="shared-negative" for x in proof),
                     individual=sum(x["uses"]=="leaf-negative" for x in proof),
                     checked_leaves_sha256=sha(canonical(proof)))
        if tree.get("ordinary_only"):
            summary["ordinary"]=tree["leaves"]
        if "common" in tree:
            summary.update(common_mobius=tree["common"]["mobius"],common_ordered=tree["common"]["ordered"],
                           union_labels_sha256=tree["common"]["labels_sha256"],
                           intersection_forbidden_sha256=tree["common"]["forbidden_sha256"])
        detail.append(summary)
    return dict(prior=result["prior"],lower=result["lower"],winning_trees=detail,
                entire_replay_sha256=sha(canonical(result)))


def make(a):
    base=Path(__file__).resolve().parent
    ds=json.loads((base/"conditioned-design.json").read_bytes())
    inputs=[(a.pilot,[r["id"] for r in ds["pilot"]])]
    if a.batches:
        extension=json.loads((base/"conditioned-extension.json").read_bytes())
        count=extension["batch_size"]
        nb=(len(extension["ids"])+count-1)//count
        last=a.through_batch or nb
        assert 1<=last<=nb
        for b in range(1,last+1):
            inputs.append((a.batches/f"batch-{b:02d}.json",extension["ids"][(b-1)*count:b*count]))
    rows={}
    for p,expected_ids in inputs:
        v=json.loads(p.read_bytes())
        assert v["design_sha256"]==sha((base/"conditioned-design.json").read_bytes())
        assert [r["id"] for r in v["rows"]]==expected_ids
        for r in v["rows"]:
            assert r["id"] not in rows
            rows[r["id"]]=r
    gains={k:summarize(r) for k,r in sorted(rows.items()) if r["lower"]>r["prior"]}
    out=dict(snapshot=ds["snapshot"],plain_certificates_sha256=ds["plain_certificates_sha256"],
             pilot_design_sha256=sha((base/"conditioned-design.json").read_bytes()),cases=len(rows),
             gains=len(gains),sum_gain=sum(x["lower"]-x["prior"] for x in gains.values()),rows=gains)
    if a.archive:
        a.archive.write_bytes(gzip.compress(canonical(rows),mtime=0))
    a.output.write_bytes((json.dumps(out,indent=1)+"\n").encode())
    print("screened",len(rows),"strict rows",out["gains"],"strict increments",out["sum_gain"])


def verify(a):
    base=Path(__file__).resolve().parent
    cfg,trees,baseline,original=load(a.repo,a.puzzles,base)
    doc=json.loads(a.receipt.read_bytes())
    assert doc["snapshot"]==cfg["snapshot"] and doc["plain_certificates_sha256"]==cfg["plain_certificates_sha256"]
    assert doc["pilot_design_sha256"]==sha((base/"conditioned-design.json").read_bytes())
    sys.path.insert(0,str(a.repo))
    from elf import read_puzzles
    ps={p.id:p for p in read_puzzles(a.puzzles)}
    before=sum(baseline.values());cases=[]
    for pid,r in doc["rows"].items():
        assert r["prior"]==baseline[pid]<r["lower"]<=int(original[pid]["best_verified_upper"])
        cases.append((a.repo,ps[pid],trees[pid],baseline[pid]))
    with ProcessPoolExecutor(a.jobs) as pool:
        for result in pool.map(solve,cases):
            pid=result["id"]
            assert summarize(result)==doc["rows"][pid]
            baseline[pid]=result["lower"]
    assert len(cases)==doc["gains"] and sum(baseline.values())-before==doc["sum_gain"]
    print("verified",len(cases),"previous",before,"new",sum(baseline.values()),"strict gain",doc["sum_gain"])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    c=p.add_subparsers(dest="action",required=True)
    m=c.add_parser("make")
    m.add_argument("--pilot",type=Path,required=True);m.add_argument("--batches",type=Path)
    m.add_argument("--through-batch",type=int,help="include this many completed extension batches")
    m.add_argument("--archive",type=Path);m.add_argument("--output",type=Path,required=True)
    v=c.add_parser("verify");v.add_argument("--repo",type=Path,required=True)
    v.add_argument("--puzzles",type=Path,required=True);v.add_argument("--receipt",type=Path,required=True)
    v.add_argument("--jobs",type=int,default=4)
    a=p.parse_args();(make if a.action=="make" else verify)(a)


if __name__=="__main__":
    main()
