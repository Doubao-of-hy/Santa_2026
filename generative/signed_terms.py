"""Refactor additive regions by cancellation and reusable signed subset sums."""
import argparse
import csv
import json
import random
from collections import Counter,defaultdict
from concurrent.futures import ProcessPoolExecutor,as_completed
from functools import cache
from itertools import combinations
from pathlib import Path

from run_source import ROOT
from elf import check,read_puzzles,read_submission,sha256
from graph import active_graph,first_recipes
from shrink_select import run_one
from smooth_search import apply_patches


def normalize(terms):
    counts=Counter()
    for t in terms:counts[abs(t)]+=1 if t>0 else -1
    return tuple(t if n>0 else -t for t,n in sorted(counts.items()) for _ in range(abs(n)))


def combine(a,b):
    if a*b>0:return "+",min(abs(a),abs(b)),max(abs(a),abs(b))
    return "-",max(abs(a),abs(b)),min(abs(a),abs(b))


def subtrees(p,g,scaled=False):
    roots=set(p.targets);users=defaultdict(set);ancestors={s:0 for s in p.seeds}
    index={v:i for i,v in enumerate(g)}
    for v,(_,a,b) in g.items():
        users[a].add(v);users[b].add(v)
        ancestors[v]=ancestors[a]|ancestors[b]|(1<<index[v])
    forms=defaultdict(set)
    modes=[(3,99,False),(7,3,False),(9,99,False)]
    if scaled:modes.extend(((4,3,True),(7,99,True)))
    for depth,barrier,scale in modes:
        @cache
        def expand(v,d):
            if v not in g or not d:return (v,)
            op,a,b=g[v]
            if scale and op=="*" and min(a,b)<=7:
                k=min(a,b);x=max(a,b)
                terms=expand(x,d-1) if len(users[x])<barrier else (x,)
                return normalize(terms*k) if len(terms)*k<=22 else (v,)
            if op not in "+-":return (v,)
            x=expand(a,d-1) if len(users[a])<barrier else (a,)
            y=expand(b,d-1) if len(users[b])<barrier else (b,)
            if len(x)+len(y)>28:return (v,)
            return normalize((*x,*(y if op=="+" else tuple(-t for t in y))))
        for v,r in g.items():
            if r[0] not in "+-" and not(scale and r[0]=="*" and min(r[1:])<=7):continue
            q=expand(v,depth)
            if 2<=len(q)<=18 and sum(q)==v:forms[v].add(q)
    private={}
    for v in forms:
        removed={v};stack=[v]
        while stack:
            u=stack.pop()
            for a in g[u][1:]:
                if a in g and a not in roots and a not in removed and users[a]<=removed:
                    removed.add(a);stack.append(a)
        private[v]=removed
    return forms,ancestors,index,private


def subset_tree(terms,root,limit,free,pop,share):
    n=1<<len(terms);values=[0]*n;cost=[1.e9]*n;cuts=[0]*n
    for mask in range(1,n):
        bit=mask&-mask
        values[mask]=s=values[mask^bit]+terms[bit.bit_length()-1]
        val=abs(s)
        if val>limit:continue
        if mask==bit or not s or (val!=root and val in free):
            cost[mask]=0;continue
        first=(mask-1)&mask
        while first:
            other=mask^first
            if first<other:
                a=values[first];b=values[other]
                unit=0 if not a or not b else 1
                c=cost[first]+cost[other]+unit
                if c<cost[mask]:
                    cost[mask]=c;cuts[mask]=first
            first=(first-1)&mask
        if share and cuts[mask] and val!=root:cost[mask]-=min(.65,.12*pop.get(val,0))
    patch={}
    def collect(m):
        l=cuts[m]
        if not l:return
        r=m^l;collect(l);collect(r)
        a,b=values[l],values[r]
        if a and b and a+b and abs(a+b) not in (abs(a),abs(b)):
            patch[abs(a+b)]=combine(a,b)
    if cost[-1]<1.e8:collect(n-1)
    return patch if root in patch else {}


