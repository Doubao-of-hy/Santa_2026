"""Choose a topologically closed prefix whose boundary uses few registers."""
from collections import defaultdict
from solvers.graphs.crossover_lns import load_solver
from solvers.registers.register_windows import profile

def cut(p,graph,order,left,middle,right,seconds,seed):
    cp=load_solver();model=cp.CpModel();pos={v:i for i,v in enumerate(order)}
    before={v:1 for v in p.seeds};variables=[]
    for v in order:
        i=pos[v]
        if i<left:before[v]=1
        elif i>=right:before[v]=0
        else:
            before[v]=model.new_bool_var('');variables.append(before[v]);model.add_hint(before[v],int(i<middle))
    model.add(sum(variables)==middle-left)
    users=defaultdict(set)
    for v,(_,a,b) in graph.items():
        for x in {a,b}:
            users[x].add(v)
            if not isinstance(before[v],int) and not isinstance(before[x],int):model.add(before[v]<=before[x])
    fixed=0;cross=[]
    for v,prior in before.items():
        if isinstance(prior,int) and not prior:continue
        future=[before[w] for w in users[v]]
        if any(isinstance(f,int) and not f for f in future):
            if isinstance(prior,int):fixed+=1
            else:cross.append(prior)
            continue
        others=[f for f in future if not isinstance(f,int)]
        if not others:continue
        live=model.new_bool_var('');cross.append(live)
        for f in others:model.add(live>=prior-f)
    old_count=sum((v in p.seeds or pos[v]<middle) and any(pos[w]>=middle for w in sons) for v,sons in users.items())
    count=fixed+sum(cross);model.add(count<old_count);model.minimize(count)
    solver=cp.CpSolver();solver.parameters.max_time_in_seconds=seconds;solver.parameters.num_search_workers=1
    solver.parameters.random_seed=seed
    status=solver.solve(model)
    if status not in (cp.FEASIBLE,cp.OPTIMAL):return order
    segment=order[left:right]
    moved=order[:left]+[v for v in segment if solver.value(before[v])]+[v for v in segment if not solver.value(before[v])]+order[right:]
    at={v:i for i,v in enumerate(moved)}
    if any(at.get(x,-1)>=at[v] for v in moved for x in graph[v][1:]):raise ValueError('invalid chronological cut')
    return moved

def hierarchical(p,graph,seconds,seed):
    order=list(graph);vary=(.43,.57,.5,.32,.68);top=vary[seed%len(vary)]
    def divide(left,right,depth):
        nonlocal order
        if right-left<24 or depth>3:return
        prof=profile(p,order,graph)
        if max(prof[left:right])<p.registers-1:return
        n=right-left
        if depth==0:middle=left+int(n*top)
        else:
            near=range(left+n//3,left+2*n//3+1)
            middle=max(near,key=lambda i:(prof[i],-abs(i-left-n*.5)))
        order=cut(p,graph,order,left,middle,right,seconds,seed+left+17*depth)
        divide(left,middle,depth+1);divide(middle,right,depth+1)
    divide(0,len(order),0)
    return {v:graph[v] for v in order}
