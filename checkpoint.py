"""Merge partial solver runs, record per-row origins, and independently replay the export."""
import argparse
from collections import Counter
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from datetime import datetime, timedelta, timezone

from elf import read_puzzles, read_submission, check, sha256, write_submission


def independent_score(data, submission):
    with data.open(encoding="utf-8-sig",newline="") as f:
        puzzles={row["id"]:row for row in csv.DictReader(f)}
    counts=[]
    with submission.open(encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        if reader.fieldnames!=["id","program"]:
            raise ValueError("bad submission header")
        for line in reader:
            identifier=line["id"]
            puzzle=puzzles.pop(identifier)
            seeds=json.loads(puzzle["starting_values"])
            limit=int(puzzle["value_limit"])
            n=int(puzzle["registers"])
            values=dict(enumerate(seeds))
            found=set(seeds)
            raw=line["program"]
            instructions=json.loads(raw)
            if len(raw.encode("utf8"))>131072 or len(instructions)>4096:
                raise ValueError(identifier)
            for op,i,j,k in instructions:
                if not all(type(index) is int and 0<=index<n for index in (i,j,k)):
                    raise ValueError(identifier)
                x,y=values[i],values[j]
                if op=="+": v=x+y
                elif op=="-": v=x-y
                elif op=="*": v=x*y
                elif op=="/" and x%y==0: v=x//y
                else: raise ValueError(identifier)
                if not 1<=v<=limit: raise ValueError(identifier)
                values[k]=v
                found.add(v)
            if set(json.loads(puzzle["targets"]))-found:
                raise ValueError(identifier)
            counts.append(len(instructions))
    if puzzles: raise ValueError("missing puzzle rows")
    return sorted(counts)


def atomic_text(path, contents):
    with tempfile.NamedTemporaryFile("w",dir=path.parent,encoding="utf8",
                                     newline="",delete=False) as f:
        f.write(contents)
        temp=Path(f.name)
    os.replace(temp,path)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs",nargs="+",type=Path)
    parser.add_argument("--directory",type=Path,default=Path(__file__).resolve().parent)
    args=parser.parse_args()
    root=args.directory.resolve()
    data=root/"data/puzzles.csv"
    output=root/"submission.csv"
    details=root/"result.json"
    origin_file=root/"origins.csv"
    puzzles=read_puzzles(data)
    by_id={p.id:p for p in puzzles}
    programs=read_submission(output)
    old=sha256(output)
    evidence=json.loads(details.read_text(encoding="utf8"))
    if evidence["sha256"]!=old: raise ValueError("incumbent disagrees with recorded hash")
    board_path=root/"work/leaderboard.json"
    board_changed=False
    lower_path=root/"work/virtual/certificates.json"
    if lower_path.exists():
        lower=json.loads(lower_path.read_text(encoding="utf8"))
        if lower["puzzles_sha256"]!=sha256(data) or lower["certificate_csv_sha256"]!=sha256(lower_path.with_suffix(".csv")):
            raise ValueError("lower bound certificate mismatch")
        if evidence.get("arithmetic_lower_bound")!=lower["certified_instruction_bound"]:
            evidence["target_count_lower_bound"]=lower["target_count_bound"]
            evidence["arithmetic_lower_bound"]=lower["certified_instruction_bound"]
            evidence["lower_bound_certificate"]=str(lower_path.with_suffix(".csv").relative_to(root).as_posix())
            board_changed=True
    if board_path.exists():
        observed=json.loads(board_path.read_text(encoding="utf8"))
        benchmark=evidence["benchmarks"]
        if benchmark.get("latest_official_leaderboard")!=observed:
            benchmark["latest_official_leaderboard"]=observed
            benchmark["public_leaderboard_first_steps"]=observed["top_scores"][0]
            local=datetime.fromisoformat(observed["checked_at"]).astimezone(timezone(timedelta(hours=8)))
            benchmark["public_leaderboard_snapshot_beijing"]=local.strftime("%Y-%m-%d %H:%M")
            board_changed=True
    origins={p.id:"original-172868" for p in puzzles}
    if origin_file.exists():
        with origin_file.open(encoding="utf8",newline="") as f:
            origins={line["id"]:line["source"] for line in csv.DictReader(f)}
        if set(origins)!=set(by_id): raise ValueError("origin ledger incomplete")
    history=evidence.setdefault("optimization_checkpoints",[])
    adopted={}
    for path in args.inputs:
        if not path.exists():
            continue
        snapshot=read_submission(path)
        changed=delta=0
        used=hashlib.sha256()
        label=path.resolve().relative_to(root).as_posix()
        for pid,prog in snapshot.items():
            if len(prog)<len(programs[pid]):
                check(by_id[pid],prog)
                delta+=len(programs[pid])-len(prog)
                programs[pid]=prog
                origins[pid]=label
                changed+=1
                used.update((pid+"\t"+json.dumps(prog,separators=(",",":"))+"\n").encode("ascii"))
        if changed:
            adopted[label]={"rows":changed,"saved":delta,"snapshot_size":len(snapshot),
                            "adopted_programs_sha256":used.hexdigest()}
    if not adopted:
        if board_changed:
            atomic_text(details,json.dumps(evidence,indent=2,ensure_ascii=False)+"\n")
        print("No shorter rows."); return
    # Verify the replacement in a private file before publishing it as the champion.
    with tempfile.TemporaryDirectory(dir=root/"work",prefix="verify-") as scratch:
        candidate=Path(scratch)/"verified.csv"
        score=write_submission(candidate,puzzles,programs)
        counts=independent_score(data,candidate)
        if sum(counts)!=score: raise ValueError("independent scores disagree")
        digest=sha256(candidate)
        size=candidate.stat().st_size
        os.replace(candidate,output)
    history.append({"utc":datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "previous_sha256":old,"score":score,"sha256":digest,"adopted":adopted})
    evidence.update(instructions=score,sha256=digest,longest_program=counts[-1],
                    selected=dict(Counter(origins.values())))
    evidence["verification"].update(independent_full_replay=True,
                    median_program=(counts[(len(counts)-1)//2]+counts[len(counts)//2])/2,
                    p90_program=counts[math.ceil(.9*len(counts))-1],submission_bytes=size,
                    kaggle_submission_status="local_only")
    evidence["benchmarks"]["current_reduction_from_sample_percent"]=round(
        100*(1-score/evidence["benchmarks"]["official_sample_steps"]),4)
    atomic_text(origin_file,"id,source,instructions\n"+"".join(
        f"{p.id},{origins[p.id]},{len(programs[p.id])}\n" for p in puzzles))
    atomic_text(details,json.dumps(evidence,indent=2,ensure_ascii=False)+"\n")
    print(json.dumps({"verified_score":score,"adopted":adopted}))


if __name__=="__main__":
    main()
