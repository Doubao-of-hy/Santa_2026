"""SPDX-License-Identifier: Apache-2.0
Original multi-trace recipe selection. Concepts: shared helpers and recipe MILPs,
attributed in SOURCES.md. No third-party source or cached programs embedded.
"""
import argparse
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
import csv
import hashlib
import heapq
import json
import os
from pathlib import Path
import random
import time

os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')

from run_solver import replay


def read_graph(starts, program):
    bank = list(starts) + [None] * (48 - len(starts))
    graph = {}
    for op, i, j, d in program:
        a, b = bank[i], bank[j]
        v = operation(op, a, b)
        if v not in starts and v not in graph:
            graph[v] = (op, a, b)
        bank[d] = v
    return graph


def operation(op, a, b):
    if op == '+': return a + b
    if op == '-': return a - b
    if op == '*': return a * b
    if op == '/':
        assert a % b == 0
        return a // b
    raise ValueError(op)


def ops(a, b, cap):
    if a + b <= cap: yield a + b, ('+', a, b)
    if a != b: yield abs(a - b), ('-', max(a, b), min(a, b))
    if a <= cap // b: yield a * b, ('*', a, b)
    if a % b == 0: yield a // b, ('/', a, b)
    if b % a == 0 and b != a: yield b // a, ('/', b, a)


def inverse(v, a, cap):
    if v > a: yield v-a, ('+', a, v-a)
    if a > v: yield a-v, ('-', a, a-v)
    if v+a <= cap: yield v+a, ('-', v+a, a)
    if v % a == 0: yield v//a, ('*', a, v//a)
    if a % v == 0: yield a//v, ('/', a, a//v)
    if v <= cap//a: yield v*a, ('/', v*a, a)


def canonical(r):
    op, a, b = r
    return (op, min(a,b), max(a,b)) if op in ('+', '*') else r


def make_pool(starts, targets, programs, cap, helpers):
    roots = set(starts)
    graphs = [read_graph(starts, p) for p in programs]
    values = list(dict.fromkeys([*starts, *(v for g in graphs for v in g)]))
    have = set(values)
    choices = {v: set() for v in values if v not in roots}
    for g in graphs:
        for v, r in g.items(): choices[v].add(canonical(r))
    for i, a in enumerate(values):
        for b in values[:i+1]:
            for v, r in ops(a,b,cap):
                if v in choices and v not in r[1:]: choices[v].add(canonical(r))
    if helpers:
        # Helpers are only kept when they join a forward and backward operation.
        # Include two witnesses to avoid prescribing one construction direction.
        middle = {}
        primary = list(dict.fromkeys([*starts, *graphs[0]]))
        for i, a in enumerate(primary):
            for b in primary[:i+1]:
                for v,r in ops(a,b,cap):
                    if v not in have:
                        bucket = middle.setdefault(v, [])
                        if len(bucket) < 2: bucket.append(canonical(r))
        uses = defaultdict(set)
        for v in graphs[0]:
            for a in primary:
                if a == v: continue
                for h,r in inverse(v,a,cap):
                    if h in middle and v not in r[1:] and h not in roots:
                        uses[h].add((v, canonical(r)))
        # Preference to helpers that bridge two or more different dependent values.
        ranked = sorted(uses, key=lambda h:(-len({v for v,_ in uses[h]}), h))[:helpers]
        for h in ranked:
            choices[h] = set(middle[h])
            values.append(h)
            for v,r in uses[h]: choices[v].add(r)
    return choices, graphs


def topological_order(starts, choices, primary, seed):
    rng = random.Random(seed)
    # Any recipe becoming buildable inserts its result. All original recipes are
    # retained in the pool; random priorities expose different acyclic subgraphs.
    rank = {v:i for i,v in enumerate(primary)}
    recipes = [(v,r) for v in sorted(choices) for r in sorted(choices[v])]
    waiting = defaultdict(list)
    remaining = []
    for i, (_, r) in enumerate(recipes):
        parents = set(r[1:]) - set(starts)
        remaining.append(len(parents))
        for p in parents: waiting[p].append(i)
    heap=[]
    keys={}
    for v in choices:
        if seed == 0: key = (rank.get(v, -1), v)
        elif seed == 1: key = (rank.get(v, 10**9), v)
        elif seed == 2: key = (v.bit_length(), v)
        else: key = (rng.random(), v)
        keys[v] = key
    for i,(v,_) in enumerate(recipes):
        if not remaining[i]: heapq.heappush(heap,(keys[v],v))
    order = {v:-1 for v in starts}
    while heap:
        _,v=heapq.heappop(heap)
        if v in order: continue
        order[v]=len(order)
        for i in waiting[v]:
            remaining[i]-=1
            if not remaining[i]:
                u=recipes[i][0];heapq.heappush(heap,(keys[u],u))
    return order


