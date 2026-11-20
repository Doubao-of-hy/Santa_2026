"""Compare the exact symbolic four-clique test to independent finite enumeration."""
import argparse
from collections import Counter
from itertools import combinations
import json
from pathlib import Path
import random

from cliques import resolve
from sorted_quads import audit


def actual_products(a, b, cap):
    a, b = min(a, b), max(a, b)
    options = {a+b, b-a, a*b}
    if b % a == 0:
        options.add(b//a)
    return {g for g in options if 1 <= g <= cap}


def assignment(families, seen=frozenset()):
    if not families:
        return True
    return any(assignment(families[1:], seen | {x}) for x in families[0] - seen)


def brute(labels, forbidden, cap):
    vertices = sorted(set(range(1, cap+1)) - set(forbidden))
    pairs = {(a, b): actual_products(a, b, cap) & set(labels) for a, b in combinations(vertices, 2)}
    for nodes in combinations(vertices, 4):
        options = sorted((pairs[e] for e in combinations(nodes, 2)), key=len)
        if all(options) and assignment(options):
            return True
    return False


def check_witness(w, labels, forbidden, cap):
    verts = dict(zip("abcd", w["vertices"]))
    assert len(set(verts.values())) == 4 and not (set(verts.values()) & set(forbidden))
    assert len(set(w["labels"])) == 6 and set(w["labels"]) <= set(labels)
    for edge, label in zip(w["edges"], w["labels"]):
        assert label in actual_products(verts[edge[0]], verts[edge[1]], cap)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("output", type=Path)
    args = ap.parse_args()
    counts = Counter()
    def trial(labels, excluded, cap):
        yes = brute(labels, excluded, cap)
        answer, stats, witness = resolve(labels, excluded, cap)
        assert answer == ("PRESENT" if yes else "ABSENT"), (labels, excluded, cap, yes, answer)
        if yes:
            check_witness(witness, labels, excluded, cap)
        independent, quad = audit(labels, excluded, cap)
        assert independent == answer
        if quad:
            u,v,w,h,x,y,z,i,j,k=quad
            check_witness(dict(vertices=[u,v,w,h],labels=[x,y,z,i,j,k],
                               edges=["ab","ac","bc","ad","bd","cd"]),labels,excluded,cap)
        counts[answer] += 1
        counts["identity_cases"] += int(stats["identities"] > 0)
    for cap in (6, 7, 8):
        for size in range(6, cap+1):
            for labels in combinations(range(1, cap+1), size):
                for forbidden in (set(), {1}, {cap//2, cap}):
                    trial(labels, forbidden, cap)
    rng = random.Random(222616)
    for _ in range(100):
        cap = rng.randint(9, 17)
        labels = sorted(rng.sample(range(1, cap+1), rng.randint(6, min(10, cap))))
        excluded = rng.sample(range(1, cap+1), rng.randint(0, 5))
        trial(labels, excluded, cap)
    for _ in range(200):
        cap=rng.randint(14,24)
        labels=rng.sample(range(1,cap+1),6)
        kept=rng.sample(range(1,cap+1),rng.randint(4,6))
        trial(labels,set(range(1,cap+1))-set(kept),cap)
    labels = [10, 14, 26, 18, 30, 34]
    result, counts_planted, witness = resolve(labels, set(labels), 64)
    assert result == "PRESENT"
    check_witness(witness, labels, set(labels), 64)
    # A symbolic identity offers infinitely many formal starting values; forcing
    # a tiny cap on exact processing must not yield a spurious negative.
    for labels in combinations(range(1, 10), 6):
        result, stats, w = resolve(labels, {1, 3, 5, 7}, 11, identity_limit=0)
        if result == "UNKNOWN":
            break
    else:
        raise AssertionError("missing conservative identity test")
    args.output.write_bytes((json.dumps(dict(exhaustive_and_seeded=dict(counts), planted=witness,
                                             identity_fallback=result), indent=1)+"\n").encode())
    print(counts, witness, result)


if __name__ == "__main__":
    main()
