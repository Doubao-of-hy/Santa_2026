"""Minimize a fixed-order arithmetic program with optional values and 48 real registers."""
import argparse
from collections import Counter,defaultdict
from concurrent.futures import ThreadPoolExecutor,as_completed
import heapq
import json
from pathlib import Path
import random
import subprocess
import time
from crossover_lns import load_solver
from elf import check,read_puzzles,read_submission,sha256,write_submission
from graph import _allocate,active_graph,first_recipes

def skeleton(p,tape):
    first=first_recipes(p,tape);needed=active_graph(p,first)
    return {v:r for v,r in first.items() if v in needed}

def bank(p,a,b):
    values=list(dict.fromkeys((*p.seeds,*a,*b)));recent=set(values)-set(p.seeds)
    ways={v:{} for v in recent}
    for g in (a,b):
        for v,(op,l,r) in g.items():ways[v].setdefault(tuple(sorted((l,r))),(op,l,r))
    for i,x in enumerate(values):
        for y in values[:i+1]:
            lo,hi=sorted((x,y));key=(lo,hi)
            for out,op,l,r in ((x+y,'+',x,y),(hi-lo,'-',hi,lo),(x*y,'*',x,y),(hi//lo if hi%lo==0 else 0,'/',hi,lo)):
                if out in recent and out!=x and out!=y:ways[out].setdefault(key,(op,l,r))
    return {v:list(options.values()) for v,options in ways.items()}

def arrangement(p,guide,other,ways,variant):
    main=list(guide);step={v:i for i,v in enumerate(main)};desired=defaultdict(list)
    for k,v in enumerate(main):
        for _,l,r in ways[v]:
            for atom in {l,r}:
                if atom not in step:desired[atom].append(k)
    due={}
    for v in reversed(list(other)):
        if v in step:continue
        opts=sorted(desired[v])
        due[v]=opts[(len(opts)-1)//2 if variant else 0] if opts else len(main)
        for arg in set(other[v][1:]):
            if arg not in step:desired[arg].append(due[v])
    remain=[];outputs=[];depend=defaultdict(list);queue=[]
    known=set(p.seeds);waiting=set()
    for v in other:
        if v in guide:continue
        for rec in ways[v]:
            args=set(rec[1:])-known;idx=len(remain);remain.append(len(args));outputs.append(v)
            for x in args:depend[x].append(idx)
            if not args and v not in waiting:
                heapq.heappush(queue,(due[v],v));waiting.add(v)
    order=[]
    def emit(v):
        known.add(v);order.append(v)
        for j in depend[v]:
            remain[j]-=1;w=outputs[j]
            if not remain[j] and w not in waiting:
                heapq.heappush(queue,(due[w],w));waiting.add(w)
    for k,v in enumerate(main):
        while queue and queue[0][0]<=k:emit(heapq.heappop(queue)[1])
        emit(v)
    while queue:emit(heapq.heappop(queue)[1])
    assert set(order)==set(ways)
    return order

def solve(p,old,guide,ways,order,seconds):
    cp=load_solver();model=cp.CpModel();pos={v:i for i,v in enumerate(order)}
    pos.update({s:-1 for s in p.seeds});opts={}
    for i,v in enumerate(order):
        opts[v]=[r for r in ways[v] if pos[r[1]]<i and pos[r[2]]<i]
        if not opts[v]:raise ValueError('unreachable ordered value')
    # Starting with all targets, traverse backwards over every usable recipe.
    relevant=set(p.targets)
    for v in reversed(order):
        if v in relevant:
            for r in opts[v]:relevant.update(r[1:])
    seq=[v for v in order if v in relevant];where={v:i for i,v in enumerate(seq)}
    where.update({s:-1 for s in p.seeds})
    forced=set(p.targets)|set(p.seeds)
    for v in reversed(seq):
        if v in forced:forced.update(set.intersection(*(set(r[1:]) for r in opts[v])))
    # Each bit asks whether its optional value can be removed. Grounding the
    # fixed order in parallel gives an unconditional mandatory-value bound.
    optional=[v for v in seq if v not in forced]
    all_bits=(1<<len(optional))-1
    denied={v:1<<i for i,v in enumerate(optional)}
    def possible(bans,live):
        reachable={v:live for v in p.seeds}
        for v in seq:
            mask=0
            for _,a,b in opts[v]:mask|=reachable[a]&reachable[b]
            reachable[v]=mask&~bans.get(v,0)
        result=live
        for t in p.targets:result&=reachable[t]
        return result
    single=possible(denied,all_bits)
    forced.update(v for v in optional if not (single&denied[v]))
    mandatory=len(forced.intersection(seq))
    if mandatory>=len(old):return old,'singleton-bound',len(seq)
    optional=[v for v in seq if v not in forced]
    cliques=[]
    if 1<len(optional)<=340:
        # Two omitted values that destroy reachability cannot be omitted
        # together. Disjoint cliques turn those implications into a bound.
        m=len(optional);pairs=m*(m-1)//2;nbytes=(pairs+7)//8
        masks=[bytearray(nbytes) for _ in optional];j=0
        for y in range(1,m):
            for x in range(y):
                byte,bit=divmod(j,8);masks[x][byte]|=1<<bit;masks[y][byte]|=1<<bit;j+=1
        bans={v:int.from_bytes(buf,'little') for v,buf in zip(optional,masks)}
        bits=possible(bans,(1<<pairs)-1).to_bytes(nbytes,'little')
        adjacent=[set() for _ in optional];j=0
        for y in range(1,m):
            for x in range(y):
                if not bits[j//8]&(1<<(j%8)):adjacent[x].add(y);adjacent[y].add(x)
                j+=1
        left=set(range(m))
        while left:
            v=max(left,key=lambda z:len(adjacent[z]&left))
            group={v};available=adjacent[v]&left
            while available:
                w=max(available,key=lambda z:len(adjacent[z]&available));group.add(w);available&=adjacent[w]
            left-=group
            if len(group)>1:cliques.append([optional[i] for i in group])
        if mandatory+sum(len(g)-1 for g in cliques)>=len(old):return old,'pair-bound',len(seq)
    pay={v:(1 if v in forced else model.new_bool_var('')) for v in seq}
    for group in cliques:model.add(sum(pay[v] for v in group)>=len(group)-1)
    flags={};touch=defaultdict(lambda:defaultdict(list))
    for i,v in enumerate(seq):
        rs=opts[v];present=pay[v]
        if len(rs)==1:flags[v]=[present]
        else:
            flags[v]=[model.new_bool_var('') for r in rs]
            model.add(sum(flags[v])==present)
        chosen=set(guide[v][1:]) if v in guide else None
        if v not in forced:model.add_hint(present,int(v in guide))
        for flag,r in zip(flags[v],rs):
            if len(rs)>1:model.add_hint(flag,int(set(r[1:])==chosen))
            for x in set(r[1:]):
                if x not in forced:model.add(pay[x]>=flag)
                touch[x][i].append(flag)
    live=[[] for v in seq];fixed=[0]*len(seq)
    for v,birth in where.items():
        uses=touch.get(v,{})
        if not uses:continue
        suffix=None
        for t in range(max(uses)-1,birth,-1):
            update=uses.get(t+1)
            if update and not isinstance(suffix,int):
                terms=list(update);terms.extend([suffix] if suffix is not None else [])
                if any(isinstance(term,int) for term in terms):suffix=1
                elif len(terms)==1:suffix=terms[0]
                else:suffix=model.new_bool_var('');model.add_max_equality(suffix,terms)
            if isinstance(suffix,int):fixed[t]+=1
            elif suffix is not None:live[t].append(suffix)
    for i,v in enumerate(seq):
        if fixed[i]+len(live[i])+1>p.registers:
            model.add(sum(live[i])+pay[v]+fixed[i]<=p.registers)
    total=sum(pay.values());model.add(total<len(old));model.minimize(total)
    solver=cp.CpSolver();solver.parameters.max_time_in_seconds=seconds
    solver.parameters.num_search_workers=1;solver.parameters.random_seed=8903
    status=solver.solve(model)
    if status not in (cp.OPTIMAL,cp.FEASIBLE):return old,solver.status_name(status),len(seq)
    selected={}
    for v in seq:
        if not solver.value(pay[v]):continue
        selected[v]=next(r for f,r in zip(flags[v],opts[v]) if solver.value(f))
    needed=active_graph(p,selected);selected={v:r for v,r in selected.items() if v in needed}
    tape=_allocate(p,selected,False,0,fixed_order=True)
    if tape is None or check(p,tape)!=len(selected):raise ValueError('capacity model failed replay')
    return tape,solver.status_name(status),len(seq)

def ingredients(p,g,exe,count):
    lines=[' '.join(map(str,(p.id,p.limit,len(p.seeds),len(p.targets),len(g),*p.seeds,*p.targets)))]
    lines.extend(f'{v} {op} {l} {r}' for v,(op,l,r) in g.items())
    raw=subprocess.run([str(exe),str(count)],input='\n'.join(lines)+'\n',capture_output=True,check=True,text=True)
    it=iter(raw.stdout.splitlines());result={}
    for _ in range(int(next(it))):
        v,op,l,r=next(it).split();result[int(v)]=(op,int(l),int(r))
    return result

def row(p,tape,donor,seconds,orders,exe=None,count=0,live_rounds=0):
    g=skeleton(p,tape);d=skeleton(p,donor);extra=ingredients(p,g,exe,count) if count else {}
    other_with_extra=extra|d;ways=bank(p,g,other_with_extra);best=tape;states=Counter()
    previous=set()
    for k in range(orders):
        guide,other=(g,other_with_extra) if k%4<2 else (d,extra|g)
        order=arrangement(p,guide,other,ways,k%2);key=tuple(order)
        if key in previous:continue
        previous.add(key)
        if live_rounds:
            from register_livebank import solve as physical_search
            supplied={};known=set(p.seeds)
            for v in order:
                supplied[v]=next(r for r in ways[v] if r[1] in known and r[2] in known);known.add(v)
            candidate,stats=physical_search(p,supplied,live_rounds,7313+13*k,g,len(best))
            states['simulated_orders']+=stats[0]
            if candidate is not None and len(candidate)<len(best):best=candidate
        else:
            candidate,status,n=solve(p,best,guide,ways,order,seconds)
            states[status]+=1;best=candidate
    return p.id,best,states

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('base',type=Path);ap.add_argument('donor',type=Path);ap.add_argument('output',type=Path)
    ap.add_argument('--jobs',type=int,default=3);ap.add_argument('--seconds',type=float,default=.6)
    ap.add_argument('--rows',type=int,default=0);ap.add_argument('--orders',type=int,default=2)
    ap.add_argument('--menu',type=int,default=0);ap.add_argument('--exe',type=Path,default=Path('work/gpu/ingredient-menu.exe'))
    ap.add_argument('--live-rounds',type=int,default=0,help='Dynamically choose recipes and evictions instead of a fixed-order model')
    args=ap.parse_args();puzzles=read_puzzles('data/puzzles.csv');a=read_submission(args.base);b=read_submission(args.donor)
    selected=list(puzzles);random.Random(41993).shuffle(selected)
    if args.rows:selected=selected[:args.rows]
    meta=dict(base_sha=sha256(args.base),donor_sha=sha256(args.donor),solver_sha=sha256(Path(__file__)),orders=args.orders,seconds_per_order=args.seconds)
    if args.menu:meta.update(menu=args.menu,menu_exe_sha=sha256(args.exe))
    if args.live_rounds:meta.update(live_rounds=args.live_rounds,live_exe_sha=sha256(Path('work/gpu/live-menu.exe')))
    out={};counts=Counter();start=time.monotonic()
    if args.output.is_file() and args.output.with_suffix('.json').is_file():
        log=json.loads(args.output.with_suffix('.json').read_text())
        if all(log.get(k)==v for k,v in meta.items()):
            saved=read_submission(args.output)
            if len(saved)==log['rows'] and set(saved)<={p.id for p in selected}:
                out=saved;counts.update(log['solver_status'])
    def save():
        write_submission(args.output,[p for p in puzzles if p.id in out],out)
        info=dict(meta,rows=len(out),wins=sum(len(a[i])>len(v) for i,v in out.items()),saved=sum(len(a[i])-len(v) for i,v in out.items()),solver_status=dict(counts),elapsed=round(time.monotonic()-start,2))
        args.output.with_suffix('.json').write_text(json.dumps(info,indent=2));print(info['rows'],info['saved'],flush=True)
    with ThreadPoolExecutor(args.jobs) as pool:
        fut=[pool.submit(row,p,a[p.id],b[p.id],args.seconds,args.orders,args.exe.resolve(),args.menu,args.live_rounds) for p in selected if p.id not in out]
        for work in as_completed(fut):
            i,tape,res=work.result();out[i]=tape;counts.update(res)
            if len(out)%25==0:save()
    save()
if __name__=='__main__':main()
