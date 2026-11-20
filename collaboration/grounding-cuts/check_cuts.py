"""Check generated blocking sets against direct enumeration of tiny arithmetic libraries."""
from itertools import combinations, combinations_with_replacement
import json
from pathlib import Path
import random
from search import Bank

def arithmetic(a,b):
    yield a+b,('+',a,b)
    yield b-a,('-',b,a)
    yield a*b,('*',a,b)
    if not b%a:yield b//a,('/',b,a)

def run():
    rng=random.Random(20261120);seen=0;states=0;cuts=0
    for trial in range(100):
        roots={2,3};universe=set(range(1,10))
        goals=set(rng.sample(sorted(universe-roots),2));rules={v:set() for v in universe-roots}
        for a,b in combinations_with_replacement(sorted(universe),2):
            for v,recipe in arithmetic(a,b):
                if v in rules and v not in (a,b) and rng.random()<0.8:rules[v].add(recipe)
        bank=Bank(roots,goals,rules);full=(1<<bank.n)-1
        if bank.close(full)&bank.goals!=bank.goals:continue
        seen+=1
        def brute(allow):
            available=roots.copy()
            while True:
                new={v for v,ops in rules.items() if v in allow and any(a in available and b in available for _,a,b in ops)}
                if new<=available:return available
                available|=new
        allstates={}
        for count in range(len(bank.optional)+1):
            for choice in combinations(bank.optional,count):
                enable=bank.base|sum(bank.bit[i] for i in choice)
                allow={v for v,b in zip(bank.values,bank.bit) if enable&b}
                known=brute(allow);reached=bank.close(enable)
                assert reached==sum(bank.bit[bank.index[v]] for v in known)
                allstates[enable]=reached;states+=1
        for enabled,reached in allstates.items():
            for goal in sorted(goals):
                b=bank.bit[bank.index[goal]]
                if reached&b:continue
                order=bank.optional[:];rng.shuffle(order)
                cut=bank.cut(enabled,reached,b,order);mask=sum(bank.bit[i] for i in cut);cuts+=1
                assert mask and all(not r&b or a&mask for a,r in allstates.items())
                complement=full^mask
                assert not allstates[complement]&b and all(allstates[complement|bank.bit[i]]&b for i in cut)
    return dict(libraries=seen,exhaustive_helper_sets=states,independently_checked_minimal_cuts=cuts)
if __name__=='__main__':print(json.dumps(run(),indent=2))
