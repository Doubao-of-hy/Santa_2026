"""Run a virtual-register planner, then compile each arithmetic graph to 48 registers."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
from pathlib import Path
import random
import sqlite3
import subprocess
import time

from elf import check, read_puzzles, read_submission, sha256, write_submission
from graph import active_graph, compile_graph, first_recipes


def solve(exe, settings, batch):
    lines=[]
    for p, incumbent, warm in batch:
        graph=first_recipes(p,incumbent) if warm else {}
        lines.append(" ".join(map(str,(p.id,p.limit,len(p.seeds),len(p.targets),
                                       *p.seeds,*p.targets,len(graph)))))
        lines.extend(f"{v} {op} {a} {b}" for v,(op,a,b) in graph.items())
    response=subprocess.run([exe,*settings],input="\n".join(lines)+"\n",
                            capture_output=True,encoding="ascii")
    if response.returncode:
        raise RuntimeError(f"planner failed on {[p.id for p,_,_ in batch]}: {response.stderr}")
    stream=iter(response.stdout.splitlines())
    rows=[]
    for p,incumbent,_ in batch:
        pid,n=next(stream).split()
        if pid!=p.id:
            raise ValueError(f"expected {p.id}, got {pid}")
        graph={}
        for _ in range(int(n)):
            v,op,a,b=next(stream).split()
            graph[int(v)]=(op,int(a),int(b))
        bound=len(active_graph(p,graph))
        program=compile_graph(p,graph,attempts=8,recompute=True,schedule_width=10)
        rows.append((pid,program,bound))
    if next(stream,None) is not None:
        raise ValueError("unexpected trailing planner output")
    return rows


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("puzzles",type=Path)
    ap.add_argument("incumbent",type=Path)
    ap.add_argument("output",type=Path)
    ap.add_argument("--exe",type=Path,default=Path("work/virtual/planner.exe"))
    ap.add_argument("--leaves",type=int,default=72)
    ap.add_argument("--scan",type=int,default=1)
    ap.add_argument("--width",type=int,default=4)
    ap.add_argument("--alpha",type=float,default=.18)
    ap.add_argument("--lookahead",type=float,default=.32)
    ap.add_argument("--tail",type=int,default=0)
    ap.add_argument("--style",type=int,default=0)
    ap.add_argument("--seed",type=int,default=17)
    ap.add_argument("--jobs",type=int,default=4)
    ap.add_argument("--rows",type=int,default=0)
    ap.add_argument("--ids",type=Path)
    ap.add_argument("--checkpoint",type=int,default=25)
    ap.add_argument("--fresh",action="store_true")
    ap.add_argument("--metrics",type=Path)
    ap.add_argument("--joins",type=int,default=0)
    ap.add_argument("--journal",type=Path,
                    help="Store every raw program and resume matching work after interruption")
    ap.add_argument("--raw",type=Path,help="Write all successfully generated programs, including donors")
    args=ap.parse_args()
    puzzles=read_puzzles(args.puzzles)
    initial=read_submission(args.incumbent)
    rows=puzzles.copy()
    random.Random(args.seed).shuffle(rows)
    if args.ids:
        selected=set(args.ids.read_text().split())
        rows=[p for p in rows if p.id in selected]
    if args.rows:
        rows=rows[:args.rows]
    if not rows:
        raise ValueError("empty selection")
    programs=initial.copy()
    settings=list(map(str,(args.leaves,args.scan,args.width,args.alpha,args.lookahead,
                           args.tail,args.style,args.seed)))
    if args.joins: settings.append(str(args.joins))
    journal_path=args.journal or args.output.with_suffix(".sqlite")
    journal_path.parent.mkdir(exist_ok=True,parents=True)
    db=sqlite3.connect(journal_path)
    db.execute("CREATE TABLE IF NOT EXISTS run (settings TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS solved (id TEXT PRIMARY KEY, program TEXT, graph INTEGER)")
    signature=json.dumps([sha256(args.puzzles),sha256(args.exe),settings,
                          None if args.fresh else sha256(args.incumbent)])
    old=db.execute("SELECT settings FROM run").fetchone()
    if old and old[0]!=signature:
        raise ValueError(f"{journal_path} contains a different search configuration")
    if not old:
        db.execute("INSERT INTO run VALUES (?)",(signature,))
        db.commit()
    total=delta=improved=done=0
    start=time.monotonic()
    by_id={p.id:p for p in rows}
    raw={}
    previous=set()
    metrics=[]
    failures=[]
    def accept(pid,program,bound):
        nonlocal done,total,delta,improved
        done+=1
        if program is None:
            return
        check(by_id[pid],program)
        raw[pid]=program
        total+=len(program)
        metrics.append(f"{pid},{len(initial[pid])},{bound},{len(program)}\n")
        gain=len(programs[pid])-len(program)
        if gain>0:
            programs[pid]=program
            delta+=gain
            improved+=1
    for pid,packed,bound in db.execute("SELECT id,program,graph FROM solved ORDER BY rowid"):
        if pid not in by_id: continue
        previous.add(pid)
        program=tuple(map(tuple,json.loads(packed))) if packed is not None else None
        accept(pid,program,bound)
    def export():
        result=write_submission(args.output,puzzles,programs)
        if args.raw and raw:
            write_submission(args.raw,[p for p in puzzles if p.id in raw],raw)
        if args.metrics:
            args.metrics.write_text("id,incumbent,graph,instructions\n"+"".join(metrics),encoding="ascii")
        print(f"{done}/{len(rows)} score {result} gain {delta} on {improved}, "
              f"raw steps {total}, errors {len(failures)}, {time.monotonic()-start:.1f}s",flush=True)
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        futures={pool.submit(solve,str(args.exe.resolve()),settings,
                             [(p,initial[p.id],not args.fresh)]):p.id for p in rows if p.id not in previous}
        for future in as_completed(futures):
            try:
                answer=future.result()
                for pid,program,bound in answer:
                    accept(pid,program,bound)
                    packed=json.dumps(program,separators=(",",":")) if program is not None else None
                    db.execute("INSERT INTO solved VALUES (?,?,?)",(pid,packed,bound))
                db.commit()
            except Exception as error:
                failures.append(futures[future])
                print(f"{futures[future]} failed: {error!r}",flush=True)
            if done and done%args.checkpoint==0:
                try:
                    export()
                except OSError as error:
                    print(f"CSV export deferred; rows saved in {journal_path}: {error}",flush=True)
    export()
    db.close()
    if failures:
        raise RuntimeError(f"unresolved planner errors on {len(failures)} rows: {failures[:12]}")


if __name__=="__main__":
    main()
