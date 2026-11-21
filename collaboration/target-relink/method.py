import hashlib,json,random,subprocess,time,sys
from pathlib import Path
from elf import check
from graph import active_graph,first_recipes,compile_graph
from solvers.gpu.gpu_schedule import schedule_like
def normalized(recipe):
    op, a, b = recipe
    return (op, min(a,b), max(a,b)) if op in "+*" else recipe

def closures(puzzle, tape):
    graph = {v: normalized(r) for v,r in active_graph(puzzle,first_recipes(puzzle,tape)).items()}
    return graph, {t: frozenset(active_graph(puzzle,graph,[t]).items()) for t in set(puzzle.targets) - set(puzzle.seeds)}

def wang(p, tapes, rounds, seed):
    fields = [[1], [p.limit,p.registers,rounds,0,seed], [len(p.seeds),*p.seeds], [len(p.targets),*p.targets],[len(tapes)]]
    for t in tapes:
        fields.append([len(t)])
        fields.extend(t)
    proc = subprocess.run([str(WANG_BINARY)],input="\n".join(" ".join(map(str,l)) for l in fields)+"\n",
                          text=True,capture_output=True,check=True,timeout=180)
    raw = proc.stdout.split()
    n = int(raw[0])
    assert len(raw)==1+4*n
    answer = tuple((raw[i],int(raw[i+1]),int(raw[i+2]),int(raw[i+3])) for i in range(1,len(raw),4))
    assert check(p,answer)==n
    return answer, [int(x) for x in proc.stderr.split()]

def independent_replay(p,tape):
    registers=dict(enumerate(p.seeds))
    reached=set(p.seeds)
    for op,left,right,destination in tape:
        assert all(type(k) is int and 0<=k<p.registers for k in (left,right,destination))
        a,b=registers[left],registers[right]
        if op=="+": value=a+b
        elif op=="-": value=a-b
        elif op=="*": value=a*b
        else:
            assert op=="/" and a%b==0
            value=a//b
        assert 1<=value<=p.limit
        registers[destination]=value
        reached.add(value)
    assert set(p.targets)<=reached
    return len(tape)

def stamp(t):
    return hashlib.sha256(json.dumps(t,separators=(",",":")).encode()).hexdigest()

def path(p,a,b,direction,mode,seed):
    ag,ac=closures(p,a);bg,bc=closures(p,b)
    targets=tuple(dict.fromkeys(p.targets))
    remaining=[i for i,t in enumerate(targets) if t in ac and ac[t]!=bc[t]]
    rng=random.Random(seed)
    rng.shuffle(remaining)
    cache={}
    def combine(fixed):
        if fixed in cache:return cache[fixed]
        # The guide graph for fixed targets has priority over the left-hand graph.
        # Original targets stop expanding at any already-paid guide value.
        kept={}
        todo=[targets[i] for i in fixed]
        while todo:
            v=todo.pop()
            if v in kept or v not in bg:continue
            recipe=bg[v];kept[v]=recipe
            todo.extend(recipe[1:])
        todo=list(targets)
        while todo:
            v=todo.pop()
            if v in kept or v not in ag:continue
            recipe=ag[v];kept[v]=recipe
            todo.extend(recipe[1:])
        cache[fixed]=kept
        return kept
    previous=a;best=a if len(a)<=len(b) else b
    root_bound=len(best);fixed=frozenset();states=[]
    assert combine(fixed)==ag
    for _ in range(len(remaining)):
        if mode=="greedy":
            chosen=min(remaining,key=lambda i:(len(combine(fixed|{i})),i))
        else:chosen=remaining[0]
        remaining.remove(chosen);fixed=fixed|{chosen}
        graph=combine(fixed);nodes=len(graph)
        assert active_graph(p,graph)==graph
        if graph==ag: emitted=a
        elif graph==bg: emitted=b
        else:
            emitted=compile_graph(p,graph,attempts=4,schedule_width=2)
            if emitted is None:
                emitted=schedule_like(p,previous,graph)
            if emitted is None:
                emitted=compile_graph(p,graph,attempts=4,schedule_width=2,recompute=True)
        if emitted is not None:
            n=check(p,emitted)
            assert n==independent_replay(p,emitted)
            preserved,_=closures_graph(p,emitted)
            # If a physical schedule recomputed a value, first-use direction can change
            # but an implementation that silently substitutes another recipe is rejected.
            assert preserved==graph
            states.append({"direction":direction,"target_index":chosen,"nodes":nodes,"length":n,
                           "above_best_endpoint":n>root_bound,"sha256":stamp(emitted)})
            if n<len(best):best=emitted
            previous=emitted
        else:
            states.append({"direction":direction,"target_index":chosen,"nodes":nodes,"length":None})
        cache.clear()
    assert combine(fixed)==bg
    return states,best

def closures_graph(p,tape):
    
    from graph import first_recipes
    g=active_graph(p,first_recipes(p,tape))
    return {v:normalized(r) for v,r in g.items()}, None

def one(args):
    p,a,b,guide_source=args
    original=len(a)
    if b is None:
        return {"id":p.id,"before":original,"eligible":False},{}
    seed=int.from_bytes(hashlib.sha256(("target-relink-7b786db:"+p.id).encode()).digest()[:4],"big")%2000000000
    result={"id":p.id,"before":original,"guide":len(b),"guide_source":guide_source,"eligible":True,"seed":seed}
    wins={}
    budget=None
    for mode in ("greedy","random"):
        started=time.process_time();states=[];best=a
        for direction,left,right in (("AB",a,b),("BA",b,a)):
            partial,winner=path(p,left,right,direction,mode,seed+(direction=="BA"))
            states.extend(partial)
            if len(winner)<len(best):best=winner
        if budget is None:budget=len(states)
        assert budget==len(states)
        result[mode]={"best":len(best),"allocated":budget,"physical":sum(r["length"] is not None for r in states),
                      "above_both_endpoints":sum((r["length"] or 0)>max(original,len(b)) for r in states),
                      "distinct_physical":len({r["sha256"] for r in states if "sha256" in r}),
                      "cpu_sec":round(time.process_time()-started,5),"steps":states}
        if len(best)<original:wins[mode]=best
    started=time.perf_counter()
    control,counts=wang(p,[a,b],budget,seed)
    assert counts[0]==budget and independent_replay(p,control)==len(control)
    result["wang"]={"best":len(control),"allocated":budget,"used":counts[0],"original_crossover_calls":counts[1],
                    "native_wall_s":round(time.perf_counter()-started,5),"sha256":stamp(control)}
    if len(control)<original:wins["wang"]=control
    return result,wins
