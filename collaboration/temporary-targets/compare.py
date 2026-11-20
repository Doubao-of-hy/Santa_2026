"""Test whether temporarily requiring a historical intermediate helps shorten an official program."""
import argparse
import csv
import gzip
import hashlib
import importlib.util
import io
import json
import random
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
from checkpoint import independent_score
from elf import check, read_puzzles, score, sha256, write_submission
from graph import active_graph, compile_graph, first_recipes

module = importlib.util.spec_from_file_location('partition', HERE.parent/'target-partition/compare.py')
partition = importlib.util.module_from_spec(module)
module.loader.exec_module(partition)
DESIGN = json.loads((HERE/'design.json').read_bytes())
ARMS = ('ordinary','graft_only','ranked','random')

def stable(obj):
    return hashlib.sha256(json.dumps(obj,separators=(',',':')).encode()).hexdigest()

def blob(rev,name):
    return subprocess.check_output(['git','show',rev+':'+name],cwd=REPO)

def snapshot(rev,lane):
    prefix = '' if lane=='own' else 'public-assisted/'
    csv_rows = lambda name: csv.DictReader(io.StringIO(blob(rev,prefix+name).decode('utf-8-sig')))
    programs = {r['id']:tuple(tuple(x) for x in json.loads(r['program'])) for r in csv_rows('submission.csv')}
    credits = {r['id']:r.get('upstream_source') or r['source'] for r in csv_rows('origins.csv')}
    return programs,credits

def inputs():
    base=DESIGN['base']
    sources={(base,lane):snapshot(base,lane) for lane in ('own','public')}
    for rev in DESIGN['history']:
        for lane in ('own','public'):
            sources[rev,lane]=snapshot(rev,lane)
    return sources

