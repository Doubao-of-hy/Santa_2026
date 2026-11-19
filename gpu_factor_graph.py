"""Share factor pairs of neighboring template coefficients across their arithmetic programs."""
from collections import Counter,defaultdict
from functools import lru_cache
from math import isqrt,log2

from gpu_conditioned import normalized


@lru_cache(maxsize=65536)
def divisor_pairs(value):
    if value<4:return ()
    n=value;factors=[];prime=2
    while prime*prime<=n:
        count=0
        while n%prime==0:n//=prime;count+=1
        if count:factors.append((prime,count))
        prime=3 if prime==2 else prime+2
    if n>1:factors.append((n,1))
    divisors=[1]
    for prime,count in factors:
        old=divisors[:];mul=1
        for _ in range(count):
            mul*=prime;divisors.extend(x*mul for x in old)
    return tuple((a,value//a) for a in divisors if 1<a<=isqrt(value))


def augment(p,bank,initial,desired,supply):
    active=sorted(v for v in desired if 8<v<=2_000_000_000)
    freq=Counter(x for v in active for pair in divisor_pairs(v) for x in pair)
    def cost(v):
        if v in initial:return .35
        return max(.6,1.2+.19*v.bit_length()-.58*log2(freq[v]+1))
    offsets={0,1,2,3,5,8}|{v for v in p.seeds if v<=32}
    offsets|={-v for v in offsets}
    proposals=[]
    wanted=set()
    for t in active:
        possible=[]
        for shift in offsets:
            center=t-shift
            if not 1<center<=p.limit:continue
            pairs=divisor_pairs(center)
            for a,b in pairs:
                score=cost(a)+(cost(b) if b!=a else 0)+(cost(abs(shift))+.8 if shift else 0)
                possible.append((score,abs(shift),center,a,b,shift))
        possible.sort()
        for _,_,center,a,b,h in possible[:12]:
            proposals.append((t,center,a,b,h))
            wanted.update((a,b))
            if h:wanted.add(abs(h))
    available=supply(p,bank,initial,wanted)
    additions=0
    for t,center,a,b,shift in proposals:
        if a not in available or b not in available or (shift and abs(shift) not in available):continue
        bank[center].add(normalized('*',a,b))
        if shift:bank[t].add(normalized('+' if shift>0 else '-',center,abs(shift)))
        additions+=1
    return additions
