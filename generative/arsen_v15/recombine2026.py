"""SPDX-License-Identifier: Apache-2.0
Original deterministic arithmetic recipe recombination and liveness scheduling.
Conceptual references: IceFire and goodpjw's public Santa 2026 notebooks.
No upstream source, programs, or puzzle records are embedded.
"""
import argparse
from collections import defaultdict, Counter
from concurrent.futures import ProcessPoolExecutor
import csv, hashlib, json, time
from pathlib import Path
from recipe_milp import make_pool, canonical, compile_graph
from run_solver import replay


def schedule(starts, targets, graph, primary, mode):
    """Try a no-rematerialization list schedule, consuming dead source registers."""
    roots=set(starts); needed=set(); stack=list(targets)
    while stack:
        v=stack.pop()
        if v in roots or v in needed: continue
        needed.add(v); stack.extend(graph[v][1:])
    graph={v:graph[v] for v in sorted(needed)}
    users=defaultdict(set); indegree={}
    for v,(_,a,b) in graph.items():
        indegree[v]=len({a,b}-roots)
        for x in {a,b}: users[x].add(v)
    remain={v:len(users[v]) for v in roots|needed}
    rank={v:i for i,v in enumerate(primary)}
    ready={v for v in graph if indegree[v]==0}
    regs=list(starts)+[None]*(48-len(starts)); loc={v:i for i,v in enumerate(starts)}
    for i,v in enumerate(regs):
        if v is not None and (remain[v]==0 or loc[v]!=i): regs[i]=None
    out=[]
    while ready:
        def priority(v):
            parents=set(graph[v][1:]); freed=sum(remain[x]==1 for x in parents)
            delta=int(remain[v]>0)-freed
            if mode==0: return (rank.get(v,10**9),v)
            if mode==1: return (delta,rank.get(v,10**9),v)
            return (delta,-len(users[v]),v.bit_length(),v)
        v=min(ready,key=priority); ready.remove(v)
        op,a,b=graph[v]
        if a not in loc or b not in loc:return None
        i,j=loc[a],loc[b]
        if regs[i]!=a or regs[j]!=b:return None
        for x in {a,b}:
            remain[x]-=1
            if remain[x]==0: regs[loc[x]]=None
        if None not in regs:return None
        d=regs.index(None);regs[d]=v;loc[v]=d;out.append([op,i,j,d])
        if remain[v]==0:regs[d]=None
        for u in sorted(users[v]):
            indegree[u]-=1
            if indegree[u]==0:ready.add(u)
    return out if len(out)==len(graph) else None


