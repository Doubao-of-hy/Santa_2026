"""Generate and verify fresh cumulative-benefit programs from puzzle inputs."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import json
from pathlib import Path
import random
import subprocess
import time

from elf import check, read_puzzles, read_submission
from graph import active_graph, compile_graph


def generate(puzzle, exe, options):
    line=" ".join(map(str,(puzzle.id,puzzle.limit,len(puzzle.seeds),len(puzzle.targets),
                           *puzzle.seeds,*puzzle.targets,0)))
    result=subprocess.run([str(exe),*options],input=line+"\n",capture_output=True,text=True)
    if result.returncode:
        raise RuntimeError(f"{puzzle.id} failed: {result.returncode} {result.stderr}")
    rows=iter(result.stdout.splitlines())
    pid,count=next(rows).split()
    if pid!=puzzle.id:
        raise ValueError("unexpected puzzle identifier")
    graph={}
    for _ in range(int(count)):
        value,op,left,right=next(rows).split()
        graph[int(value)]=(op,int(left),int(right))
    if next(rows,None) is not None:
        raise ValueError("trailing planner output")
    count=len(active_graph(puzzle,graph))
    program=compile_graph(puzzle,graph,attempts=8,recompute=True,schedule_width=10)
    if program is None:
        raise ValueError(f"{pid} could not compile its arithmetic graph")
    check(puzzle,program)
    return pid,program,count,result.stderr.strip()


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("puzzles",type=Path)
    ap.add_argument("output",type=Path)
    ap.add_argument("--exe",type=Path,default=Path("work/creative/hcub.exe"))
    ap.add_argument("--compare",type=Path)
    ap.add_argument("--ids",type=Path)
    ap.add_argument("--rows",type=int,default=0)
    ap.add_argument("--jobs",type=int,default=2)
    ap.add_argument("--leaves",type=int,default=86)
    ap.add_argument("--width",type=int,default=3)
    ap.add_argument("--refresh",type=int,default=5)
    ap.add_argument("--credit",type=float,default=.9)
    ap.add_argument("--seed",type=int,default=397)
    ap.add_argument("--bilinear",type=int,default=0)
    ap.add_argument("--joint",type=int,default=0)
    args=ap.parse_args()
    puzzles=read_puzzles(args.puzzles)
    random.Random(args.seed).shuffle(puzzles)
    if args.ids:
        lookup={p.id:p for p in puzzles}
        puzzles=[lookup[pid] for pid in args.ids.read_text().split()]
    if args.rows:
        puzzles=puzzles[:args.rows]
    existing=read_submission(args.output) if args.output.exists() else {}
    baseline=read_submission(args.compare) if args.compare else {}
    options=list(map(str,(args.leaves,args.width,args.refresh,args.credit,args.seed)))
    if args.bilinear or args.joint: options.append(str(args.bilinear))
    if args.joint: options.append(str(args.joint))
    exe=args.exe.resolve()
    flags=(args.output.with_suffix(".settings.json"))
    from hashlib import sha256
    settings=dict(executable=sha256(exe.read_bytes()).hexdigest(),options=options)
    if existing and (not flags.exists() or json.loads(flags.read_text())!=settings):
        raise ValueError("incompatible output checkpoint")
    flags.write_text(json.dumps(settings),encoding="utf8")
    raw=0
    gain=0
    wins=0
    seen=0
    unchanged=[]
    for p in puzzles:
        if p.id in existing:
            check(p,existing[p.id])
        else:
            unchanged.append(p)
    start=time.monotonic()
    with args.output.open("a",encoding="utf8",newline="") as stream, \
            args.output.with_suffix(".metrics.csv").open("a",encoding="utf8",newline="") as metrics, \
            ThreadPoolExecutor(max_workers=args.jobs) as pool:
        out=csv.writer(stream,lineterminator="\n")
        audit=csv.writer(metrics,lineterminator="\n")
        if not stream.tell():
            out.writerow(("id","program"))
        if not metrics.tell():
            audit.writerow(("id","graph","instructions","baseline","search"))
        futures=[pool.submit(generate,p,exe,options) for p in unchanged]
        for task in as_completed(futures):
            pid,program,graph,trace=task.result()
            reference=len(baseline[pid]) if pid in baseline else None
            out.writerow((pid,json.dumps(program,separators=(",",":"))))
            stream.flush()
            audit.writerow((pid,graph,len(program),reference,trace))
            metrics.flush()
            raw+=len(program)
            if reference is not None:
                gain+=max(0,reference-len(program)); wins+=reference>len(program)
            seen+=1
            if seen%10==0 or seen==len(unchanged):
                print(f"{seen}/{len(unchanged)} raw {raw}, gain {gain} on {wins}, {time.monotonic()-start:.1f}s",flush=True)


if __name__=="__main__":
    main()
