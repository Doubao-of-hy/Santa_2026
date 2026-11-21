"""Propagate changes of integer scale through an arithmetic program."""
from collections import Counter


def alternatives(p, traces, rounded=False):
    """Generate exact equivalent computations when intermediate scales differ."""
    hard=set(p.seeds)|set(p.targets)
    observed=set(hard)
    use=Counter()
    instructions=set()
    for graph in traces:
        observed.update(graph)
        for v,(op,a,b) in graph.items():
            use.update((a,b))
            instructions.add((v,op,a,b))
    preferred=(2,3,4,5,6,7,8,9,10,12,15,16,24,25,27,32,64,81,125,128,256)
    divisors=sorted(preferred,key=lambda x:(x not in observed,-use[x],x))[:8]
    scale={1,*divisors}
    ways=set()
    def edge(v,op,a,b):
        if min(v,a,b)<1 or max(v,a,b)>p.limit or v==a or v==b:return
        if op in '+*' and a>b:a,b=b,a
        ways.add((v,op,a,b))
    def plus(a,b):
        if min(a,b)<=0 or a>p.limit-b:return
        v=a+b
        edge(v,'+',a,b);edge(a,'-',v,b);edge(b,'-',v,a)
    def times(a,b):
        if min(a,b)<=0 or a>p.limit//b:return
        v=a*b
        edge(v,'*',a,b);edge(a,'/',v,b);edge(b,'/',v,a)
    def displaced(x,r):
        if r>0:plus(x,r)
        elif r<0:plus(x+r,-r)
    for v in observed:
        for d in divisors:
            if v%d==0:times(v//d,d)
    for v,op,a,b in instructions:
        if op in '+-':
            total,left,right=(v,a,b) if op=='+' else (a,v,b)
            for d in divisors:
                if left%d==0 and right%d==0:
                    plus(left//d,right//d)
                if total<=p.limit//d and (total*d in observed or left*d in observed or right*d in observed):
                    plus(left*d,right*d)
                    times(total,d);times(left,d);times(right,d)
                if not rounded or max(left,right)<2*d:continue
                # Signed, centered residues let one carry serve multiple rows.
                # The quotient of a sum differs from its component sum by at most one.
                qs=[(n+d//2)//d for n in (total,left,right)]
                if min(qs)<1 or any(q*d>p.limit for q in qs):continue
                if not any(q in observed for q in qs) and all(n%d for n in (total,left,right)):continue
                qt,qa,qb=qs
                plus(qa,qb);displaced(qa+qb,qt-qa-qb)
                for n,q in zip((total,left,right),qs):
                    times(q,d);displaced(q*d,n-q*d)
        else:
            product,left,right=(v,a,b) if op=='*' else (a,v,b)
            for d in divisors:
                if left%d==0:
                    times(left//d,right)
                    if right<=p.limit//d:
                        times(left//d,right*d);times(right,d)
                if right%d==0:
                    times(left,right//d)
                    if left<=p.limit//d:
                        times(left*d,right//d);times(left,d)
                if product%d==0:times(product//d,d)
                if left%d==0:
                    for q in divisors:
                        if d*q not in scale or right%q:continue
                        times(left//d,right//q);times(product//(d*q),d*q)
    return sorted(ways)
