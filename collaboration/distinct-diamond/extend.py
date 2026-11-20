"""Seek stronger diamond-free certificates and save independently replayable rows in batches."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import csv
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
from diamonds import find_diamond, validate

def root_paths(git):
    sys.path[:0]=[str(git/'collaboration/distinct-helper-edges'),str(git/'collaboration/subset-capacity'),str(git)]

def screen(task):
    git,p,previous,upper=task
    root_paths(git)
    from verify import capacity,choose_targets
    from domain_bounds import domains
    from lower_bounds import certificate
    m,_,minimum,_=certificate(p)
    best=previous
    states=[]
    goals=set(p.targets)
    domain={0:set(p.seeds),**dict(domains(p,min(minimum,4),3500))}
    for k,A in sorted(domain.items(),reverse=True):
        h=best-m-k
        if h<4 or best>=upper or m<=h*h//4:continue
        labels=choose_targets((A,A|goals),goals,p.limit)
        if len(labels)<=h*h//4:continue
        def ceiling(n):
            ordinary,terms=capacity(A,goals,labels,p.limit,n)
            u=terms["top_unary"];D=terms["top_degrees"];B=terms["top_pair_bonuses"];M=terms["top_mixed"]
            return n*n//4+min(u+min(D//2,B),M//2)
        c=ceiling(h)
        if c>=len(labels):continue
        status,w=find_diamond(labels,A|goals,p.limit)
        state=dict(k=k,h=h,cap=c,unsupported=len(labels),status=status)
        if w:
            assert validate(w,p.limit,labels,A|goals)
            state["witness"]=w
        if status=="ABSENT":
            n=h
            while m+k+n+1<upper and len(labels)>((n+1)**2)//4 and ceiling(n+1)<len(labels):
                n+=1
            best=max(best,m+k+n+1)
            state.update(excluded_budget=n,final_cap=ceiling(n),established=best)
        states.append(state)
    return dict(id=p.id,prior=previous,best=best,states=states)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for arg in ('git','puzzles','out','design'):parser.add_argument('--'+arg,type=Path,required=True)
    parser.add_argument('--jobs',type=int,default=4)
    parser.add_argument('--batch',type=int)
    a=parser.parse_args()
    root_paths(a.git)
    from elf import read_puzzles
    d=json.loads(a.design.read_bytes())
    assert hashlib.sha256(a.puzzles.read_bytes()).hexdigest()==d['official_sha256']
    frozen=subprocess.check_output(['git','show',d['base']+':collaboration/puzzle-bounds.csv'],cwd=a.git)
    rows={r["id"]:r for r in csv.DictReader(io.StringIO(frozen.decode()))}
    ps={p.id:p for p in read_puzzles(a.puzzles)}
    k4=json.loads((a.git/'collaboration/distinct-helper-edges/full-certificates.json').read_bytes())['rows']
    subs=json.loads((a.git/'collaboration/subset-capacity/verified.json').read_bytes())['rows']
    floors={pid:max(int(r['certified_lower']),k4.get(pid,{}).get('lower',0),subs.get(pid,{}).get('new',0)) for pid,r in rows.items()}
    assert sum(floors.values())==d['baseline_total']
    order=sorted((i for i in rows if floors[i]<int(rows[i]['best_verified_upper'])),key=lambda i:hashlib.sha256((d['order_seed']+i).encode()).digest())
    a.out.mkdir(parents=True,exist_ok=True)
    size=d['batch_size']
    for number,start in enumerate(range(0,len(order),size),1):
        if a.batch is not None and a.batch!=number:continue
        dest=a.out/f'batch-{number:02}.json'
        if dest.exists():continue
        cases=order[start:start+size]
        with ProcessPoolExecutor(a.jobs) as pool:
            result=list(pool.map(screen,[(a.git,ps[i],floors[i],int(rows[i]['best_verified_upper'])) for i in cases]))
        tmp=dest.with_suffix('.tmp');tmp.write_bytes((json.dumps(result,separators=(',',':'))+'\n').encode());tmp.replace(dest)
        print(number,len(result),sum(r['best']-r['prior'] for r in result),flush=True)
if __name__=='__main__':main()
