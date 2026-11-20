"""Synthesize and temporarily require a new intermediate that serves multiple existing operations."""
from collections import Counter,defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from itertools import combinations_with_replacement
import argparse,csv,gzip,hashlib,importlib.util,io,json,random,subprocess,sys,tempfile
from pathlib import Path

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]
sys.path.insert(0,str(REPO))
from elf import check,read_puzzles,write_submission,sha256
from graph import active_graph,first_recipes,compile_graph
from checkpoint import independent_score
spec=importlib.util.spec_from_file_location('earlier_partition',HERE.parent/'target-partition/compare.py')
old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
cfg=json.loads((HERE/'design.json').read_bytes())

def put(file,obj):
    b=(json.dumps(obj,ensure_ascii=False,separators=(',',':'))+'\n').encode()
    file.write_bytes(gzip.compress(b,mtime=0) if file.suffix=='.gz' else b)
def get(f):
    b=f.read_bytes()
    return json.loads(gzip.decompress(b) if f.suffix=='.gz' else b)
def hashed(obj):
    return hashlib.sha256(json.dumps(obj,separators=(',',':')).encode()).hexdigest()
def snapshot(lane):
    prefix='' if lane=='own' else 'public-assisted/'
    def lines(name):
        b=subprocess.check_output(['git','show',cfg['base']+':'+prefix+name],cwd=REPO)
        return csv.DictReader(io.StringIO(b.decode('utf-8-sig')))
    return {r['id']:tuple(tuple(x) for x in json.loads(r['program'])) for r in lines('submission.csv')},{r['id']:r.get('upstream_source') or r['source'] for r in lines('origins.csv')}

