"""Branch on membership of a high-coverage helper in a fixed, diamond-free prefix model."""
import argparse
from collections import Counter,defaultdict
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
from itertools import combinations,permutations
from math import isqrt
from pathlib import Path
import csv,gzip,hashlib,io,json,subprocess,sys

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]
sys.path.insert(0,str(REPO))
from solvers.proofs.domain_bounds import operands,unary_capacity
from lower_bounds import values,double_witnesses
from elf import read_puzzles

def sha(b):return hashlib.sha256(b).hexdigest()
def stamp(v):return sha((','.join(map(str,sorted(v)))+'\n').encode())
def edge_limit(h):return h*(h-1)//2 if h<4 else h*h//4

class Profile:
    def __init__(self,allowed,goals,limit):
        self.base=allowed|goals
        self.limit=limit
        self.member=defaultdict(int)
        self.labels=[]
        for t in sorted(goals-allowed):
            cand=set()
            if t%2==0:cand.add(t//2)
            rt=isqrt(t)
            if rt*rt==t:cand.add(rt)
            for b in self.base-{t}:
                choices=operands(t,b,limit)
                if choices&self.base:break
                cand.update(choices)
            else:
                flag=1<<len(self.labels);self.labels.append(t)
                for v in cand-self.base:self.member[v]|=flag
        self.indices={v:1<<i for i,v in enumerate(self.labels)}
        self.heavy={v for v,m in self.member.items() if m.bit_count()>1}
        self.pairs={}
        for x,y in permutations(self.labels,2):
            for a,b in double_witnesses(x,y):
                if 1<=b<a<=limit and a not in self.base and b not in self.base and (a,b) not in self.pairs:
                    mask=self.mask(values(a,b,limit));assert mask.bit_count()>=2
                    self.pairs[a,b]=mask
        self.all=(1<<len(self.labels))-1
        self.cached={}
    def mask(self,v):
        return sum(self.indices.get(t,0) for t in set(v))
    def make(self,chosen):
        if chosen in self.cached:return self.cached[chosen]
        fixed=self.base|set(chosen);free=0
        for v in chosen:free|=self.member.get(v,0)
        for a,b in combinations(chosen,2):free|=self.mask(values(a,b,self.limit))
        remain=self.all & ~free;dynamic=defaultdict(int)
        for i,t in enumerate(self.labels):
            if remain>>i&1:
                for a in chosen:
                    for v in operands(t,a,self.limit)-fixed:dynamic[v]|=1<<i
        masks={v:remain&(self.member.get(v,0)|dynamic.get(v,0)) for v in self.heavy|dynamic.keys()}
        counts={}
        for v,m in masks.items():
            if v in fixed or m.bit_count()<2:continue
            n=unary_capacity(v,{t for i,t in enumerate(self.labels) if m>>i&1},fixed,self.limit)
            if n>1:counts[v]=n
        bonuses=[]
        for (a,b),m in self.pairs.items():
            if a in fixed or b in fixed:continue
            n=(remain&m).bit_count()-1
            if n>0:bonuses.append((a,b,n))
        answer=(remain.bit_count(),counts,bonuses)
        self.cached[chosen]=answer
        return answer
    def estimate(self,used,forbidden,h):
        needed,singles,pairs=self.make(used);deg=Counter();bonus=[]
        for a,b,n in pairs:
            if a in forbidden or b in forbidden:continue
            deg.update({a:n,b:n});bonus.append(n)
        vals=(singles.keys()|deg.keys())-forbidden
        order=sorted(vals,key=lambda x:(2*singles.get(x,1)+deg[x],singles.get(x,1),-x),reverse=True)
        edge=edge_limit(h)
        top=lambda seq,n:sum(sorted(seq,reverse=True)[:n])
        # Pad with h single-coverage helpers. This permits all omitted helpers with capacity 0 or 1.
        u=h+top((singles.get(x,1)-1 for x in vals),h)
        m=2*h+top((2*(singles.get(x,1)-1)+deg[x] for x in vals),h)
        d=top(deg.values(),h);b=top(bonus,edge)
        result=edge+min(u+min(b,d//2),m//2)
        return needed,result,order

def search(model,h,depth=192,limit=1500):
    visits=0;leaves=0
    def walk(used,banned,left,remaining_depth):
        nonlocal visits,leaves
        visits+=1
        needed,ceiling,order=model.estimate(used,banned,left)
        if ceiling<needed:
            leaves+=1
            return {'needed':needed,'ceiling':ceiling}
        if visits>=limit or not order or left<1 or not remaining_depth:return None
        x=order[0]
        # Failure in either sibling invalidates the whole proposed proof.
        yes=walk(tuple(sorted((*used,x))),banned,left-1,remaining_depth-1)
        if yes is None:return None
        no=walk(used,banned|{x},left,remaining_depth-1)
        if no is None:return None
        return {'value':x,'included':yes,'excluded':no}
    result=walk((),frozenset(),h,depth)
    return result,visits,leaves

def work(task):
    p,claim,base=task
    from solvers.proofs.domain_bounds import domains
    k=claim['k'];allowed=set(p.seeds) if k==0 else dict(domains(p,k,3500))[k]
    assert stamp(allowed)==claim['evidence']['allowed_sha256']
    m=Profile(allowed,set(p.targets),p.limit)
    assert stamp(m.labels)==claim['evidence']['label_sha256'] and claim['evidence']['ordered']==claim['primary']=='ABSENT'
    missing=len(set(p.targets)-set(p.seeds));h=base-missing-k
    assert h>=claim['excluded_budget']
    target,ceil,_=m.estimate((),frozenset(),h)
    result,n,leaves=search(m,h)
    return dict(id=p.id,k=k,h=h,old=base,target_count=target,plain_ceiling=ceil,visits=n,closed_leaves=leaves,tree=result)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--puzzles',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--jobs',type=int,default=4);ap.add_argument('--group',default='pilot')
    a=ap.parse_args();ds=json.loads((HERE/'design.json').read_bytes())
    raw=(REPO/ds['claims']).read_bytes();assert sha(raw)==ds['claims_sha256']
    j=json.loads(gzip.decompress(raw));assert sha(a.puzzles.read_bytes())==j['design']['official_sha256']
    original=subprocess.check_output(['git','show',ds['base']+':collaboration/puzzle-bounds.csv'],cwd=REPO)
    rows={r['id']:r for r in csv.DictReader(io.StringIO(original.decode()))}
    ps={p.id:p for p in read_puzzles(a.puzzles)}
    eligible=sorted((c for c in j['claims'] if not int(rows[c['id']]['tight'])),key=lambda c:sha((ds['salt']+c['id']).encode()))
    if a.group=='pilot':cs=eligible[:ds['pilot']]
    elif a.group=='extension':cs=eligible[ds['pilot']:ds['pilot']+64]
    else:
        number=int(a.group.removeprefix('block-'))
        assert a.group==f'block-{number:02}' and number>=0
        start=ds['pilot']+64+64*number;cs=eligible[start:start+64]
        if not cs:raise ValueError('No remaining puzzles')
    batch=[(ps[c['id']],c,int(rows[c['id']]['certified_lower'])) for c in cs]
    with ProcessPoolExecutor(a.jobs) as pool:result=list(pool.map(work,batch))
    a.out.write_bytes((json.dumps({'base':ds['base'],'group':a.group,'rows':result},separators=(',',':'))+'\n').encode())
    print(len(result),sum(r['tree'] is not None for r in result),sum(r['visits'] for r in result),flush=True)
if __name__=='__main__':main()
