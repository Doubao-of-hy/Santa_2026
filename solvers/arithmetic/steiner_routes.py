"""Replace several connected arithmetic outputs with a shared directed tree."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations
from pathlib import Path
import random
import subprocess

from elf import check, read_puzzles, read_submission, write_submission
from graph import active_graph, compile_graph, first_recipes
from solvers.gpu.gpu_join import cut_many
from solvers.gpu.gpu_schedule import schedule_like
from solvers.proofs.domain_bounds import operands


def neighborhoods(p, graph, limit):
    seeds = set(p.seeds)
    use = Counter(x for _, a, b in graph.values() for x in {a, b})
    ancestors = {s: set() for s in seeds}
    for v, (_, a, b) in graph.items():
        ancestors[v] = ancestors[a] | ancestors[b] | {v}
    core = sorted(graph, key=lambda v: (-use[v], v))
    dictionary = seeds | set(core[:33])
    rng = random.Random(p.id)
    trials = {}
    users = defaultdict(set)
    for v,(_,a,b) in graph.items():
        users[a].add(v)
        users[b].add(v)
    goals = set(p.targets)
    shared = {}
    for h,consumers in users.items():
        if h in seeds or not 2<=len(consumers)<=4:
            continue
        rim = set(consumers)
        if h in goals:
            rim.add(h)
        for depth in range(3):
            if not 2<=len(rim)<=5:
                break
            packed = tuple(sorted(rim))
            shared[packed] = max(shared.get(packed,0), min(25,len(ancestors[h])) + 4*depth + rng.random())
            expandable = sorted(rim-goals,key=lambda v:(len(users[v]),v))
            if not expandable:
                break
            v=expandable[0]
            rim=(rim-{v})|users[v]
    for pool in (set(p.targets)-seeds, (set(p.targets)-seeds) | set(core[:20]) - seeds):
        inverse = defaultdict(set)
        for t in pool:
            for b in dictionary:
                for h in operands(t,b,p.limit):
                    inverse[h].add(t)
        affinity = Counter()
        for h, links in inverse.items():
            if len(links) <= 12:
                for x,y in combinations(sorted(links),2):
                    affinity[x,y] += 1 if h not in dictionary else 2
        for t in sorted(pool):
            def closeness(x):
                shared = ancestors[x] & ancestors[t] - dictionary
                return 1.8 * min(8,affinity[tuple(sorted((x,t)))]) + len(shared) / 5 + rng.random()
            if len(pool)<2:
                continue
            others = sorted(((closeness(x),x) for x in sorted(pool-{t})), reverse=True)
            for count in (2,3,4):
                if len(others)<count-1:
                    continue
                group = tuple(sorted([t]+[x for _,x in others[:count-1]]))
                weight = sum(s for s,_ in others[:count-1])/(count-1)
                trials[group] = max(trials.get(group,0),weight)
    # Mix the best pair, triple and four-way cuts with less obvious neighbors.
    picked=[]
    for n in (2,3,4):
        choices=sorted((k for k in trials if len(k)==n),key=lambda k:-trials[k])
        if choices:
            picked.extend(choices[:max(1,limit//5)])
    tail=[g for g in trials if g not in picked]
    rng.shuffle(tail)
    # The exits of one internal fan-out give multi-terminal cuts even when
    # no output values from the puzzle itself are numerically close.
    internal=sorted(shared,key=lambda g:-shared[g])
    return list(dict.fromkeys(internal[:limit//2]+picked+tail+internal))


def context(p,graph,group,width):
    keep, paid = cut_many(p, graph, set(group))
    free = set(p.seeds) | set(paid)
    goals = sorted(set(group)-free)
    budget = len(graph)-len(keep)
    if not goals or budget <= len(goals):
        return None
    cost = {}
    required = {}
    for v, (_, a, b) in graph.items():
        if v in free:
            continue
        required[v] = required.get(a,set()) | required.get(b,set()) | {v}
    cone = set().union(*(required[t] for t in goals))
    for x in cone:
        cost[x] = len(required[x])
    use = Counter(x for v in cone for x in set(graph[v][1:]) if x in free)
    popular = Counter(x for _,a,b in paid.values() for x in {a,b})
    constants = sorted(free,key=lambda x:(x not in p.seeds,-use[x],-popular[x],x))
    anchors = sorted(free)
    generators = constants[:width]
    encoded = [p.limit,len(anchors),len(generators),len(goals),len(cost),*anchors,*generators,*goals]
    for x,n in cost.items():
        encoded.extend((x,n))
    return " ".join(map(str,encoded)),keep


def solve(task):
    p, old, exe, count, width = task
    graph = active_graph(p,first_recipes(p,old))
    cases=[]
    for g in neighborhoods(p,graph,count):
        case=context(p,graph,g,width)
        if case:
            cases.append(case)
        if len(cases)>=count:
            break
    if not cases:
        return p.id,old,0
    response=subprocess.run([str(exe)],input="\n".join(c[0] for c in cases)+"\n",
                            capture_output=True,text=True,check=True)
    lines=iter(response.stdout.splitlines())
    candidates=[]
    for _,keep in cases:
        _,count_edges=map(int,next(lines).split())
        patch={}
        for _ in range(count_edges):
            t,op,a,b=next(lines).split()
            patch[int(t)]=(op,int(a),int(b))
        try:
            new=active_graph(p,graph|patch|keep)
        except (KeyError,ValueError):
            continue
        if len(new)<len(old):
            candidates.append(new)
    if next(lines,None) is not None:
        raise ValueError("unexpected native output")
    best=old
    for new in sorted(candidates,key=len):
        if len(new)>=len(best):
            continue
        feasible=schedule_like(p,old,new)
        if feasible is None or len(feasible)>len(new):
            another=compile_graph(p,new,attempts=3,recompute=True,schedule_width=6)
            if another and (feasible is None or len(another)<len(feasible)):
                feasible=another
        if feasible and len(feasible)<len(best):
            check(p,feasible)
            best=feasible
    return p.id,best,len(cases)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("base","output","exe"):
        parser.add_argument(name,type=Path)
    for name,default in (("rows",48),("cuts",10),("width",30),("workers",3),("seed",137)):
        parser.add_argument("--"+name,type=int,default=default)
    args=parser.parse_args()
    ps=read_puzzles("data/puzzles.csv")
    base=read_submission(args.base)
    eligible=[p for p in ps if len(p.targets)>6]
    random.Random(args.seed).shuffle(eligible)
    if args.rows:
        eligible=eligible[:args.rows]
    done={};attempts=0
    with ThreadPoolExecutor(args.workers) as pool:
        for pid,pg,n in pool.map(solve,((p,base[p.id],args.exe.resolve(),args.cuts,args.width) for p in eligible)):
            done[pid]=pg;attempts+=n
            if len(done)%40==0:
                write_submission(args.output,[p for p in ps if p.id in done],done)
    write_submission(args.output,[p for p in ps if p.id in done],done)
    print(len(done),attempts,sum(len(base[k])-len(v) for k,v in done.items()))


if __name__=="__main__":main()