def choose(p,tape,lane):
    g=active_graph(p,first_recipes(p,tape));vals=list(dict.fromkeys((*p.seeds,*g)))
    idx={v:j for j,v in enumerate(vals)};fixed=set(vals);targets=set(p.targets);limit=p.limit
    uses=Counter(v for _,a,b in g.values() for v in {a,b})
    priority=lambda x:(-uses[x],idx[x])
    pool=list(dict.fromkeys(vals[:40]+sorted(vals,key=priority)[:40]))
    makers={}
    for a,b in combinations_with_replacement(pool,2):
        hi,lo=max(a,b),min(a,b)
        for x,op in ((a+b,'+'),(hi-lo,'-'),(a*b,'*'),(hi//lo if hi%lo==0 else 0,'/')):
            if not 0<x<=limit or x in fixed:continue
            key=(max(idx[a],idx[b]),-(uses[a]+uses[b]),op,hi,lo)
            if x not in makers or key<makers[x]:makers[x]=key
    edits=defaultdict(dict);weight=defaultdict(int)
    for v,(op0,a0,b0) in g.items():
        boundary=idx[v]
        for q in vals[:boundary]:
            for x,op,swap in ((v-q,'+',False),(v+q,'-',False),(q-v,'-',True),
                              (v//q if v%q==0 else 0,'*',False),(v*q,'/',False),(q//v if q%v==0 else 0,'/',True)):
                if x not in makers or makers[x][0]>=boundary:continue
                if v in edits[x]:continue
                a,b=(q,x) if swap else (x,q)
                edits[x][v]=(op,a,b)
                weight[x]+=1+2*sum(uses[z]==1 and z not in targets for z in {a0,b0}-{q})
    eligible=[x for x,es in edits.items() if len(es)>=2]
    if len(eligible)<2:return None
    rng=random.Random(hashed((cfg['salt'],lane,p.id)))
    elite=sorted(eligible,key=lambda x:(-weight[x],-len(edits[x]),makers[x][0],x))[:36]
    sampled=rng.sample(sorted(eligible),min(len(eligible),18))
    plans={}
    for x in dict.fromkeys(elite+sampled):
        _,_,op,a,b=makers[x];new=g|{x:(op,a,b)}|edits[x]
        aug=replace(p,targets=tuple(p.targets)+(x,))
        active=active_graph(aug,new)
        uses_x=sum(x in (a,b) for _,a,b in active.values())
        if uses_x<2:continue
        plans[x]={'value':x,'birth':[op,a,b],'edits':[[v,*e] for v,e in edits[x].items()],
                  'active_size':len(active),'live_uses':uses_x}
    if len(plans)<2:return None
    ranked=min(plans,key=lambda x:(plans[x]['active_size'],-plans[x]['live_uses'],x))
    alt=rng.choice(sorted(x for x in plans if x!=ranked))
    return dict(id=p.id,source_sha256=hashed(tape),base_steps=len(tape),eligible=len(eligible),ranked=plans[ranked],random=plans[alt])

def synthesize(p,g,choice):
    x=choice['value'];aug=replace(p,targets=tuple(p.targets)+(x,))
    m={v:(op,a,b) for v,op,a,b in choice['edits']}
    added=g|{x:tuple(choice['birth'])}|m
    assert len(active_graph(aug,added))==choice['active_size']
    t=compile_graph(aug,added,recompute=True,schedule_width=8)
    if t is None:
        # Keep the tested new value when the fully rerouted graph is hard to schedule.
        t=compile_graph(aug,g|{x:tuple(choice['birth'])},attempts=12,recompute=True,schedule_width=8)
    return aug,t

def run(task):
    p,lane,tape,case,exe=task
    assert hashed(tape)==case['source_sha256']
    g=active_graph(p,first_recipes(p,tape))
    options={k:synthesize(p,g,case[k]) for k in ('ranked','random')};results={}
    seeds=[int(hashed((cfg['salt'],lane,p.id,j))[:8],16) for j in (1,2)]
    for arm in cfg['arms']:
        if arm=='ordinary':aug,source=p,tape
        else:aug,source=options['random' if arm=='random' else 'ranked']
        if source is None:
            results[arm]=dict(steps=len(tape),sha256=hashed(tape),unallocated=True);continue
        goal=aug if arm in ('protected','random') else p
        first=old.run_native(goal,source,exe,seeds[0],cfg['rounds'][0])
        trimmed=compile_graph(p,first_recipes(p,first),recompute=True,schedule_width=8)
        if trimmed is None or len(trimmed)>len(first):trimmed=first
        last=old.run_native(p,trimmed,exe,seeds[1],cfg['rounds'][1])
        picked=min((tape,last,trimmed,first,source),key=len);check(p,picked)
        row=dict(steps=len(picked),sha256=hashed(picked),start=len(source),before_release=len(first),released=len(trimmed),final=len(last))
        if picked!=tape:row['program']=picked
        results[arm]=row
    return lane,p.id,results

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--puzzles',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--exe',type=Path);ap.add_argument('--phase',choices=('freeze','development','holdout'),required=True)
    ap.add_argument('--replay-only',action='store_true');ap.add_argument('--jobs',type=int,default=5)
    a=ap.parse_args();a.out.mkdir(exist_ok=True,parents=True);ps=read_puzzles(a.puzzles);pm={p.id:p for p in ps}
    lanes={lane:snapshot(lane) for lane in ('own','public')};sel=a.out/'selection.json.gz'
    if a.phase=='freeze':
        chosen={};size=cfg['development']+cfg['holdout']
        for lane,(table,ledger) in lanes.items():
            batch=[]
            for p in sorted(ps,key=lambda p:hashed((cfg['salt'],lane,p.id))):
                if len(p.targets)<8 or len(table[p.id])<35:continue
                case=choose(p,table[p.id],lane)
                if case:
                    case['credit']=ledger[p.id];batch.append(case)
                if len(batch)==size:break
            assert len(batch)==size;chosen[lane]=batch
        put(sel,chosen);print(sha256(sel),flush=True);return
    selected=get(sel);rows={lane:(cases[:cfg['development']] if a.phase=='development' else cases[cfg['development']:]) for lane,cases in selected.items()}
    path=a.out/(a.phase+'.json.gz')
    if not a.replay_only:
        jobs=[(pm[c['id']],lane,lanes[lane][0][c['id']],c,a.exe.resolve()) for lane,cases in rows.items() for c in cases]
        packets={lane:{} for lane in rows}
        with ThreadPoolExecutor(a.jobs) as pool:
            for lane,i,record in pool.map(run,jobs):packets[lane][i]=record
        put(path,packets)
    packets=get(path);report={}
    for lane,cases in rows.items():
        baseline,ledger=lanes[lane];results=packets[lane]
        assert set(results)=={c['id'] for c in cases}
        full={};winner={};adv=[]
        for arm in (*cfg['arms'],'best'):
            changed={}
            for case in cases:
                i=case['id'];assert hashed(baseline[i])==case['source_sha256']
                records=results[i]
                selected_arm=min(cfg['arms'],key=lambda k:records[k]['steps']) if arm=='best' else arm
                rec=records[selected_arm];t=tuple(tuple(v) for v in rec.get('program',baseline[i]))
                assert hashed(t)==rec['sha256'] and check(pm[i],t)==rec['steps']<=len(baseline[i])
                if rec['steps']<len(baseline[i]):changed[i]=t
                if arm=='best' and i in changed:winner[i]=selected_arm
                if arm=='best' and min(records[k]['steps'] for k in ('graft','protected'))<records['ordinary']['steps']:adv.append(i)
            with tempfile.TemporaryDirectory(dir=a.out) as tmp:
                dest=Path(tmp)/'full.csv';total=write_submission(dest,ps,baseline|changed)
                assert total==sum(independent_score(a.puzzles,dest))
            full[arm]=dict(score=total,changed={i:len(baseline[i])-len(t) for i,t in changed.items()})
            if arm=='best':
                dest=a.out/(a.phase+'-'+lane+'.csv');write_submission(dest,[p for p in ps if p.id in changed],changed)
                with dest.with_suffix('.origins.csv').open('w',encoding='utf8',newline='') as stream:
                    w=csv.writer(stream);w.writerow(('id','source','upstream_source','instructions'))
                    for i,t in sorted(changed.items()):w.writerow((i,'synthetic intermediate search',ledger[i],len(t)))
        report[lane]={'arms':full,'winner':winner,'beats_ordinary':adv}
    put(a.out/(a.phase+'.json'),report);print({lane:([v['score'] for v in rec['arms'].values()],rec['beats_ordinary']) for lane,rec in report.items()},flush=True)

if __name__=='__main__':main()
