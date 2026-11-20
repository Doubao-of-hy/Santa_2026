"""Apply the registered two-oracle certificate to the remaining finite puzzle set."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import csv
import hashlib
import io
import json
from math import ceil
from pathlib import Path
import subprocess
import sys

from check_cases import check_one
from screen import work


def digest(data):
    return hashlib.sha256(data).hexdigest()


def run_one(entry):
    repo,p,prior=entry
    result=work((repo,p,prior))
    proof=check_one((repo,p,result,True)) if result["eligible"] else dict(id=p.id,previous=prior,certified=prior,cases=[])
    for state in result["states"]:
        state["labels_sha256"]=digest((",".join(map(str,state.pop("labels")))+"\n").encode())
    for case in proof["cases"]:
        case.pop("seconds")
        case.pop("independent_seconds")
        case.pop("independent_statistics",None)
    return dict(screen=result,evidence=proof)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo",type=Path,required=True)
    ap.add_argument("--puzzles",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    ap.add_argument("--design",type=Path,default=Path(__file__).with_name("extension-design.json"))
    ap.add_argument("--jobs",type=int,default=4)
    ap.add_argument("--batch",action="append",type=int)
    args=ap.parse_args()
    design=json.loads(args.design.read_bytes())
    sys.path.insert(0,str(args.repo))
    from elf import read_puzzles
    ps={p.id:p for p in read_puzzles(args.puzzles)}
    blob=subprocess.check_output(["git","-C",str(args.repo),"show",design["snapshot"]+":collaboration/puzzle-bounds.csv"])
    assert digest(blob)==design["bound_table_sha256"] and digest(args.puzzles.read_bytes())==design["official_sha256"]
    rows={r["id"]:r for r in csv.DictReader(io.StringIO(blob.decode()))}
    todo=sorted((k for k,r in rows.items() if k not in set(design["prior_tests"]+design["exclude"]) and int(r["gap"])>0),
                key=lambda k:digest(("turan-full-v1/"+k).encode()))
    assert todo==design["ids"] and len(todo)==design["count"]
    args.out.mkdir(parents=True,exist_ok=True)
    n=design["batch_size"];last=ceil(len(todo)/n)
    batches=sorted(set(args.batch or range(1,last+1)))
    if not all(1<=b<=last for b in batches):
        ap.error("invalid batch")
    with ProcessPoolExecutor(args.jobs) as pool:
        for b in batches:
            ids=todo[(b-1)*n:b*n]
            file=args.out/f"batch-{b:02d}.json"
            if file.exists():
                prior=json.loads(file.read_bytes())
                assert prior["design_sha256"]==digest(args.design.read_bytes()) and [r["evidence"]["id"] for r in prior["rows"]]==ids
                continue
            finished=list(pool.map(run_one,[(args.repo,ps[k],int(rows[k]["certified_lower"])) for k in ids]))
            wins={r["evidence"]["id"]:r["evidence"]["certified"] for r in finished if r["evidence"]["certified"]>r["evidence"]["previous"]}
            material=dict(design_sha256=digest(args.design.read_bytes()),batch=b,wins=wins,rows=finished)
            tmp=file.with_suffix(".tmp")
            tmp.write_bytes((json.dumps(material,separators=(",",":"))+"\n").encode())
            tmp.replace(file)
            print(b,len(ids),len(wins),sum(v-int(rows[k]["certified_lower"]) for k,v in wins.items()),flush=True)


if __name__=="__main__":
    main()
