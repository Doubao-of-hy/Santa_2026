"""Invert two exact operations in which an unknown integer is used twice."""
from math import isqrt


def square_root(d):
    if d<0 or (d & 15) not in (0,1,4,9):
        return None
    x=isqrt(d)
    return x if x*x==d else None


def inverse_pair(n,a,limit):
    """Return h and a legal two-instruction path for n from h and anchor a.

    Covers the product of h with h+a, h-a or a-h, and the sum or
    either directed difference of h and a/h. All divisions are exact.
    """
    # f*g=n with |g-f|=a, or f+g=a.
    for discriminant,total in ((a*a+4*n,False),(a*a-4*n,True)):
        d=square_root(discriminant)
        if d is None or (d-a)%2:continue
        if total:
            f,g=(a-d)//2,(a+d)//2
        else:
            f,g=(d-a)//2,(d+a)//2
        if f<=0 or g>limit:continue
        for h,other in ((f,g),(g,f)):
            if total:inner=('-',a,h)
            elif h==f:inner=('+',h,a)
            else:inner=('-',h,a)
            yield h,((other,inner),(n,('*',h,other)))
    # h*k=a and n=|h-k| or h+k. Recover k exactly from the discriminant.
    for discriminant,total in ((n*n+4*a,False),(n*n-4*a,True)):
        d=square_root(discriminant)
        if d is None or (d-n)%2:continue
        if total:
            f,g=(n-d)//2,(n+d)//2
        else:
            f,g=(d-n)//2,(d+n)//2
        if f<=0 or g>limit:continue
        for h,other in ((f,g),(g,f)):
            outer=('+',h,other) if total else ('-',g,f)
            yield h,((other,('/',a,h)),(n,outer))


def additional_queries(p,regions,queries,quota,offsets):
    if quota<=0:return []
    by_region=[[] for _ in regions]
    for i,value,path in queries:
        if len(path)<=1 and len(by_region[i])<=offsets:
            by_region[i].append((value,path))
    additions=[]
    for i,(root,private,paid,_) in enumerate(regions):
        if len(private)<3:continue
        pool=set(paid);options={}
        for n,suffix in by_region[i]:
            for a in pool:
                for h,steps in inverse_pair(n,a,p.limit):
                    if h in (n,root) or h==steps[0][0]:continue
                    if steps[0][0] in (n,root) or steps[0][0] in pool:continue
                    path=steps+suffix
                    # Favor cheaper supplies, then short suffixes and small leaves.
                    key=(h not in pool,len(path),h.bit_length(),h,path)
                    options[h,path]=key
        for (h,path),_ in sorted(options.items(),key=lambda item:item[1])[:quota]:
            additions.append((i,h,path))
    return additions
