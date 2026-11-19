"""Recover product-table hypotheses and verify each exact integer identity."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
from pathlib import Path
import subprocess

from elf import read_puzzles


def recover(puzzle,exe,wide=False):
    line=" ".join(map(str,(puzzle.id,puzzle.limit,len(puzzle.targets),*puzzle.targets)))
    process=subprocess.run([exe,*(["wide"] if wide else [])],input=line+"\n",text=True,capture_output=True,check=True)
    rows=iter(process.stdout.splitlines())
    pid,count,covered,score=next(rows).split()
    if pid!=puzzle.id:raise ValueError(pid)
    hubs=list(map(int,next(rows).split())) if int(count) else []
    targets=[]
    for _ in range(int(covered)):
        fields=next(rows).split()
        t,a,b,k,r,d,e=map(int,fields[:7])
        if t!=k*a*b+r or r!=k*d+e or a not in hubs or b not in hubs or t not in puzzle.targets:
            raise ValueError("invalid recovered identity")
        targets.append(dict(t=t,a=a,b=b,k=k,r=r,d=d,e=e,weight=float(fields[7])))
    if next(rows,None) is not None:raise ValueError("trailing output")
    return dict(id=pid,hubs=hubs,targets=targets,total=len(puzzle.targets),fit=float(score))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("data",type=Path)
    ap.add_argument("output",type=Path)
    ap.add_argument("--exe",type=Path,default=Path("work/creative/matrix-recover.exe"))
    ap.add_argument("--jobs",type=int,default=2)
    ap.add_argument("--rows",type=int,default=0)
    ap.add_argument("--all",action="store_true")
    ap.add_argument("--wide",action="store_true")
    args=ap.parse_args()
    puzzles=read_puzzles(args.data)
    if not args.all:puzzles=[p for p in puzzles if max(p.seeds)<=35 and len(p.targets)>=6]
    if args.rows:puzzles=puzzles[:args.rows]
    existing={json.loads(line)["id"] for line in args.output.read_text(encoding="utf8").splitlines()} if args.output.exists() else set()
    with args.output.open("a",encoding="utf8") as out,ProcessPoolExecutor(args.jobs) as pool:
        futures=[pool.submit(recover,p,str(args.exe.resolve()),args.wide) for p in puzzles if p.id not in existing]
        for i,task in enumerate(as_completed(futures),1):
            r=task.result();out.write(json.dumps(r,separators=(",",":"))+"\n");out.flush()
            if i%60==0 or i==len(futures): print(f"{i}/{len(futures)}",flush=True)


if __name__=="__main__":main()
