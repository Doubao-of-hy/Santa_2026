"""Replace private target computations using near-rational relationships to live values."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor,as_completed
from functools import lru_cache
import hashlib
import heapq
import json
from pathlib import Path
import random
import sqlite3

from elf import check, read_puzzles, read_submission, sha256, write_submission
from graph import active_graph,compile_graph,first_recipes
from gpu_join import cut_many
from gpu_schedule import schedule_like


def convergents(a,b,bound):
    h0,h1,k0,k1=0,1,1,0
    while b:
        f,r=divmod(a,b)
        h,k=f*h1+h0,f*k1+k0
        if max(h,k)>bound:break
        if min(h,k)>0:yield h,k
        h0,h1,k0,k1=h1,h,k1,k
        a,b=b,r


def alternatives(p,graph,y):
    keep,free_graph=cut_many(p,graph,{y})
    budget=len(graph)-len(keep)
    if budget<3:return []
    free=set(p.seeds)|set(free_graph)
    use=Counter(x for _,a,b in keep.values() for x in (a,b))
    # Restrict the constant dictionary to independent retained nodes. Every
    # chosen recipe can then be materialized without reintroducing the pivot.
    core=sorted(free,key=lambda x:(x not in p.seeds,-use[x],x))[:85]
    one={}
    for i,a in enumerate(core):
        for b in core[:i+1]:
            if a+b<=p.limit:one.setdefault(a+b,('+',a,b))
            if a!=b:one.setdefault(abs(a-b),('-',max(a,b),min(a,b)))
            if a*b<=p.limit:one.setdefault(a*b,('*',a,b))
            if a%b==0:one.setdefault(a//b,('/',a,b))
            if b%a==0:one.setdefault(b//a,('/',b,a))
    offsets=sorted({0,*[x for x in free if x<1<<25],*range(1,25)})
    signed=sorted({r for u in offsets for r in (u,-u)})
    @lru_cache(None)
    def residues(d):
        out={}
        for r in signed:out.setdefault(r%d,[]).append(r)
        return {key:sorted(vals,key=abs)[:18] for key,vals in out.items()}
    @lru_cache(None)
    def purchase(v):
        if v in free:return ()
        if v in one:return ((v,one[v]),)
        for b in core:
            for w,op,rev in ((v-b,'+',False),(v+b,'-',False),(b-v,'-',True),
                             (v//b if v%b==0 else 0,'*',False),(v*b,'/',False),
                             (b//v if b%v==0 else 0,'/',True)):
                if w in one and w!=v:
                    return ((w,one[w]),(v,(op,b,w) if rev else (op,w,b)))
        return None
    moves={}
    def offer(x,h,n,d):
        if min(h,n,d)<1 or max(h*n,h*d)>p.limit:return
        dx=h*d-x;dy=y-h*n
        if not (dx or dy or n!=d):return
        extra={}
        def define(v,op,a,b):
            if v not in free:extra.setdefault(v,(op,a,b))
        def literal(v):
            if v<=1 or v in free or v in extra:return True
            nodes=purchase(v)
            if nodes is None:return False
            for z,r in nodes:extra.setdefault(z,r)
            return True
        def adjust(a,difference):
            if difference:define(a+difference,'+' if difference>0 else '-',a,abs(difference))
        required={abs(dx),abs(dy),n,d}-{0}
        # One can be needed as an offset even if it is not initially present.
        if 1 in required and 1 not in free:
            extra[1]=('/',p.seeds[0],p.seeds[0])
        if not all(literal(z) for z in required):return
        adjust(x,dx)
        if d!=1:define(h,'/',h*d,d)
        if n!=1:define(h*n,'*',h,n)
        adjust(h*n,dy)
        if y not in extra:return
        # Drop unused numerical coincidences before pricing the proposal.
        used={};visiting=set()
        def gather(z):
            if z in free or z in used:return True
            if z in visiting or z not in extra:return False
            op,a,b=extra[z];visiting.add(z)
            if not gather(a) or not gather(b):return False
            visiting.remove(z);used[z]=(op,a,b)
            return True
        if not gather(y) or len(used)>=budget:return
        moves.setdefault(tuple(sorted(used)),used)
    # One partial quotient between convergents can also be a known multiplier.
    anchors=[x for x in free if x>=128 and abs(x.bit_length()-y.bit_length())<=19]
    for x in anchors:
        fractions=set(convergents(y,x,32768))
        for d in (1,2,3,4,5,7,8,9,12,16,24,32,64,128,256):
            n=(y*d+x//2)//x
            if n>0 and n<=32768 and n in free:fractions.add((n,d))
        for n,d in fractions:
            if abs(y*d-x*n)>512*n*d:continue
            if n>1 and n not in free and n not in one:continue
            if d>1 and d not in free and d not in one:continue
            if n==d:
                gap=y-x
                if gap and abs(gap)<=1<<25:offer(x,x,1,1)
                continue
            h0=(x+d//2)//d
            guesses={h0,(y+n//2)//n}
            guesses.update((x-r)//d for r in residues(d).get(x%d,()) if abs(r)<=d*768)
            guesses.update((y-r)//n for r in residues(n).get(y%n,()) if abs(r)<=n*768)
            for h in guesses:
                if h<2:continue
                dx=abs(h*d-x);dy=abs(y-h*n)
                approx=1+int(n!=1)+int(d!=1)+int(dx!=0)+int(dy!=0)
                approx+=sum(v not in free for v in {n,d,dx,dy}-{0,1})
                if approx<=budget+2:offer(x,h,n,d)
    return heapq.nsmallest(8,moves.values(),key=len)


def improve(p,old,rounds):
    best=old
    for _ in range(rounds):
        graph=active_graph(p,first_recipes(p,best))
        found=[]
        for y in p.targets:
            if y<128:continue
            for patch in alternatives(p,graph,y):
                try:new=active_graph(p,graph|patch)
                except (KeyError,ValueError):continue
                if len(new)<len(graph):found.append((len(new),patch))
        before=len(best)
        for _,patch in sorted(found,key=lambda pair:pair[0]):
            try:new=active_graph(p,graph|patch)
            except (KeyError,ValueError):continue
            if len(new)>=len(graph):continue
            prog=schedule_like(p,best,new)
            if not prog or len(prog)>len(new):
                other=compile_graph(p,new,attempts=3,recompute=True,schedule_width=6)
                if other and (not prog or len(other)<len(prog)):prog=other
            if prog and len(prog)<len(best):check(p,prog);best=prog;graph=new
        if len(best)==before:break
    return best


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('base',type=Path);ap.add_argument('output',type=Path)
    ap.add_argument('--rows',type=int,default=60);ap.add_argument('--jobs',type=int,default=3)
    ap.add_argument('--rounds',type=int,default=2);ap.add_argument('--seed',type=int,default=7297)
    a=ap.parse_args();base=read_submission(a.base);puzzles=read_puzzles('data/puzzles.csv')
    selected=[p for p in puzzles if len(p.targets)>6];random.Random(a.seed).shuffle(selected)
    if a.rows:selected=selected[:a.rows]
    db=sqlite3.connect(a.output.with_suffix('.sqlite'))
    db.execute('CREATE TABLE IF NOT EXISTS runs(k TEXT PRIMARY KEY,program TEXT)')
    done={};cfg=(sha256(Path(__file__)),a.rounds)
    def export():
        write_submission(a.output,[p for p in puzzles if p.id in done],done)
        print(len(done),sum(len(base[k])-len(v) for k,v in done.items()),flush=True)
    with ProcessPoolExecutor(a.jobs) as pool:
        tasks={}
        for p in selected:
            digest=hashlib.sha256(repr((cfg,p,base[p.id])).encode()).hexdigest()
            prior=db.execute('SELECT program FROM runs WHERE k=?',(digest,)).fetchone()
            if prior:done[p.id]=tuple(map(tuple,json.loads(prior[0])));continue
            tasks[pool.submit(improve,p,base[p.id],a.rounds)]=p,digest
        for task in as_completed(tasks):
            p,k=tasks[task];prog=task.result();check(p,prog);done[p.id]=prog
            db.execute('INSERT OR REPLACE INTO runs VALUES(?,?)',(k,json.dumps(prog)));db.commit()
            if len(done)%10==0:export()
    if done:export()
    db.close()


if __name__=='__main__':main()
