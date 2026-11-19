"""Select table decompositions jointly by their union of paid intermediate values."""
from collections import defaultdict

from crossover_lns import load_solver


def coordinate(options,selected,cost,seed):
    cp=load_solver()
    choice_sets={}
    paid=set().union(*(pair[1] for pair in selected.values()))
    for t,group in options.items():
        best=selected[t]
        # Keep options that introduce few new ingredients as well as those
        # with low stand-alone cost. Include the feasible greedy assignment.
        reduced={}
        for item in group:reduced.setdefault(frozenset(item[1]),item)
        values=list(reduced.values())
        direct=sorted(values,key=lambda x:sum(cost[v] for v in x[1]))[:21]
        marginal=sorted(values,key=lambda x:sum(cost[v] for v in x[1] if v not in paid))[:25]
        distinct={frozenset(best[1]):best}
        for item in direct+marginal:distinct.setdefault(frozenset(item[1]),item)
        choice_sets[t]=list(distinct.values())
    who=defaultdict(set)
    for t,group in choice_sets.items():
        for _,vs in group:
            for v in vs:
                if cost[v]>0:who[v].add(t)
    model=cp.CpModel()
    shared={v:model.new_bool_var(f"pay{v}") for v,ts in who.items() if len(ts)>1}
    weights={v:round(40*cost[v]) for v in who}
    terms=[weights[v]*flag for v,flag in shared.items()]
    variables={}
    for t,group in choice_sets.items():
        flags=[model.new_bool_var(f"r{t}_{i}") for i in range(len(group))]
        model.add_exactly_one(flags);variables[t]=flags
        usage=defaultdict(list)
        for i,(_,vs) in enumerate(group):
            private=0
            for v in vs:
                if v in shared:usage[v].append(flags[i])
                elif v in weights:private+=weights[v]
            if private:terms.append(private*flags[i])
            model.add_hint(flags[i],int(i==0))
        for v,required in usage.items():
            if len(required)==len(flags):model.add(shared[v]==1)
            else:model.add(sum(required)<=shared[v])
    for v,flag in shared.items():model.add_hint(flag,int(v in paid))
    upper=sum(weights.get(v,0) for v in paid)
    obj=sum(terms)
    model.add(obj<=upper);model.minimize(obj)
    solver=cp.CpSolver()
    solver.parameters.num_search_workers=1
    solver.parameters.max_deterministic_time=.17
    solver.parameters.max_time_in_seconds=3.5
    solver.parameters.random_seed=seed%(1<<30)
    status=solver.solve(model)
    if status not in (cp.OPTIMAL,cp.FEASIBLE):return selected
    trial={t:choice_sets[t][next(i for i,v in enumerate(flags) if solver.value(v))]
           for t,flags in variables.items()}
    def price(rows):return sum(cost[v] for v in set().union(*(value[1] for value in rows.values())))
    return trial if price(trial)<price(selected) else selected
