"""Mine seed-parametric DAG fragments only from programs generated for labelled official practice inputs."""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse,csv,hashlib,json,math,random,sys
HERE=Path(__file__).resolve().parent
ROOT=next(p for p in HERE.parents if (p/'elf.py').exists())
sys.path[:0]=[str(ROOT),str(ROOT/'collaboration/official-heads')]
from practice_runtime import generate
from elf import read_puzzles,sha256
from graph import first_recipes

def split(files):
    g=defaultdict(list)
    for r in csv.DictReader(files.open(encoding='utf-8-sig')):
        if r['family']=='tiny' or len(json.loads(r['targets']))<15:continue
        g[r['family']].append(r['id'])
    train=[];hold=[]
    for f,ids in sorted(g.items()):
        ids.sort(key=lambda s:hashlib.sha256(('glyph:20261120:'+s).encode()).digest())
        train+=ids[:10];hold+=ids[10:16]
    return train,hold

def motifs(p,tape):
    g=first_recipes(p,tape)
    # Compiles a concrete dependency graph into relative references. Negative
    # operands address variable seed roles; other operands address earlier steps.
    closure={};height={}
    for v,(op,a,b) in g.items():
        old=(closure.get(a,set())|closure.get(b,set())|{v})
        closure[v]=old
        height[v]=1+max(height.get(a,0),height.get(b,0))
    out=set()
    for t in g:
        if not 5<=len(closure[t])<=9:continue
        variables={};nodes={};program=[]
        def visit(v):
            if v not in g:
                if v not in variables:variables[v]=-1-len(variables)
                return variables[v]
            if v in nodes:return nodes[v]
            op,a,b=g[v]
            if op in '+*' and (height.get(a,0),a)<(height.get(b,0),b):a,b=b,a
            i=visit(a);j=visit(b)
            idx=len(program);nodes[v]=idx;program.append((op,i,j))
            return idx
        visit(t)
        if 2<=len(variables)<=4:out.add((len(variables),tuple(program)))
    return out

def rewrite(key,rng):
    nv,prog=key;ops=[op for op,_,_ in prog]
    if len(set(ops))>1:
        for _ in range(30):
            alt=ops[:];rng.shuffle(alt)
            if alt!=ops:break
        return nv,tuple((a,*p[1:]) for a,p in zip(alt,prog))
    # A homogeneous product or sum can be exchangeable under operand relabelling.
    # Keep it in the control and report how many such controls coincide.
    return key

def fragments(key):
    _,steps=key
    def cone(i,depth):
        if i<0:return 's'
        op,l,r=steps[i]
        if depth==0:return op
        x,y=cone(l,depth-1),cone(r,depth-1)
        if op in '+*' and x>y:x,y=y,x
        return f'{op}[{x},{y}]{int(l==r)}'
    return {cone(i,depth) for i in range(len(steps)) for depth in (1,2)}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('practice',type=Path);ap.add_argument('exe',type=Path)
    ap.add_argument('out',type=Path);ap.add_argument('--jobs',type=int,default=4)
    a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    learn,hold=split(a.practice);ps={p.id:p for p in read_puzzles(a.practice)}
    def job(i):
        p=ps[i];t=generate(p,p.targets,a.exe.resolve())
        return i,len(t),motifs(p,t)
    support=defaultdict(set);lengths={}
    with ThreadPoolExecutor(a.jobs) as pool:
        for i,n,keys in pool.map(job,learn):
            lengths[i]=n
            for key in keys:support[key].add(i)
    local=defaultdict(set)
    for key,owners in support.items():
        for feature in fragments(key):local[feature].update(owners)
    def strength(key):
        features=fragments(key)
        return sum(math.log1p(len(local[f]-support[key])) for f in features)/len(features)
    cells=defaultdict(list)
    for key in support:cells[(key[0],len(key[1]))].append(key)
    arms={'frequent':[],'rare':[],'scrambled':[]};rng=random.Random(1102607)
    for form,keys in sorted(cells.items()):
        # Hash tie-break avoids favoring addition or multiplication on ties.
        keys.sort(key=lambda k:(-len(support[k]),-strength(k),hashlib.sha256(repr(k).encode()).digest()))
        n=min(40,len(keys)//2)
        if not n:continue
        arms['frequent']+=keys[:n];arms['rare']+=keys[-n:];arms['scrambled'] += [rewrite(k,rng) for k in keys[:n]]
    vs={};stat={}
    for arm,keys in arms.items():
        vs[arm]=[dict(variables=k[0],steps=k[1],practice_support=len(support.get(k,())),source_ids=sorted(support.get(k,()))) for k in keys]
        stat[arm]=dict(templates=len(keys),multi_practice=sum(len(support.get(k,()))>=2 for k in keys))
        if arm!='scrambled':stat[arm]['mean_fragment_strength']=sum(strength(k) for k in keys)/len(keys)
    doc={'official':sha256(a.practice),'training':learn,'held_practice':hold,'tape_lengths':lengths,'unique':len(support),'exact_repeat':sum(len(v)>1 for v in support.values()),'by_arm':stat,'same_scramble':sum(x==y for x,y in zip(arms['scrambled'],arms['frequent'])),'vocabulary':vs}
    (a.out/'library.json').write_text(json.dumps(doc,separators=(',',':'))+'\n',encoding='utf8')
    for mode,entries in vs.items():
        lines=[]
        for row in entries:
            terms=[str(row['variables']),str(len(row['steps']))]
            for op,x,y in row['steps']:terms += [op,str(x),str(y)]
            lines.append(' '.join(terms))
        (a.out/(mode+'.txt')).write_text('\n'.join(lines)+'\n',encoding='utf8')
    print(len(learn),len(hold),len(support),stat,flush=True)

if __name__=='__main__':main()
