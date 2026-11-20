"""Split target sets, optimize both partial tapes, and replay the recombined physical program."""
import argparse
import csv
import gzip
import hashlib
import importlib.util
import io
import json
import os
import random
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parent

def fingerprint(data):
    return hashlib.sha256(data).hexdigest()

def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()

def archive(path, obj):
    data=gzip.compress(encode(obj),mtime=0)
    path.write_bytes(data)

def run_native(p, tape, exe, seed, budget):
    from elf import check
    rows=[[1],[p.limit,p.registers,budget,0,seed],[len(p.seeds),*p.seeds],
          [len(p.targets),*p.targets],[1],[len(tape)],*tape]
    wire='\n'.join(' '.join(map(str,r)) for r in rows)+'\n'
    process=subprocess.run([str(exe)],input=wire,capture_output=True,text=True,check=True,
                           creationflags=getattr(subprocess,'BELOW_NORMAL_PRIORITY_CLASS',0))
    words=process.stdout.split()
    n=int(words[0])
    if len(words)!=1+4*n:raise ValueError('Invalid native output')
    program=tuple((words[i],*map(int,words[i+1:i+4])) for i in range(1,len(words),4))
    if check(p,program)!=n or n>len(tape):raise ValueError('Invalid or increasing optimizer result')
    return program

def partitions(p,graph,rng):
    from graph import active_graph
    targets=sorted(set(p.targets)-set(p.seeds))
    if len(targets)<2:raise ValueError(p.id)
    coverage={t:set(active_graph(p,graph,[t])) for t in targets}
    def split():
        values=targets.copy()
        rng.shuffle(values)
        n=len(values)//2
        return tuple(sorted(values[:n])),tuple(sorted(values[n:]))
    def weight(pair):
        a,b=(set.union(*(coverage[v] for v in group)) for group in pair)
        return len(a&b),max(len(a),len(b))
    candidates=[split() for _ in range(160)]
    return (candidates[0],min(candidates,key=weight)),weight

