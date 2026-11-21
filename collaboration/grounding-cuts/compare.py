"""Replay the same historical arithmetic bank with a rank model and a helper-only cut model."""
import argparse,csv,gzip,hashlib,io,json,subprocess,sys,tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from search import Bank,hitting_set,rank_model
HERE=Path(__file__).resolve().parent

def sha(b):return hashlib.sha256(b).hexdigest()
def encoded(x):return json.dumps(x,ensure_ascii=False,separators=(',',':')).encode()
def graph_bank(p,tapes):
    from graph import active_graph,first_recipes
    from solvers.graphs.corpus_prefix import arithmetic_edges
    target_set=set(p.targets);seeds=set(p.seeds)
    graphs=[active_graph(p,first_recipes(p,t)) for t in tapes]
    values=sorted(seeds.union(*[g.keys() for g in graphs]))
    bank={v:set() for v in values if v not in seeds}
    for i,a in enumerate(values):
        for j in range(i+1):
            b=values[j]
            for v,recipe in arithmetic_edges(a,b,p.limit):
                if v in bank and v not in (a,b):bank[v].add(recipe)
    return Bank(seeds,target_set,bank),graphs[0]

def setup(repo):
    sys.path.insert(0,str(repo))

def trial(task):
    from elf import check
    p,lane,tapes=task;parent=tapes[0];bank,primary=graph_bank(p,tapes)
    seed=int(sha(('grounded/'+p.id).encode())[:7],16)
    arms={}
    for name,fn in [('ranks',rank_model),('cuts',hitting_set)]:
        program,stats=fn(p,bank,parent,primary,3.,seed)
        assert check(p,program)==len(program)<=len(parent)
        detail=dict(steps=len(program),sha256=sha(encoded(program)),**stats)
        if len(program)<len(parent):detail['program']=program
        arms[name]=detail
    return dict(id=p.id,lane=lane,before=len(parent),parent_sha256=sha(encoded(parent)),
                values=bank.n,recipes=sum(map(len,bank.rules)),arms=arms)

def controls():
    from elf import Puzzle,check
    p=Puzzle('toy',(2,),(6,8),20)
    data={1:{('/',2,2)},3:{('+',1,2)},4:{('+',2,2)},6:{('+',3,3),('+',2,4),('-',8,2)},8:{('+',6,2),('+',4,4)}}
    parent=(('/',0,0,1),('+',0,1,2),('+',2,2,3),('+',0,3,4))
    bank=Bank(p.seeds,p.targets,data)
    assert bank.close(bank.base)&bank.goals != bank.goals
    for target in (6,8):
        cut=bank.cut(bank.base,bank.close(bank.base),bank.bit[bank.index[target]],bank.optional)
        # Exhaustively test the validity of each generated cut on all tiny helper subsets.
        for subset in range(1<<len(bank.optional)):
            sel=[i for j,i in enumerate(bank.optional) if subset>>j&1]
            known=bank.close(bank.base|sum(bank.bit[i] for i in sel))
            if known&bank.bit[bank.index[target]]:assert set(sel)&set(cut)
    answers={}
    for name,f in [('ranks',rank_model),('cuts',hitting_set)]:
        t,stats=f(p,bank,parent,{1:None,3:None,6:None,8:None},3,3)
        assert check(p,t)==len(t)==3;answers[name]=len(t)
    return answers

