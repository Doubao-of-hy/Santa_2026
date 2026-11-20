"""Verify the complete five-fixed/five-free cover and optionally repeat native searches."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import gzip
from hashlib import sha256
from itertools import combinations
import json
from math import comb
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
GRID_SHA = "3ce862dde4261fce05159e1f5c438d13e568c0283c72de7bab23e81526501642"
LOWER_SHA = "bfd7930400c7aaba76a7e2b9df1101df55e1da83e4d9fe336bb68e0de5f0eb4a"


def require(value, message):
    if not value:
        raise ValueError(message)


def native(binary, engine, texts):
    arguments = ["--original","0","1"] if engine=="generic" else ["star","0","1","0","1","0","1"]
    result = subprocess.run([str(binary.resolve()), *arguments], input="".join(texts), text=True,
                            capture_output=True, check=True, env={**os.environ, "SANTA_GROUP_WIDTH":"16"})
    require(not result.stderr.strip(), "unexpected native diagnostics")
    return result.stdout


def payload(p, old, cap):
    goals = sorted(set(p.targets) | set(old))
    return " ".join(map(str,[p.limit,len(p.seeds),len(goals),5,cap,*p.seeds,*goals]))+"\n"


def read_archive(puzzles, repo):
    history = repo/"collaboration/puzzle-0882-diversity"
    sys.path.insert(0,str(history))
    from verify import check, read_puzzles, replay
    require(sha256((repo/"proofs/local/proofs/helper-wave17.json").read_bytes()).hexdigest()==LOWER_SHA,
            "the earlier nine-helper lower certificate differs")
    family = json.loads((history/"parents.json").read_bytes())
    require(sha256(puzzles.read_bytes()).hexdigest()==family["official_puzzles_sha256"],"unexpected official table")
    p = next(p for p in read_puzzles(puzzles) if p.id==family["id"])
    base = set(p.seeds)|set(p.targets)
    donors = set()
    for row in family["parents"]:
        require(check(p,row["program"])==row["steps"],"historical independent program does not replay")
        donors.update(t.output for t in replay(p,row["program"]) if t.output not in base)
    donors = sorted(donors)
    require(donors==family["union"] and len(donors)==20 and len(set(p.targets)-set(p.seeds))==12,
            "unexpected donor or target universe")
    raw = gzip.decompress((HERE/"five-new-initial.json.gz").read_bytes())
    require(sha256(raw).hexdigest()==GRID_SHA,"unexpected original grid")
    doc = json.loads(raw)
    spec = doc["protocol"]
    engines = json.loads((history/"batch-receipt.json").read_bytes())
    expected = dict(puzzle=p.id, family="all", engine="star", budget=10, required_from_union=5, arbitrary_helpers=5,
                    donors=donors, shards=1024, node_limit=2500000, old_upper_length=23,
                    official_sha256=family["official_puzzles_sha256"], frozen_sha256=family["frozen_experiment_sha256"],
                    binary_sha256=engines["star"]["binary"])
    require(spec==expected,"unexpected grid configuration")
    groups = list(combinations(donors,5))
    require(len(groups)==comb(20,5)==15504,"unexpected combination count")
    records = doc["shard_results"]
    require([r["shard"] for r in records]==list(range(1024)),"missing or repeated shard")
    unresolved = set()
    total = Counter()
    for row in records:
        indices = list(range(row["shard"],len(groups),1024))
        counts = Counter(row["counts"]); unknown = row["unknown_indices"]
        require(set(counts)<={"UNSAT","UNKNOWN"} and all(type(v)==int and v>=0 for v in counts.values()) and
                sum(counts.values())==row["subsets"]==len(indices) and counts["UNKNOWN"]==len(unknown) and
                len(set(unknown))==len(unknown) and set(unknown)<=set(indices) and not row["found"],
                f"invalid cover for shard {row['shard']}")
        unresolved.update(unknown); total.update(counts)
    require(total==doc["totals"]=={"UNSAT":15499,"UNKNOWN":5} and
            unresolved=={59,88,452,453,482} and sum(row["nodes"] for row in records)==doc["nodes"]==1012077541,
            "grid totals or original undecided cases differ")
    archive = json.loads((HERE/"five-new-retries.json").read_bytes())
    require(archive["original_sha256"]==GRID_SHA,"retries belong to different grid")
    resolved = set()
    keys = set()
    for row in archive["retries"]:
        i,engine,cap = row["index"],row["engine"],row["cap"]
        key=i,engine,cap
        require(i in unresolved and key not in keys and engine in engines,"unexpected retry")
        keys.add(key)
        require(row["selected"]==list(groups[i]) and row["stdin_sha256"]==sha256(payload(p,groups[i],cap).encode()).hexdigest()
                and row["source_sha256"]==engines[engine]["compiled_source"] and row["binary_sha256"]==engines[engine]["binary"],
                f"retry input or engine differs for {i}")
        require(row["status"]=="UNSAT" and 0<=row["nodes"]<=cap and cap>spec["node_limit"],
                f"no conclusive exclusion for index {i}")
        text="UNSAT "+" ".join(map(str,row["counters"]))+"\n"
        require(row["counters"][:2]==[row["nodes"],row["terminals"]] and
                len(row["counters"])==(2 if engine=="generic" else 4) and
                sha256(text.encode()).hexdigest()==row["stdout_lf_sha256"],"native retry output differs")
        resolved.add(i)
    require(resolved==unresolved and archive["unique_excluded"]==len(groups),"incomplete retry coverage")
    return p, groups, records, archive["retries"]


def replay_grid(p, groups, row, binary):
    idx = list(range(row["shard"],len(groups),1024))
    t = native(binary,"star",[payload(p,groups[i],2500000) for i in idx])
    outputs = [line.split() for line in t.splitlines()]
    require(len(outputs)==len(idx) and all(len(z)==5 and z[0] in ("UNSAT","UNKNOWN") for z in outputs),
            "unexpected native outputs for grid")
    require(Counter(z[0] for z in outputs)==Counter(row["counts"]) and
            [i for i,z in zip(idx,outputs) if z[0]=="UNKNOWN"]==row["unknown_indices"] and
            sum(int(z[1]) for z in outputs)==row["nodes"] and sum(int(z[2]) for z in outputs)==row["terminals"] and
            sha256(t.encode()).hexdigest()==row["stdout_sha256"],f"search trace differs in shard {row['shard']}")


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo",type=Path,default=HERE.parents[1])
    ap.add_argument("--puzzles",type=Path,required=True)
    ap.add_argument("--grid-shard",type=int,action="append",default=[])
    ap.add_argument("--all-grid",action="store_true")
    ap.add_argument("--retries",action="store_true")
    ap.add_argument("--retry-index",type=int)
    ap.add_argument("--jobs",type=int,default=3)
    ap.add_argument("--cxx",default="g++")
    ap.add_argument("--temp-dir",type=Path)
    args=ap.parse_args()
    require(args.jobs>=1 and all(0<=i<1024 for i in args.grid_shard),"invalid selection")
    p,groups,records,rows=read_archive(args.puzzles,args.repo.resolve())
    print("Validated 15,504 conditional exclusions, including all five originally undecided indices.",flush=True)
    if not (args.all_grid or args.grid_shard or args.retries or args.retry_index is not None):
        return
    from verify_four import build
    selected=rows if args.retries else [r for r in rows if r["index"]==args.retry_index]
    if args.retry_index is not None:
        require(any(row["index"]==args.retry_index for row in rows),"unknown retry index")
        selected=[r for r in selected if r["index"]==args.retry_index]
    grid=records if args.all_grid else [records[i] for i in sorted(set(args.grid_shard))]
    wanted={r["engine"] for r in selected}
    if grid:wanted.add("star")
    if args.temp_dir:args.temp_dir.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.temp_dir) as tmp:
        bins={engine:build(engine,args.cxx,Path(tmp)) for engine in sorted(wanted)}
        def retry(r):
            out=native(bins[r["engine"]],r["engine"],[payload(p,groups[r["index"]],r["cap"])])
            require(sha256(out.encode()).hexdigest()==r["stdout_lf_sha256"],f"retry differs at index {r['index']}")
        with ThreadPoolExecutor(args.jobs) as pool:
            tasks=[pool.submit(replay_grid,p,groups,row,bins["star"]) for row in grid]
            tasks += [pool.submit(retry,row) for row in selected]
            for task in tasks:task.result()
    print("Native replays matched:", len(grid), "original shards and", len(selected), "retries.")


if __name__=="__main__":
    main()
