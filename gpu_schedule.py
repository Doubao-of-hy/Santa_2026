"""Place rewrites in the incumbent instruction order, keeping repeated occurrences distinct."""
from collections import Counter
import heapq

from elf import check
from graph import active_graph
from graph import _allocate


def schedule_like(puzzle,old,proposed):
    graph=active_graph(puzzle,proposed)
    seeds=len(puzzle.seeds)
    values=list(puzzle.seeds)
    warm_slots=list(range(seeds))+[None]*(puzzle.registers-seeds)
    latest={v:i for i,v in enumerate(puzzle.seeds)}
    operations=[None]*seeds
    targets=set(puzzle.targets)
    hit={v:i for i,v in enumerate(puzzle.seeds) if v in targets}
    def emit(v,op,a,b):
        index=len(values)
        values.append(v)
        operations.append((op,a,b))
        latest[v]=index
        if v in targets: hit.setdefault(v,index)
        return index
    def need(v):
        if v not in latest:
            op,a,b=graph[v]
            emit(v,op,need(a),need(b))
        return latest[v]
    for op,rs,rt,rd in old:
        ia,ib=warm_slots[rs],warm_slots[rt]
        a,b=values[ia],values[ib]
        v=(a+b if op=="+" else a-b if op=="-" else a*b if op=="*" else a//b)
        if v in graph and v not in latest:
            symbol,x,y=graph[v]
            if symbol==op and x==a and y==b:
                out=emit(v,op,ia,ib)
            elif symbol==op and op in "+*" and x==b and y==a:
                out=emit(v,op,ib,ia)
            else:
                out=emit(v,symbol,need(x),need(y))
        else:
            out=emit(v,op,ia,ib)
        warm_slots[rd]=out
    for t in targets: need(t)

    def allocate(goal_nodes):
        required=set()
        visit=list(goal_nodes)
        while visit:
            node=visit.pop()
            if node in required or node<seeds: continue
            required.add(node)
            _,a,b=operations[node]
            visit.extend((a,b))
        order=sorted(required)
        consumers=Counter(x for node in order for x in set(operations[node][1:]))
        mapped={i:i for i in range(seeds) if consumers[i]}
        available=list(set(range(puzzle.registers))-set(mapped.values()))
        heapq.heapify(available)
        program=[]
        for node in order:
            op,a,b=operations[node]
            ra,rb=mapped[a],mapped[b]
            for source in {a,b}:
                consumers[source]-=1
                if not consumers[source]: heapq.heappush(available,mapped.pop(source))
            if not available: return None
            dest=heapq.heappop(available)
            program.append((op,ra,rb,dest))
            if consumers[node]:
                mapped[node]=dest
            else:
                heapq.heappush(available,dest)
        return tuple(program)

    results=[allocate(hit.values()),allocate(latest[t] for t in targets)]
    # Anchor single-occurrence rewrites to their former physical placement.
    # A new prerequisite naturally appears just before its earliest old consumer.
    ordered=active_graph(puzzle,graph,targets=[v for v in values if v in graph])
    results.append(_allocate(puzzle,ordered,False,0,True))
    best=min((p for p in results if p is not None),key=len,default=None)
    if best is not None: check(puzzle,best)
    return best
