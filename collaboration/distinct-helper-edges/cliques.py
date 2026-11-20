"""Exact rational triangle closure followed by a distinct-label four-clique check."""
from functools import lru_cache
from itertools import combinations
from math import isqrt


def transforms(t):
    return ((-1, t, 0, 1), (1, -t, 0, 1), (1, t, 0, 1),
            (0, t, 1, 0), (1, 0, 0, t), (t, 0, 0, 1))


def compose(left, right):
    a, b, c, d = left
    e, f, g, h = right
    return a*e+b*g, a*f+b*h, c*e+d*g, c*f+d*h


def fixed_points(m, cap):
    a, b, c, d = m
    q = d - a
    if c == 0:
        if q == 0:
            return None if b == 0 else ()
        v, rem = divmod(b, q)
        return (v,) if rem == 0 and 1 <= v <= cap else ()
    disc = q*q + 4*c*b
    if disc < 0 or (disc & 15) not in (0, 1, 4, 9):
        return ()
    sqrt = isqrt(disc)
    if sqrt * sqrt != disc:
        return ()
    result = set()
    for s in (sqrt, -sqrt):
        v, rem = divmod(s-q, 2*c)
        if rem == 0 and 1 <= v <= cap:
            result.add(v)
    return tuple(sorted(result))


def apply(m, x, cap):
    a, b, c, d = m
    numerator, denominator = a*x+b, c*x+d
    if denominator == 0:
        return None
    value, rem = divmod(numerator, denominator)
    return value if rem == 0 and 1 <= value <= cap else None


def distinct(sets):
    """Hall's condition on the three edges incident to the fourth vertex."""
    a, b, c = sets
    return bool(a and b and c and (a | b).bit_count() >= 2 and (b | c).bit_count() >= 2
                and (a | c).bit_count() >= 2 and (a | b | c).bit_count() >= 3)


def resolve(labels, forbidden, cap, identity_limit=128):
    labels = tuple(sorted(set(labels)))
    transform = [transforms(t) for t in labels]
    flags = [1 << i for i in range(len(labels))]
    forbid = set(forbidden)
    counters = dict(triples=0, maps=0, identities=0, triangles=0)
    if len(labels) < 6 or cap - sum(1 <= v <= cap for v in forbid) < 4:
        return "ABSENT", counters, None

    @lru_cache(maxsize=256)
    def neighbors(a):
        result = {}
        for t, flag in zip(labels, flags):
            candidates = [t-a, a-t, a+t, a*t]
            if t % a == 0:
                candidates.append(t // a)
            if a % t == 0:
                candidates.append(a // t)
            for v in candidates:
                if 1 <= v <= cap and v != a and v not in forbid:
                    result[v] = result.get(v, 0) | flag
        return result

    def fourth(a, b, c, li):
        seen = flags[li[0]] | flags[li[1]] | flags[li[2]]
        na, nb, nc = neighbors(a), neighbors(b), neighbors(c)
        small = min((na, nb, nc), key=len)
        for d in small:
            available = (na.get(d, 0) & ~seen, nb.get(d, 0) & ~seen, nc.get(d, 0) & ~seen)
            if not distinct(available):
                continue
            def members(mask):
                return [labels[i] for i in range(len(labels)) if flags[i] & mask]
            for x in members(available[0]):
                for y in members(available[1]):
                    if y != x:
                        for z in members(available[2]):
                            if z not in (x, y):
                                return dict(vertices=[a, b, c, d],
                                            labels=[labels[li[0]], labels[li[1]], labels[li[2]], x, y, z],
                                            edges=["ab", "bc", "ca", "ad", "bd", "cd"])

    unresolved = False
    for i, j, k in combinations(range(len(labels)), 3):
        counters["triples"] += 1
        seen = set()
        for first in transform[i]:
            for second in transform[j]:
                path = compose(second, first)
                for third in transform[k]:
                    counters["maps"] += 1
                    roots = fixed_points(compose(third, path), cap)
                    if roots is None:
                        counters["identities"] += 1
                        if cap > identity_limit:
                            unresolved = True
                            continue
                        roots = range(1, cap+1)
                    for a in roots:
                        if a in forbid:
                            continue
                        b = apply(first, a, cap)
                        if b is None or b == a or b in forbid:
                            continue
                        c = apply(second, b, cap)
                        if c is None or c in (a, b) or c in forbid or apply(third, c, cap) != a:
                            continue
                        vertices = tuple(sorted((a, b, c)))
                        if vertices in seen:
                            continue
                        seen.add(vertices)
                        counters["triangles"] += 1
                        w = fourth(a, b, c, (i, j, k))
                        if w is not None:
                            return "PRESENT", counters, w
    return "UNKNOWN" if unresolved else "ABSENT", counters, None
