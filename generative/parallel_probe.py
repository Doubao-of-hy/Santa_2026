"""Measure four-target arithmetic relations against scale-matched held-out controls."""
import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path
import subprocess
from run_source import ROOT,compile_engine,compiler_path
from elf import read_puzzles


def puzzle_line(p):
    return " ".join(map(str,(p.id,p.limit,len(p.seeds),len(p.targets),*p.seeds,*p.targets)))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("output",type=Path)
    args=ap.parse_args()
    path=ROOT/"data/practice_puzzles.csv"
    puzzles=read_puzzles(path)
    with path.open() as f: labels={r["id"]:r["family"] for r in csv.DictReader(f)}
    exe,_,_=compile_engine("parallels",compiler_path(None))
    proc=subprocess.run([str(exe),"1","probe"],input="\n".join(map(puzzle_line,puzzles))+"\n",
                        capture_output=True,text=True,check=True)
    groups=defaultdict(lambda:[0]*8)
    for line in proc.stdout.splitlines():
        pid,t,variant,error,sep=line.split()
        if int(t)<10**7:continue
        error=int(error)
        record=groups[labels[pid]]
        offset=4*int(int(variant)>0)
        record[offset]+=1
        for j,band in enumerate((16,256,4096),1):
            record[offset+j]+=error<=band
    result={"minimum_target":10**7,"absolute_error_thresholds":[16,256,4096],
            "columns":"real count, real hits at thresholds, matched-null count, null hits at thresholds",
            "families":groups}
    args.output.write_text(json.dumps(result,indent=2)+"\n",encoding="utf8")
    print(json.dumps(result),flush=True)


if __name__=="__main__":
    main()
