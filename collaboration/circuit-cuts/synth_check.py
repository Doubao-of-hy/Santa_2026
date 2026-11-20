"""Verify a built circuit enumerator using planted identities and exhaustive shallow circuits."""
from collections import Counter, defaultdict
from pathlib import Path
import subprocess
import sys

MODULUS = 1000000007
POINTS = ((173, 617), (1009, 379))
SLOTS = tuple(zip(*POINTS)) + ((1, 1),)


def evaluate(program, x, y, modulus=None):
    values = [x, y, 1]
    for op, i, j in program:
        left, right = values[i], values[j]
        if op == "+": value = left + right
        elif op == "-": value = left - right
        elif op == "*": value = left * right
        elif modulus: value = left * pow(right, -1, modulus)
        elif right and left % right == 0: value = left // right
        else: return None
        if modulus: value %= modulus
        elif value <= 0: return None
        values.append(value)
    return values[-1]


def shallow_signatures():
    found = defaultdict(set)
    def visit(values, masks, ones, d):
        if d == 3: return
        for i, (x, u) in enumerate(values):
            for j, (y, v) in enumerate(values):
                m = masks[i] | masks[j] | (1 << d)
                one = ones[i] or ones[j]
                options = {((x+y)%MODULUS, (u+v)%MODULUS),
                           ((x-y)%MODULUS, (u-v)%MODULUS),
                           (x*y%MODULUS, u*v%MODULUS)}
                if y and v:
                    options.add((x*pow(y,-1,MODULUS)%MODULUS, u*pow(v,-1,MODULUS)%MODULUS))
                for candidate in options:
                    if m == (1 << (d+1))-1: found[candidate,d+1].add(one)
                    visit(values+(candidate,), masks+(m,), ones+(one,), d+1)
    visit(SLOTS, (0, 0, 0), (False, False, True), 0)
    return found


def main(binary):
    expected = shallow_signatures()
    signatures = sorted({sig for sig, _ in expected})
    query = "".join(f"{a} {b}\n" for a,b in signatures)
    out = subprocess.run([str(binary.resolve())], input=query, text=True, capture_output=True, check=True)
    assert not out.stderr
    counts = Counter()
    recorded = defaultdict(set)
    tapes = defaultdict(set)
    for line in out.stdout.splitlines():
        a, b, *fields = line.split()
        assert len(fields) % 3 == 0
        program = tuple((fields[i],int(fields[i+1]),int(fields[i+2])) for i in range(0,len(fields),3))
        size = len(program)
        assert 1 <= size <= 4
        dependency = [0]*3
        for k, (op, i, j) in enumerate(program):
            assert op in ("+", "-", "*", "/") and 0 <= i < k+3 and 0 <= j < k+3
            dependency.append(dependency[i]|dependency[j]|(1<<k))
        assert dependency[-1] == (1<<size)-1
        sig = (int(a),int(b))
        assert tuple(evaluate(program,x,y,MODULUS) for x,y in POINTS) == sig
        assert program not in tapes[sig]
        tapes[sig].add(program)
        counts[sig,size] += 1
        if size <= 3:
            recorded[sig,size].add(any(i==2 or j==2 for _,i,j in program))
    assert max(counts.values()) <= 8 and recorded == expected
    signature = lambda f: tuple(f(x,y)%MODULUS for x,y in POINTS)
    squared = signature(lambda x,y:(x+y)**2)
    assert (("+",0,1),("*",3,3)) in tapes[squared]
    cross = signature(lambda x,y:(x+y)*(x+y+1))
    assert any(len(t)==3 and evaluate(t,11,5)==272 and sum((i==3)+(j==3) for _,i,j in t)>=2 for t in tapes[cross])
    difference = signature(lambda x,y:x*x-y*y)
    assert {t[-1][0] for t in tapes[difference] if len(t)==3 and evaluate(t,11,5)==96} >= {"-","*"}
    for left,right in ((0,1),(1,0)):
        program = (("/",left,right),)
        assert program in tapes[signature(lambda x,y:evaluate(program,x,y,MODULUS))]
    print(f"{len(signatures)} signatures, {len(expected)} signature/depth pairs, {sum(counts.values())} replays.")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
