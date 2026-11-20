"""Replay one recorded-recipe or cut-and-rebuild control from frozen source programs."""
import argparse
import gzip
import json
from pathlib import Path
import time
from solver import search
from rooted_sets import optimize
from elf import check, read_puzzles, sha256
from graph import first_recipes
HERE=Path(__file__).resolve().parent

def signature(p,t):
    return frozenset((v,tuple(sorted((a,b)))) for v,(op,a,b) in first_recipes(p,t).items())


def worker(case):
    p,tapes,budget=case; start=time.monotonic()
    sig=[signature(p,t) for t in tapes];base=tapes[0];best=base;arm={}
    # First cross the closest topologies that still introduce new recipes, then pool all parents.
    ids=[]
    for i in range(1,len(tapes)):
        if sig[i]!=sig[0] and all(sig[i]!=sig[j] for j in ids):ids.append(i)
    ids.sort(key=lambda i:(len(sig[0]^sig[i]),len(tapes[i])))
    cases=[('pair'+str(i),[0,i]) for i in ids]+([('joint',[0,*ids])] if len(ids)>1 else [])
    for name,ind in cases:
        group=[tapes[i] for i in ind]
        if len(best)<min(map(len,group)):
            # Use a valid warm start only in the full bank that already supports the recipe.
            if name=='joint':group.append(best)
        out,z=search(p,group,budget)
        z['source_indices']=ind;arm[name]=z
        if len(out)<len(best):best=out
    return dict(id=p.id,before=len(base),after=check(p,best),arms=arm,seconds=round(time.monotonic()-start,3)),best



def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--puzzles',type=Path,required=True)
    parser.add_argument('--lane',choices=['own','assisted'],required=True)
    parser.add_argument('--mode',choices=['rooted','union'],required=True)
    parser.add_argument('--part',choices=['pilot','holdout'],default='pilot')
    parser.add_argument('--id',help='Check one puzzle in the selected part')
    args=parser.parse_args()
    design=json.loads((HERE/'design.json').read_bytes())
    if sha256(args.puzzles)!=design['official']:raise ValueError('Puzzle data hash differs')
    bank=json.loads(gzip.decompress((HERE/'parents.json.gz').read_bytes()))
    expected=json.loads(gzip.decompress((HERE/'rows.json.gz').read_bytes()))['/'.join([args.mode,args.lane,args.part])]
    ids=set(design[args.part]) if args.id is None else {args.id}
    if not ids<=expected.keys():raise ValueError('Requested puzzle outside this subset')
    count=0
    for p in read_puzzles(args.puzzles):
        if p.id not in ids:continue
        tapes=[tuple(tuple(op) for op in bank[n][p.id]['program']) for n in design['lanes'][args.lane]]
        for t in tapes:check(p,t)
        if args.mode=='union':
            record,tape=worker((p,tapes,design['budget']))
            fields=['before','after','arms']
        else:
            top=tapes[0];guides=[]
            for t in tapes[1:]:
                if t!=top and t not in guides and len(t)<=len(top)*1.55+8:guides.append(t)
            guides.sort(key=len);tape,record=optimize(p,[top,*guides[:2]],32)
            fields=['before','after','cases','rooted','variants']
        assert check(p,tape)==record['after']
        for field in fields:
            if record[field]!=expected[p.id][field]:raise ValueError((p.id,field))
        count+=1
    print(f'{count} puzzles matched the archived results')
if __name__=='__main__':main()
