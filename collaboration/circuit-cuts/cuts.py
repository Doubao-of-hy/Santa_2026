"""Replace two-input DAG cuts using enumerated arithmetic circuits and physical replay."""
import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PRIME = 1000000007
X = (173, 1009)
Y = (617, 379)
ONE = (1, 1)

@lru_cache(maxsize=8192)
def inverse(x):
    return pow(x, -1, PRIME)

def apply(op, a, b):
    if op == '+': return a + b
    if op == '-': return a - b
    if op == '*': return a * b
    if b == 0: raise ZeroDivisionError
    return a * inverse(b)

def enumerate_cuts(graph, seeds):
    """Construct all <=2-leaf cuts, retaining the nearest 96 boundary pairs per value."""
    frontiers = {v: [(v,)] if v != 1 else [()] for v in seeds}
    for v, (op, a, b) in graph.items():
        boundary = {tuple(sorted(set(l) | set(r))) for l in frontiers[a] for r in frontiers[b]
                    if len(set(l) | set(r)) <= 2}
        if v == 1:
            frontiers[v] = [()]
            continue
        accepted = []
        for leaves in sorted(boundary, key=lambda f: (len(f), f)):
            if not leaves: continue
            mapping = {leaf: X if i == 0 else Y for i,leaf in enumerate(leaves)}
            mapping[1] = ONE
            pending = [v]
            inside = set()
            while pending:
                node = pending.pop()
                if node in mapping or node in inside: continue
                inside.add(node)
                _, left, right = graph[node]
                pending.extend((left, right))
            accepted.append((len(inside), leaves, inside, mapping))
        accepted.sort(key=lambda item: (item[0], item[1]))
        frontiers[v] = [(v,)] + [item[1] for item in accepted[:96]]
        for size, leaves, inside, mapping in accepted[:96]:
            if not 3 <= size <= 16: continue
            try:
                def calc(node):
                    if node not in mapping:
                        op, left, right = graph[node]
                        pair = zip(calc(left), calc(right))
                        mapping[node] = tuple(apply(op, a, b) % PRIME for a, b in pair)
                    return mapping[node]
                key = calc(v)
            except ZeroDivisionError:
                continue
            yield v, leaves, size, key

def legal_recipe(seq, inputs, maximum, expected):
    from elf import arithmetic
    values = [*inputs, None] if len(inputs) == 1 else list(inputs)
    values.append(1)
    recipes = {}
    for op, i, j in seq:
        a, b = values[i], values[j]
        if a is None or b is None: return
        if op == '/' and a % b: return
        value = arithmetic(op, a, b)
        if not 1 <= value <= maximum or value in (a, b): return
        recipes[value] = (op, a, b)
        values.append(value)
    if values[-1] == expected: return recipes

def synthesize(keys, executable):
    text = ''.join(f'{a} {b}\n' for a,b in sorted(keys))
    out = subprocess.run([str(executable)],input=text,text=True,capture_output=True,check=True)
    lib = defaultdict(list)
    for line in out.stdout.splitlines():
        data = line.split()
        if not data:continue
        key = tuple(map(int,data[:2]))
        assert key in keys and (len(data)-2)%3 == 0
        lib[key].append(tuple((data[i],int(data[i+1]),int(data[i+2])) for i in range(2,len(data),3)))
    return lib

def evaluate(p, tape, graph, cuts, lib):
    from graph import active_graph, compile_graph
    from elf import check
    metrics = Counter(cuts=len(cuts))
    best = tape
    visited = set()
    for node, leaves, size, key in cuts:
        sequences = lib.get(key, ())
        if sequences:metrics['matching_cuts'] += 1
        for seq in sequences:
            if 1 not in p.seeds and 1 not in graph and any(i==2 or j==2 for _,i,j in seq):continue
            changes = legal_recipe(seq, leaves, p.limit, node)
            if not changes:continue
            for prefer_old in (True,False):
                diff = tuple((v,recipe) for v,recipe in changes.items()
                             if v not in p.seeds and recipe != graph.get(v)
                             and (not prefer_old or v==node or v not in graph))
                if not diff or diff in visited:continue
                visited.add(diff)
                try: revised=active_graph(p,graph | dict(diff))
                except (KeyError,ValueError):continue
                if len(revised)>=len(best):continue
                metrics['smaller_graphs']+=1
                program=compile_graph(p,revised,attempts=8,recompute=True)
                if program is not None and len(program)<len(best):
                    assert check(p,program)==len(program)
                    best=program
    metrics['distinct_replacements']=len(visited)
    return best, dict(metrics)