def options(p,lane,sources):
    base=DESIGN['base'];main=sources[base,lane][0][p.id]
    live=active_graph(p,first_recipes(p,main))
    fixed=set(live)|set(p.seeds)
    candidates={}
    targetset=set(p.targets)
    donors=[(rev,lane) for rev in DESIGN['history']]
    if lane=='public':donors.insert(0,(base,'own'))
    used={main}
    for key in donors:
        tape=sources[key][0][p.id]
        if tape in used:continue
        used.add(tape)
        foreign=active_graph(p,first_recipes(p,tape));extensions={}
        # A graft stops at any value already available in the incumbent's complete DAG.
        uses=Counter()
        for out,(_,a,b) in foreign.items():
            if out in fixed:
                for operand in {a,b}:
                    uses[operand]+=1+2*(out in targetset)
            if out in fixed:extensions[out]=frozenset();continue
            sub=extensions.get(a,frozenset())|extensions.get(b,frozenset())|{out}
            extensions[out]=sub
        for x,ex in extensions.items():
            if not 1<=len(ex)<=6 or x in targetset:continue
            # Count all incumbent interior values that admit an alternative parent pair using x.
            supported=0
            for v in live:
                if (abs(v-x) in fixed or v+x in fixed or
                    (v%x==0 and v//x in fixed) or (x%v==0 and x//v in fixed) or
                    (v<=p.limit//x and v*x in fixed)):
                    supported+=1+(v in targetset)
            ranking=(3*uses[x]+supported-2*len(ex),uses[x],-len(ex))
            old=candidates.get(x)
            if old is None or ranking>old[0]:
                candidates[x]=(ranking,key,{v:foreign[v] for v in foreign if v in ex})
    return live,candidates

def candidate_rows(ps,lane,sources):
    base=DESIGN['base']
    ordered=sorted(ps,key=lambda p:stable((DESIGN['salt'],lane,p.id)))
    for p in ordered:
        if len(p.targets)<8:continue
        _,choices=options(p,lane,sources)
        if len(choices)<2:continue
        ranked=max(choices,key=lambda x:(choices[x][0],-x))
        alt=random.Random(stable((DESIGN['salt'],lane,p.id,'random'))).choice(sorted(x for x in choices if x!=ranked))
        row={'id':p.id,'candidates':len(choices),'base_sha256':stable(sources[base,lane][0][p.id])}
        for name,x in [('ranked',ranked),('random',alt)]:
            ranking,key,patch=choices[x]
            row[name]=dict(value=x,rank=ranking,origin=key,patch=[[v,*recipe] for v,recipe in patch.items()],
                           donor_sha256=stable(sources[key][0][p.id]),credit=sources[key][1][p.id])
        yield row

def freeze(ps,sources):
    from itertools import islice
    n=DESIGN['development']+DESIGN['holdout']
    result={lane:list(islice(candidate_rows(ps,lane,sources),n)) for lane in ('own','public')}
    if any(len(rows)!=n for rows in result.values()):raise ValueError('Too few eligible puzzles')
    return result

def evaluate(task):
    p,lane,row,parent,donors,exe=task
    graph=active_graph(p,first_recipes(p,parent))
    compiled={};seeds=[int(stable((DESIGN['salt'],p.id,lane,j))[:8],16) for j in (0,1)]
    for k in ('ranked','random'):
        plan=row[k];x=plan['value'];aug=replace(p,targets=tuple(p.targets)+(x,))
        patch={v:(op,a,b) for v,op,a,b in plan['patch']}
        assert not set(patch)&(set(graph)|set(p.seeds))
        tape=compile_graph(aug,graph|patch,recompute=True,schedule_width=6)
        if tape is None:tape=donors[k]
        check(aug,tape);compiled[k]=aug,tape
    tapes={};stats={}
    for arm in ARMS:
        if arm=='ordinary':goal=p;start=parent
        elif arm=='graft_only':goal=p;start=compiled['ranked'][1]
        else:goal,start=compiled[arm]
        midway=partition.run_native(goal,start,exe,seeds[0],DESIGN['rounds'][0])
        # Apply exactly the same removal of unused operations at each arm's midpoint.
        trimmed=compile_graph(p,first_recipes(p,midway),recompute=True,schedule_width=6)
        if trimmed is None or len(trimmed)>len(midway):trimmed=midway
        check(p,trimmed)
        result=partition.run_native(p,trimmed,exe,seeds[1],DESIGN['rounds'][1])
        alternatives=[parent,result,trimmed,midway,start]
        tape=min(alternatives,key=len);check(p,tape)
        tapes[arm]=tape
        stats[arm]=dict(start=len(start),first=len(midway),released=len(trimmed),second=len(result),selected=len(tape))
    return lane,p.id,{'tapes':tapes,'stats':stats}

def report(phase,observed,selection,ps,sources,out,puzzles):
    base=DESIGN['base'];memo={};pids={p.id:p for p in ps}
    for lane in ('own','public'):
        baseline=sources[base,lane][0];subset=observed[lane]
        sel={r['id']:r for r in selection[lane]}
        expected_ids=[r['id'] for r in (selection[lane][:DESIGN['development']] if phase=='development' else selection[lane][DESIGN['development']:])]
        assert sorted(subset)==sorted(expected_ids) and len(subset)==len(expected_ids)
        memo[lane]={'total':{},'wins':{},'protected_exclusive':[], 'selected':{}}
        for arm in (*ARMS,'best'):
            changes={}
            for i,item in subset.items():
                assert stable(baseline[i])==sel[i]['base_sha256']
                winner=min(ARMS,key=lambda k:len(item['tapes'][k])) if arm=='best' else arm
                tape=tuple(tuple(t) for t in item['tapes'][winner])
                assert check(pids[i],tape)==item['stats'][winner]['selected']<=len(baseline[i])
                if len(tape)<len(baseline[i]):
                    changes[i]=tape
                    if arm=='best':memo[lane]['selected'][i]=winner
            with tempfile.TemporaryDirectory(dir=out) as scratch:
                dest=Path(scratch)/'full.csv'
                total=write_submission(dest,ps,baseline|changes)
                assert total==sum(independent_score(puzzles,dest))==score(ps,baseline|changes)
            memo[lane]['total'][arm]=total
            memo[lane]['wins'][arm]={k:len(baseline[k])-len(t) for k,t in changes.items()}
            if arm=='best':
                dest=out/(phase+'-'+lane+'.csv')
                write_submission(dest,[p for p in ps if p.id in changes],changes)
                with dest.with_suffix('.origins.csv').open('w',encoding='utf8',newline='') as stream:
                    w=csv.writer(stream);w.writerow(('id','source','upstream_source','instructions'))
                    for i,t in sorted(changes.items()):
                        win=memo[lane]['selected'][i];credit=sources[base,lane][1][i]
                        if win!='ordinary':
                            donor=sel[i]['random' if win=='random' else 'ranked'];credit+=' | '+':'.join(donor['origin'])+' '+donor['credit']
                        w.writerow((i,'local temporary-target comparison',credit,len(t)))
        for i,item in subset.items():
            stats=item['stats']
            if min(stats[k]['selected'] for k in ('ranked','random'))<min(stats[k]['selected'] for k in ('ordinary','graft_only')):
                memo[lane]['protected_exclusive'].append(i)
    (out/(phase+'.json')).write_bytes((json.dumps(memo,indent=2)+'\n').encode())
    return memo

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--puzzles',type=Path,required=True);ap.add_argument('--exe',type=Path)
    ap.add_argument('--out',type=Path,required=True);ap.add_argument('--phase',choices=['freeze','development','holdout'],required=True)
    ap.add_argument('--jobs',type=int,default=4);ap.add_argument('--replay-only',action='store_true')
    a=ap.parse_args();ps=read_puzzles(a.puzzles);sources=inputs();a.out.mkdir(parents=True,exist_ok=True)
    file=a.out/'selection.json'
    if a.phase=='freeze':
        if file.exists():raise FileExistsError(file)
        file.write_bytes((json.dumps(freeze(ps,sources),ensure_ascii=False,indent=1)+'\n').encode())
        print(sha256(file));return
    selected=json.loads(file.read_bytes());pmap={p.id:p for p in ps}
    saved=a.out/(a.phase+'.json.gz');base=DESIGN['base']
    if not a.replay_only:
        jobs=[]
        for lane,rows in selected.items():
            part=rows[:DESIGN['development']] if a.phase=='development' else rows[DESIGN['development']:]
            for row in part:
                i=row['id'];parent=sources[base,lane][0][i]
                assert stable(parent)==row['base_sha256']
                donors={k:sources[tuple(row[k]['origin'])][0][i] for k in ('ranked','random')}
                assert all(stable(t)==row[k]['donor_sha256'] for k,t in donors.items())
                jobs.append((pmap[i],lane,row,parent,donors,a.exe.resolve()))
        observed={'own':{},'public':{}}
        with ThreadPoolExecutor(a.jobs) as ex:
            for lane,i,result in ex.map(evaluate,jobs):
                observed[lane][i]=result
        saved.write_bytes(gzip.compress(json.dumps(observed,separators=(',',':')).encode(),mtime=0))
    observed=json.loads(gzip.decompress(saved.read_bytes()))
    memo=report(a.phase,observed,selected,ps,sources,a.out,a.puzzles)
    print({lane:(v['total'],v['protected_exclusive']) for lane,v in memo.items()},flush=True)

if __name__=='__main__':
    main()
