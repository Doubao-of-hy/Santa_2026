"""Jointly translate local target clusters to reuse an alphabet of signed offsets."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations,combinations_with_replacement
from pathlib import Path
import argparse,hashlib,json,random,sys
HERE=Path(__file__).resolve().parent
ROOT=next(p for p in HERE.parents if (p/'elf.py').exists())
sys.path[:0]=[str(ROOT),str(HERE.parent)]
from selector import compile_selection
from elf import check,read_puzzles,read_submission,sha256,write_submission
from graph import active_graph,compile_graph,first_recipes
from gpu_join import cut_many
from gpu_schedule import schedule_like

PILOT=['0567','0730','0768','0801','0755','0305']
HOLD=['0988','0976','0874','0568','0027','0127']
MAX=4096

def clusters(p):
    ts=sorted(set(p.targets));parts=[[ts[0]]]
    for x,y in zip(ts,ts[1:]):
        if x>8192 and y-x<=MAX and x>64*(y-x):parts[-1].append(y)
        else:parts.append([y])
    return [r for r in parts if len(r)>1]


def ops(a,b):
    if a<b:a,b=b,a
    yield a+b,('+',a,b);yield a*b,('*',a,b)
    if a>b:yield a-b,('-',a,b)
    if a%b==0:yield a//b,('/',a,b)


def step(target,base,offset):
    if target>base:return '+',base,offset
    return '-',base,offset


def prepare(p,pg):
    g=first_recipes(p,pg);needed=active_graph(p,g);g={v:e for v,e in g.items() if v in needed}
    gr=clusters(p);goals=set(v for group in gr for v in group)
    _,free=cut_many(p,g,goals)
    bank=sorted(set(free)|set(p.seeds))
    allone={};low={s:() for s in bank if s<=MAX}
    for x,y in combinations_with_replacement(bank,2):
        for v,e in ops(x,y):
            if v>p.limit:continue
            allone.setdefault(v,e)
            if v<=MAX and v not in low:low[v]=((v,e),)
    one=list(low.items());small=[v for v in bank if v<65536]
    for x,path in one:
        if not path:continue
        for y in small:
            for v,e in ops(x,y):
                if v<=MAX and v not in low:low[v]=path+((v,e),)
    return g,gr,bank,low,allone


def label_score(v,gaps,low):
    cost=len(low[v]);cnt=0;cheap=0
    for d in gaps:
        options=[len(low[u]) for u in (abs(v-d),v+d) if u in low]
        if options:
            c=cost+min(options);cnt+=int(c<=2);cheap+=max(0,5-c)
    return cnt,cheap,-cost,-v


def case_options(p,group,low,one,bank,alphabet,rng):
    lo,hi=group[0],group[-1]
    offsets=set(alphabet);near=sorted(x for x in bank if lo-2*MAX<=x<=hi+2*MAX)
    possible=set()
    for t in group:
        for d in offsets:
            possible.add(t-d);possible.add(t+d)
    # Retain constructible nearby values even when all their shifts have modest global rank.
    possible.update(v for v in one if lo-MAX<=v<=hi+MAX)
    possible.update(near)
    entries=[]
    for c in sorted(possible):
        if c<=0 or c>p.limit or c in p.targets:continue
        links={t:abs(t-c) for t in group if abs(t-c) in low}
        if len(links)<2:continue
        sources=[(v,abs(c-v)) for v in near if v!=c and abs(c-v) in low]
        ischeap=c in bank or c in one
        common=sum(d in offsets for d in links.values())
        cheapest=sorted(len(low[d]) for d in links.values())
        rank=(int(ischeap)*4+min(5,len(links))*1.3+min(3,common)*.75-sum(cheapest[:2]),int(c in bank),-min(links.values()),-c)
        entries.append((rank,c,links,sources))
    if not entries:return [],[]
    by=sorted(entries,reverse=True)
    # Give each high-coverage offset signature at most one slot in a cluster.
    ranked=[];seen=set()
    for row in by:
        _,c,links,_=row
        sig=tuple(sorted(links.values()))
        if sig in seen:continue
        seen.add(sig);ranked.append(row)
        if len(ranked)==24:break
    rand=rng.sample(entries,len(ranked))
    return rand,ranked


def menus(p,pg):
    g,groups,bank,low,one=prepare(p,pg);base=set(bank)
    gaps=[b-a for group in groups for a,b in combinations(group,2) if b-a<=MAX]
    alphabet=sorted(low,key=lambda v:label_score(v,gaps,low),reverse=True)[:100]
    rng=random.Random(20261127+int(p.id[-4:]));direct=[];sets={'random':[],'ruler':[]};shapes={'random':[],'ruler':[]}
    def flat(vs):
        patch={}
        for v in vs:patch.update(low[v])
        return patch
    for group in groups:
        near=[v for v in bank if group[0]-MAX<=v<=group[-1]+MAX]
        for target in group:
            for v in sorted(set(near)|set(group)):
                if v==target:continue
                d=abs(target-v)
                if d not in low:continue
                patch=flat([d]);patch[target]=step(target,v,d);direct.append(patch)
            if target in one:
                direct.append({target:one[target]})
        selected=case_options(p,group,low,one,bank,alphabet,rng)
        for mode,entries in zip(sets,selected):
            for rank,c,links,sources in entries:
                all_rec={}
                for t,d in links.items():
                    path=flat([d]);path[t]=step(t,c,d);all_rec[t]=path
                starts=[]
                if c in base:starts.append((None,{}))
                elif c in one:starts.append((None,{c:one[c]}))
                for origin,d in [*sources,*links.items()]:
                    header=flat([d]);header[c]=step(c,origin,d);starts.append((origin,header))
                for path in all_rec.values():sets[mode].append(path)
                for origin,header in starts:
                    if header:sets[mode].append(header)
                    left=[t for t in links if t!=origin]
                    for count in range(1,min(3,len(left))+1):
                        for sub in combinations(left,count):
                            patch=dict(header)
                            for t in sub:patch.update(all_rec[t])
                            shapes[mode].append(patch)
    return g,groups,direct,sets,shapes


def greedy(p,base,tape,patches):
    scored=[];seen=set()
    for patch in patches:
        key=frozenset(patch.items())
        if key in seen:continue
        seen.add(key)
        try:g=active_graph(p,base|patch)
        except (ValueError,KeyError):continue
        if len(g)<len(tape):scored.append((len(g),patch))
    best=tape
    for _,patch in sorted(scored,key=lambda x:x[0])[:48]:
        old=first_recipes(p,best)
        try:g=active_graph(p,old|patch)
        except (ValueError,KeyError):continue
        if len(g)>=len(best):continue
        trial=schedule_like(p,best,g) or compile_graph(p,g,attempts=3,recompute=True,schedule_width=3)
        if trial and check(p,trial)<len(best):best=trial
    return best


def run(p,tape,out):
    g,gr,direct,sets,shapes=menus(p,tape)
    r={'before':len(tape),'clusters':list(map(len,gr)),'arms':{}}
    for mode in ('direct','random','ruler'):
        extra=sets.get(mode,[]); patches=direct+shapes.get(mode,[])
        best=greedy(p,g,tape,patches)
        # Identical arithmetic selector budget. The common fixed feasible graph is also available in each arm.
        primary=first_recipes(p,best)
        active=active_graph(p,primary);primary={v:e for v,e in primary.items() if v in active}
        stats,t=compile_selection(p,best,primary,[g,*direct,*extra],False)
        final=min((best,t),key=len);n=check(p,final)
        r['arms'][mode]={'score':n,'greedy':len(best),'direct_recipes':len(direct),'center_recipes':len(extra),'group_patches':len(patches),'selection':stats}
        if n<len(tape):write_submission(out/(p.id+'-'+mode+'.csv'),[p],{p.id:final})
    (out/(p.id+'.json')).write_text(json.dumps(r,separators=(',',':'))+'\n',encoding='utf8')
    print(p.id,len(tape),*(r['arms'][k]['score'] for k in ('direct','random','ruler')),flush=True)


def main():
    a=argparse.ArgumentParser();a.add_argument('puzzles',type=Path);a.add_argument('independent',type=Path);a.add_argument('out',type=Path)
    a.add_argument('--split',choices=['pilot','holdout'],required=True);a.add_argument('--jobs',type=int,default=2)
    o=a.parse_args();o.out.mkdir(parents=True,exist_ok=True);old=read_submission(o.independent);ps={p.id:p for p in read_puzzles(o.puzzles)}
    with ThreadPoolExecutor(o.jobs) as pool:
        futures=[pool.submit(run,ps['scored_'+k],old['scored_'+k],o.out) for k in (PILOT if o.split=='pilot' else HOLD)]
        for f in futures:f.result()

if __name__=='__main__':main()
