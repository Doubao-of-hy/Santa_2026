"""Mask targets before fitting recurrences; compare predicted held-outs with a size- and residue-matched null."""
import argparse,csv,hashlib,json,random,subprocess,sys
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=next(p for p in HERE.parents if (p/'elf.py').is_file())
sys.path.insert(0,str(ROOT))
from elf import read_puzzles,sha256

SCORED=['0636','0799','0165','0012','0080','0438','0704','0199','0846','0068','0961','0995']
def seed(s):return int.from_bytes(hashlib.sha256(s.encode()).digest()[:8],'big')
def make(p,rep,mode,radius,rule):
    xs=sorted(set(p.targets)-set(p.seeds))
    xs=[t for t in xs if t>4096]
    if len(xs)<5:return
    order=list(range(len(xs)));random.Random(seed(f'split1120:{p.id}')).shuffle(order)
    split={j for i,j in enumerate(order) if i%3==rep}
    if mode=='jitter':
        rng=random.Random(seed(f'null1120:{p.id}'))
        used=set()
        for j,t in enumerate(xs):
            w=max(120,t//64);lo=min(w,t-4097)//30;hi=min(w,p.limit-t)//30
            for _ in range(64):
                u=t+30*rng.randint(-lo,hi)
                if u>4096 and (u!=t or lo==hi==0) and u not in used:break
            xs[j]=u;used.add(u)
    learn=[x for j,x in enumerate(xs) if j not in split];test=[x for j,x in enumerate(xs) if j in split]
    ident=f'{p.id}:{rep}:{mode}:{radius}'
    return ident,(p.id,rule,mode,radius,rep),[ident,p.limit,radius,len(p.seeds),len(learn),len(test),*p.seeds,*learn,*test]

def planted():
    qs=[]
    for j in range(72):
        rng=random.Random(90417+j)
        x,y=rng.sample(range(10**7,10**8),2);c=rng.randrange(10**7,10**9);a,b=(1,1) if j%2 else (2,1)
        line=[x,y]
        for h in range(6):line.append(a*line[-1]+b*line[-2]+c)
        seeds=[3,7,23];learn=line[:5]+rng.sample(range(10**8,10**10),8);test=line[5:7]+rng.sample(range(10**8,10**10),2)
        ident=f'planted_{j:04}:0:planted:0'
        qs.append((ident,(f'planted_{j:04}','positive','planted',0,0),[ident,10**15,0,len(seeds),len(learn),len(test),*seeds,*learn,*test]))
    return qs

def batch(exe,qs):
    stream='\n'.join(' '.join(map(str,q[2])) for q in qs)+'\n'
    r=subprocess.run([str(exe)],input=stream,text=True,capture_output=True,check=True)
    rows=iter(r.stdout.splitlines());out=[]
    for id,meta,inp in qs:
        fields=next(rows).split();assert fields[0]==id
        chains,n,exact,near,extra=map(int,fields[1:])
        hits=[list(map(int,next(rows).split())) for _ in range(extra)]
        out.append((meta,dict(chains=chains,predicted=n,exact=exact,near=near,beyond_pairwise=extra,held=inp[5],
                              beyond_ids=[hashlib.sha256(str(x[0]).encode()).hexdigest()[:12] for x in hits]),hits))
    return out

def main():
    ap=argparse.ArgumentParser();ap.add_argument('puzzles',type=Path);ap.add_argument('exe',type=Path);ap.add_argument('out',type=Path)
    ap.add_argument('--set',choices=['practice','scored','planted'],required=True);ap.add_argument('--jobs',type=int,default=4)
    a=ap.parse_args();ps=read_puzzles(a.puzzles)
    labels={r['id']:r['family'] for r in csv.DictReader(a.puzzles.open(encoding='utf-8-sig'))} if a.set=='practice' else {}
    if a.set=='planted':qs=planted()
    else:
        if a.set=='scored':ps=[p for p in ps if p.id[-4:] in SCORED]
        qs=[q for p in ps for rep in range(3) for mode in ('observed','jitter') for radius in (0,16) if (q:=make(p,rep,mode,radius,labels.get(p.id,'scored')))]
    chunks=[qs[i::a.jobs] for i in range(a.jobs)]
    with ThreadPoolExecutor(a.jobs) as pool:
        raw=[r for block in pool.map(lambda chunk:batch(a.exe.resolve(),chunk),chunks) for r in block]
    metrics=defaultdict(lambda:defaultdict(int));found=defaultdict(set);records={};examples={}
    for (id,family,mode,rad,rep),rec,hits in raw:
        key=f'{family}/{mode}/{rad}';m=metrics[key]
        for n,v in rec.items():
            if isinstance(v,int):m[n]+=v
        if rec['beyond_pairwise']:found[key].add(id)
        ident=f'{id}:{rep}:{mode}:{rad}'
        records[ident]=rec
        if hits:examples[ident]=hits
    for k in metrics:metrics[k]['puzzles_beyond']=len(found[k])
    a.out.mkdir(parents=True,exist_ok=True)
    (a.out/'results.json').write_text(json.dumps(dict(input_hash=sha256(a.puzzles),design_set=a.set,rows=len(ps),groups=dict(metrics),records=records),separators=(',',':'))+'\n',encoding='utf8')
    (a.out/'examples.json').write_text(json.dumps(examples,separators=(',',':'))+'\n',encoding='utf8')
    for k,v in sorted(metrics.items()):print(k,v['held'],v['exact'],v['near'],v['beyond_pairwise'],v['puzzles_beyond'])

if __name__=='__main__':main()
