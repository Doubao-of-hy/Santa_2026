"""Rerun three cross-version selections for one of the frozen 96 puzzles."""
import argparse,csv,gzip,json,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'generative/arsen_v15')]
from elf import read_puzzles,check
from paid import paid_alternatives
from recombine2026 import solve

def worker(x):
    p,row,old,new,inc=x
    base=len(inc);best=inc;hist={}
    arr=[[list(e) for e in t] for t in (old,new)]
    paid=sorted(set(paid_alternatives(row,arr[0],24))|set(paid_alternatives(row,arr[1],24)))
    for label,helpers,extra in [('pool',0,None),('expand',24,None),('paid',0,paid)]:
        out,stat=solve(row,arr,helpers=helpers,extra=extra,budget=.65,slack=10)
        out=tuple(tuple(v) for v in out)
        hist[label]=dict(steps=check(p,out),status=stat['status'])
        if len(out)<len(best):best=out
    return p.id,best,dict(before=base,after=len(best),arms=hist)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--puzzles',type=Path,required=True)
    parser.add_argument('--id',required=True)
    args=parser.parse_args()
    archive=json.loads(gzip.decompress((HERE/'parents.json.gz').read_bytes()))[args.id]
    p=next(p for p in read_puzzles(args.puzzles) if p.id==args.id)
    with args.puzzles.open(encoding='utf-8-sig',newline='') as f:row=next(r for r in csv.DictReader(f) if r['id']==p.id)
    parents=[tuple(tuple(op) for op in t['program']) for t in archive]
    for t in parents:check(p,t)
    i,prog,summary=worker((p,row,*parents))
    print(json.dumps(summary))
if __name__=='__main__':main()