def run():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo',type=Path,required=True)
    ap.add_argument('--puzzles',type=Path,required=True)
    ap.add_argument('--pure',type=Path,required=True)
    ap.add_argument('--assisted',type=Path,required=True)
    ap.add_argument('--executable',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    sys.path.insert(0,str(args.repo.resolve()))
    from elf import Puzzle, check, read_submission, read_puzzles, write_submission, sha256
    from graph import first_recipes, active_graph
    from checkpoint import independent_score
    banks = {k:read_submission(f) for k,f in [('pure',args.pure),('assisted',args.assisted)]}
    assert sum(map(len,banks['pure'].values()))==140811 and sum(map(len,banks['assisted'].values()))==134385
    ps = read_puzzles(args.puzzles)
    sorted_ids=sorted(banks['assisted'],key=lambda k:(len(banks['assisted'][k]),k))
    cohort={}
    for i in range(8):
        ordered=sorted(sorted_ids[125*i:125*(i+1)],key=lambda k:hashlib.sha256(('two-input-circuit/1/'+k).encode()).digest())
        cohort.update((k,'development' if j<4 else 'holdout') for j,k in enumerate(ordered[:8]))
    work=[];keys=set()
    def add(lane,group,p,tape):
        graph=active_graph(p,first_recipes(p,tape))
        cuts=list(enumerate_cuts(graph,p.seeds))
        keys.update(c[3] for c in cuts)
        work.append((lane,group,p,tape,graph,cuts))
    # x^2 - 2xy + y^2, arranged as x^2 + y^2 - 2xy.
    artificial=Puzzle('positive', (7,3,1), (16,), 10000)
    control=(('*',0,0,3),('*',1,1,4),('+',3,4,5),('*',0,1,6),('+',6,6,7),('-',5,7,8))
    assert check(artificial,control)==6
    add('control','planted',artificial,control)
    for lane,bank in banks.items():
        for p in ps:
            if p.id in cohort:add(lane,cohort[p.id],p,bank[p.id])
    lib=synthesize(keys,args.executable)
    report={'hashes':{'pure':sha256(args.pure),'assisted':sha256(args.assisted)},'signatures':len(keys),'hits':len(lib),'rows':[]}
    args.output.mkdir(exist_ok=True,parents=True)
    wins={k:{} for k in banks}
    for lane,group,p,tape,graph,cuts in work:
        program,metrics=evaluate(p,tape,graph,cuts,lib)
        report['rows'].append(dict(lane=lane,cohort=group,id=p.id,before=len(tape),after=len(program),**metrics))
        if lane=='control':
            assert len(program)==2, report['rows'][-1]
            print('control',len(tape),len(program),'signatures',len(keys),'hits',len(lib),flush=True)
        elif len(program)<len(tape):
            wins[lane][p.id]=program
            print(lane,group,p.id,len(tape),len(program),flush=True)
    for lane,bank in banks.items():
        proposed=bank|wins[lane]
        out=args.output/(lane+'-full.csv')
        total=write_submission(out,ps,proposed)
        assert total==sum(independent_score(args.puzzles,out))
        write_submission(args.output/(lane+'-wins.csv'),[p for p in ps if p.id in wins[lane]],wins[lane])
        report[lane]={'full_score':total,'sha256':sha256(out),'strict_wins':len(wins[lane])}
    (args.output/'results.json').write_text(json.dumps(report,indent=1)+'\n',encoding='utf8')
    print({k:report[k] for k in banks},flush=True)

if __name__=='__main__':run()