def select_graph(starts, targets, choices, order, node_limit):
    import numpy as np
    from scipy.optimize import milp, Bounds, LinearConstraint
    from scipy.sparse import coo_matrix
    roots=set(starts)
    allowed={v: [r for r in sorted(rs) if all(order.get(p,10**12)<order.get(v,-1) for p in r[1:])]
             for v,rs in choices.items() if v in order}
    # Reverse closure discards nodes that cannot participate in any target.
    needed=set();stack=list(set(targets)-roots)
    while stack:
        v=stack.pop()
        if v in roots or v in needed:continue
        if not allowed.get(v):return None
        needed.add(v)
        for r in allowed[v]: stack.extend(r[1:])
    fixed=set(targets)|roots
    for v in sorted(needed,key=order.get,reverse=True):
        if v in fixed:
            mandatory=set(allowed[v][0][1:])
            for r in allowed[v][1:]:mandatory.intersection_update(r[1:])
            fixed.update(mandatory)
    nodes={v:i for i,v in enumerate(sorted(needed))}
    # Node-presence variables plus conjunctions for two-parent alternatives.
    n=len(nodes); rr=[];cc=[];dd=[];lower=[]
    def add(terms):
        k=len(lower);lower.append(0)
        for col,weight in terms:rr.append(k);cc.append(col);dd.append(weight)
    for v,i in nodes.items():
        sets={frozenset(r[1:])-fixed for r in allowed[v]}
        if frozenset() in sets:continue
        minimal=[s for s in sets if not any(t<s for t in sets)]
        if len(minimal)==1:
            for p in next(iter(minimal)):add([(nodes[p],1),(i,-1)])
        else:
            terms=[(i,-1)]
            for parents in sorted(minimal,key=lambda x:sorted(x)):
                if len(parents)==1:terms.append((nodes[next(iter(parents))],1))
                else:
                    terms.append((n,1))
                    for p in parents:add([(nodes[p],1),(n,-1)])
                    n+=1
            add(terms)
    lb=np.zeros(n)
    for v in fixed-roots:lb[nodes[v]]=1
    objective=np.zeros(n);objective[:len(nodes)]=1
    if lower:
        mat=coo_matrix((dd,(rr,cc)),shape=(len(lower),n)).tocsc()
        result=milp(objective,integrality=np.ones(n),bounds=Bounds(lb,np.ones(n)),
                    constraints=LinearConstraint(mat,np.zeros(len(lower)),np.inf),
                    options={'node_limit':node_limit,'mip_rel_gap':0})
        if result.x is None:return None
        present=roots|{v for v,i in nodes.items() if result.x[i]>.5}
    else:present=fixed
    solution={};stack=list(targets)
    while stack:
        v=stack.pop()
        if v in roots or v in solution:continue
        available=[r for r in allowed[v] if set(r[1:])<=present]
        if not available:return None
        solution[v]=available[0];stack.extend(available[0][1:])
    return solution