def solve(row, programs, budget=2., slack=3, helpers=0, seed=20261120, extra=None):
    from ortools.sat.python import cp_model
    starts=json.loads(row['starting_values']);targets=json.loads(row['targets'])
    unique={json.dumps(p,separators=(',',':')):p for p in programs}
    programs=sorted(unique.values(),key=len);best=programs[0]
    programs=[p for p in programs if len(p)<=len(best)+slack][:12]
    for p in programs:replay(row,p)
    choices,graphs=make_pool(starts,targets,programs,int(row['value_limit']),helpers)
    primary=graphs[0];roots=set(starts);vals=sorted(choices)
    if extra:
        from recipe_milp import operation, ops
        cap=int(row['value_limit'])
        for op,a,b,v in extra:
            assert 0<a<=cap and 0<b<=cap and 0<v<=cap and operation(op,a,b)==v
            if v not in roots and v not in (a,b):choices.setdefault(v,set()).add(canonical((op,a,b)))
        values=sorted(set(choices)|roots)
        assert all(p in choices or p in roots for rs in choices.values() for r in rs for p in r[1:])
        for i,a in enumerate(values):
            for b in values[:i+1]:
                for v,r in ops(a,b,cap):
                    if v in choices and v not in r[1:]:choices[v].add(canonical(r))
        vals=sorted(choices)
    if not vals:return best,{'status':'already_covered','gain':0}
    m=cp_model.CpModel();n=len(vals)
    active={v:m.NewBoolVar('') for v in vals}
    depth={v:m.NewIntVar(0,n,'') for v in vals}
    selected={};penalty=[];level={v:0 for v in roots}
    for v,r in primary.items():level[v]=1+max(level[x] for x in r[1:])
    for v in vals:
        alternatives=[]
        for r in sorted(choices[v]):
            x=m.NewBoolVar('');selected[v,r]=x;alternatives.append(x)
            for p in sorted(set(r[1:])-roots):
                m.AddImplication(x,active[p]);m.Add(depth[v]>depth[p]).OnlyEnforceIf(x)
            original=v in primary and canonical(primary[v])==r
            if not original:penalty.append(x)
            m.AddHint(x,int(original))
        m.Add(sum(alternatives)==active[v])
        m.AddHint(active[v],int(v in primary));m.AddHint(depth[v],level.get(v,0))
        if v in targets:m.Add(active[v]==1)
    m.Add(sum(active.values())<=len(primary))
    m.Minimize((n+1)*sum(active.values())+sum(penalty))
    s=cp_model.CpSolver();s.parameters.num_search_workers=1
    s.parameters.random_seed=seed;s.parameters.max_deterministic_time=budget
    status=s.Solve(m);name=s.StatusName(status);best_graph=len(primary)
    if status in (cp_model.OPTIMAL,cp_model.FEASIBLE):
        solution={v:r for (v,r),x in selected.items() if s.Value(x)}
        best_graph=len(solution)
        if best_graph<len(best):
            for mode in range(15):
                p=(schedule(starts,targets,solution,primary,mode) if mode<3 else
                   compile_graph(starts,targets,solution,mode-3,len(best)))
                if p is not None and len(p)<len(best):replay(row,p);best=p
    return best,{'status':name,'gain':len(programs[0])-len(best),'values':n,
                 'recipes':len(selected),'graph_size':best_graph,
                 'deterministic_time':s.ResponseProto().deterministic_time}


def work(task):
    row,programs,config=task
    prog,stat=solve(row,programs,**config)
    return row['id'],prog,stat


def main():
    a=argparse.ArgumentParser();a.add_argument('inputs',nargs='+')
    a.add_argument('--puzzles',required=True);a.add_argument('--output',required=True)
    a.add_argument('--budget',type=float,default=2);a.add_argument('--slack',type=int,default=3)
    a.add_argument('--helpers',type=int,default=0);a.add_argument('--seed',type=int,default=20261120)
    a.add_argument('--count',type=int,default=0);a.add_argument('--workers',type=int,default=4)
    a.add_argument('--resume',action='store_true');a=a.parse_args()
    csv.field_size_limit(10**9);rows=list(csv.DictReader(open(a.puzzles)))
    if a.count:rows=rows[:a.count]
    banks=[{r['id']:json.loads(r['program']) for r in csv.DictReader(open(f))} for f in a.inputs]
    existing={}
    if a.resume and Path(a.output).exists():existing={r['id']:json.loads(r['program']) for r in csv.DictReader(open(a.output))}
    config={k:getattr(a,k) for k in ['budget','slack','helpers','seed']}
    tasks=[(r,[b[r['id']] for b in banks if r['id'] in b],config) for r in rows if r['id'] not in existing]
    stats={};total=before=0;t0=time.time()
    with open(a.output,'w',newline='') as f,ProcessPoolExecutor(a.workers) as pool:
        w=csv.writer(f);w.writerow(['id','program']);it=pool.map(work,tasks)
        for i,r in enumerate(rows):
            pid=r['id'];before+=min(len(b[pid]) for b in banks if pid in b)
            if pid in existing:p=existing[pid];stat={'status':'resumed'}
            else:oid,p,stat=next(it);assert oid==pid
            total+=replay(r,p);stats[pid]=stat
            w.writerow([pid,json.dumps(p,separators=(',',':'))]);f.flush()
            if (i+1)%10==0: print(i+1,'total',total,'saved',before-total,'elapsed',round(time.time()-t0,1),flush=True)
    report={'score':total,'baseline':before,'config':vars(a),'stats':stats,
            'seconds':time.time()-t0,'input_sha256':{f:hashlib.sha256(Path(f).read_bytes()).hexdigest() for f in a.inputs}}
    Path(a.output).with_suffix('.report.json').write_text(json.dumps(report,indent=2))
    print('COMPLETE',total,'gain',before-total,Counter(s['status'] for s in stats.values()),flush=True)

if __name__=='__main__':main()