def greedy_tree(terms,root,limit,free,pop,share):
    q=list(terms);patch={}
    while len(q)>1:
        choices=[]
        for i,j in combinations(range(len(q)),2):
            a,b=q[i],q[j];s=a+b;v=abs(s)
            if v>limit or (v==root and len(q)>2):continue
            priority=(not s, v in free, min(12,pop.get(v,0)) if share else 0,
                      -(v.bit_length()),-i,-j)
            choices.append((priority,i,j,s))
        if not choices:return {}
        _,i,j,s=max(choices);a=q[i];b=q[j]
        q.pop(j);q.pop(i)
        if s:
            if abs(s) not in free or abs(s)==root:patch[abs(s)]=combine(a,b)
            if -s in q:q.remove(-s)
            else:q.append(s)
    return patch if q==[root] and root in patch else {}


def factor_trees(terms,root,limit,known,free,pop,depth):
    factors={}
    for f in known:
        if f<2 or f>=limit:continue
        group=tuple(t for t in terms if abs(t)>f and t%f==0 and abs(t)//f in known)
        if len(group)<2 or not sum(group):continue
        q=abs(sum(group))//f
        score=len(group)+2*(q in free)+int(f in free)
        factors[f]=(score,group)
    def tree(seq,goal,paid):
        if goal in paid:return {}
        seq=normalize(seq)
        if sum(seq)<0:seq=tuple(-x for x in seq)
        if len(seq)==1:return {}
        fn=subset_tree if len(seq)<=depth else greedy_tree
        return fn(seq,goal,limit,paid,pop,True)
    for f,(_,group) in sorted(factors.items(),key=lambda x:-x[1][0])[:9]:
        signed=sum(group);v=abs(signed);q=v//f
        if v>limit or q==root or f==root:continue
        patch=tree([t//f for t in group],q,free)
        if q not in known and q not in patch:continue
        if v not in free:
            if q==1:continue
            patch[v]=("*",min(f,q),max(f,q))
        if v!=root:
            rest=list(terms)
            for term in group:rest.remove(term)
            rest.append(signed)
            patch.update(tree(rest,root,free|{v}))
        if root in patch:yield patch


def difference_trees(q,root,free,forms,term_index,g,limit,pop,depth):
    # Reuse a whole funded linear expression, then synthesize its signed
    # difference from this output. Neither leaf set has to contain the other.
    candidates=Counter()
    for t in set(q):
        for v in term_index.get(abs(t),()):
            if v in free:candidates[v]+=1
    options=[]
    for v,hits in candidates.most_common(20):
        if hits<2:break
        for other in forms[v]:
            for sign in (1,-1):
                residual=normalize((*q,*(-sign*x for x in other)))
                width=len(residual)
                if not 1<=width<=min(8,len(q)-1):continue
                amount=root-sign*v;u=abs(amount)
                if not u or u>limit or u in (v,root):continue
                options.append((width-2*(u in free),width,v,sign,amount,residual))
    seen=set()
    for _,_,v,sign,amount,residual in sorted(options)[:12]:
        u=abs(amount)
        if (v,amount,residual) in seen:continue
        seen.add((v,amount,residual))
        if u in free or len(residual)==1:patch={}
        else:
            positive=residual if amount>0 else tuple(-x for x in residual)
            builder=subset_tree if len(positive)<=depth else greedy_tree
            patch=builder(positive,u,limit,free,pop,True)
            if not patch and u not in g:continue
        if sign==1:
            patch[root]=("+",min(v,u),max(v,u)) if amount>0 else ("-",v,u)
        else:patch[root]=("-",u,v)
        yield patch


def job(p,tape,exe,depth,seconds,scaled,differences=False):
    raw=first_recipes(p,tape);g=active_graph(p,raw)
    forms,ancestors,index,private=subtrees(p,g,scaled)
    pop=Counter()
    for variants in forms.values():
        used={abs(x+y) for q in variants for x,y in combinations(q,2) if x+y}
        pop.update(used)
    term_index=defaultdict(set)
    if differences:
        for v,variants in forms.items():
            for q in variants:
                for x in q:term_index[abs(x)].add(v)
    patches=[];eligible=[]
    for v,variants in forms.items():
        bit=1<<index[v]
        free={x for x,mask in ancestors.items() if not mask&bit and x not in private[v]}
        visited=set()
        for q in sorted(variants):
            builder=subset_tree if len(q)<=depth else greedy_tree
            proposals=[builder(q,v,p.limit,free,pop,share) for share in (False,True)]
            if scaled:
                known={x for x,mask in ancestors.items() if not mask&bit}
                proposals.extend(factor_trees(q,v,p.limit,known,free,pop,depth))
            if differences:
                proposals.extend(difference_trees(q,v,free,forms,term_index,g,p.limit,pop,depth))
            for patch in proposals:
                key=tuple(sorted(patch.items()))
                if not patch or key in visited:continue
                visited.add(key);patches.append(patch)
                # A funded intermediate can be left to its original producer.
                local={x:r for x,r in patch.items() if x==v or x not in free}
                try:cost=len(active_graph(p,g|local))
                except (KeyError,ValueError):continue
                if cost<len(tape):eligible.append((len(tape)-cost,v,local))
    best=apply_patches(p,tape,raw,eligible)
    if patches and exe:
        _,best,_=run_one(p,[tape,best],None,exe,95,0,patches,False,seconds,False)
    check(p,best)
    return p.id,best,len(patches),len(eligible)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for k in ("puzzles","input","output"):ap.add_argument(k,type=Path)
    ap.add_argument("--exe",type=Path)
    ap.add_argument("--rows",type=int,default=0)
    ap.add_argument("--jobs",type=int,default=2)
    ap.add_argument("--depth",type=int,default=7)
    ap.add_argument("--component-seconds",type=float,default=0)
    ap.add_argument("--scaled",action="store_true")
    ap.add_argument("--differences",action="store_true")
    a=ap.parse_args()
    ps=read_puzzles(a.puzzles);base=read_submission(a.input);random.Random(617).shuffle(ps)
    if a.rows:ps=ps[:a.rows]
    rows={p.id:p for p in ps}
    done=read_submission(a.output) if a.output.exists() else {}
    settings=a.output.with_suffix(".settings.json")
    code=Path(__file__).resolve()
    sig=dict(input=sha256(a.input),solver=sha256(code),bank=sha256(code.with_name("shrink_select.py")),
             exe=sha256(a.exe) if a.exe else None,depth=a.depth,seconds=a.component_seconds,
             scaled=a.scaled,differences=a.differences)
    if done and json.loads(settings.read_text())!=sig:raise ValueError("checkpoint mismatch")
    settings.write_text(json.dumps(sig),encoding="utf8")
    for k,v in done.items():check(rows[k],v)
    gain=sum(len(base[k])-len(v) for k,v in done.items());total=singles=0
    with a.output.open("a",encoding="utf8",newline="") as f,ProcessPoolExecutor(a.jobs) as pool:
        w=csv.writer(f,lineterminator="\n")
        if not f.tell():w.writerow(("id","program"))
        work=[pool.submit(job,p,base[p.id],str(a.exe.resolve()) if a.exe else None,
                          a.depth,a.component_seconds,a.scaled,a.differences) for p in ps if p.id not in done]
        for i,future in enumerate(as_completed(work),len(done)+1):
            k,v,n,s=future.result();total+=n;singles+=s;gain+=len(base[k])-len(v)
            w.writerow((k,json.dumps(v,separators=(",",":"))));f.flush()
            if i%12==0 or i==len(ps):print(f"{i}/{len(ps)} saved {gain}, {total} trees, {singles} local improvements",flush=True)


if __name__=="__main__":main()
