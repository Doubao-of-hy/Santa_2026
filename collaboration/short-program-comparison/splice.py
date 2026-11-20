"""Fallback after a null assisted result. Recombine full value sets even when their union exceeds 60."""
import argparse
from collections import Counter, defaultdict
from itertools import combinations_with_replacement
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
STUDY = HERE/"replay/study.json"
sys.path.insert(0,str(ROOT))
from elf import check, read_puzzles, replay, sha256, write_submission
from graph import compile_graph
from tiny import encode

import fixed_pool as upper
from fixed_pool import outputs


def packed(data):
    return (json.dumps(data,ensure_ascii=False,separators=(',',':'),sort_keys=True)+'\n').encode()



def compile_order(p,values):
    if len(values)+len(p.seeds)<=p.registers:return encode(p,values)
    live=list(p.seeds);recipes={}
    for v in values:
        for a,b in combinations_with_replacement(live,2):
            if a+b==v:op,x,y='+',a,b
            elif a*b==v:op,x,y='*',a,b
            elif a-b==v:op,x,y='-',a,b
            elif b-a==v:op,x,y='-',b,a
            elif a==v*b:op,x,y='/',a,b
            elif b==v*a:op,x,y='/',b,a
            else:continue
            recipes[v]=(op,x,y);live.append(v);break
        else:raise ValueError('unrooted returned witness')
    return compile_graph(p,recipes,attempts=8,recompute=False,schedule_width=8,operation_width=8)


def bridge_pool(p,rows,extra):
    base=set(p.seeds)|set(p.targets);families=[]
    for row in rows:
        fam={s.output for s in replay(p,row['program'])};families.append(fam);base.update(fam)
    left=families[0]-families[-1];right=families[-1]-families[0];g=set(p.targets);start=set(p.seeds)
    birth=Counter();target_links=defaultdict(set);other_links=defaultdict(set);from_starts=set();mixed=set()
    for a,b in combinations_with_replacement(sorted(base),2):
        for v in outputs(a,b,p.limit)-base:
            birth[v]+=1
            if a in start and b in start:from_starts.add(v)
            if (a in left and b in right) or (a in right and b in left):mixed.add(v)
    for z in base-start:
        for operand in base-{z}:
            for v in upper.reverse(z,operand,p.limit):
                if v in birth:(target_links if z in g else other_links)[v].add(z)
    rank=lambda v:(-len(target_links[v]),-min(len(other_links[v]),5),-(v in from_starts),-(v in mixed),-min(birth[v],4),v)
    return sorted(base|set(sorted(birth,key=rank)[:extra]))


def run(p,j,arm,out):
    rows=j['arms'][arm];old=len(rows[0]['program']);missing=len(set(p.targets)-set(p.seeds));bank=bridge_pool(p,rows,48)
    best=old;attempts=[];cut=0;winner=None
    while len(attempts)<4 and best>missing:
        model=upper.Pool(p,bank,best-1-missing,True)
        chosen=[s.output for s in replay(p,winner if winner else rows[0]['program'])];program,reason=model.solve(set(),set(chosen),8000,30)
        cut+=model.cuts;model.solver.delete();attempts.append({'budget':best-1,'status':'UNSCHEDULED' if reason=='FOUND' and not program else reason})
        if not program:break
        assert check(p,program)<best;best=len(program);winner=program
    rec={'id':p.id,'arm':arm,'protocol_sha256':sha256(STUDY),'bank':bank,'from':old,'to':best,'attempts':attempts,'cuts':cut}
    if winner:
        target=out/f'{p.id}-{arm}-{best}.csv';write_submission(target,[p],{p.id:winner});rec.update({'file':target.name,'sha256':sha256(target)})
    (out/f'{p.id}-{arm}.json').write_bytes(packed(rec));print(p.id,arm,old,best,flush=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--id',required=True);parser.add_argument('--arm',choices=('one','multi','assisted'),required=True)
    parser.add_argument('--puzzles',type=Path,default=ROOT/'data/puzzles.csv')
    parser.add_argument('--output',type=Path,required=True)
    a=parser.parse_args()
    doc=json.loads(STUDY.read_bytes());ps={p.id:p for p in read_puzzles(a.puzzles)};pid='scored_'+a.id
    p=ps[pid];rows=doc['jobs'][pid];out=a.output;out.mkdir(exist_ok=True,parents=True)
    assert len(set(p.seeds)|{s.output for row in rows['arms']['multi'] for s in replay(p,row['program'])})>60
    upper.encode=compile_order
    run(p,rows,a.arm,out)


if __name__=='__main__':main()
