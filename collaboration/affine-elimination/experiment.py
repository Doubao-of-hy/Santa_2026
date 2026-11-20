"""Compile inverse witnesses for two open linear inputs across attributed programs."""
import argparse
import csv
import hashlib
import itertools
import io
import json
import math
import os
import subprocess
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path

HERE = Path(__file__).resolve().parent
def checkout():
    for folder in HERE.parents:
        if (folder / 'collaboration/structure-controls/ruler/selector.py').is_file():
            return folder
    return Path('E:/Codex/Santa2026-GitHub')


PUBLISHED = Path(os.getenv('SANTA_CHECKOUT', checkout()))
BASE = Path(os.getenv('SANTA_PROJECT', PUBLISHED))
DATASETS = Path(os.getenv('SANTA_DONORS', BASE / 'work/creative/resume-135077'))
OFFICIAL = Path(os.getenv('SANTA_PUZZLES', BASE / 'data/puzzles.csv'))
REV = '472b715858b74910ca9b1eafcbea4d64183fa09d'
NAMES = ['incumbent', 'local-independent', 'asterios118', 'hanif23', 'rudolph67']
HASHES = [
    '85f46d2d7a67afb91ec59c9b2ace8b974d7334ed8677250170aae36805561035',
    'f1bb3f6b2eb7f20280db2b551710aa080a09f1e0405f9cc7b13d845481ae3a5f',
    '5d5afb3f812996488f1f6e83687d38e8674b9442a0514435b5c7872c0e7ac8fe',
    '48f7dbc58893dc54d0d601adde202cddd8fd356bfaa6be90ed3486d1a5e7d260',
    '085eda6649d8f3b8d51d5f32e9f998c3978b5fa29ffb45e45e7e93fb322d3051',
]
sys.path[:0] = [str(PUBLISHED / 'collaboration/structure-controls/ruler'), str(BASE)]
from selector import compile_selection
from elf import arithmetic, check, read_puzzles, write_submission
from graph import active_graph, first_recipes

DEV = '0750 0161 0331 0435 0807 0793 0309 0754'.split()
HOLD = '0830 0148 0109 0530 0144 0062 0428 0991 0152 0568 0745 0785 0757 0781 0334 0317'.split()


def normalize(path):
    with path.open(encoding='utf-8-sig',newline='') as file:
        programs={r['id']:json.loads(r['program']) for r in csv.DictReader(file)}
    buffer=io.StringIO(newline='')
    output=csv.writer(buffer,lineterminator='\n')
    output.writerow(['id','program'])
    for identifier,program in sorted(programs.items()):
        output.writerow([identifier,json.dumps(program,separators=(',',':'))])
    return buffer.getvalue().encode('utf8')


def parents():
    paths = ['public-assisted/submission.csv', 'submission.csv']
    blobs = [subprocess.check_output(['git','-C',str(PUBLISHED),'show',f'{REV}:{f}']) for f in paths]
    for dataset,raw_name in zip(NAMES[2:], ['best_programs.csv','submission.csv','rudolph_programs.csv']):
        normalized=DATASETS/dataset/'programs.csv'
        if normalized.is_file():
            blobs.append(normalized.read_bytes())
        else:
            blobs.append(normalize(DATASETS/dataset/raw_name))
    result = []
    for blob, h in zip(blobs, HASHES):
        # Published checkout uses CRLF even when the corresponding Git blob uses LF.
        if hashlib.sha256(blob).hexdigest() != h:
            blob = blob.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
        assert hashlib.sha256(blob).hexdigest() == h, h
        rows = csv.DictReader(blob.decode('utf-8-sig').splitlines())
        result.append({r['id']:r['program'] for r in rows})
    return result


