"""Search virtual programs, then reuse physical registers as intermediate values expire."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from corpus_prefix import arithmetic_edges
from elf import check, read_puzzles, read_submission, replay, sha256, write_submission
from graph import compile_graph, first_recipes


def search(job, binary, rounds, seed_offset):
    p, tape = job
    seed = seed_offset + int(p.id[-4:])
    trace = replay(p, tape)
    control = compile_graph(p, first_recipes(p,tape), attempts=6)
    best = min((x for x in (control,tape) if x is not None), key=len)
    result = dict(id=p.id, before=len(tape), recompiled=len(best), native_wins=[])
    fields = [p.limit,len(p.seeds),len(p.targets),1,len(tape),*p.seeds,*p.targets,len(trace)]
    payload = [" ".join(map(str,fields)),*(f"{s.output} {s.left} {s.right}" for s in trace)]
    out = subprocess.run([str(binary),str(seed),str(rounds)], input="\n".join(payload)+"\n",
                         text=True,capture_output=True,check=True)
    lines = iter(out.stdout.splitlines())
    for line in lines:
        parts = line.split()
        if parts[0]=="WIN":
            iteration, length = map(int,parts[1:])
            recipes = {}
            known = set(p.seeds)
            for _ in range(length):
                value,a,b = map(int,next(lines).split())
                if a not in known or b not in known:
                    raise ValueError(f"Unproduced operand in {p.id}")
                recipe = next(edge for val,edge in arithmetic_edges(a,b,p.limit) if val==value)
                if value not in known:
                    recipes[value] = recipe
                known.add(value)
            if not set(p.targets)<=known:
                raise ValueError(f"Target missing in {p.id}")
            executable = compile_graph(p,recipes,attempts=6)
            row = dict(iteration=iteration, virtual_steps=length, physical_steps=None)
            if executable is not None:
                row["physical_steps"] = check(p,executable)
                if len(executable)<len(best):
                    best = executable
            result["native_wins"].append(row)
        elif parts[0]=="END":
            result["iterations"],result["native_best"],result["visited"] = map(int,parts[1:4])
    if result.get("iterations")!=rounds:
        raise ValueError(f"Incomplete run for {p.id}")
    result["verified"] = check(p,best)
    return result,best


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lane",choices=("own","assisted"))
    parser.add_argument("submission",type=Path)
    parser.add_argument("puzzles",type=Path)
    parser.add_argument("binary",type=Path)
    parser.add_argument("output",type=Path)
    parser.add_argument("--jobs",type=int,default=2)
    args=parser.parse_args()
    design=json.loads((HERE/"design.json").read_bytes())
    if sha256(args.submission)!=design[args.lane+"_sha256"] or args.jobs<1:
        raise ValueError("Unexpected comparison snapshot or worker count")
    parents=read_submission(args.submission)
    ps={p.id:p for p in read_puzzles(args.puzzles)}
    jobs=[(ps[i],parents[i]) for i in design["ids"]]
    with ThreadPoolExecutor(args.jobs) as pool:
        tasks=[pool.submit(search,job,args.binary.resolve(),design["rounds"],design["seed_offset"]) for job in jobs]
        runs=[task.result() for task in tasks]
    programs={r["id"]:t for r,t in runs if len(t)<r["before"]}
    write_submission(args.output,[ps[i] for i in programs],programs)
    evidence=dict(lane=args.lane,parents_sha256=sha256(args.submission),official_sha256=sha256(args.puzzles),
                  binary_sha256=sha256(args.binary),wins_sha256=sha256(args.output),rows=[r for r,_ in runs])
    args.output.with_suffix(".json").write_text(json.dumps(evidence,indent=2)+"\n",encoding="utf8",newline="\n")
    print(args.lane,[(r["id"],r["before"],r["verified"]) for r,_ in runs if r["verified"]<r["before"]])


if __name__=="__main__":
    main()
