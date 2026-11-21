"""Recombine alternative arithmetic derivations with exact shared-ancestor costs."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import random
import sqlite3
import subprocess
import time

from elf import check, read_puzzles, read_submission, sha256, write_submission
from graph import active_graph, compile_graph, first_recipes


def optimize(exe, settings, puzzle, programs, seed,model=None,scaling=0):
    traces = [first_recipes(puzzle, program) for program in programs]
    lines = [" ".join(map(str, (puzzle.limit, len(puzzle.seeds), len(puzzle.targets),
                len(traces), *puzzle.seeds, *puzzle.targets)))]
    for trace in traces:
        lines.append(str(len(trace)))
        lines.extend(f"{v} {op} {a} {b}" for v, (op, a, b) in trace.items())
    alternatives=[]
    if model:
        from solvers.graphs.model_edges import support
        alternatives.extend(support(puzzle,model))
    if scaling:
        from solvers.arithmetic.scale_edges import alternatives as scaled
        alternatives.extend(scaled(puzzle,traces,rounded=scaling>=2))
    if alternatives:
        lines.append(str(len(alternatives)))
        lines.extend(f"{v} {op} {a} {b}" for v,op,a,b in alternatives)
    proc = subprocess.run([exe, *map(str, settings), str(seed)], input="\n".join(lines)+"\n",
                          text=True, capture_output=True, check=False)
    if proc.returncode:
        raise RuntimeError(f"{puzzle.id}: native status {proc.returncode} {proc.stderr}")
    stream = iter(proc.stdout.splitlines())
    variants = int(next(stream))
    best = programs[0]
    lower = len(best)
    for _ in range(variants):
        graph = {}
        for _ in range(int(next(stream))):
            v, op, a, b = next(stream).split()
            graph[int(v)] = (op, int(a), int(b))
        lower = min(lower, len(graph))
        if len(graph) >= len(best):
            continue
        # Keep the order of the old schedule where dependencies allow it. Several
        # reference programs use nearly all 48 registers on their original order.
        goals = tuple(v for v in traces[0] if v in graph) + puzzle.targets
        chronological = active_graph(puzzle, graph, goals)
        for ordered in (chronological, graph):
            program = compile_graph(puzzle, ordered, attempts=4, recompute=True, schedule_width=8)
            if program is not None and len(program) < len(best):
                best = program
            if len(best) == len(graph):
                break
    if next(stream, None) is not None:
        raise RuntimeError("extra records")
    check(puzzle,best)
    return puzzle.id, best, lower


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for key in ("puzzles","incumbent","output"):
        ap.add_argument(key,type=Path)
    ap.add_argument("donors",nargs="*",type=Path)
    ap.add_argument("--exe",type=Path,default=Path("work/virtual/hypergraph.exe"))
    ap.add_argument("--ids",type=Path)
    ap.add_argument("--models",type=Path)
    ap.add_argument("--scaling",type=int,default=0,choices=(0,1,2))
    for key,default in (("trials",22),("core",64),("bridges",12),("variants",3),
                        ("rows",0),("seed",6323),("workers",3),("checkpoint",15),
                        ("islands",0),("perturb",0)):
        ap.add_argument("--"+key,type=int,default=default)
    a=ap.parse_args()
    puzzles=read_puzzles(a.puzzles)
    base=read_submission(a.incumbent)
    donors=[read_submission(path) for path in a.donors]
    selected=puzzles.copy()
    random.Random(a.seed).shuffle(selected)
    models={}
    if a.models:
        models={m["id"]:m for line in a.models.read_text().splitlines()
                if line.strip() and (m:=json.loads(line))["targets"]}
        selected=[p for p in selected if p.id in models]
    if a.ids:
        ids=set(a.ids.read_text().split())
        selected=[p for p in selected if p.id in ids]
    if a.rows: selected=selected[:a.rows]
    if not selected: raise ValueError("empty selection")
    settings=(a.trials,a.core,a.bridges,a.variants)
    if a.perturb or a.islands: settings+=(a.islands,a.perturb)
    tag=(sha256(a.exe),settings,a.seed)
    if a.scaling:tag+=(a.scaling,sha256((Path(__file__).resolve().parents[2]/"solvers/arithmetic/scale_edges.py")))
    db=sqlite3.connect(a.output.with_suffix(".sqlite"))
    db.execute("CREATE TABLE IF NOT EXISTS rows (id TEXT, digest TEXT, program TEXT, lower INTEGER, PRIMARY KEY(id,digest))")
    raw={}
    completed=saved=logical=0
    started=time.monotonic()
    def record(p,program,lower):
        nonlocal completed,saved,logical
        check(p,program)
        completed+=1
        saved+=len(base[p.id])-len(program)
        logical+=len(base[p.id])-lower
        raw[p.id]=program
    def save():
        write_submission(a.output,[p for p in puzzles if p.id in raw],raw)
        print(f"{completed}/{len(selected)} physical gain {saved}, logical potential {logical}, "
              f"{time.monotonic()-started:.1f}s",flush=True)
    with ProcessPoolExecutor(a.workers) as pool:
        futures={}
        for p in selected:
            rows=tuple(dict.fromkeys([base[p.id],*(d[p.id] for d in donors if p.id in d)]))
            m=models.get(p.id)
            digest=hashlib.sha256(repr((p,tag,rows,m)).encode("ascii")).hexdigest()
            prior=db.execute("SELECT program,lower FROM rows WHERE id=? AND digest=?",(p.id,digest)).fetchone()
            if prior:
                record(p,tuple(map(tuple,json.loads(prior[0]))),prior[1])
                continue
            job=pool.submit(optimize,str(a.exe.resolve()),settings,p,rows,a.seed+int(p.id.split("_")[-1]),m,a.scaling)
            futures[job]=(p,digest)
        for job in as_completed(futures):
            p,digest=futures[job]
            pid,program,lower=job.result()
            record(p,program,lower)
            db.execute("INSERT OR REPLACE INTO rows VALUES (?,?,?,?)",
                       (pid,digest,json.dumps(program,separators=(",",":")),lower))
            db.commit()
            if completed%a.checkpoint==0: save()
    save()
    db.close()


if __name__=="__main__":
    main()
