"""Test for four distinct helper values linked by five different target outputs."""
from functools import lru_cache
from itertools import combinations, permutations
from pathlib import Path
import sys

def find_diamond(labels, forbidden, limit, identity_limit=128):
    from cliques import transforms, apply, compose, fixed_points
    labels = sorted(set(labels))
    if len(labels) < 5 or limit - len(forbidden) < 4:
        return "ABSENT", None
    @lru_cache(maxsize=384)
    def neighbors(a):
        result = {}
        for index, t in enumerate(labels):
            for b in (t-a, a-t, a+t, a*t, t//a if t%a==0 else 0, a//t if a%t==0 else 0):
                if 1<=b<=limit and b!=a and b not in forbidden:
                    result[b] = result.get(b, 0) | (1<<index)
        return result
    maps = [transforms(t) for t in labels]
    unresolved = False
    for i,j,k in combinations(range(len(labels)),3):
        used = (1<<i)|(1<<j)|(1<<k)
        visited = set()
        for first in maps[i]:
            for second in maps[j]:
                path = compose(second, first)
                for third in maps[k]:
                    roots = fixed_points(compose(third, path),limit)
                    if roots is None:
                        if limit>identity_limit:
                            unresolved=True
                            continue
                        roots=range(1,limit+1)
                    for a in roots:
                        if a in forbidden:
                            continue
                        b=apply(first,a,limit)
                        if b is None or b==a or b in forbidden:
                            continue
                        c=apply(second,b,limit)
                        if c is None or c in (a,b) or c in forbidden or apply(third,c,limit)!=a:
                            continue
                        vertices=tuple(sorted((a,b,c)))
                        if vertices in visited:
                            continue
                        visited.add(vertices)
                        for v,w in combinations(vertices,2):
                            nv,nw=neighbors(v),neighbors(w)
                            smaller,larger=(nv,nw) if len(nv)<=len(nw) else (nw,nv)
                            for x,mask in smaller.items():
                                if x in vertices:continue
                                left=mask & ~used
                                right=larger.get(x,0) & ~used
                                if left and right and (left|right).bit_count()>=2:
                                    for left_index in range(len(labels)):
                                        if (left>>left_index)&1:
                                            others=right&~(1<<left_index)
                                            if others:
                                                right_index=(others & -others).bit_length()-1
                                                order=(v,w) if smaller is nv else (w,v)
                                                return "PRESENT", dict(triangle=[a,b,c],labels=[labels[i],labels[j],labels[k]],extended=[*order,x],other_labels=[labels[left_index],labels[right_index]])
    return ("UNKNOWN" if unresolved else "ABSENT"), None

def outputs(a,b,limit):
    x,y=max(a,b),min(a,b)
    s={x+y,x-y,x*y}
    if x%y==0:s.add(x//y)
    return {v for v in s if 0<v<=limit}

def validate(w,limit,labels,forbidden):
    a,b,c=w["triangle"]
    i,j,k=w["labels"]
    v,z,x=w["extended"]
    l,m=w["other_labels"]
    return (len({a,b,c,x})==4 and {v,z}<={a,b,c} and v!=z and not ({a,b,c,x} & forbidden)
            and len({i,j,k,l,m})==5 and {i,j,k,l,m}<=set(labels)
            and all(t in outputs(e,f,limit) for e,f,t in ((a,b,i),(b,c,j),(c,a,k),(v,x,l),(z,x,m))))

def brute(labels,forbidden,limit):
    from itertools import product
    labels=set(labels)
    for a,b,c,d in combinations(set(range(1,limit+1))-forbidden,4):
        for x,y in combinations((a,b,c,d),2):
            z,w=sorted({a,b,c,d}-{x,y})
            legal=[outputs(i,j,limit)&labels for i,j in ((x,y),(x,z),(y,z),(x,w),(y,w))]
            if any(len(set(values))==5 for values in product(*legal)):
                return "PRESENT"
    return "ABSENT"