def split_solve(p,tape,graph,partition,exe,seeds,budgets):
    from graph import compile_graph, first_recipes, active_graph
    from elf import check
    sides=[]
    costs=[]
    for group,seed,budget in zip(partition,seeds,budgets):
        part=replace(p,targets=group)
        parent=compile_graph(part,active_graph(part,graph),recompute=True,schedule_width=4)
        if parent is None:parent=tape
        short=run_native(part,parent,exe,seed,budget)
        side=active_graph(part,first_recipes(part,short))
        sides.append(side)
        costs.append((len(parent),len(short)))
    a,b=sides
    options=[tape]
    rejected=0
    seen=set()
    for patch in (a|b,b|a,a,b):
        combined=graph|patch
        try:active=active_graph(p,combined)
        except (KeyError,ValueError):
            rejected+=1
            continue
        key=frozenset(active.items())
        if key in seen:continue
        seen.add(key)
        if len(active)>len(tape):continue
        cand=compile_graph(p,active,recompute=True,schedule_width=4)
        if cand is not None and check(p,cand)<=len(tape):options.append(cand)
    # A different equally short join gets to start the third search.
    parent=min(reversed(options),key=len)
    result=run_native(p,parent,exe,seeds[-1],budgets[-1])
    return result,dict(half_lengths=costs,merge_steps=len(parent),join_choices=len(options)-1,rejected_cycles=rejected,
                       changed_join=(parent!=tape))

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for k in ('repo','puzzles','exe','out','design'):ap.add_argument('--'+k,type=Path,required=True)
    ap.add_argument('--jobs',type=int,default=4)
    ap.add_argument('--group',choices=['development','holdout','extension'],required=True)
    ap.add_argument('--replay-only',action='store_true')
    a=ap.parse_args()
    repo=a.repo.resolve();a.out.mkdir(parents=True,exist_ok=True);sys.path.insert(0,str(repo))
    from elf import read_puzzles, check, write_submission
    from graph import active_graph,first_recipes
    from checkpoint import independent_score
    spec=importlib.util.spec_from_file_location('alt_interpreter',repo/'collaboration/polish/replay.py')
    alt=importlib.util.module_from_spec(spec);spec.loader.exec_module(alt)
    design=json.loads(a.design.read_bytes())
    assert fingerprint(a.puzzles.read_bytes())==design['puzzles_sha256']
    puzzles=read_puzzles(a.puzzles);ps={p.id:p for p in puzzles}
    def frozen(path):
        blob=subprocess.check_output(['git','show',design['snapshot']+':'+path],cwd=repo)
        expected=design['inputs'].get(path)
        if expected:assert fingerprint(blob)==expected
        return {r['id']:r for r in csv.DictReader(io.StringIO(blob.decode('utf8')))}
    base={};origins={}
    for lane,prefix in [('independent',''),('assisted','public-assisted/')]:
        raw=frozen(prefix+'submission.csv')
        base[lane]={k:tuple(tuple(op) for op in json.loads(r['program'])) for k,r in raw.items()}
        origins[lane]=frozen(prefix+'origins.csv')
        assert set(base[lane])==ps.keys()
    tasks=[(i,lane) for i in design['groups'][a.group] for lane in base]
    def run(task):
        i,lane=task
        p=ps[i];tape=base[lane][i]
        graph=active_graph(p,first_recipes(p,tape))
        rng=random.Random(int(fingerprint(('part/seeds/'+i).encode())[:12],16))
        seeds=[rng.randrange(1,2**30) for _ in range(3)]
        splits,measure=partitions(p,graph,rng)
        arms={}
        short=tape
        for budget,seed in zip(design['rounds'],seeds):
            short=run_native(p,short,a.exe,seed,budget)
        arms['whole']=(short,{})
        for name,sp in zip(('random','minimum_shared'),splits):
            program,details=split_solve(p,tape,graph,sp,a.exe,seeds,design['rounds'])
            details.update(partition=sp,shared=measure(sp)[0])
            arms[name]=(program,details)
        row=dict(id=i,lane=lane,seeds=seeds,parent=fingerprint(encode(tape)),before=len(tape),arms={})
        for name,(program,info) in arms.items():
            assert check(p,program)==alt.run_program([i,p.seeds,p.targets,p.limit,p.registers],[list(op) for op in program])
            entry=dict(steps=len(program),hash=fingerprint(encode(program)),**info)
            if len(program)<len(tape):entry['program']=program
            row['arms'][name]=entry
        return row
    journal=a.out/(a.group+'.json.gz')
    if not a.replay_only:
        completed=[]
        with ThreadPoolExecutor(a.jobs) as ex:
            futures=[ex.submit(run,t) for t in tasks]
            for future in as_completed(futures):
                row=future.result();completed.append(row)
                counts={m:v['steps'] for m,v in row['arms'].items()}
                if min(counts.values())<row['before']:print(row['id'],row['lane'],row['before'],counts,flush=True)
        completed.sort(key=lambda r:tasks.index((r['id'],r['lane'])))
        archive(journal,completed)
    rows=json.loads(gzip.decompress(journal.read_bytes()))
    assert [(r['id'],r['lane']) for r in rows]==tasks
    report={'frozen':design['snapshot'],'group':a.group,'results':{}}
    for lane,bank in base.items():
        selected=dict(bank);wins={};savings={m:0 for m in design['arms']};unique=0;win_origins=[]
        for r in rows:
            if r['lane']!=lane:continue
            i=r['id'];p=ps[i];parent=bank[i];assert r['parent']==fingerprint(encode(parent)) and len(parent)==r['before']
            for m,v in r['arms'].items():
                savings[m]+=r['before']-v['steps']
                if v['steps']<len(parent):
                    op=v['program']
                    assert len(op)==v['steps']==check(p,op)==alt.run_program([i,p.seeds,p.targets,p.limit,p.registers],op)
                    assert fingerprint(encode(op))==v['hash']
            name=min(design['arms'],key=lambda m:r['arms'][m]['steps'])
            best=r['arms'][name]
            if best['steps']<r['arms']['whole']['steps']:unique+=1
            if best['steps']<len(parent):
                wins[i]=best['program'];selected[i]=tuple(tuple(op) for op in wins[i])
                f=origins[lane][i]
                prior=' / '.join(str(f[k]) for k in ('source','upstream_source') if f.get(k))
                win_origins.append((i,'Local target partition / '+name,prior+'; Wang Jakie (incremental solver, Apache-2.0)',len(wins[i])))
        sparse=a.out/(a.group+'-'+lane+'.csv');credit=sparse.with_suffix('.origins.csv')
        with sparse.open('w',encoding='utf8',newline='') as f:
            wr=csv.writer(f,lineterminator='\n');wr.writerow(['id','program'])
            for i,program in wins.items():wr.writerow([i,encode(program).decode()])
        with credit.open('w',encoding='utf8',newline='') as f:
            wr=csv.writer(f,lineterminator='\n');wr.writerow(['id','source','upstream_source','instructions']);wr.writerows(win_origins)
        with tempfile.TemporaryDirectory(dir=a.out) as temp:
            out=Path(temp)/'submission.csv';total=write_submission(out,puzzles,selected)
            assert sum(independent_score(a.puzzles,out))==total==sum(len(op) for op in selected.values())
            report['results'][lane]=dict(before=sum(map(len,bank.values())),after=total,sha256=fingerprint(out.read_bytes()),savings=savings,
                                         strictly_better_than_whole=unique,winners=list(wins))
    (a.out/(a.group+'.json')).write_bytes((json.dumps(report,indent=2)+'\n').encode())
    print(report,flush=True)
if __name__=='__main__':main()
