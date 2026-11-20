"""Replay the three preassigned population trajectories on immutable starting tapes."""
import argparse,csv,gzip,hashlib,importlib.util,io,json,os,subprocess,sys,tempfile,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
REV='aca4989fad3a364af53362841790b7e65d935f12'
ARMS=('original','three','tabu')
def digest(x):return hashlib.sha256(x).hexdigest()
def rows(blob):
    return {r['id']:r for r in csv.DictReader(io.StringIO(blob.decode('utf-8-sig')))}
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo',type=Path,required=True);ap.add_argument('--puzzles',type=Path,required=True)
    ap.add_argument('--bin',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--jobs',type=int,default=3);ap.add_argument('--group',choices=('development','holdout','remaining'),required=True)
    ap.add_argument('--summarize',action='store_true',help='Verify and reassemble an existing completed group journal')
    a=ap.parse_args();a.out.mkdir(exist_ok=True,parents=True);repo=a.repo.resolve()
    sys.path.insert(0,str(repo))
    from elf import read_puzzles,check,write_submission
    from checkpoint import independent_score
    spec=importlib.util.spec_from_file_location('second',repo/'collaboration/polish/replay.py')
    second=importlib.util.module_from_spec(spec);spec.loader.exec_module(second)
    ps=read_puzzles(a.puzzles);puzzles={p.id:p for p in ps}
    def take(name):return subprocess.check_output(['git','-C',str(repo),'show',REV+':'+name])
    inputs={};credits={}
    for lane,prefix in [('assisted','public-assisted/'),('pure','')]:
        inputs[lane]={k:tuple(tuple(op) for op in json.loads(r['program'])) for k,r in rows(take(prefix+'submission.csv')).items()}
        credits[lane]=rows(take(prefix+'origins.csv'))
    ids=sorted(inputs['assisted'],key=lambda k:(len(inputs['assisted'][k]),k))
    start,stop={'development':(0,3),'holdout':(3,9),'remaining':(9,125)}[a.group]
    cohort=[k for i in range(8) for k in sorted(ids[i*125:(i+1)*125],key=lambda k:hashlib.sha256(('reactive-search/1/'+k).encode()).digest())[start:stop]]
    prefix=a.bin.resolve();suffix='.exe' if os.name=='nt' else ''
    exes={m:prefix/(('original' if m=='original' else 'three')+suffix) for m in ARMS}
    def trial(task):
        lane,k=task;p=puzzles[k];original=inputs[lane][k];before=len(original)
        seed=817031+int(k[-4:])
        r={'lane':lane,'id':k,'seed':seed,'before':before,'parent_sha256':digest(json.dumps(original,separators=(',',':')).encode()),'arms':{}}
        result=original;best=None
        descriptor=[k,list(p.seeds),list(p.targets),p.limit,p.registers]
        for method in ARMS:
            fields=[[1],[p.limit,p.registers,150,int(method=='tabu'),seed],[len(p.seeds),*p.seeds],[len(set(p.targets)),*sorted(set(p.targets))],[1],[before],*original]
            wire='\n'.join(' '.join(map(str,x)) for x in fields)+'\n';start_time=time.monotonic()
            pr=subprocess.run([str(exes[method])],input=wire,text=True,capture_output=True,check=True,creationflags=getattr(subprocess,'BELOW_NORMAL_PRIORITY_CLASS',0))
            words=pr.stdout.split();n=int(words[0]);assert len(words)==1+4*n
            cand=tuple((words[i],*map(int,words[i+1:i+4])) for i in range(1,len(words),4))
            assert check(p,cand)==second.run_program(descriptor,[list(op) for op in cand])==n<=before
            di={}
            if method!='original':
                proposals,accept,blocked,repeat=map(int,pr.stderr.split())
                assert proposals==150 and (method=='tabu' or blocked==0)
                di=dict(proposals=proposals,accepted=accept,blocked=blocked,revisits=repeat)
            r['arms'][method]=dict(count=n,sha256=digest(json.dumps(cand,separators=(',',':')).encode()),seconds=round(time.monotonic()-start_time,4),**di)
            if n<len(result):result=cand;best=method
        if best:r.update(selected=best,parent_credit=credits[lane][k],program=result)
        return r
    jobs=[(lane,k) for k in cohort for lane in ('pure','assisted')]
    journal=a.out/(a.group+'.json.gz')
    if a.summarize:
        trials=json.loads(gzip.decompress(journal.read_bytes()))
        assert [(v['lane'],v['id']) for v in trials]==jobs
        for row in trials:
            lane,k=row['lane'],row['id'];source=inputs[lane][k]
            assert row['before']==len(source) and row['parent_sha256']==digest(json.dumps(source,separators=(',',':')).encode())
            if 'selected' in row:
                prog=row['program'];k0=row['selected'];p=puzzles[k]
                assert len(prog)==check(p,prog)==second.run_program([k,list(p.seeds),list(p.targets),p.limit,p.registers],prog)==row['arms'][k0]['count']
                assert digest(json.dumps(prog,separators=(',',':')).encode())==row['arms'][k0]['sha256']
                row['program']=tuple(tuple(op) for op in prog)
    else:
        with ThreadPoolExecutor(a.jobs) as ex:
            trials=[]
            for row in ex.map(trial,jobs):
                trials.append(row)
                if 'selected' in row:print(a.group,row['lane'],row['id'],row['before'],len(row['program']),row['selected'],flush=True)
        (a.out/(a.group+'.json.gz')).write_bytes(gzip.compress(json.dumps(trials,ensure_ascii=False,separators=(',',':')).encode(),mtime=0))
    report={'commit':REV,'group':a.group,'puzzle_sha256':digest(a.puzzles.read_bytes()),'binary_sha256':{m:digest(e.read_bytes()) for m,e in exes.items()}}
    for lane in ('pure','assisted'):
        subset=[r for r in trials if r['lane']==lane];winners={r['id']:r['program'] for r in subset if 'selected' in r}
        base=inputs[lane];f=a.out/(lane+'-'+a.group)
        write_submission(f.with_suffix('.csv'),[p for p in ps if p.id in winners],winners)
        with (a.out/(f.name+'.origins.csv')).open('w',encoding='utf8',newline='') as stream:
            writer=csv.writer(stream);writer.writerow(('id','source','upstream_source','instructions'))
            for v in subset:
                if 'selected' not in v:continue
                credit=v['parent_credit'].get('upstream_source') or v['parent_credit']['source']
                writer.writerow((v['id'],'Local search '+v['selected'],'Wang Jakie incremental search (Apache-2.0); local trajectory variant '+v['selected']+'; parent '+REV[:7]+': '+credit,len(v['program'])))
        with tempfile.TemporaryDirectory(dir=a.out) as tmp:
            full=Path(tmp)/'out.csv';total=write_submission(full,ps,base|winners);assert total==sum(independent_score(a.puzzles,full));sha=digest(full.read_bytes())
        report[lane]={'rows':len(subset),'wins':len(winners),'full_score':total,'full_sha256':sha,'arms':{m:{'savings':sum(r['before']-r['arms'][m]['count'] for r in subset),'unique_savings':sum(max(0,min(r['arms'][o]['count'] for o in ARMS if o!=m)-r['arms'][m]['count']) for r in subset),'blocked':sum(r['arms'][m].get('blocked',0) for r in subset)} for m in ARMS}}
    (a.out/(a.group+'.json')).write_text(json.dumps(report,indent=1)+'\n',encoding='utf8');print(report,flush=True)
if __name__=='__main__':main()