def component_forms(graph):
    """Track bounded integral affine forms over pairs actually mixed by an instruction."""
    descendants = defaultdict(list)
    for w, (_, a, b) in graph.items():
        for k in {a,b}:
            descendants[k].append(w)
    def roots(v):
        r = [v]
        for _ in range(2):
            edge = graph.get(r[-1])
            if edge is None:
                break
            op,a,b = edge
            if op in '+-' and min(a,b) <= 16 and max(a,b)>16:
                r.append(max(a,b))
            elif op == '*' and min(a,b) <= 16 and max(a,b)>16:
                r.append(max(a,b))
            elif op == '/' and b<=16 and a>16:
                r.append(a)
            elif op=='+' and a==b:
                r.append(a)
            else:
                break
        return r
    pairs = set()
    for op,a,b in graph.values():
        if op in '+-' and a!=b:
            pairs.update(tuple(sorted((x,y))) for x in roots(a) for y in roots(b) if x!=y)
    output = defaultdict(dict)
    for x,y in sorted(pairs):
        known = {x:(1,0,0,0), y:(0,1,0,0)}
        queue = deque((x,y))
        def fetch(v):
            return known.get(v, (0,0,v,0) if v<=16 else None)
        while queue:
            k = queue.popleft()
            for z in descendants[k]:
                if z in known:
                    continue
                op,u,v = graph[z]
                a,b = fetch(u),fetch(v)
                if op in '+-' and a and b:
                    s = 1 if op=='+' else -1
                    coeff = tuple(a[j] + s*b[j] for j in range(3))
                elif op=='*' and min(u,v)<=16 and (src:=fetch(max(u,v))):
                    coeff = tuple(t*min(u,v) for t in src[:3])
                    a=b=src
                elif op=='/' and v<=16 and a and all(t%v==0 for t in a[:3]):
                    coeff=tuple(t//v for t in a[:3]); b=a
                else:
                    continue
                depth=1+max(a[3],b[3])
                if depth>6 or max(abs(t) for t in coeff[:2])>24 or abs(coeff[2])>48:
                    continue
                if not (coeff[0] or coeff[1]):
                    continue
                assert coeff[0]*x+coeff[1]*y+coeff[2] == z
                known[z]=(*coeff,depth); queue.append(z)
                if coeff[0] and coeff[1]:
                    output[x,y][z]=coeff
    return output


def formula(e1,e2):
    z,(a,b,c)=e1
    w,(d,e,f)=e2
    det=a*e-b*d
    if det==0:
        return []
    return [(z,e,w,-b,b*f-e*c,det),(z,-d,w,a,d*c-a*f,det)]


def expressions(target, spec, pool, limit):
    z,m,w,n,k,den=spec
    div=math.gcd(m,n,k,den)
    if den<0:
        div=-div
    m,n,k,den=m//div,n//div,k//div,den//div
    # Only constants already available in some parent may be used as literal operands.
    if den!=1 and den not in pool:
        return []
    patch={}
    def record(x,op,a,b):
        assert arithmetic(op,a,b)==x
        if not 1<=x<=limit or x in (a,b):
            raise ValueError
        patch.setdefault(x,(op,a,b))
        return x
    try:
        terms=[]
        for v,c in [(z,m),(w,n)]:
            if c:
                t=v
                if abs(c)>1:
                    if abs(c) not in pool:
                        return []
                    t=record(v*abs(c),'*',v,abs(c))
                terms.append((1 if c>0 else -1,t))
        if k:
            if abs(k) not in pool:
                return []
            terms.append((1 if k>0 else -1,abs(k)))
    except ValueError:
        return []
    base=patch.copy(); found=[]
    for order in itertools.permutations(terms):
        if order[0][0]<0:
            continue
        patch=base.copy(); value=order[0][1]
        try:
            for sign,t in order[1:]:
                value=record(value+sign*t, '+' if sign>0 else '-', value,t)
            if den!=1:
                value=record(value//den,'/',value,den)
            if value==target and target in patch:
                found.append(patch)
        except ValueError:
            continue
    return found


def grounded(seeds,graphs,holes):
    free=set(seeds)-set(holes)
    changed=True
    while changed:
        changed=False
        for graph in graphs:
            for z,(_,a,b) in graph.items():
                if z not in free and z not in holes and a in free and b in free:
                    free.add(z); changed=True
    return free


def collect(graphs,seeds,limit):
    pool=set(seeds).union(*(set(g) for g in graphs))
    unique=[]
    source_names=[]
    for j,g in enumerate(graphs):
        if g not in unique:
            unique.append(g);source_names.append([NAMES[j]])
        else:
            source_names[unique.index(g)].append(NAMES[j])
    forms=defaultdict(lambda:defaultdict(set))
    for g,names in zip(unique,source_names):
        for pair,outputs in component_forms(g).items():
            for z,coef in outputs.items():
                forms[pair][z,coef].update(names)
    records={}; stats=Counter()
    for (x,y), outputs in forms.items():
        if len(outputs)<2 or x in seeds or y in seeds:
            continue
        free=None
        for e1,e2 in itertools.combinations(outputs,2):
            if e1[0]==e2[0]:
                continue
            specs=formula(e1,e2)
            if not specs:
                continue
            stats['nonsingular']+=1
            if free is None:
                free=grounded(seeds,unique,{x,y})
            if not {e1[0],e2[0]}<=free:
                continue
            stats['jointly_grounded']+=1
            for h,spec in zip((x,y),specs):
                for path in expressions(h,spec,pool,limit):
                    outside=set(path)-pool
                    if not outside:
                        continue
                    if any(a not in free and a not in path for _,a,b in path.values()) or any(b not in free and b not in path for _,a,b in path.values()):
                        continue
                    key=tuple(sorted(path.items()))
                    if key not in records:
                        records[key]={'holes':[x,y],'equations':[e1,e2], 'sources':[sorted(outputs[e1]),sorted(outputs[e2])], 'output':h,'fresh':sorted(outside)}
    stats['usable_routes']=len(records)
    stats['fresh_values']=len(set().union(*(set(r['fresh']) for r in records.values())))
    return dict(stats),records


def run(p,tapes):
    graphs=[first_recipes(p,t) for t in tapes]
    # Prune dead values and keep the original dependency order for solver hints.
    active = [active_graph(p,g) for g in graphs]
    assert all(set(g)==set(a) for g,a in zip(graphs,active)), 'A donor contains unpriced dead intermediates'
    control, tc=compile_selection(p,tapes[0],graphs[0],graphs[1:],False)
    stats, records=collect(graphs,set(p.seeds),p.limit)
    treatment,tt=(compile_selection(p,tapes[0],graphs[0],graphs[1:]+[dict(k) for k in records],False) if records else (control,tc))
    report={'id':p.id,'parent_lengths':[len(t) for t in tapes], 'control':control, 'treatment':treatment, 'elimination':stats}
    if records:
        used=first_recipes(p,tt)
        report['active_witnesses']=[r for k,r in records.items() if any(used.get(v)==e for v,e in k if v in r['fresh'])]
        report['example']=next(iter(records.values()))
    if len(tt)<len(tc) and len(tt)<len(tapes[0]):
        assert check(p,tt)==len(tt)
        return report,tt
    return report,None


def audit_control(p,tapes):
    graphs=[first_recipes(p,t) for t in tapes]
    records=[]; wins=[]
    for k in range(5):
        for subset in itertools.combinations(range(1,5),k):
            arm,t=compile_selection(p,tapes[0],graphs[0],[graphs[j] for j in subset],False)
            records.append({'donors':[NAMES[j] for j in subset], 'length':len(t), 'status':arm['status']})
            if len(t)<len(tapes[0]):
                wins.append((subset,t))
    least=min(len(subset) for subset,_ in wins)
    minimum=[w for w in wins if len(w[0])==least]
    def canonical(e):
        op,a,b=e
        return (op,min(a,b),max(a,b)) if op in '+*' else e
    options=[]
    for subset,t in minimum:
        counts=Counter()
        for v,e in first_recipes(p,t).items():
            eligible=[NAMES[j] for j in (0,*subset) if v in graphs[j] and canonical(graphs[j][v])==canonical(e)]
            assert eligible
            counts['|'.join(eligible)]+=1
        options.append({'donors':[NAMES[j] for j in subset], 'edge_counts':dict(counts)})
    subset,t=minimum[0]
    assert check(p,t)==len(t)
    outfile=HERE/'control-wins.csv'
    write_submission(outfile,[p],{p.id:t})
    report={'id':p.id, 'parent_lengths':[len(t) for t in tapes], 'all_subsets':records,
            'minimum_extra_donor_count':least,'minimum_options':options,
            'selected':[NAMES[j] for j in (0,*subset)],'output':outfile.name,
            'sha256':hashlib.sha256(outfile.read_bytes()).hexdigest()}
    (HERE/'control-origins.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    import tempfile
    from checkpoint import independent_score
    # The second interpreter expects one submission record for each input puzzle.
    with OFFICIAL.open(encoding='utf-8-sig',newline='') as source:
        reader=csv.DictReader(source); header=reader.fieldnames
        row=next(r for r in reader if r['id']==p.id)
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf8',newline='',suffix='.csv',dir=HERE,delete=False) as f:
        writer=csv.DictWriter(f,header);writer.writeheader();writer.writerow(row)
        tmp=Path(f.name)
    try:
        assert independent_score(tmp,outfile)==[114]
    finally:
        tmp.unlink()


def witness():
    from elf import Puzzle
    x,y=43,26; z,w=x+y,x-y
    q=Puzzle('witness',(2,z,w),(x,y),200)
    g={z:('+',x,y),w:('-',x,y)}
    pool={2,x,y,z,w}
    outputs=component_forms(g)[y,x]
    assert z in outputs and w in outputs
    specs=formula((z,outputs[z]),(w,outputs[w]))
    patches=[expressions(v,s,pool,200)[0] for v,s in zip((y,x),specs)]
    from graph import compile_graph
    joined={key:e for path in patches for key,e in path.items()}
    physical=compile_graph(q,joined)
    assert check(q,physical)==4
    assert not formula((69,(1,1,0)),(138,(2,2,0)))
    return {'anchors':[z,w], 'holes':[x,y], 'new':sorted(set(joined)-pool), 'physical_steps':len(physical), 'singular_rejected':True}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('split',choices=['dev','hold','audit'])
    args=ap.parse_args()
    puzzles={p.id:p for p in read_puzzles(OFFICIAL)}
    tables=parents(); rows=[]; results={}
    tests=witness()
    if args.split=='audit':
        p=puzzles['scored_0152']
        audit_control(p,[tuple(tuple(op) for op in json.loads(t[p.id])) for t in tables])
        return
    ids=DEV if args.split=='dev' else HOLD
    for tail in ids:
        i='scored_'+tail
        tapes=[tuple(tuple(op) for op in json.loads(t[i])) for t in tables]
        r,t=run(puzzles[i],tapes)
        print(i,r['control']['physical'],r['treatment']['physical'],r['elimination'],flush=True)
        rows.append(r)
        if t:results[i]=t
        write_submission(HERE/(args.split+'-wins.csv'),[puzzles[i] for i in sorted(results)],results)
        (HERE/(args.split+'.json')).write_text(json.dumps({'witness':tests,'rows':rows},indent=2)+'\n',encoding='utf8')
if __name__=='__main__':
    main()
