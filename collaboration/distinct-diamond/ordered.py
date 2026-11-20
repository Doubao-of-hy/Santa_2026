"""Integer diamond oracle using two ordered larger neighbors of the minimum triangle vertex."""
from functools import lru_cache
from itertools import combinations
from math import isqrt

def actual(a,b,cap):
    hi,lo=max(a,b),min(a,b)
    vals={hi+lo,hi-lo,hi*lo}
    if hi%lo==0:vals.add(hi//lo)
    return {n for n in vals if 1<=n<=cap}

def adjacent(a,labels,banned,cap):
    ans={}
    for t in labels:
        candidates=[a+t,t-a,a-t,a*t]
        if t%a==0:candidates.append(t//a)
        if a%t==0:candidates.append(a//t)
        for b in candidates:
            if 1<=b<=cap and b!=a and b not in banned:
                ans.setdefault(b,set()).add(t)
    return ans

def extend(edges,labels,banned,cap,neighbors):
    vertices={v for a,b,t in edges for v in (a,b)}
    used={t for a,b,t in edges}
    for a,b,t in edges:
        # A triangle's fourth vertex may be below, between or above its numeric vertices.
        left=neighbors(a);right=neighbors(b)
        for d in (left.keys() & right.keys()) - vertices:
            aa=left[d]-used;bb=right[d]-used
            if not aa or not bb or len(aa|bb)<2:continue
            for i in aa:
                others=bb-{i}
                if others:return edges+[(a,d,i),(b,d,min(others))]
    return None

def roots(c,b,a,cap):
    """Return all positive integral roots of a*u^2+b*u+c, or None for an identity."""
    if a==0:
        if b==0:return None if c==0 else ()
        q,r=divmod(-c,b)
        return (q,) if not r and 0<q<=cap else ()
    delta=b*b-4*a*c
    if delta<0 or delta%16 not in (0,1,4,9):return ()
    s=isqrt(delta)
    if s*s!=delta:return ()
    out=set()
    for nom in (-b-s,-b+s):
        q,r=divmod(nom,2*a)
        if not r and 0<q<=cap:out.add(q)
    return tuple(out)

def shapes(t):
    # (s*u+i)/u^d, restricted to greater-than-u values by the caller.
    return ((-1,t,0),(1,t,0),(t,0,0),(0,t,1))

def evaluate(f,u):
    s,i,d=f
    q,r=divmod(s*u+i,u if d else 1)
    return q if not r else 0

def calculate(labels,banned,cap,identity_limit=128):
    labels=tuple(sorted(set(labels)));banned=set(banned)
    stats={'equations':0,'identities':0,'triangles':0}
    if len(labels)<5 or cap-sum(1<=b<=cap for b in banned)<4:return 'ABSENT',None,stats
    neighbors=lru_cache(maxsize=384)(lambda a:adjacent(a,labels,banned,cap))
    triangles=set();pending=False
    for x,y in combinations(labels,2):
        for f in shapes(x):
            A,B,d=f
            for g in shapes(y):
                C,D,e=g
                deg=max(d,e)
                # Coefficient triples are in constant, linear, quadratic order.
                p=(B,A,0) if deg==d else (0,B,A)
                q=(D,C,0) if deg==e else (0,D,C)
                add=tuple(a+b for a,b in zip(p,q))
                diff=tuple(a-b for a,b in zip(p,q))
                prod=(B*D,A*D+B*C,A*C)
                for z in labels:
                    if z==x or z==y:continue
                    rhs=(z,0,0) if deg==0 else (0,z,0)
                    rhs2=[0,0,0];rhs2[d+e]=z
                    eqs=[tuple(a-b for a,b in zip(add,rhs)),tuple(a-b for a,b in zip(diff,rhs)),
                         tuple(-a-b for a,b in zip(diff,rhs)),tuple(a-b for a,b in zip(prod,rhs2)),
                         tuple(a-z*b for a,b in zip(p,q)),tuple(b-z*a for a,b in zip(p,q))]
                    stats['equations']+=6
                    for coefficients in eqs:
                        solutions=roots(*coefficients,cap)
                        if solutions is None:
                            stats['identities']+=1
                            if cap>identity_limit:
                                pending=True;continue
                            solutions=range(1,cap+1)
                        for u in solutions:
                            if u in banned:continue
                            v,w=evaluate(f,u),evaluate(g,u)
                            if not (u<v<=cap and u<w<=cap) or v==w or v in banned or w in banned:continue
                            if z not in actual(v,w,cap):continue
                            if v<w:key=(u,v,w,x,y,z)
                            else:key=(u,w,v,y,x,z)
                            if key in triangles:continue
                            triangles.add(key);stats['triangles']+=1
                            edges=[(u,v,x),(u,w,y),(v,w,z)]
                            extras=extend(edges,labels,banned,cap,neighbors)
                            if extras:
                                return 'PRESENT',extras,stats
    return ('UNKNOWN' if pending else 'ABSENT'),None,stats

def check_witness(w,labels,banned,cap):
    if len(w)!=5:return False
    pairs={tuple(sorted((a,b))) for a,b,t in w}
    vertices=set(v for a,b,t in w for v in (a,b));levels={t for a,b,t in w}
    return (len(vertices)==4 and len(pairs)==5 and len(levels)==5 and
            not vertices&set(banned) and levels<=set(labels) and
            all(1<=a<=cap and 1<=b<=cap and a!=b and t in actual(a,b,cap) for a,b,t in w))