def select_unordered(starts, targets, choices, node_limit, cut_rounds=20):
    """Exact binary recipe/node formulation with cycle-elimination cuts.

    No value ordering is assumed: inverse arithmetic can be selected. An SCC of
    k values in a DAG cannot have k chosen recipes reading within that SCC.
    Adding that valid cut forbids the observed cycle without forbidding a DAG.
    """
    import numpy as np
    from scipy.optimize import milp, Bounds, LinearConstraint
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    roots=set(starts);nodes={v:i for i,v in enumerate(sorted(choices))}
    rules=[(v,r) for v in sorted(choices) for r in sorted(choices[v])]
    nr=len(nodes);n=nr+len(rules)
    rr=[];cc=[];dd=[];lo=[];hi=[]
    def constraint(terms,lower,upper):
        k=len(lo);lo.append(lower);hi.append(upper)
        for j,x in terms:rr.append(k);cc.append(j);dd.append(x)
    by_node=defaultdict(list)
    for j,(v,r) in enumerate(rules,nr):
        by_node[v].append(j)
        for p in set(r[1:])-roots:constraint([(nodes[p],1),(j,-1)],0,np.inf)
    for v,i in nodes.items():constraint([(i,-1)]+[(j,1) for j in by_node[v]],0,0)
    lb=np.zeros(n)
    for v in set(targets)-roots:lb[nodes[v]]=1
    objective=np.zeros(n);objective[:nr]=1
    for cut_round in range(cut_rounds):
        mat=coo_matrix((dd,(rr,cc)),shape=(len(lo),n)).tocsc()
        result=milp(objective,integrality=np.ones(n),bounds=Bounds(lb,np.ones(n)),
                    constraints=LinearConstraint(mat,np.array(lo),np.array(hi)),
                    options={'node_limit':node_limit,'mip_rel_gap':0,'time_limit':10})
        if result.x is None:return None
        solution={v:r for j,(v,r) in enumerate(rules,nr) if result.x[j]>.5}
        er=[];ec=[]
        for v,r in solution.items():
            for p in set(r[1:])-roots:er.append(nodes[v]);ec.append(nodes[p])
        adjacency=coo_matrix((np.ones(len(er)),(er,ec)),shape=(nr,nr)).tocsr()
        _,labels=connected_components(adjacency,directed=True,connection='strong')
        groups=defaultdict(list)
        for v in solution:groups[labels[nodes[v]]].append(v)
        cyclic=[set(vs) for vs in groups.values() if len(vs)>1]
        if not cyclic:
            live={};stack=list(targets)
            while stack:
                v=stack.pop()
                if v in roots or v in live:continue
                live[v]=solution[v];stack.extend(solution[v][1:])
            return live
        for group in cyclic:
            internal=[(j,1) for j,(v,r) in enumerate(rules,nr) if v in group and set(r[1:])&group]
            constraint(internal,-np.inf,len(group)-1)
    return None


def compile_graph(starts, targets, graph, seed, bound):
    from bisect import bisect_right
    roots=set(starts)
    order=[];seen=set(roots);cost=dict.fromkeys(roots,0)
    def visit(v):
        if v in seen:return
        seen.add(v);r=graph[v]
        visit(r[1]);visit(r[2]);order.append(v)
        cost[v]=min(100,1+sum(cost[p] for p in set(r[1:])))
    goals=list(targets)
    if seed==1:goals.reverse()
    elif seed>1:random.Random(seed).shuffle(goals)
    for v in goals:visit(v)
    uses=defaultdict(list)
    for i,v in enumerate(order):
        for p in set(graph[v][1:]):uses[p].append(i)
    bank=list(starts)+[None]*(48-len(starts));live={v:i for i,v in enumerate(starts)}
    output=[];now=0
    def emit(v,lock):
        if v in live:return live[v]
        if len(output)>=bound:raise RuntimeError('bound')
        op,a,b=graph[v];i=emit(a,lock);j=emit(b,lock|{a})
        if None in bank:d=bank.index(None)
        else:
            def eviction(x):
                p=bisect_right(uses[x],now)
                distance=1e12 if p==len(uses[x]) else uses[x][p]-now
                return distance/(1+cost[x])**(1.5 if seed%2 else 0)
            old=max((x for x in live if x not in lock and x not in roots),key=eviction)
            d=live.pop(old)
        bank[d]=v;live[v]=d;output.append([op,i,j,d]);return d
    try:
        for now,v in enumerate(order):emit(v,set())
    except (RuntimeError,ValueError):return None
    return output