def main():
    ap=argparse.ArgumentParser()
    for k in ('repo','puzzles','out'):ap.add_argument('--'+k,type=Path,required=True)
    ap.add_argument('--design',type=Path,default=HERE/'design.json')
    ap.add_argument('--phase',choices=('development','holdout'),required=True)
    ap.add_argument('--jobs',type=int,default=4);ap.add_argument('--replay-only',action='store_true')
    a=ap.parse_args();repo=a.repo.resolve();setup(repo);a.out.mkdir(exist_ok=True,parents=True)
    from elf import read_puzzles,write_submission,check
    from checkpoint import independent_score
    cfg=json.loads(a.design.read_bytes());assert sha(a.puzzles.read_bytes())==cfg['official_sha256']
    ps=read_puzzles(a.puzzles);byid={p.id:p for p in ps}
    def read(rev,file):
        raw=subprocess.check_output(['git','show',rev+':'+file],cwd=repo)
        return {r['id']:r for r in csv.DictReader(io.StringIO(raw.decode()))}
    cases={};parents={};groups=cfg['groups'][a.phase];all_inputs={}
    for lane,prefix in [('independent',''),('assisted','public-assisted/')]:
        refs=[(v,prefix) for v in (cfg['revision'],*cfg['history'])]
        if lane=='assisted':refs.append((cfg['revision'],''))
        pool={i:[] for i in groups};credit={i:[] for i in groups}
        for rev,pr in refs:
            tapes=read(rev,pr+'submission.csv');origins=read(rev,pr+'origins.csv')
            if (rev,pr)==refs[0]:parents[lane]={i:tuple(tuple(op) for op in json.loads(r['program'])) for i,r in tapes.items()}
            for i in groups:
                t=tuple(tuple(op) for op in json.loads(tapes[i]['program']))
                if t not in pool[i]:
                    check(byid[i],t);pool[i].append(t)
                    credit[i].append(dict(revision=rev,path=pr+'submission.csv',origin=origins[i],sha256=sha(encoded(t))))
        for i in groups:
            cases[lane,i]=(byid[i],lane,pool[i]);all_inputs[lane,i]=credit[i]
    journal=a.out/(a.phase+'.json.gz')
    if not a.replay_only:
        assert controls()=={'ranks':3,'cuts':3}
        with ProcessPoolExecutor(a.jobs,initializer=setup,initargs=(repo,)) as ex:
            rows=list(ex.map(trial,cases.values()))
        for r in rows:r['inputs']=all_inputs[r['lane'],r['id']]
        with journal.open('wb') as f:
            with gzip.GzipFile(fileobj=f,mode='wb',filename='',mtime=0) as z:z.write(encoded(rows))
    rows=json.loads(gzip.decompress(journal.read_bytes()))
    if [(r['lane'],r['id']) for r in rows]!=list(cases):raise ValueError('Incomplete group')
    stats={'controls':{'input':4,'ranks':3,'cuts':3},'phase':a.phase,'lanes':{}}
    for lane,bank in parents.items():
        results={};wins={};credits=[]
        for arm in ('ranks','cuts','union'):
            chosen=bank.copy();details=[]
            for r in rows:
                if r['lane']!=lane:continue
                i=r['id'];assert r['inputs']==all_inputs[lane,i] and r['parent_sha256']==sha(encoded(bank[i])) and r['before']==len(bank[i])
                name=arm if arm!='union' else min(('ranks','cuts'),key=lambda k:r['arms'][k]['steps'])
                entry=r['arms'][name]
                if entry['steps']>=len(bank[i]):continue
                t=tuple(tuple(op) for op in entry['program']);assert sha(encoded(t))==entry['sha256'] and check(byid[i],t)==entry['steps']
                chosen[i]=t;details.append(i)
                if arm=='union':
                    wins[i]=t;source=' | '.join(x['revision'][:7]+' '+x['path']+' '+str(x['origin'].get('source',''))+' '+str(x['origin'].get('upstream_source','')) for x in all_inputs[lane,i])
                    credits.append([i,'Local finite-bank '+name,source,len(t)])
            with tempfile.TemporaryDirectory(dir=a.out) as tmp:
                f=Path(tmp)/'submission.csv';total=write_submission(f,ps,chosen)
                assert total==sum(independent_score(a.puzzles,f))
                results[arm]=dict(replayed=1000,total=total,sha256=sha(f.read_bytes()),wins=details)
        output=a.out/(a.phase+'-'+lane+'.csv')
        with output.open('w',encoding='utf8',newline='') as f:
            writer=csv.writer(f,lineterminator='\n');writer.writerow(('id','program'));writer.writerows((i,encoded(t).decode()) for i,t in wins.items())
        with output.with_suffix('.origins.csv').open('w',encoding='utf8',newline='') as f:
            writer=csv.writer(f,lineterminator='\n');writer.writerow(('id','source','upstream_source','instructions'));writer.writerows(credits)
        stats['lanes'][lane]=results
    (a.out/(a.phase+'.json')).write_bytes((json.dumps(stats,indent=2)+'\n').encode())
    print(a.phase,{k:{m:r['total'] for m,r in v.items()} for k,v in stats['lanes'].items()},flush=True)
if __name__=='__main__':main()
