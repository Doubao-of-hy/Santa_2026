"""Seed-only synthesis with physically paid, matched preliminary dictionaries."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from itertools import combinations_with_replacement
from pathlib import Path
import argparse,hashlib,json,random
from reorder import CONFIG,SEED,check,first_recipes,generate,opt,read_puzzles,write_submission
from graph import active_graph,compile_graph
from elf import arithmetic


def operations(a,b,limit):
    for op,l,r in [('+',a,b),('*',a,b),('-',max(a,b),min(a,b)),('/',max(a,b),min(a,b))]:
        if op=='/' and l%r:continue
        v=arithmetic(op,l,r)
        if 0<v<=limit:yield v,(op,l,r)


def options(p,tape):
    graph=first_recipes(p,tape);seeds=set(p.seeds);paths={};terms=Counter();uses=Counter()
    for a,b in combinations_with_replacement(p.seeds,2):
        for v,e in operations(a,b,p.limit):
            if v not in seeds:paths.setdefault(v,((v,e),))
    for x,px in list(paths.items()):
        for y in (*p.seeds,x):
            for v,e in operations(x,y,p.limit):
                if v!=x and v not in seeds:paths.setdefault(v,px+((v,e),))
    for a,b in combinations_with_replacement(sorted(v for v,path in paths.items() if len(path)==1),2):
        for v,e in operations(a,b,p.limit):
            if v not in seeds and v not in paths:
                edges=tuple(dict.fromkeys((*paths[a],*paths[b],(v,e))))
                paths[v]=edges
    for _,a,b in graph.values():uses.update({a,b})
    for t in p.targets:terms.update(active_graph(p,graph,[t]).keys())
    for v in graph:
        sub=active_graph(p,graph,[v])
        if len(sub)<=4 and (v not in paths or len(paths[v])>len(sub)):paths[v]=tuple(sub.items())
    return paths,terms,uses


def matched_header(p,paths,terms,uses,case):
    rng=random.Random(SEED+731*case+int(p.id[-4:]))
    floor=(1,max(p.seeds),max(p.seeds)**2,1,max(p.seeds))[case]
    eligible=[v for v in paths if v>floor and v not in p.targets]
    ballot=[v for v in eligible if terms[v]>=2]
    def score(v):
        return ((terms[v]+1)**.70*(uses[v]+1)**.65*v.bit_length()**.7/len(paths[v])**.65,v)
    ballot.sort(key=score,reverse=True)
    if not ballot:ballot=sorted(eligible,key=score,reverse=True)
    k=(1,2,1,2,3)[case]
    shift=(0,0,0,2,2)[case]
    if len(ballot)<=shift:shift=0
    chosen=ballot[shift:shift+k]
    controls=[]
    for value in chosen:
        pool=[v for v in eligible if v not in chosen+controls and len(paths[v])==len(paths[value])]
        if not pool:pool=[v for v in eligible if v not in chosen+controls]
        d=min(abs(v.bit_length()-value.bit_length()) for v in pool)
        pool=sorted(v for v in pool if abs(v.bit_length()-value.bit_length())<=d+1)
        controls.append(rng.choice(pool))
    return controls,chosen


def path_for(values,paths):
    g={}
    for v in values:
        for x,e in paths[v]:g.setdefault(x,e)
    return tuple(g.items())


def construct(p,header,exe):
    starts=list(p.seeds);prefix=[]
    for v,(op,a,b) in header:
        if v in starts:continue
        prefix.append((op,starts.index(a),starts.index(b),len(starts)))
        starts.append(v)
    assert len(starts)<=p.registers
    virtual=replace(p,seeds=tuple(starts))
    tape=tuple(prefix)+generate(virtual,p.targets,exe)
    check(p,tape)
    graph=first_recipes(p,tape)
    compact=compile_graph(p,graph,attempts=4,recompute=True,schedule_width=5)
    if compact is not None and len(compact)<len(tape):tape=compact
    check(p,tape)
    return tape


def run(p,exe,out):
    initial=generate(p,p.targets,exe)
    paths,terms,uses=options(p,initial);scores={};cache={}
    pools={'random':[initial],'directed':[initial]};cases=[]
    for n in range(5):
        pairs=matched_header(p,paths,terms,uses,n);record={}
        for label,options_ in zip(pools,pairs):
            h=path_for(options_,paths)
            if h not in cache:cache[h]=construct(p,h,exe)
            t=cache[h];pools[label].append(t)
            record[label]={'count':len(options_),'header_cost':len(h),'score':len(t),
                           'fingerprint':hashlib.sha256(str(h).encode()).hexdigest()}
        cases.append(record)
    for arm,items in pools.items():
        val,t,stats=opt(p,items)
        write_submission(out/(p.id+'-'+arm+'.csv'),[p],{p.id:t})
        scores[arm]={'mixed':val,'raw':min(map(len,items)),'mix_stats':stats}
    report={'common_start':len(initial),'cases':cases,'scores':scores}
    (out/(p.id+'.json')).write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(p.id,report['common_start'],scores,flush=True)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('puzzles',type=Path)
    ap.add_argument('exe',type=Path);ap.add_argument('out',type=Path);ap.add_argument('ids',nargs='+')
    ap.add_argument('--jobs',type=int,default=2)
    a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=True);ps={p.id:p for p in read_puzzles(a.puzzles)}
    with ThreadPoolExecutor(a.jobs) as pool:
        futures=[pool.submit(run,ps['scored_'+s.zfill(4)],a.exe.resolve(),a.out) for s in a.ids]
        for f in futures:f.result()

if __name__=='__main__':main()
