"""Matched whole-program comparisons of root groups rebuilt from jointly available radix digits."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import itertools,json,random,subprocess,sys,time
D=Path(__file__).resolve().parent
ROOT=next(p for p in D.parents if (p/'elf.py').exists())
sys.path.insert(0,str(ROOT))
from elf import arithmetic,check,read_puzzles,read_submission,sha256,write_submission
from graph import active_graph,compile_graph,first_recipes
from gpu_join import cut_many
from gpu_schedule import schedule_like
from checkpoint import atomic_text

def native(queries,exe):
    fields=[' '.join(map(str,(maximum,len(vals),len(goals),mode,*vals,*goals))) for maximum,vals,goals,mode in queries]
    cmd=subprocess.run([str(exe)],input='\n'.join(fields)+'\n',text=True,capture_output=True,check=True)
    lines=iter(cmd.stdout.splitlines());out=[]
    for maximum,vals,goals,_ in queries:
        n=int(next(lines))
        if n<0:out.append(None);continue
        known=set(vals);graph={}
        for _ in range(n):
            v,op,l,r=next(lines).split();v,l,r=map(int,(v,l,r))
            assert l in known and r in known and v not in known and 1<=v<=maximum and arithmetic(op,l,r)==v
            graph[v]=(op,l,r);known.add(v)
        assert set(goals)<=known
        out.append(graph)
    assert next(lines,None) is None
    return out

def planted(exe,path):
    rng=random.Random(840604)
    cases=[]
    for i in range(80):
        anchors=sorted(rng.sample(range(3,180),7))
        a,b,c,k,r=rng.sample(anchors,5)
        t=(a*b+c)*k+r;u=(a*b+c)*r+k
        cases.append((10**12,anchors,[t,u]))
    results=native([(*case,m) for case in cases for m in (0,1)],exe)
    rec=[{'direct':len(a) if a is not None else None,'mixed':len(b) if b is not None else None} for a,b in zip(results[::2],results[1::2])]
    atomic_text(path,json.dumps({'cases':len(rec),'direct_feasible':sum(v['direct'] is not None for v in rec),'mixed_feasible':sum(v['mixed'] is not None for v in rec),'rows':rec},indent=2)+'\n')
    return rec

def build_groups(p,pg):
    original=first_recipes(p,pg);active=active_graph(p,original)
    g={v:e for v,e in original.items() if v in active}
    singles=[]
    for t in p.targets:
        if t not in g:continue
        remain,free=cut_many(p,g,{t})
        singles.append((len(g)-len(remain),t))
    singles.sort(reverse=True)
    ordered=[(t,) for _,t in singles[:8]]
    for i,j in [(0,1),(2,3),(0,4),(1,3)]:
        if max(i,j)<len(singles):
            pair=(singles[i][1],singles[j][1]);ordered.extend([pair,pair[::-1]])
    return g,ordered

def search(p,pg,exe):
    started=time.monotonic()
    g,groups=build_groups(p,pg);cases=[];queries=[]
    for k,targets in enumerate(groups):
        remain,free=cut_many(p,g,set(targets))
        available=tuple(dict.fromkeys((*p.seeds,*free)))
        for mode in (0,1):
            cases.append((targets,remain,mode))
            queries.append((p.limit,available,targets,mode))
    paths=native(queries,exe);records=[];wins=[];best=[pg,pg]
    for (targets,keep,mode),patch in zip(cases,paths):
        row=dict(goals=list(targets),removed=len(g)-len(keep),mode=mode,patch=None if patch is None else len(patch))
        if patch is not None:
            graph=keep|patch
            try:compact=active_graph(p,graph)
            except (KeyError,ValueError):records.append(row);continue
            row['graph']=len(compact)
            if len(compact)<len(pg):
                candidates=[schedule_like(p,pg,compact),compile_graph(p,compact,attempts=4,recompute=True,schedule_width=6)]
                tapes=[t for t in candidates if t is not None]
                if tapes:
                    t=min(tapes,key=len);row['physical']=check(p,t)
                    if len(t)<len(pg):
                        wins.append((mode,targets,patch,t))
                        if len(t)<len(best[mode]):best[mode]=t
        records.append(row)
    # Disjoint successful rewrites can cooperate in a full graph; re-evaluate each joint candidate physically.
    for mode in (0,1):
        current=best[mode];tries=0
        for _,targets,patch,t in sorted((w for w in wins if w[0]==mode),key=lambda w:len(w[3])):
            original=first_recipes(p,current);altern=original|patch
            try:compact=active_graph(p,altern)
            except (KeyError,ValueError):continue
            if len(compact)>=len(current):continue
            newer=compile_graph(p,compact,attempts=4,recompute=True,schedule_width=6)
            if newer is not None and check(p,newer)<len(current):current=newer
            tries+=1
        best[mode]=current
    rec={'id':p.id,'before':len(pg),'direct':len(best[0]),'mixed':len(best[1]),'elapsed':round(time.monotonic()-started,3),'groups':records}
    return rec,best

def main():
    a=argparse.ArgumentParser();a.add_argument('lane',choices=('own','assisted'));a.add_argument('--split',choices=('pilot','holdout','all'),default='pilot');a.add_argument('--jobs',type=int,default=2);a.add_argument('--engine',choices=('quotient','factor_join'),default='quotient');args=a.parse_args()
    design=json.loads((D/'design.json').read_bytes());f=D/(args.lane+'.csv');exe=D/(args.engine+'.exe');assert sha256(f)==design['parents'][args.lane]
    ps={p.id:p for p in read_puzzles(ROOT/'data/puzzles.csv')};parents=read_submission(f)
    ids=design[args.split] if args.split!='all' else [i for i,p in ps.items() if len(p.targets)>=15 and i not in design['pilot']+design['holdout']]
    tag=args.lane+'-'+args.split+('' if args.engine=='quotient' else '-'+args.engine)
    path=D/(tag+'.json');out=D/(tag+'.csv')
    record={'official':sha256(ROOT/'data/puzzles.csv'),'parent':sha256(f),'solver':sha256(exe),'source':sha256(D/(args.engine+'.cpp')),'records':{}}
    programs={}
    with ThreadPoolExecutor(args.jobs) as pool:
        futures={pool.submit(search,ps[i],parents[i],exe):i for i in ids}
        for task in as_completed(futures):
            i=futures[task];row,best=task.result();record['records'][i]=row
            shortest=min(best,key=len)
            if len(shortest)<len(parents[i]):programs[i]=shortest
            write_submission(out,[ps[i] for i in sorted(programs)],programs);atomic_text(path,json.dumps(record,separators=(',',':'))+'\n')
            print(i,row['before'],row['direct'],row['mixed'],row['elapsed'],flush=True)
    record.update(complete=True,rows=len(ids),saved=sum(len(parents[i])-len(v) for i,v in programs.items()),output_sha256=sha256(out))
    atomic_text(path,json.dumps(record,separators=(',',':'))+'\n');print(args.lane,args.split,record['saved'],flush=True)

if __name__=='__main__':main()
