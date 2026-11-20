"""Generate whole programs from official inputs. Only the process's own generated trials inform ordering."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import random
import subprocess
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=next(p for p in HERE.parents if (p/'elf.py').exists())
sys.path[:0]=[str(ROOT),str(ROOT/'generative')]
from elf import check, read_puzzles, sha256, write_submission
from graph import first_recipes
from component_select import solve as mix

CONFIG=('12','.18','60','80','16','40','1','0','0','0','2','2')
SEED=2026112047


def generate(p, order, exe):
    row=' '.join(map(str,(p.id,p.limit,len(p.seeds),len(order),*p.seeds,*order)))
    output=subprocess.run([str(exe),*CONFIG],input=row+'\n',capture_output=True,text=True,check=True)
    pid,data=output.stdout.strip().split(' ',1)
    if pid!=p.id:raise ValueError(pid)
    program=tuple(map(tuple,json.loads(data)))
    check(p,program)
    return program


def adaptive(p, order, tape, variant, rng):
    edges=first_recipes(p,tape);deps={}
    def ancestors(v):
        if v not in edges:return set()
        if v not in deps:
            _,a,b=edges[v]
            deps[v]=ancestors(a)|ancestors(b)|{v}
        return deps[v]
    sets={t:ancestors(t) for t in p.targets}
    usage=Counter(v for s in sets.values() for v in s)
    order=list(order)
    if variant%3==1:
        # Move targets with a long individual branch later so other targets may pay for it.
        shares={t:sum(1/usage[v] for v in sets[t]) for t in p.targets}
        n=max(2,len(order)//5)
        chosen=sorted(rng.sample(order,max(n,len(order)//2)),key=shares.get,reverse=True)[:n]
        for t in chosen:order.remove(t)
        for t in chosen:
            order.insert(rng.randrange(len(order)//2,len(order)+1),t)
    elif variant%3==2:
        # Frontload arithmetic that is shared by many as-yet-unbuilt targets.
        paid=set(p.seeds);pending=order[:];order=[]
        while pending:
            counts=Counter(v for t in pending for v in sets[t]-paid)
            def priority(t):
                extra=sets[t]-paid
                score=sum(min(6,counts[v]-1) for v in extra)/max(1,len(extra))
                return score+.025*rng.random()
            q=max(pending,key=priority)
            pending.remove(q);paid.update(sets[q]);order.append(q)
    else:
        # Relocate a contiguous block. Its destination maximizes shared ancestry at the join.
        n=min(len(order)-1,max(2,len(order)//4))
        start=rng.randrange(len(order)-n+1);block=order[start:start+n]
        del order[start:start+n]
        def value(i):
            left=sum(len(sets[v]&sets[block[0]]) for v in order[max(0,i-2):i])
            right=sum(len(sets[v]&sets[block[-1]]) for v in order[i:i+2])
            return left+right+rng.random()
        choices=[i for i in range(len(order)+1) if i!=start]
        pos=max(choices,key=value);order[pos:pos]=block
    return order


def opt(p, tapes):
    _, tape, detail=mix(p,tapes,3,.4)
    return check(p,tape),tape,detail


def run(p, exe, out, trials):
    generated={};report={}
    initial=list(p.targets)
    def call(order):
        k=tuple(order)
        if k not in generated:generated[k]=generate(p,k,exe)
        return generated[k]
    bases=call(initial)
    for arm in ('random','adaptive'):
        rng=random.Random(SEED+int(p.id[-4:]))
        pool=[(initial,bases)]
        for k in range(1,trials):
            if arm=='random':
                order=initial[:];rng.shuffle(order)
            else:
                selected=sorted(pool,key=lambda x:len(x[1]))[0 if k<=3 or k%3 else min(1,len(pool)-1)]
                order=adaptive(p,*selected,k,rng)
            if tuple(order) in {tuple(o) for o,_ in pool}:
                i,j=rng.sample(range(len(order)),2);order[i],order[j]=order[j],order[i]
            tape=call(order);pool.append((order,tape))
        raw=min(len(t) for _,t in pool)
        mixed,tape,stats=opt(p,[t for _,t in pool])
        write_submission(out/(p.id+'-'+arm+'.csv'),[p],{p.id:tape})
        report[arm]={'minimum':raw,'mixed':mixed,'mix_stats':stats,
                     'trials':[{'digest':hashlib.sha256(','.join(map(str,o)).encode()).hexdigest(),'score':len(t)} for o,t in pool]}
    (out/(p.id+'.json')).write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(p.id,*[(a,v['minimum'],v['mixed']) for a,v in report.items()],flush=True)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('puzzles',type=Path);ap.add_argument('exe',type=Path)
    ap.add_argument('out',type=Path);ap.add_argument('ids',nargs='+')
    ap.add_argument('--trials',type=int,default=5);ap.add_argument('--jobs',type=int,default=2)
    a=ap.parse_args();a.out.mkdir(exist_ok=True,parents=True)
    puzzles={p.id:p for p in read_puzzles(a.puzzles)}
    with ThreadPoolExecutor(a.jobs) as pool:
        futures=[pool.submit(run,puzzles['scored_'+k.zfill(4)],a.exe.resolve(),a.out,a.trials) for k in a.ids]
        for f in futures:f.result()

if __name__=='__main__':main()
