"""Infer unobserved common scalar-affine ancestors of multiple targets in a recovered table cell."""
from collections import Counter,defaultdict
from math import log2

from gpu_factor_graph import divisor_pairs
from matrix_construct import Route


def expand(p,model,options):
    cells=defaultdict(dict);cost_count=Counter()
    derived={v:(op,a,b) for v,op,a,b in model.get('derived',())}
    for row in model['targets']:
        a,b,k,r,t=(row[z] for z in ('a','b','k','r','t'))
        cells[a,b][t]=(k,r)
        cost_count.update(set(abs(row[z]) for z in ('k','r','d','e') if row[z]))
    seeds=set(p.seeds)
    common=seeds|set(range(1,17))|{x for x,n in cost_count.most_common(54) if x<=32768}
    # Scalar factors recur across cells even when their offsets differ.
    for group in cells.values():
        for k,r in group.values():
            if k<=2_000_000_000:
                for a,b in divisor_pairs(k):cost_count.update((a,b))
    def price(v):
        if not v or v in seeds:return 0
        return max(.75,(1.25+max(0,v.bit_length()-3)*.17)/(1+.15*log2(1+cost_count[v])))
    def quality(route):
        return len(route.graph)+sum(price(z) for z in route.leaves)
    def origins(a,b):
        g={};leaves=set()
        def build(v):
            if v in g:return
            if v in derived:
                op,x,y=derived[v];build(x);build(y);g[v]=(op,x,y)
            elif v not in seeds:leaves.add(v)
        c=a*b
        if c in derived or c==a or c==b:build(c)
        else:build(a);build(b);g[c]=('*',a,b)
        return Route(g,leaves)
    def transforms(old,v,m,gap,goal):
        near=(2*gap+m)//(2*m)
        for q in {0,near,near-1,near+1}:
            mid=v+q;prod=mid*m;e=goal-prod
            if min(mid,prod)<=0 or max(mid,prod)>p.limit or (m!=1 and goal==mid):continue
            g=old.graph.copy();leaves=set(old.leaves)
            if q:g.setdefault(mid,('+' if q>0 else '-',v,abs(q)));leaves.add(abs(q))
            if m!=1:g.setdefault(prod,('*',mid,m));leaves.add(m)
            if e:g.setdefault(goal,('+' if e>0 else '-',prod,abs(e)));leaves.add(abs(e))
            known={w for edge in g.values() for w in edge[1:] if w not in g}
            # Numeric coincidences can turn a would-be helper into an input
            # needed by its own ancestor. Admit a route only after replay.
            for w,edge in g.items():
                if w in edge[1:] or edge[1] not in known or edge[2] not in known:break
                known.add(w)
            else:
                yield Route(g,leaves-set(g)-seeds)
    def shortlist(seq,n):
        out=[];seen=set()
        for route in sorted(seq,key=quality):
            key=tuple(sorted(route.graph.items()))
            if key not in seen:out.append(route);seen.add(key)
            if len(out)>=n:break
        return out
    output={t:list(routes) for t,routes in options.items()};added=0
    for (a,b),group in cells.items():
        if len(group)<2:continue
        center=a*b;base=origins(a,b);states=defaultdict(set)
        for t,(k,r) in group.items():
            if not 1<k<=2_000_000_000:continue
            factors={1}|{x for pair in divisor_pairs(k) for x in pair}
            for d in factors:
                m=k//d
                s0=(2*r+m)//(2*m)
                choices={s0,s0-1,s0+1,0}
                for e in common:
                    for delta in {e,-e}:
                        if (r-delta)%m==0:choices.add((r-delta)//m)
                for s in choices:
                    v=d*center+s
                    if v in (center,t) or not 0<v<=p.limit:continue
                    states[d,s].add(t)
        scores=[]
        for (d,s),users in states.items():
            if len(users)<2:continue
            old_cost=0;new_cost=0
            for t in users:
                k,r=group[t];m=k//d;e=r-s*m
                # Count the actual arithmetic operators separately from small
                # constants so that zero residuals get their proper credit.
                old_cost+=(k!=1)+(r!=0)+price(k)+price(abs(r))
                new_cost+=(m!=1)+(e!=0)+price(m)+price(abs(e))
            advantage=old_cost-new_cost - ((d!=1)+(s!=0)+price(d)+price(abs(s)))
            scores.append((advantage+.8*len(users),d,s))
        scores.sort(reverse=True);taken=Counter();ancestors={}
        for _,d,s in scores:
            if taken[d]>=6:continue
            taken[d]+=1;ancestors[d,s]=[]
            if len(ancestors)>=28:break
        proposals=defaultdict(list)
        for d,s in sorted(ancestors):
            v=center*d+s
            starting=list(transforms(base,center,d,s,v))
            for t,(k,r) in group.items():
                if k>=d or d%k or t==v:continue
                starting.extend(transforms(Route({},set()),t,d//k,s-r*(d//k),v))
            for (h,bias),sources in ancestors.items():
                if h>=d or d%h or not sources:continue
                link=d//h;prev=h*center+bias
                starting.extend(transforms(sources[0],prev,link,s-link*bias,v))
            ancestors[d,s]=shortlist(starting,3)
            for t in states[d,s]:
                k,r=group[t];m=k//d;e=r-m*s
                for source in ancestors[d,s]:
                    if t in source.graph or any(t in edge[1:] for edge in source.graph.values()):continue
                    proposals[t].extend(transforms(source,v,m,e,t))
        for t,choices in proposals.items():
            old=output.setdefault(t,[])
            seen={tuple(sorted(r.graph.items())) for r in old}
            for r in shortlist(choices,32):
                if tuple(sorted(r.graph.items())) not in seen:old.append(r);added+=1
    return output,added
