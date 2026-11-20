"""Exactly reorder a bounded contiguous interval of a fixed arithmetic DAG."""
from collections import Counter,defaultdict
from crossover_lns import load_solver
from graph import _allocate

def profile(p,order,graph):
    uses=Counter(x for v in order for x in set(graph[v][1:]))
    live={v for v in p.seeds if uses[v]};out=[]
    for v in order:
        for input_value in set(graph[v][1:]):
            uses[input_value]-=1
            if not uses[input_value]:live.remove(input_value)
        out.append(len(live)+1)
        if uses[v]:live.add(v)
    return out

def penalty(p,usage):
    return max(usage),sum(max(0,v-p.registers)**2 for v in usage),sum(max(0,v-p.registers+2) for v in usage)

def improve_window(p,order,graph,start,end,seconds):
    cp=load_solver();model=cp.CpModel();n=end-start
    positions={v:i for i,v in enumerate(order)}|{v:-1 for v in p.seeds}
    nodes=order[start:end];where={v:i for i,v in enumerate(nodes)}
    clients=defaultdict(set)
    for v,(_,a,b) in graph.items():clients[a].add(v);clients[b].add(v)
    # Earliest and latest feasible times from chains wholly in the interval.
    lo={};hi={}
    for v in nodes:lo[v]=max((lo[a]+1 for a in set(graph[v][1:]) if a in where),default=0)
    for v in reversed(nodes):hi[v]=min((hi[c]-1 for c in clients[v] if c in where),default=n-1)
    prefixes={}
    def by(v,k):
        return prefixes[v][k] if k>=0 else 0
    for v in nodes:
        flags=[]
        for k in range(n):
            if k<lo[v]:b=0
            elif k>=hi[v]:b=1
            else:
                b=model.new_bool_var('');model.add_hint(b,int(where[v]<=k))
            flags.append(b)
            if k and not isinstance(b,int) and not isinstance(flags[k-1],int):model.add(b>=flags[k-1])
        prefixes[v]=flags
    for k in range(n-1):model.add(sum(by(v,k) for v in nodes)==k+1)
    for v in nodes:
        for parent in set(graph[v][1:]).intersection(where):
            for k in range(lo[v],min(hi[v],hi[parent]+1)+1):
                model.add(by(v,k)<=by(parent,k-1))
    usage=profile(p,order,graph);old_pressure=penalty(p,usage);peak=old_pressure[0]
    near=[];bad=[]
    for k in range(n):
        cut=start+k;fixed=1;optional=[]
        for v,birth in positions.items():
            before=by(v,k-1) if v in where else int(birth<cut)
            if isinstance(before,int) and not before:continue
            sons=clients[v]
            if any(positions[c]>=end for c in sons):
                if isinstance(before,int):fixed+=1
                else:optional.append(before)
                continue
            later=[by(c,k) for c in sons if c in where]
            if not later:continue
            # A child known not to have run makes the source live whenever
            # it has been born. Children already executed cannot keep it live.
            if any(isinstance(x,int) and x==0 for x in later):
                if isinstance(before,int):fixed+=1
                else:optional.append(before)
                continue
            later=[x for x in later if not isinstance(x,int)]
            if not later:continue
            alive=model.new_bool_var('')
            for x in later:model.add(alive>=before-x)
            optional.append(alive)
        if fixed>peak:return order
        count=sum(optional)+fixed
        if fixed+len(optional)>=peak:
            high=model.new_bool_var('');model.add(count<=peak-1+high);bad.append(high)
            model.add_hint(high,int(usage[cut]>=peak))
        if fixed+len(optional)>=peak-1:
            high=model.new_bool_var('');model.add(count<=peak-2+2*high);near.append(high)
            model.add_hint(high,int(usage[cut]>=peak-1))
    if not bad:return order
    weights=n+1;old_score=weights*sum(v>=peak for v in usage[start:end])+sum(v>=peak-1 for v in usage[start:end])
    cost=weights*sum(bad)+sum(near);model.add(cost<old_score);model.minimize(cost)
    solver=cp.CpSolver();solver.parameters.max_time_in_seconds=seconds;solver.parameters.num_search_workers=1
    status=solver.solve(model)
    if status not in (cp.OPTIMAL,cp.FEASIBLE):return order
    part=sorted(nodes,key=lambda v:next(k for k in range(n) if solver.value(by(v,k))))
    new=order[:start]+part+order[end:];ranks={v:i for i,v in enumerate(new)}
    if any(ranks.get(x,-1)>=ranks[v] for v in new for x in graph[v][1:]):raise ValueError('window precedence error')
    return new

def optimize(p,ordered,seconds,rounds=4):
    order=list(ordered);best=penalty(p,profile(p,order,ordered))
    for round_no in range(rounds):
        usage=profile(p,order,ordered)
        if best[0]<=p.registers:break
        peaks=[i for i,v in enumerate(usage) if v==best[0]]
        center=peaks[round_no%len(peaks)]
        width=(28,42,56,36,76,48)[round_no%6]
        for stride in (.5,.72,.28):
            start=max(0,min(len(order)-width,center-int(width*stride)));end=min(len(order),start+width)
            proposed=improve_window(p,order,ordered,start,end,seconds)
            score=penalty(p,profile(p,proposed,ordered))
            if score<best:order=proposed;best=score;break
    tape=_allocate(p,{v:ordered[v] for v in order},False,0,True)
    return tape,best