def select_cpsat(starts, targets, choices, primary, budget):
    """Cycle-safe recipe model, with constructive solution hints."""
    from ortools.sat.python import cp_model
    roots=set(starts);model=cp_model.CpModel()
    vals=sorted(choices);n=len(vals)
    active={v:model.NewBoolVar('v'+str(i)) for i,v in enumerate(vals)}
    depth={v:model.NewIntVar(1,n,'d'+str(i)) for i,v in enumerate(vals)}
    selected={}
    hint_order={v:0 for v in roots}
    for v,r in primary.items():hint_order[v]=1+max(hint_order[r[1]],hint_order[r[2]])
    for v in vals:
        rs=sorted(choices[v]);variables=[]
        for j,r in enumerate(rs):
            x=model.NewBoolVar('r'+str(v)+'_'+str(j));variables.append(x);selected[v,r]=x
            for p in set(r[1:])-roots:
                model.AddImplication(x,active[p])
                model.Add(depth[v]>depth[p]).OnlyEnforceIf(x)
            model.AddHint(x,int(v in primary and canonical(primary[v])==r))
        model.Add(sum(variables)==active[v])
        if v in targets:model.Add(active[v]==1)
        model.AddHint(active[v],int(v in primary))
        model.AddHint(depth[v],hint_order.get(v,1))
    model.Minimize(sum(active.values()))
    model.Add(sum(active.values())<=len(primary))
    solver=cp_model.CpSolver()
    solver.parameters.num_search_workers=1
    solver.parameters.random_seed=20261119
    solver.parameters.max_deterministic_time=budget
    result=solver.Solve(model)
    if result not in (cp_model.OPTIMAL,cp_model.FEASIBLE):return None
    graph={v:r for (v,r),x in selected.items() if solver.Value(x)}
    live={};stack=list(targets)
    while stack:
        v=stack.pop()
        if v in roots or v in live:continue
        live[v]=graph[v];stack.extend(graph[v][1:])
    return live


def work(task):
    row, programs, helpers, trials, node_limit=task
    starts=json.loads(row['starting_values']);targets=json.loads(row['targets'])
    for p in programs:replay(row,p)
    programs.sort(key=len)
    best=programs[0]
    pool,graphs=make_pool(starts,targets,programs,int(row['value_limit']),helpers)
    for seed in range(abs(trials)):
        primary=graphs[seed%len(graphs)]
        order=topological_order(starts,pool,primary,seed)
        solution=(select_cpsat(starts,targets,pool,graphs[0],node_limit/100) if trials==-2 else
                  select_unordered(starts,targets,pool,node_limit) if trials<0 else
                  select_graph(starts,targets,pool,order,node_limit))
        if solution is None or len(solution)>=len(best):continue
        for schedule in range(12):
            candidate=compile_graph(starts,targets,solution,schedule,len(best))
            if candidate is not None and len(candidate)<len(best):
                replay(row,candidate);best=candidate
        if trials<0:break
    return row['id'],best


def main():
    p=argparse.ArgumentParser()
    p.add_argument('inputs',nargs='+')
    p.add_argument('--puzzles',default='/task/data/puzzles.csv')
    p.add_argument('--output',required=True)
    p.add_argument('--helpers',type=int,default=300)
    p.add_argument('--trials',type=int,default=4)
    p.add_argument('--nodes',type=int,default=200)
    p.add_argument('--count',type=int,default=0)
    p.add_argument('--workers',type=int,default=4)
    p.add_argument('--resume',action='store_true')
    args=p.parse_args();start=time.time()
    rows=list(csv.DictReader(open(args.puzzles)))
    if args.count:rows=rows[:args.count]
    sources=[{r['id']:json.loads(r['program']) for r in csv.DictReader(open(f))} for f in args.inputs]
    done={}
    if args.resume and Path(args.output).exists():
        done={r['id']:json.loads(r['program']) for r in csv.DictReader(open(args.output))}
    tasks=[(r,[s[r['id']] for s in sources],args.helpers,args.trials,args.nodes) for r in rows if r['id'] not in done]
    total=0;old=0;families=defaultdict(int)
    with open(args.output,'w') as f,ProcessPoolExecutor(args.workers) as pool:
        w=csv.writer(f);w.writerow(['id','program']);it=pool.map(work,tasks)
        for i,r in enumerate(rows):
            pid=r['id']
            if pid in done:program=done[pid]
            else:
                outid,program=next(it);assert outid==pid
            total+=replay(r,program);old+=min(len(s[pid]) for s in sources)
            families[r.get('family','scored')]+=len(program)
            w.writerow([pid,json.dumps(program,separators=(',',':'))]);f.flush()
            if (i+1)%10==0:print(i+1,total,'saved',old-total,'seconds',round(time.time()-start,1),flush=True)
    report={'instructions':total,'baseline':old,'seconds':time.time()-start,'families':dict(families),
            'args':vars(args),'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'input_hashes':{f:hashlib.sha256(Path(f).read_bytes()).hexdigest() for f in args.inputs}}
    Path(args.output).with_suffix('.report.json').write_text(json.dumps(report,indent=2));print(report)

if __name__=='__main__':main()
