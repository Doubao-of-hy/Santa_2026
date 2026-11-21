"""Apply goal-directed forward synthesis to connected parts of long programs."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import random
import subprocess
import time

from checkpoint import atomic_text
from solvers.proofs.domain_bounds import operands
from elf import check, read_puzzles, read_submission, sha256, write_submission
from solvers.gpu.gpu_schedule import schedule_like
from solvers.gpu.gpu_join import cut_many
from graph import active_graph, compile_graph, first_recipes
from solvers.proofs.prefix_exact import add_value


def prefix_regions(p,graph,limit,seed):
    rng=random.Random(seed)
    users=defaultdict(set);seeds=set(p.seeds);goals=set(p.targets)
    for v,(_,a,b) in graph.items():users[a].add(v);users[b].add(v)
    order={v:k for k,v in enumerate(graph)}
    freq={v:len(users[v]) for v in graph}
    def exits_of(block):
        return {v for v in block if v in goals or users[v]-block}
    offers={}
    for mode in range(5):
        ready={v for v,(_,a,b) in graph.items() if a in seeds and b in seeds}
        known=set(seeds);block=set()
        for length in range(1,36):
            if not ready:break
            def priority(v):
                if mode==0:return order[v]
                if mode==1:return v
                if mode==2:return (-freq[v],v)
                if mode==3:return .15*v.bit_length()-freq[v]+rng.random()*3
                return rng.random()
            v=min(sorted(ready),key=priority);ready.remove(v);known.add(v);block.add(v)
            ready.update(x for x in users[v] if x not in known and set(graph[x][1:])<=known)
            exits=exits_of(block)
            budget=length-len(exits)-1
            if not (6<=length and 2<=len(exits)<=15 and 2<=budget<=14):continue
            signature=frozenset(block)
            if signature not in offers:
                rank=1.5*min(6,budget)+2*min(7,len(exits))-.12*max(exits).bit_length()+rng.random()*6
                offers[signature]=(rank,exits,budget,mode)
    # Sample different topological prefixes. Nearby lengths with precisely
    # the same live outputs add few new ways to rebuild the prefix.
    chosen=[];seen=set();ordered=sorted(offers,key=lambda key:-offers[key][0])
    for mode in (0,1,2,3,4,None):
        for block in ordered:
            rank,exits,budget,category=offers[block]
            if mode is not None and category!=mode:continue
            if any(len(block.symmetric_difference(x[0]))<3 for x in chosen):continue
            key=tuple(sorted(exits))
            if key in seen:continue
            seen.add(key)
            # No retained operation is needed for these inputs. The entire
            # prefix is regenerated from the official original seeds.
            cap=min(p.limit,max(512,2*max(max(block),max(seeds))+1))
            chosen.append((block,list(key),list(p.seeds),seeds,budget,cap))
            if len(chosen)>=limit:return chosen
            if mode is not None:break
    return chosen


def target_regions(p,graph,limit,seed):
    rng=random.Random(seed);seeds=set(p.seeds);goals=set(p.targets)-seeds
    ancestors={s:0 for s in seeds};bits={v:1<<i for i,v in enumerate(graph)}
    for v,(_,a,b) in graph.items():ancestors[v]=ancestors[a]|ancestors[b]|bits[v]
    use=Counter(v for _,a,b in graph.values() for v in {a,b})
    occurrence=Counter(v for v in graph for t in goals if ancestors[t]&bits[v])
    rare=sum(bits[v] for v,k in occurrence.items() if k<=5)
    candidates=set()
    for t in sorted(goals):
        nearest=sorted(goals-{t},key=lambda x:-(ancestors[x]&ancestors[t]&rare).bit_count()-rng.random()*1.8)
        candidates.add((t,))
        for n in (2,3,4):
            if len(nearest)>=n-1:candidates.add(tuple(sorted([t,*nearest[:n-1]])))
    regions=[]
    for g in sorted(candidates):
        exits=set(g);keep,grounded=cut_many(p,graph,exits)
        block=set(graph)-keep.keys();free=seeds|grounded.keys()
        inputs={q for v in block for q in graph[v][1:] if q not in block}
        budget=len(block)-len(g)-1
        if not 3<=budget<=24 or len(inputs)>16 or not inputs<=free:continue
        rank=2*len(g)+min(budget,12)-.45*len(inputs)+rng.random()*5
        regions.append((rank,block,g,inputs,free,budget))
    selected=[]
    for _,block,g,inputs,free,budget in sorted(regions,key=lambda x:-x[0]):
        if any(len(block^prev[0])<3 for prev in selected):continue
        scores=Counter()
        for t in g:
            for a in inputs:
                for b in operands(t,a,p.limit)&free:scores[b]+=1
        extras=sorted(free-inputs,key=lambda v:(-scores[v],v not in seeds,-min(5,use[v]),v))
        anchors=sorted(inputs|set(extras[:max(0,min(5,17-len(inputs)))]))
        cap=min(p.limit,max(512,2*max(max(block),max(anchors))+1))
        selected.append((block,list(g),anchors,free,budget,cap))
        if len(selected)==limit:break
    return selected


def regions(p,graph,limit,seed):
    rng=random.Random(seed)
    use=defaultdict(set);seeds=set(p.seeds);targets=set(p.targets);proposed={}
    for x,(_,a,b) in graph.items():
        use[a].add(x);use[b].add(x)
    ordered=list(graph)
    def offer(region):
        if not 4<=len(region)<=15:return
        frozen=frozenset(region)
        if frozen in proposed:return
        exits={x for x in region if x in targets or use[x]-region}
        inputs={v for x in region for v in graph[x][1:] if v not in region}
        budget=len(region)-len(exits)-1
        if not 1<=len(exits)<=6 or not 1<=budget<=8 or not 1<=len(inputs)<=10:return
        base=max(max(inputs),max(exits))
        # Multiple live exits favor routes which spend a helper more than once.
        rank=3*min(3,len(exits))+2*min(4,budget)-.55*len(inputs)-.06*base.bit_length()+rng.random()*5
        proposed[frozen]=(rank,exits,inputs,budget)
    for h in ordered:
        if 1<=len(use[h])<=5:
            region={h}|use[h]
            for _ in range(10):
                offer(region)
                rim={v for x in region for v in graph[x][1:] if v in graph and v not in region and use[v]<=region}
                if not rim:break
                region=region|{rng.choice(sorted(rim))}
            region={h}
            for _ in range(11):
                fringe={v for x in region for v in use[x] if v not in region}
                if not fringe:break
                v=min(sorted(fringe),key=lambda x:sum(y not in region for y in graph[x][1:])+rng.random()*2)
                region=region|{v};offer(region)
    for _ in range(len(graph)*2):
        pos=rng.randrange(len(ordered));size=rng.randint(5,11)
        offer(set(ordered[pos:pos+size]))
    taken=[];seen=set()
    for region,(rank,exits,inputs,budget) in sorted(proposed.items(),key=lambda pair:-pair[1][0]):
        free=set(seeds)
        for v,(_,a,b) in graph.items():
            if v not in region and a in free and b in free:free.add(v)
        if not inputs<=free:continue
        signature=(tuple(sorted(exits)),tuple(sorted(inputs)))
        if signature in seen:continue
        seen.add(signature)
        # Add a few already constructed values to the compulsory inputs.
        # Favor values that would bring an exit within one operation.
        helpful=Counter()
        for t in exits:
            for a in inputs:
                for b in operands(t,a,p.limit)&free:helpful[b]+=5
        preferred=sorted(free-inputs,key=lambda v:(-helpful[v],v not in seeds,-min(4,len(use[v])),v))
        anchors=sorted(inputs | set(preferred[:min(4,max(0,11-len(inputs)))]))
        maxval=max([*anchors,*region]);cap=min(p.limit,max(512,2*maxval+1))
        taken.append((region,sorted(exits),anchors,free,budget,cap))
        if len(taken)>=limit:break
    return taken


def solve_local(exe,width,variant,seed,region,goals,anchors,free,budget,cap,warm_graph=None):
    header=(cap,len(anchors),len(goals),budget,*anchors,*goals)
    command=[str(exe),str(width),str(variant),str(seed)]
    data=' '.join(map(str,header))+'\n'
    if warm_graph is not None:
        command.append('--warm')
        data+=str(len(region))+'\n'+''.join(f'{v} {op} {a} {b}\n' for v,(op,a,b) in warm_graph.items() if v in region)
    proc=subprocess.run(command,input=data,capture_output=True,text=True,check=True)
    lines=proc.stdout.splitlines();status,count=lines[0].split()
    if status=='NO_WITNESS':return None,int(count)
    if status!='FOUND':raise ValueError(status)
    seq=list(map(int,lines[1].split()))
    if seq[:len(anchors)]!=anchors:raise ValueError('input mismatch')
    known=set();choices={};fresh={}
    for v in anchors:add_value(v,known,choices,cap)
    for v in seq[len(anchors):]:
        if v not in choices:raise ValueError('invalid helper')
        fresh[v]=choices[v];add_value(v,known,choices,cap)
    if not set(goals)<=known or len(fresh)>=len(region):raise ValueError('false witness')
    return fresh,int(count)


def optimize(p,old,exe,limit,width,variant,seed,prefix,warm,targets):
    base=active_graph(p,first_recipes(p,old));best=old;stats=Counter()
    generate=target_regions if targets else prefix_regions if prefix else regions
    for n,case in enumerate(generate(p,base,limit,seed)):
        region,goals,anchors,free,_,_=case
        fresh,examined=solve_local(exe,width,variant,seed+n,*case,warm_graph=base if warm else None)
        stats['windows']+=1;stats['expanded']+=examined
        if fresh is None:continue
        stats['witnesses']+=1
        g={v:r for v,r in base.items() if v not in region}
        g.update({v:r for v,r in fresh.items() if v not in free})
        g=active_graph(p,g)
        if len(g)>=len(best):continue
        tape=schedule_like(p,old,g)
        if tape is None or len(tape)>len(g):
            other=compile_graph(p,g,attempts=3,recompute=True,schedule_width=6)
            if other is not None and (tape is None or len(other)<len(tape)):tape=other
        if tape is not None and len(tape)<len(best):check(p,tape);best=tape
    stats['saved']=len(old)-len(best)
    return p.id,best,dict(stats)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for k in ('base','exe','out'):ap.add_argument(k,type=Path)
    for k,n in [('rows',64),('jobs',3),('cuts',6),('width',48),('seed',27541),('variant',0),('minimum',45)]:
        ap.add_argument('--'+k,type=int,default=n)
    ap.add_argument('--prefix',action='store_true')
    ap.add_argument('--warm',action='store_true')
    ap.add_argument('--targets',action='store_true')
    a=ap.parse_args();puzzles=read_puzzles('data/puzzles.csv');base=read_submission(a.base)
    rows=[p for p in puzzles if p.id in base and len(base[p.id])>=a.minimum]
    random.Random(a.seed).shuffle(rows)
    if a.rows:rows=rows[:a.rows]
    begin=time.monotonic();wins={};allstats={};exe=a.exe.resolve()
    with ThreadPoolExecutor(a.jobs) as pool:
        futures=[pool.submit(optimize,p,base[p.id],exe,a.cuts,a.width,a.variant,
                            a.seed+int(p.id.split('_')[-1]),a.prefix,a.warm,a.targets) for p in rows]
        for task in as_completed(futures):
            pid,tape,stats=task.result();allstats[pid]=stats
            if stats['saved']>0:wins[pid]=tape
    if wins:write_submission(a.out,[p for p in puzzles if p.id in wins],wins)
    total=sum((Counter(s) for s in allstats.values()),Counter())
    report={'settings':{'rows':len(rows),'seed':a.seed,'cuts':a.cuts,'width':a.width,'variant':a.variant,
                        'prefix':a.prefix,'warm':a.warm,'targets':a.targets},
            'base_sha256':sha256(a.base),'solver_sha256':sha256(exe),'totals':dict(total),
            'seconds':round(time.monotonic()-begin,3),'rows':allstats,'wins':{i:len(t) for i,t in wins.items()}}
    atomic_text(a.out.with_suffix('.json'),json.dumps(report,indent=2)+'\n')
    print(report['totals'],report['seconds'],flush=True)

if __name__=='__main__':main()
