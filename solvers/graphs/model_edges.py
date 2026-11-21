"""Bidirectional arithmetic constraints induced by the fitted target families."""
from collections import Counter,defaultdict
from solvers.matrix.matrix_construct import factors


def support(p,model):
    if not model:return ()
    observations=(*model["targets"],*model.get("alternatives",()))
    corrections=defaultdict(Counter)
    for row in observations:
        corrections[row["a"]*row["b"]][row["d"]]+=1
    edges={}
    def edge(v,op,a,b):
        if min(a,b,v)<1 or max(a,b,v)>p.limit or v in (a,b):return
        if op in "+*" and a>b:a,b=b,a
        edges[v,op,a,b]=None
    def plus(a,b):
        v=a+b
        if a<1 or b<1 or v>p.limit:return None
        edge(v,"+",a,b);edge(a,"-",v,b);edge(b,"-",v,a)
        return v
    def offset(a,s):
        if not s:return a
        if s>0:return plus(a,s)
        v=a+s
        if v<1:return None
        plus(v,-s)
        return v
    def times(a,b):
        v=a*b
        if a<1 or b<1 or v>p.limit:return None
        edge(v,"*",a,b);edge(a,"/",v,b);edge(b,"/",v,a)
        return v
    for v,op,a,b in model.get("derived",()):
        if op=="+":plus(a,b)
        elif op=="-":plus(v,b)
        elif op=="*":times(a,b)
        elif op=="/":times(v,b)
    for row in observations:
        t,a,b,k,r=(row[x] for x in ("t","a","b","k","r"))
        if t!=a*b*k+r:raise ValueError((p.id,t))
        center=times(a,b)
        if center is None:continue
        d=row["d"]
        shifts={0,d,d-1,d+1}
        shifts.update(s for s,n in corrections[center].most_common(4) if n>=2)
        for shift in shifts:
            anchor=offset(center,shift)
            if anchor is None:continue
            scaled=times(anchor,k)
            if scaled is not None:offset(scaled,t-scaled)
            if shift!=d and shift!=0:continue
            for last in factors(k)[:7]:
                mid=times(anchor,k//last)
                if mid is None:continue
                diff=t-mid*last
                q=(2*diff+last)//(2*last)
                step=offset(mid,q)
                if step is not None:
                    out=times(step,last)
                    if out is not None:offset(out,t-out)
    return tuple(edges)
