"""Select a small allowed helper set using exact reachability and minimal blocking sets."""
from collections import deque
import random
import time

class Bank:
    def __init__(self,seeds,targets,rules):
        self.values=sorted(set(seeds)|set(rules));ix={v:i for i,v in enumerate(self.values)}
        self.n=len(ix);self.bit=[1<<i for i in range(self.n)]
        self.initial=sum(self.bit[ix[v]] for v in set(seeds))
        self.goals=sum(self.bit[ix[v]] for v in set(targets));self.base=self.initial|self.goals
        self.optional=[i for i,b in enumerate(self.bit) if not self.base&b]
        self.rules=[[] for _ in self.values];self.trigger=[[] for _ in self.values]
        for value,recipes in rules.items():
            out=ix[value];seen=set()
            for rule in sorted(recipes):
                _,a,b=rule;i,j=ix[a],ix[b]
                pair=(min(i,j),max(i,j))
                if pair in seen:continue
                seen.add(pair)
                both=self.bit[i]|self.bit[j];self.rules[out].append((both,rule))
                self.trigger[i].append((out,self.bit[j],rule))
                if i!=j:self.trigger[j].append((out,self.bit[i],rule))
        self.index=ix
    def spread(self,allow,reached,queue,graph=None):
        q=deque(queue)
        while q:
            i=q.popleft()
            for out,other,recipe in self.trigger[i]:
                b=self.bit[out]
                if reached&b or not allow&b or not reached&other:continue
                reached|=b;q.append(out)
                if graph is not None:graph[self.values[out]]=recipe
        return reached
    def close(self,allow,graph=None):
        q=[i for i,b in enumerate(self.bit) if self.initial&b]
        return self.spread(allow,self.initial,q,graph)
    def enable(self,allow,reached,i):
        for both,r in self.rules[i]:
            if both&reached==both:
                return self.spread(allow|self.bit[i],reached|self.bit[i],(i,))
        return reached
    def cut(self,allow,reached,goal,order):
        assert not reached&goal
        for i in order:
            b=self.bit[i]
            if b&allow:continue
            prospective=self.enable(allow,reached,i)
            if prospective&goal:continue
            reached=prospective;allow|=b
        # Even granting every helper except these, the specified target remains unreachable.
        blocked=tuple(i for i in self.optional if not allow&self.bit[i])
        assert blocked and not self.close(allow)&goal
        return blocked

def compile_result(p,graph,parent):
    from graph import compile_graph
    result=compile_graph(p,graph,recompute=True,schedule_width=6)
    return result if result is not None and len(result)<len(parent) else parent

def rank_model(p,bank,parent,primary,seconds,seed):
    from ortools.sat.python import cp_model
    start=time.perf_counter();model=cp_model.CpModel()
    use={i:model.new_bool_var('') for i,b in enumerate(bank.bit) if not bank.initial&b}
    depth={i:model.new_int_var(1,bank.n,'') for i in use}
    picked={}
    for out,x in use.items():
        candidates=[]
        for both,r in bank.rules[out]:
            z=model.new_bool_var('');candidates.append(z);picked[out,r]=z
            for v in set(r[1:]):
                i=bank.index[v]
                if i in use:
                    model.add_implication(z,use[i]);model.add(depth[out]>depth[i]).only_enforce_if(z)
        model.add(sum(candidates)==x)
        if bank.goals&bank.bit[out]:model.add(x==1)
    length=sum(use.values());model.add(length<len(parent));model.minimize(length)
    solver=cp_model.CpSolver();solver.parameters.num_search_workers=1;solver.parameters.random_seed=seed
    solver.parameters.max_time_in_seconds=max(0.001,seconds-(time.perf_counter()-start))
    status=solver.solve(model)
    if status in (cp_model.FEASIBLE,cp_model.OPTIMAL):
        graph={bank.values[i]:r for (i,r),z in picked.items() if solver.value(z)}
        parent=compile_result(p,graph,parent)
    return parent,dict(status=solver.status_name(status),seconds=round(time.perf_counter()-start,3))

def hitting_set(p,bank,parent,primary,seconds,seed):
    from ortools.sat.python import cp_model
    start=time.perf_counter();end=start+seconds;rng=random.Random(seed)
    model=cp_model.CpModel();use={i:model.new_bool_var('') for i in bank.optional}
    n=len(use);required=(bank.goals&~bank.initial).bit_count()
    model.add(sum(use.values())+required<len(parent))
    own={bank.index[v] for v in primary}
    model.minimize(sum((-1 if i in own else n+1)*x for i,x in use.items()))
    solver=cp_model.CpSolver();solver.parameters.num_search_workers=1;solver.parameters.random_seed=seed
    cuts=set();iterations=0;grounded=0;status='TIME_LIMIT'
    while time.perf_counter()<end:
        solver.parameters.max_time_in_seconds=max(0.001,end-time.perf_counter())
        result=solver.solve(model)
        if result not in (cp_model.OPTIMAL,cp_model.FEASIBLE):
            status=solver.status_name(result);break
        iterations+=1
        selected=[i for i,x in use.items() if solver.value(x)]
        allow=bank.base|sum(bank.bit[i] for i in selected)
        graph={};reached=bank.close(allow,graph);missing=bank.goals&~reached
        if not missing:
            grounded+=1;solution=compile_result(p,graph,parent)
            if len(solution)<len(parent):
                parent=solution;model.add(sum(use.values())+required<len(parent))
            else:
                # For this candidate set we retain just the first grounded physical scheduling attempt.
                model.add_bool_or([x.negated() if i in selected else x for i,x in use.items()])
            continue
        choices=[b for b in bank.bit if b&missing];rng.shuffle(choices)
        order=bank.optional[:];updated=0
        for target in choices[:4]:
            rng.shuffle(order)
            cut=bank.cut(allow,reached,target,order)
            if cut not in cuts:
                model.add_bool_or([use[i] for i in cut]);cuts.add(cut);updated+=1
            if time.perf_counter()>=end:break
        if not updated:raise ValueError('A forbidden master solution was repeated')
    return parent,dict(status=status,iterations=iterations,cuts=len(cuts),unit_cuts=sum(len(c)==1 for c in cuts),
                       grounded=grounded,seconds=round(time.perf_counter()-start,3))
