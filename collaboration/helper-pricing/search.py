"""Compare the measured LP gain of each new helper with structural selection."""
import argparse
import csv
import hashlib
import io
import json
import math
import os
import subprocess
import sys
from collections import Counter, defaultdict
from itertools import combinations_with_replacement
from pathlib import Path
from scipy.optimize import linprog
from scipy.sparse import coo_matrix

COMMIT = 'aca4989fad3a364af53362841790b7e65d935f12'
ARMS = ('existing', 'frequency', 'linear')
MAX_SCREEN = 18
MAX_HELPERS = 4

def fingerprint(data):
    return hashlib.sha256(data).hexdigest()

def inverse_values(v,u,limit):
    if v>u: yield v-u, '+', False
    if v+u<=limit: yield v+u, '-', False
    if u>v: yield u-v, '-', True
    if v%u==0: yield v//u,'*',False
    if v<=limit//u: yield v*u,'/',False
    if u%v==0: yield u//v,'/',True

def ingredients(p, tape):
    from solvers.graphs.corpus_prefix import arithmetic_edges
    from graph import active_graph, first_recipes
    ordered=first_recipes(p,tape)
    live=active_graph(p,ordered)
    original={v:r for v,r in ordered.items() if v in live}
    rank={x:-1 for x in p.seeds}|{x:i for i,x in enumerate(original)}
    values=sorted(rank)
    fixed=defaultdict(set)
    producers=defaultdict(list)
    users=Counter(x for v,(_,a,b) in original.items() for x in {a,b})
    users.update(set(p.targets))
    private={}
    def cost(x):
        return private.get(x,0) if users[x]==1 else 0
    for v,(_,a,b) in original.items():private[v]=1+sum(cost(x) for x in {a,b})
    for a,b in combinations_with_replacement(values,2):
        for v,recipe in arithmetic_edges(a,b,p.limit):
            if v in (a,b):continue
            if v not in rank:producers[v].append((max(rank[a],rank[b]),recipe))
            elif max(rank[a],rank[b])<rank[v]:fixed[v].add(recipe)
    def canon(e):
        op,a,b=e
        return (op,min(a,b),max(a,b)) if op in '+*' else e
    for v,e in original.items():
        e=canon(e)
        fixed[v]={e,*sorted(fixed[v]-{e},key=lambda r:(max(rank[r[1]],rank[r[2]]),r))[:7]}
    for h,prods in producers.items():
        prods.sort()
        if len(prods)>4:del prods[4:]
    outgoing=defaultdict(lambda:defaultdict(set))
    for v in original:
        pos=rank[v]
        for u in values:
            if rank[u]>=pos:continue
            for h,op,rev in inverse_values(v,u,p.limit):
                if h in producers and producers[h][0][0]<pos:
                    outgoing[h][v].add(canon((op,u,h) if rev else (op,h,u)))
        for h,e in ((v//2,('+',v//2,v//2)),(math.isqrt(v),('*',math.isqrt(v),math.isqrt(v)))):
            if (h+h if e[0]=='+' else h*h)==v and h in producers and producers[h][0][0]<pos:
                outgoing[h][v].add(e)
    def structural(h):
        entries=outgoing[h]
        return (-sum(min(private[v],5) for v in entries),-len(entries),producers[h][0][0],h)
    top=sorted((h for h,entries in outgoing.items() if len(entries)>=2),key=structural)
    options={}
    for h in top[:MAX_SCREEN]:
        # Insert h at its earliest producer. An alternative producer may be kept only
        # when it precedes every proposed consumer, to keep the LP bank acyclic.
        first=min(rank[v] for v in outgoing[h])
        bundle={h:{e for pos,e in producers[h] if pos<first}}
        for v,edges in outgoing[h].items():bundle[v]=set(sorted(edges)[:2])
        options[h]=bundle
    return original,fixed,options,len(top)

def extend_bank(fixed,bundles):
    current={v:set(edges) for v,edges in fixed.items()}
    for bundle in bundles:
        for v,edges in bundle.items():current.setdefault(v,set()).update(edges)
    return current

def relaxed(bank,targets):
    # pay[v] measures fractional construction, and one sum of recipe masses
    # per consumer cannot use input u more than the amount purchased of u.
    nodes=list(bank);n=len(nodes);pos={v:i for i,v in enumerate(nodes)}
    cost=[1.0]*n
    bounds=[(1,1) if v in targets else (0,1) for v in nodes]
    er=[];ec=[];ed=[];ur=[];uc=[];ud=[];constraints=0
    for idx,v in enumerate(nodes):
        er.append(idx);ec.append(idx);ed.append(-1)
        consumers=defaultdict(list)
        for _,a,b in sorted(bank[v]):
            col=len(cost);cost.append(0.0);bounds.append((0,1))
            er.append(idx);ec.append(col);ed.append(1)
            for u in {a,b}:
                if u in pos:consumers[u].append(col)
        for u,cols in consumers.items():
            ur.extend([constraints]*(1+len(cols)));uc.extend([pos[u],*cols]);ud.extend([-1,*([1]*len(cols))]);constraints+=1
    eq=coo_matrix((ed,(er,ec)),shape=(n,len(cost))).tocsr()
    ub=coo_matrix((ud,(ur,uc)),shape=(constraints,len(cost))).tocsr()
    res=linprog(cost,A_eq=eq,b_eq=[0]*n,A_ub=ub,b_ub=[0]*constraints,bounds=bounds,method='highs-ds')
    if not res.success:raise ValueError(res.message)
    return res.fun

def compare(p,tape):
    from selector import compile_selection
    from elf import check
    base,fixed,options,n=ingredients(p,tape)
    targets=set(p.targets)
    bound=relaxed(fixed,targets)
    estimates={h:bound-relaxed(extend_bank(fixed,[b]),targets) for h,b in options.items()}
    order={h:i for i,h in enumerate(options)}
    frequency=list(options)[:MAX_HELPERS]
    linear=sorted(options,key=lambda h:(-round(estimates[h],7),order[h]))[:MAX_HELPERS]
    results={};programs={}
    for method,selection in zip(ARMS,([],frequency,linear)):
        bank=extend_bank(fixed,[options[h] for h in selection])
        paths=({v:e} for v,edges in bank.items() for e in edges)
        metrics,program=compile_selection(p,tape,base,paths,False)
        assert check(p,program)==len(program)
        results[method]=dict(metrics,chosen=selection);programs[method]=program
    diag=dict(initial=len(tape),initial_relaxation=bound,candidates=n,
              scored=len(estimates),gains=estimates,arms=results)
    return diag,programs

def table(blob):
    return {r['id']:tuple(tuple(x) for x in json.loads(r['program'])) for r in csv.DictReader(io.StringIO(blob.decode('utf-8-sig')))}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo',type=Path,required=True);ap.add_argument('--puzzles',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True);ap.add_argument('--group',choices=['development','holdout','synthetic'],required=True)
    a=ap.parse_args();repo=a.repo.resolve();a.out.mkdir(exist_ok=True,parents=True)
    sys.path[:0]=[str(repo),str(repo/'collaboration/structure-controls/ruler')]
    from elf import read_puzzles,write_submission,Puzzle,check
    from checkpoint import independent_score
    from graph import compile_graph
    seeds=(1,13,17,23,31);p=Puzzle('planted',seeds,(244,252),10000)
    original={12:('-',13,1),204:('*',12,17),227:('+',204,23),244:('+',227,17),235:('+',204,31),252:('+',235,17)}
    tape=compile_graph(p,original)
    if a.group=='synthetic':
        result,programs=compare(p,tape);print('synthetic',check(p,tape),[(m,len(t)) for m,t in programs.items()])
        (a.out/'positive.json').write_text(json.dumps(result,indent=1),encoding='utf8')
        assert len(programs['linear'])==3<len(programs['existing']);return
    ps=read_puzzles(a.puzzles);by={p.id:p for p in ps}
    load=lambda f:subprocess.check_output(['git','-C',str(repo),'show',COMMIT+':'+f])
    blobs={lane:load(f) for lane,f in [('pure','submission.csv'),('assisted','public-assisted/submission.csv')]}
    banks={k:table(v) for k,v in blobs.items()}
    ids=sorted(banks['assisted'],key=lambda k:(len(banks['assisted'][k]),k))
    start,stop=(0,1) if a.group=='development' else (1,3)
    cohort=[k for i in range(8) for k in sorted(ids[i*125:(i+1)*125],key=lambda k:hashlib.sha256(('helper-price/1/'+k).encode()).digest())[start:stop]]
    for lane,bank in banks.items():
        wins={};rows=[]
        for k in cohort:
            result,alternatives=compare(by[k],bank[k])
            name=min(ARMS,key=lambda m:len(alternatives[m]))
            if len(alternatives[name])<len(bank[k]):wins[k]=alternatives[name]
            rows.append(dict(id=k,best=name,**result))
            print(lane,a.group,k,len(bank[k]),*[len(alternatives[m]) for m in ARMS],flush=True)
        f=a.out/(lane+'-'+a.group)
        write_submission(f.with_suffix('.csv'),[p for p in ps if p.id in wins],wins)
        from tempfile import TemporaryDirectory
        with TemporaryDirectory(dir=a.out) as tmp:
            full=Path(tmp)/'full.csv';n=write_submission(full,ps,bank|wins)
            assert n==sum(independent_score(a.puzzles,full));sha=fingerprint(full.read_bytes())
        f.with_suffix('.json').write_text(json.dumps(dict(commit=COMMIT,group=a.group,lane=lane,sha256=fingerprint(blobs[lane]),full_total=n,full_sha256=sha,rows=rows),indent=1),encoding='utf8')

if __name__=='__main__':main()
