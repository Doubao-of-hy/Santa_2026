"""Optimize the remaining program while selected official targets are temporarily withheld."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import csv
from dataclasses import replace
import gzip
import hashlib
import importlib.util
import io
from itertools import combinations, combinations_with_replacement
import json
from pathlib import Path
import subprocess
import sys
import tempfile

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]
sys.path.insert(0,str(REPO))
from checkpoint import independent_score
from corpus_prefix import arithmetic_edges
from elf import check, read_puzzles, sha256, write_submission
from graph import active_graph, compile_graph, first_recipes
from pooled_joins import inverse
spec=importlib.util.spec_from_file_location('partition',HERE.parent/'target-partition/compare.py')
partition=importlib.util.module_from_spec(spec)
spec.loader.exec_module(partition)
cfg=json.loads((HERE/'design.json').read_bytes())

def digest(obj):
    return hashlib.sha256(json.dumps(obj,separators=(',',':')).encode()).hexdigest()

def dump(path,obj):
    raw=(json.dumps(obj,separators=(',',':'))+'\n').encode()
    path.write_bytes(gzip.compress(raw,mtime=0) if path.suffix=='.gz' else raw)

def load(path):
    raw=path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix=='.gz' else raw)

def frozen(name):
    data=subprocess.check_output(['git','show',cfg['base']+':'+name],cwd=REPO)
    return list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))

def parent(lane):
    pre='' if lane=='own' else 'public-assisted/'
    table={r['id']:tuple(tuple(x) for x in json.loads(r['program'])) for r in frozen(pre+'submission.csv')}
    credit={r['id']:r.get('upstream_source') or r['source'] for r in frozen(pre+'origins.csv')}
    return table,credit

def choose(p,tape):
    goals=tuple(sorted(set(p.targets)-set(p.seeds)))
    if not 6<=len(goals)<=45 or len(tape)<35:return None
    graph=active_graph(p,first_recipes(p,tape))
    support=Counter()
    for j,t in enumerate(goals):
        for v in active_graph(p,graph,(t,)):support[v]|=1<<j
    hist=Counter(support.values())
    bits=[1<<j for j in range(len(goals))]
    one=max(bits,key=lambda b:(hist[b],-b))
    if hist[one]<2:return None
    ranked=[]
    for k in (2,3):
        for group in combinations(bits,k):
            shared=sum(hist[a|b] for a,b in combinations(group,2))
            if k==3:shared+=hist[sum(group)]
            cost=shared+sum(hist[b] for b in group)
            if cost>=4:ranked.append(((shared,cost/k,cost,-sum(group)),group,cost))
    if not ranked:return None
    _,group,cost=max(ranked)
    return {'id':p.id,'source_sha256':digest(tape),'one':[goals[one.bit_length()-1]],'one_removed':hist[one],
            'group':[goals[b.bit_length()-1] for b in group],'group_removed':cost}

def repair(p,backbone,original,tape,goals):
    initial=original|backbone
    candidates=[]
    core=tuple(dict.fromkeys((*p.seeds,*backbone)))
    fixed=set(core)
    makers={}
    for a,b in combinations_with_replacement(core,2):
        for v,recipe in arithmetic_edges(a,b,p.limit):
            if v not in fixed:makers.setdefault(v,recipe)
    for order in dict.fromkeys((tuple(goals),tuple(reversed(goals)))):
        graph=initial.copy()
        for t in order:
            if t in fixed:continue
            best=len(active_graph(p,graph))
            improved=None
            for anchor in core:
                for wanted,recipe in inverse(t,anchor,p.limit):
                    if wanted==t:continue
                    if wanted in fixed:patch={t:recipe}
                    elif wanted in makers:patch={wanted:makers[wanted],t:recipe}
                    else:continue
                    alt=graph|patch
                    n=len(active_graph(p,alt))
                    if n<best:
                        best=n
                        improved=alt
            if improved is not None:graph=improved
        for candidate_graph in (initial,graph):
            cand=compile_graph(p,candidate_graph,recompute=True,schedule_width=4)
            if cand is not None:candidates.append(cand)
    # Permit a new equally short program to start the next pass.
    result=min(reversed(candidates),key=len,default=tape)
    return result if len(result)<=len(tape)+3 else tape

def solve(job):
    p,tape,case,arm,seed1,seed2,exe=job
    assert digest(tape)==case['source_sha256']
    native=partition.run_native
    steps=cfg['rounds']
    if arm=='ordinary':
        first=native(p,tape,exe,seed1,steps[0]);joined=first
        pruned=len(tape)
    else:
        dropped=case[arm]
        reduced=replace(p,targets=tuple(t for t in p.targets if t not in dropped))
        original=active_graph(p,first_recipes(p,tape));spine=active_graph(reduced,original)
        assert len(original)-len(spine)==case[arm+'_removed']
        short=compile_graph(reduced,spine,recompute=True,schedule_width=4)
        if short is None:short=tape
        first=native(reduced,short,exe,seed1,steps[0]);pruned=len(short)
        joined=repair(p,active_graph(reduced,first_recipes(reduced,first)),original,tape,dropped)
    last=native(p,joined,exe,seed2,steps[1]);winner=min((tape,last,joined),key=len)
    assert check(p,winner)==len(winner)
    result={'baseline':len(tape),'partial_start':pruned,'partial_final':len(first),'rejoined':len(joined),'score':len(winner),'sha256':digest(winner)}
    if len(winner)<len(tape):result['program']=winner
    return p.id,arm,result

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for k in ('puzzles','out'):ap.add_argument('--'+k,type=Path,required=True)
    ap.add_argument('--exe',type=Path);ap.add_argument('--jobs',type=int,default=7)
    ap.add_argument('--phase',choices=['freeze','development','holdout'],required=True)
    ap.add_argument('--replay-only',action='store_true')
    a=ap.parse_args();a.out.mkdir(exist_ok=True,parents=True)
    assert sha256(a.puzzles)==cfg['puzzles_sha256']
    ps=read_puzzles(a.puzzles);pm={p.id:p for p in ps}
    parents={l:parent(l) for l in cfg['lanes']}
    selection=a.out/'selection.json'
    if a.phase=='freeze':
        eligible={r['id'] for r in frozen('collaboration/puzzle-bounds.csv') if not int(r['tight'])}
        selected={}
        for lane,(table,credit) in parents.items():
            group=[]
            for p in sorted(ps,key=lambda p:digest([cfg['salt'],lane,p.id])):
                if p.id not in eligible:continue
                case=choose(p,table[p.id])
                if case:group.append(case)
                if len(group)==cfg['development']+cfg['holdout']:break
            assert len(group)==cfg['development']+cfg['holdout']
            selected[lane]=group
        dump(selection,selected);print(sha256(selection));return
    records_file=a.out/(a.phase+'.json.gz')
    selections=load(selection)
    selected={l:(rows[:cfg['development']] if a.phase=='development' else rows[cfg['development']:]) for l,rows in selections.items()}
    if not a.replay_only:
        packets={}
        for lane,rows in selected.items():
            tasks=[]
            for c in rows:
                i=c['id'];seeds=[int(digest([cfg['salt'],lane,i,j])[:8],16) for j in (1,2)]
                tasks.extend((pm[i],parents[lane][0][i],c,k,*seeds,a.exe.resolve()) for k in cfg['arms'])
            packets[lane]={c['id']:{} for c in rows}
            with ThreadPoolExecutor(a.jobs) as pool:
                for i,arm,record in pool.map(solve,tasks):packets[lane][i][arm]=record
        dump(records_file,packets)
    packets=load(records_file);report={}
    for lane,rows in selected.items():
        table,credit=parents[lane];records=packets[lane]
        assert records.keys()=={c['id'] for c in rows}
        wins={};totals={k:0 for k in cfg['arms']};adv=[]
        for c in rows:
            i=c['id'];data=records[i]
            assert digest(table[i])==c['source_sha256'] and set(data)==set(cfg['arms'])
            for k,rec in data.items():
                candidate=tuple(tuple(s) for s in rec.get('program',table[i]))
                assert digest(candidate)==rec['sha256'] and check(pm[i],candidate)==rec['score']<=len(table[i])
                totals[k]+=len(table[i])-len(candidate)
            best=min(data,key=lambda k:data[k]['score'])
            if data[best]['score']<len(table[i]):wins[i]=tuple(tuple(x) for x in data[best]['program'])
            if data[best]['score']<data['ordinary']['score']:adv.append(i)
        with tempfile.TemporaryDirectory(dir=a.out) as tmp:
            path=Path(tmp)/'merged.csv';score=write_submission(path,ps,table|wins)
            assert score==sum(independent_score(a.puzzles,path))
        dest=a.out/(a.phase+'-'+lane+'.csv')
        write_submission(dest,[p for p in ps if p.id in wins],wins)
        with dest.with_suffix('.origins.csv').open('w',encoding='utf8',newline='') as st:
            w=csv.writer(st);w.writerow(('id','source','upstream_source','instructions'))
            for i,t in sorted(wins.items()):w.writerow((i,'withheld-target recovery',credit[i],len(t)))
        report[lane]={'score':score,'savings':totals,'wins':{i:len(table[i])-len(v) for i,v in wins.items()},'beats_ordinary':adv}
    dump(a.out/(a.phase+'.json'),report);print(report,flush=True)
if __name__=='__main__':
    main()
