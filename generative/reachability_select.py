"""Fit an order-free arithmetic value set and repair disconnected choices."""
from collections import defaultdict
import heapq
import time

from crossover_lns import load_solver
from graph import active_graph,first_recipes
from parallel_solve import compile_best


def rooted_solution(p,allowed,selected,repair):
    """Minimize the number of extra values needed along each derivation."""
    values=list(dict.fromkeys((*p.seeds,*allowed)))
    index={v:i for i,v in enumerate(values)}
    bits={v:1<<i for i,v in enumerate(values)}
    extras=sum(bits[v] for v in values if v not in selected and v not in p.seeds)
    adjacent=defaultdict(list)
    for v,options in allowed.items():
        if not repair and v not in selected:continue
        for op,a,b in options:
            if a not in index or b not in index:continue
            if not repair and ((a not in selected and a not in p.seeds) or
                               (b not in selected and b not in p.seeds)):continue
            adjacent[a].append((v,op,a,b))
            if b!=a:adjacent[b].append((v,op,a,b))
    paths={};best_key={};recipe={};queue=[]
    for s in p.seeds:
        heapq.heappush(queue,(0,0,s));best_key[s]=(0,0)
    while queue:
        new_count,length,v=heapq.heappop(queue)
        if v in paths or best_key[v]!=(new_count,length):continue
        if v in recipe:
            _,a,b=recipe[v];paths[v]=paths[a]|paths[b]|bits[v]
        else:paths[v]=0
        for w,op,a,b in adjacent[v]:
            if w in paths or a not in paths or b not in paths:continue
            deps=paths[a]|paths[b]|bits[w]
            priority=((deps&extras).bit_count(),deps.bit_count())
            if w not in best_key or priority<best_key[w]:
                best_key[w]=priority;recipe[w]=(op,a,b)
                heapq.heappush(queue,(*priority,w))
    return paths,recipe


def sources_of_cycles(missing,allowed,selected):
    """Find source SCCs among selected but unconstructible arithmetic values."""
    graph={v:set() for v in missing};reverse={v:set() for v in missing}
    for child in missing:
        for _,a,b in allowed[child]:
            if a not in selected or b not in selected:continue
            for parent in (a,b):
                if parent in missing:
                    graph[parent].add(child);reverse[child].add(parent)
    visited=set();finished=[]
    for start in missing:
        if start in visited:continue
        todo=[(start,False)]
        while todo:
            v,returning=todo.pop()
            if returning:finished.append(v);continue
            if v in visited:continue
            visited.add(v);todo.append((v,True))
            todo.extend((w,False) for w in graph[v] if w not in visited)
    group_of={};groups=[]
    for start in reversed(finished):
        if start in group_of:continue
        ix=len(groups);component=set();todo=[start]
        while todo:
            v=todo.pop()
            if v in group_of:continue
            group_of[v]=ix;component.add(v);todo.extend(reverse[v])
        groups.append(component)
    incoming={group_of[x] for x in missing for parent in reverse[x] if group_of[parent]!=group_of[x]}
    return [g for i,g in enumerate(groups) if i not in incoming]


def solve_free(p,programs,trials,seconds):
    from component_select import bank
    programs=sorted(dict.fromkeys(programs),key=len)
    best=programs[0];original=first_recipes(p,best)
    primary,ways=bank(p,programs)
    seeds=set(p.seeds)
    # The value cap in the candidate bank may truncate some donor-only cones.
    available=set(seeds)
    while True:
        before=len(available)
        for v,options in ways.items():
            if any(a in available and b in available for _,a,b in options):available.add(v)
        if len(available)==before:break
    allowed={v:tuple(sorted(r for r in rs if r[1] in available and r[2] in available))
             for v,rs in ways.items() if v in available}
    forced=seeds|set(p.targets)
    while True:
        before=len(forced)
        for v in tuple(forced-seeds):
            common=set.intersection(*(set(r[1:]) for r in allowed[v]))
            forced.update(common)
        if len(forced)==before:break
    if forced-seeds-primary.keys():raise RuntimeError("invalid forced closure")
    cp=load_solver();model=cp.CpModel()
    active={v:model.new_bool_var("") for v in allowed if v not in forced}
    pairs={}
    for v,options in allowed.items():
        choices={tuple(sorted(set(r[1:])-forced)) for r in options}
        if () in choices:continue
        singles={c[0] for c in choices if len(c)==1}
        clause=[] if v in forced else [~active[v]]
        for option in choices:
            if len(option)==1:clause.append(active[option[0]])
            elif not set(option)&singles:
                if option not in pairs:
                    var=model.new_bool_var("");pairs[option]=var
                    for x in option:model.add_implication(var,active[x])
                clause.append(pairs[option])
        model.add_bool_or(clause)
    for v,b in active.items():model.add_hint(b,int(v in primary))
    for (a,b),v in pairs.items():model.add_hint(v,int(a in primary and b in primary))
    count=sum(active.values());model.add(count<=len(primary)-len(forced-seeds));model.minimize(count)
    stats=[0,0,0,0]
    start=time.monotonic()
    for attempt in range(trials*4):
        remaining=trials*seconds-(time.monotonic()-start)
        if remaining<=0:break
        solver=cp.CpSolver();solver.parameters.num_search_workers=1
        solver.parameters.max_time_in_seconds=min(remaining,seconds)
        status=solver.solve(model);stats[0]+=1
        if status not in (cp.FEASIBLE,cp.OPTIMAL):break
        selected=forced|{v for v,b in active.items() if solver.value(b)}
        reachable,graph=rooted_solution(p,allowed,selected,False)
        valid=all(t in reachable for t in p.targets)
        if valid:
            stats[1]+=int(status==cp.OPTIMAL)
        else:
            _,graph=rooted_solution(p,allowed,selected,True);stats[2]+=1
        live=active_graph(p,graph)
        if len(live)<len(best):
            tape=compile_best(p,original,live)
            if tape is not None and len(tape)<len(best):best=tape;stats[3]+=1
        if valid:
            if status==cp.OPTIMAL:break
            # Search a strictly shorter logical derivation if time remains.
            model.add(count<=len(live)-len(forced-seeds)-1)
            continue
        missing=selected-reachable.keys()
        cuts=0
        for group in sources_of_cycles(missing,allowed,selected):
            boundary=set();has_supported_entry=False
            for v in group:
                for _,a,b in allowed[v]:
                    if a in group or b in group:continue
                    absent={a,b}-selected
                    if not absent:has_supported_entry=True
                    boundary.update(absent)
            if has_supported_entry:continue
            # Any legal derivation of a retained group member must contain a
            # first operation that enters the group using only outside inputs.
            exits=[active[v] for v in boundary]
            if group&forced:model.add_bool_or(exits)
            else:
                for v in group:model.add_bool_or([~active[v],*exits])
            cuts+=1
        if not cuts:break
    return p.id,best,stats
