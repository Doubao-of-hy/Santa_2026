"""Run equal-iteration, equal-seed comparisons of arithmetic-program parent banks."""
import argparse
import csv
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE=Path(__file__).resolve().parent
ROOT=next(p for p in HERE.parents if (p/"elf.py").is_file() and (p/"tiny.py").is_file())
sys.path.insert(0,str(ROOT))
from checkpoint import independent_score
from elf import check, read_puzzles, replay, sha256, write_submission
from graph import compile_graph
from tiny import encode

ARMS=("one","multi","assisted")
DEFAULT_BIN=ROOT/"work/gpu/bridge-36731/construct"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(obj):
    packed=json.dumps(obj,ensure_ascii=False,separators=(",",":"),sort_keys=True).encode()
    return hashlib.sha256(packed).hexdigest()


def write_json(path, obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as tmp:
        tmp.write((json.dumps(obj,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode())
    try:
        os.replace(tmp.name,path)
    finally:
        Path(tmp.name).unlink(missing_ok=True)


@dataclass
class ParentBank:
    start: int
    best_parent: int
    programs: list
    parents: list
    native_input: str


def dual_check(p, raw_puzzle, tape):
    n=check(p,tape)
    with tempfile.TemporaryDirectory(dir=HERE) as folder:
        official=Path(folder)/"puzzle.csv";submission=Path(folder)/"candidate.csv"
        with official.open("w",encoding="utf8",newline="") as stream:
            writer=csv.DictWriter(stream,fieldnames=raw_puzzle.keys())
            writer.writeheader();writer.writerow(raw_puzzle)
        program=tuple(tuple(step) for step in tape)
        write_submission(submission,[p],{p.id:program})
        require(independent_score(official,submission)==[n],f"{p.id}: independent replay mismatch")
    return n


def compile_values(p, rows):
    known=set(p.seeds);recipes={}
    for value,a,b in rows:
        require(a in known and b in known and value not in known and 1<=value<=p.limit,
                f"{p.id}: invalid native value or missing operand")
        if a+b==value:op="+"
        elif a-b==value:op="-"
        elif b-a==value:op="-";a,b=b,a
        elif a*b==value:op="*"
        elif a==b*value:op="/"
        elif b==a*value:op="/";a,b=b,a
        else:raise ValueError(f"{p.id}: invalid native arithmetic")
        recipes[value]=(op,a,b);known.add(value)
    require(set(p.targets)<=known,f"{p.id}: native result omitted a target")
    if len(rows)+len(p.seeds)<=p.registers:
        return encode(p,tuple(recipes))
    return compile_graph(p,recipes,attempts=8,recompute=False,schedule_width=8,operation_width=8)


def make_bank(p, raw_puzzle, arm, rows):
    label=f"{p.id}/{arm}"
    require(isinstance(rows,list) and rows,f"{label}: empty parent list")
    require(arm!="one" or len(rows)==1,f"{label}: exactly one parent is required")
    require(arm!="multi" or len(rows)>=2,f"{label}: at least two parents are required")
    parents=[];programs=[];traces=[]
    for index,row in enumerate(rows):
        ref=f"{label}/{index}"
        require(isinstance(row,dict) and isinstance(row.get("source"),str) and row["source"],f"{ref}: missing source")
        program=tuple(tuple(s) for s in row["program"])
        require(len(program)+len(p.seeds)<=60,f"{ref}: more than 60 births including the seeds")
        dual_check(p,raw_puzzle,program)
        trace=replay(p,program)
        values=[s.output for s in trace]
        require(len(set(values))==len(values) and not set(values).intersection(p.seeds),
                f"{ref}: repeated births or a seed recomputation; normalize the parent before freezing")
        if "row_sha256" in row:
            packed=(json.dumps(program,ensure_ascii=False,separators=(",",":"),sort_keys=True)+"\n").encode()
            require(hashlib.sha256(packed).hexdigest()==row["row_sha256"],f"{ref}: frozen row hash mismatch")
        parents.append({"source":row["source"],"steps":len(trace),"program_sha256":digest(program),
                        "values_sha256":digest(sorted(values))})
        programs.append(program);traces.append(trace)
    start=min(map(len,traces))
    require(max(map(len,traces))<=start+8,f"{label}: parent exceeds initial shortest length + 8")
    require(start>0 and p.targets,f"{label}: generator needs at least one target and a nonempty parent")
    require(len({r["program_sha256"] for r in parents})==len(parents),f"{label}: duplicate program in parent list")
    blocks=[" ".join(map(str,[p.limit,len(p.seeds),len(p.targets),len(traces),start,*p.seeds,*p.targets]))]
    for trace in traces:
        blocks.append(str(len(trace)))
        blocks.extend(f"{s.output} {s.left} {s.right}" for s in trace)
    return ParentBank(start,next(i for i,p in enumerate(programs) if len(p)==start),programs,parents,"\n".join(blocks)+"\n")


def load_study(study_path, official_path):
    doc=json.loads(study_path.read_bytes())
    require(doc.get("schema")==1,"unknown study schema")
    require(doc.get("official_sha256")==sha256(official_path),"official input digest mismatch")
    iterations=doc["iterations"]
    require(type(iterations) is int and 0<iterations<=2**31-1,"invalid iteration budget")
    ps={p.id:p for p in read_puzzles(official_path)}
    with official_path.open(encoding="utf-8-sig",newline="") as stream:
        raw_puzzles={r["id"]:r for r in csv.DictReader(stream) if r["id"] in doc["jobs"]}
    require(isinstance(doc["jobs"],dict) and doc["jobs"],"no study cases")
    cases={}
    for pid,row in doc["jobs"].items():
        p=ps[pid];raw=raw_puzzles[pid]
        require(p.limit<=10**12,f"{pid}: official ceiling above the paired-study bound")
        seeds=row["rng"] if isinstance(row["rng"],list) else [row["rng"]]
        require(bool(seeds) and all(type(s) is int and 0<=s<=2**31-1 for s in seeds) and
                len(set(seeds))==len(seeds),f"{pid}: invalid or repeated run seed")
        arms=row["arms"]
        require(set(arms) in ({"one","multi"},{"one","multi","assisted"}),f"{pid}: unexpected arm names")
        banks={arm:make_bank(p,raw,arm,arms[arm]) for arm in ARMS if arm in arms}
        one=banks["one"];multi=banks["multi"]
        require(one.start==multi.start,f"{pid}: unmatched independent initial best")
        require(one.programs[0] in multi.programs,f"{pid}: multi does not include the one-arm parent")
        require(len({v["values_sha256"] for v in multi.parents})>=2,f"{pid}: multi has only one value family")
        profile="sparse" if p.limit<=10**9 else "large"
        cases[pid]=(p,seeds,banks,profile,raw)
    return doc,cases


def check_record(record,p,raw_puzzle,bank,meta):
    require(record["run"]==meta,f"{p.id}: cached manifest/runner/binary mismatch")
    current=bank.start;previous=-1
    for hit in record["wins"]:
        program=hit["program"];n=dual_check(p,raw_puzzle,program);iteration=hit["iteration"]
        require(previous<iteration<meta["iterations"] and n==hit["steps"]<current,f"{p.id}: bad progress")
        require(digest(program)==hit["program_sha256"],f"{p.id}: winner digest mismatch")
        current=n;previous=iteration
    events=sorted([(v["iteration"],v["native_steps"]) for v in record["wins"]]+
                  [(v["iteration"],v["native_steps"]) for v in record["refused"]]+
                  [(v["iteration"],v["native_steps"]) for v in record["dominated"]])
    last=-1;native_best=bank.start
    for iteration,cost in events:
        require(last<iteration<meta["iterations"] and cost<native_best,f"{p.id}: invalid native events")
        last=iteration;native_best=cost
    require(record["native"]["end_steps"]==native_best,f"{p.id}: incorrect native best")
    require(current==record["end_steps"] and bank.start==record["start_steps"],f"{p.id}: inconsistent costs")
    require(bank.parents==record["parents"],f"{p.id}: altered parent references")
    return record


def native_lines(binary,seed,budget,encoded):
    with subprocess.Popen([str(binary),str(seed),str(budget)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                          text=True,creationflags=getattr(subprocess,"BELOW_NORMAL_PRIORITY_CLASS",0)) as proc:
        proc.stdin.write(encoded);proc.stdin.close()
        yield from proc.stdout
        status=proc.wait()
        require(status==0,f"native process exited with code {status}")


def run_arm(p,raw_puzzle,bank,meta,binary,output):
    dest=output/"records"/p.id/f"{meta['rng']}-{meta['arm']}.json"
    if dest.exists():
        return check_record(json.loads(dest.read_bytes()),p,raw_puzzle,bank,meta)
    current=native_best=bank.start;wins=[];refused=[];dominated=[];native_end=None;retained=0
    lines=iter(native_lines(binary,meta["rng"],meta["iterations"],bank.native_input))
    for line in lines:
        fields=line.split();tag=fields[0]
        if tag=="POOL":
            require(len(fields)==int(fields[1])+2,f"{p.id}: malformed native pool")
            retained+=1
        elif tag=="WIN":
            iteration,n=map(int,fields[1:])
            rows=[tuple(map(int,next(lines).split())) for _ in range(n)]
            require(n<native_best,f"{p.id}: nonmonotone native WIN");native_best=n
            tape=compile_values(p,rows)
            if tape is None:
                refused.append({"iteration":iteration,"native_steps":n,"reason":"no verified register schedule","recipes":rows})
                continue
            steps=dual_check(p,raw_puzzle,tape)
            require(steps<=n,f"{p.id}: unexpectedly longer schedule")
            if steps>=current:
                dominated.append({"iteration":iteration,"native_steps":n,"verified_steps":steps})
                continue
            artifact=output/"witnesses"/meta["arm"]/f"{p.id}-{meta['rng']}-{steps}.csv"
            artifact.parent.mkdir(parents=True,exist_ok=True)
            write_submission(artifact,[p],{p.id:tape})
            wins.append({"iteration":iteration,"native_steps":n,"steps":steps,"program":tape,"program_sha256":digest(tape),
                         "csv":artifact.relative_to(output).as_posix(),"csv_sha256":sha256(artifact)})
            print("WIN",p.id,meta["arm"],bank.start,steps,iteration,artifact,flush=True)
            current=steps
        elif tag=="END":
            require(native_end is None and int(fields[1])==meta["iterations"] and int(fields[2])==native_best,
                    f"{p.id}: invalid terminal record")
            native_end={"end_steps":native_best,"distinct_candidate_hashes":int(fields[3]),"pool_records":retained}
        else:
            raise ValueError(f"{p.id}: unknown native output {tag}")
    require(native_end is not None,f"{p.id}: native terminal record missing")
    record={"run":meta,"parents":bank.parents,"start_steps":bank.start,"best_parent":bank.best_parent,
            "wins":wins,"refused":refused,"dominated":dominated,"end_steps":current,"native":native_end}
    check_record(record,p,raw_puzzle,bank,meta);write_json(dest,record)
    return record


def summarize(results,study_hash):
    by_pair=defaultdict(dict)
    for r in results:
        run=r["run"]
        by_pair[run["puzzle"],run["rng"]][run["arm"]]=r
    pairs=[];counts=Counter()
    for (pid,seed),group in sorted(by_pair.items()):
        if "one" not in group or "multi" not in group:continue
        one=group["one"];multi=group["multi"]
        a,b=one["end_steps"],multi["end_steps"]
        counts["one_saves"]+=one["start_steps"]-a
        counts["multi_saves"]+=multi["start_steps"]-b
        counts["one_better" if a<b else "multi_better" if b<a else "tie"]+=1
        row={"id":pid,"rng":seed,"initial":one["start_steps"],"one":a,"multi":b,
             "iterations_per_arm":one["run"]["iterations"]}
        if "assisted" in group:
            assist=group["assisted"]
            row["assisted"]={"initial":assist["start_steps"],"final":assist["end_steps"]}
        pairs.append(row)
    return {"refused_candidates":sum(len(r["refused"]) for r in results),"study_sha256":study_hash,"paired_runs":len(pairs),"distinct_puzzles":len({p["id"] for p in pairs}),
            "totals":dict(counts),"pairs":pairs}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--study",type=Path,default=HERE.parent/"study.json")
    ap.add_argument("--puzzles",type=Path,default=ROOT/"data/puzzles.csv")
    ap.add_argument("--out",type=Path,default=HERE/"results")
    ap.add_argument("--sparse-binary",type=Path,default=DEFAULT_BIN/"balance_sparse.exe")
    ap.add_argument("--large-binary",type=Path,default=DEFAULT_BIN/"balance_large.exe")
    ap.add_argument("--ids",nargs="+",help="Run an explicit subset of frozen puzzle IDs")
    ap.add_argument("--jobs",type=int,default=1)
    ap.add_argument("--validate-only",action="store_true")
    args=ap.parse_args()
    doc,cases=load_study(args.study,args.puzzles)
    study_hash=sha256(args.study)
    ids=sorted(cases) if not args.ids else sorted(set(i if i.startswith("scored_") else "scored_"+i for i in args.ids))
    require(set(ids)<=set(cases),"unknown requested puzzle")
    require(args.jobs>=1,"number of jobs must be positive")
    print(f"Validated {len(cases)} frozen cases, {sum(len(c[1]) for c in cases.values())} paired seed runs. Study {study_hash}.",flush=True)
    if args.validate_only:return
    profiles={c[3] for i,c in cases.items() if i in ids}
    bins={"sparse":args.sparse_binary.resolve(),"large":args.large_binary.resolve()}
    hashes={profile:sha256(bins[profile]) for profile in profiles}
    base_meta={"study_sha256":study_hash,"runner_sha256":sha256(Path(__file__)),"iterations":doc["iterations"]}
    results=[]
    with ThreadPoolExecutor(args.jobs) as pool:
        tasks=[]
        for pid in ids:
            puzzle,seeds,banks,profile,raw_puzzle=cases[pid]
            for seed in seeds:
                for arm,bank in banks.items():
                    meta={**base_meta,"puzzle":pid,"rng":seed,"arm":arm,"profile":profile,"binary_sha256":hashes[profile]}
                    tasks.append(pool.submit(run_arm,puzzle,raw_puzzle,bank,meta,bins[profile],args.out))
        for f in as_completed(tasks):
            r=f.result();results.append(r)
            print(r["run"]["puzzle"],r["run"]["rng"],r["run"]["arm"],r["start_steps"],r["end_steps"],flush=True)
    summary=summarize(results,study_hash)
    name="summary.json" if len(ids)==len(cases) else f"summary-subset-{digest(ids)[:12]}.json"
    write_json(args.out/name,summary)
    print(json.dumps({k:v for k,v in summary.items() if k!="pairs"},ensure_ascii=False),flush=True)


if __name__=="__main__":
    main()
