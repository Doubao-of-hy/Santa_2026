"""Independent oracle using ordered helpers and Laurent polynomials, without Mobius matrices."""
from functools import lru_cache
from itertools import combinations
from math import isqrt


def larger_shapes(t):
    # w>u; store (coefficient of u^-1, constant, coefficient of u).
    return ((0, t, -1), (0, t, 1), (t, 0, 0), (0, 0, t))


def evaluate(poly, u, cap):
    rec, intercept, slope = poly
    if rec % u:
        return 0
    value = rec // u + intercept + slope*u
    return value if u < value <= cap else 0


def roots(coeff, cap, identity_limit=128):
    # Remove zero powers at each end. Positive integer roots are preserved by multiplication by u.
    lo, hi = 0, len(coeff)-1
    while lo <= hi and not coeff[lo]:
        lo += 1
    if lo > hi:
        return range(1, cap+1) if cap <= identity_limit else None
    while not coeff[hi]:
        hi -= 1
    deg = hi-lo
    if deg == 0:
        return ()
    if deg == 1:
        x, r = divmod(-coeff[lo], coeff[hi])
        return (x,) if r == 0 and 1 <= x <= cap else ()
    if deg != 2:
        raise AssertionError(("unexpected polynomial degree", coeff))
    a, b, c = coeff[hi], coeff[lo+1], coeff[lo]
    disc = b*b - 4*a*c
    if disc < 0 or disc % 16 not in (0, 1, 4, 9):
        return ()
    s = isqrt(disc)
    if s*s != disc:
        return ()
    values = []
    for numerator in {-b+s, -b-s}:
        x, r = divmod(numerator, 2*a)
        if not r and 1 <= x <= cap:
            values.append(x)
    return values


def pair_values(a, b, cap):
    assert 1 <= a < b <= cap
    result = {b-a}
    if a+b <= cap:
        result.add(a+b)
    if a*b <= cap:
        result.add(a*b)
    if b % a == 0:
        result.add(b//a)
    return result


def audit(labels, forbidden, cap, counts=None):
    labels = set(labels)
    banned = set(forbidden)
    if counts is None:
        counts={}
    counts.update(label_pairs=0,equations=0,unresolved_identity=0,grounded_triangles=0)
    if len(labels)<6 or cap-sum(1<=v<=cap for v in banned)<4:
        return "ABSENT", None
    @lru_cache(maxsize=384)
    def next_edges(a):
        result = {}
        for t in labels:
            for larger in (a+t, t-a, a*t, t//a if t%a==0 else 0):
                if a < larger <= cap and larger not in banned:
                    result.setdefault(larger, set()).add(t)
        return result
    def finish(u, v, w, x, y, z):
        skip = {x,y,z}
        for h, uf in next_edges(u).items():
            if h <= w:
                continue
            uf = uf-skip
            vf = (pair_values(v,h,cap)&labels)-skip
            wf = (pair_values(w,h,cap)&labels)-skip
            for i in uf:
                for j in vf-{i}:
                    others = wf-{i,j}
                    if others:
                        return [u,v,w,h,x,y,z,i,j,min(others)]
    unresolved = False
    visited = set()
    sorted_labels=sorted(labels)
    for x,y in combinations(sorted_labels,2):
        counts["label_pairs"]+=1
        # Fix the lowest auxiliary u of the four and its two neighbors v,w.
        # The numeric order of the two edge labels does not fix the order of the neighbors.
        for left in larger_shapes(x):
            a,b,c=left
            for right in larger_shapes(y):
                d,e,f=right
                # The sum and product are symmetric. Both difference/ratio orientations must be tried.
                candidates=((a+d,b+e,c+f),(a-d,b-e,c-f),(d-a,e-b,f-c))
                product=(a*d, a*e+b*d, a*f+b*e+c*d, b*f+c*e, c*f)
                for z in sorted_labels:
                    if z==x or z==y:
                        continue
                    equations = [(j,k-z,l) for j,k,l in candidates]
                    equations.extend(((a-z*d,b-z*e,c-z*f),(d-z*a,e-z*b,f-z*c),
                                      (product[0],product[1],product[2]-z,product[3],product[4])))
                    counts["equations"]+=len(equations)
                    for equation in equations:
                        possible=roots(equation,cap)
                        if possible is None:
                            unresolved=True
                            counts["unresolved_identity"]+=1
                            continue
                        for u in possible:
                            if u in banned:
                                continue
                            lv,rv=evaluate(left,u,cap),evaluate(right,u,cap)
                            if not lv or not rv or lv==rv or lv in banned or rv in banned:
                                continue
                            v,w=sorted((lv,rv))
                            if z not in pair_values(v,w,cap):
                                continue
                            key=(u,v,w,x,y,z)
                            if key in visited:
                                continue
                            visited.add(key)
                            counts["grounded_triangles"]+=1
                            first,second=(x,y) if lv<rv else (y,x)
                            found=finish(u,v,w,first,second,z)
                            if found is not None:
                                return "PRESENT",found
    return ("UNKNOWN" if unresolved else "ABSENT"), None
