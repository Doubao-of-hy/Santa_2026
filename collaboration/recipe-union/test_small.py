"""Compare the recorded-recipe search with breadth-first state enumeration on small banks."""
from collections import deque
import random
from solver import search
from elf import Puzzle, check, replay
from graph import compile_graph
from solvers.graphs.corpus_prefix import arithmetic_edges


def shortest(p,parents):
    allowed=set()
    for tape in parents:
        for v,_,a,b in replay(p,tape):
            allowed.add((v,a,b))
    start=frozenset(p.seeds);queue=deque([start]);seen={start}
    while queue:
        reached=queue.popleft()
        if reached.issuperset(p.targets):
            return len(reached-start)
        for v,a,b in allowed:
            if v not in reached and a in reached and b in reached:
                add=reached|{v}
                if add not in seen:
                    seen.add(add);queue.append(add)
    raise RuntimeError("invalid input bank")


def main():
    rng=random.Random(4215)
    p=Puzzle('control',(2,3,5,7),(10,14),32)
    parents=[(('*',0,2,4),('+',2,3,5),('+',5,0,6)),(('*',0,3,4),('+',1,1,5),('-',5,0,6),('+',5,6,7))]
    tape,r=search(p,parents,1000)
    assert r['complete'] and check(p,tape)==shortest(p,parents)==2
    verified=cycles=gains=0
    while verified<128:
        paths=[]
        for _ in range(3):
            known=[2,3];path=[]
            for j in range(8):
                options=[(v,op,a,b) for i,x in enumerate(known) for y in known[:i+1] for v,(op,a,b) in arithmetic_edges(x,y,19) if v not in known]
                if not options:break
                v,op,a,b=rng.choice(options);path.append((op,known.index(a),known.index(b),len(known)));known.append(v)
            paths.append((known,tuple(path)))
        pool=set.intersection(*(set(z[0]) for z in paths))-{2,3}
        if len(pool)<2:continue
        targets=tuple(sorted(rng.sample(sorted(pool),2)))
        p=Puzzle('small',(2,3),targets,19)
        parents=[entry[1] for entry in paths]
        tape,r=search(p,parents,50000);expected=shortest(p,parents)
        assert r['complete'] and r['graph_upper']==expected==check(p,tape),(r,expected)
        cycles+=r['cycles'];gains+=r['before']>expected;verified+=1
    print(f'{verified} random banks match BFS, {gains} shorter than their supplied tapes; planted case 3 to 2')


if __name__=='__main__':
    main()
