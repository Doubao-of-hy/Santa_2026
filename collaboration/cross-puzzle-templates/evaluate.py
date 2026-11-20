"""Compare legal seed substitutions. The native generator receives only the official seeds and limit."""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from itertools import combinations_with_replacement
from pathlib import Path
import argparse,hashlib,json,random,subprocess,sys
HERE=Path(__file__).resolve().parent
ROOT=next(p for p in HERE.parents if (p/'elf.py').is_file())
sys.path[:0]=[str(ROOT),str(HERE.parent),str(ROOT/'collaboration/official-heads')]
from selector import compile_selection
from practice_runtime import generate
from elf import arithmetic,check,read_puzzles,read_submission,sha256,write_submission
from gpu_join import cut_many
from gpu_schedule import schedule_like
from graph import active_graph,compile_graph,first_recipes

PILOT=['0636','0799','0012','0080','0704','0199','0068','0961']
HOLDOUT=['0165','0438','0846','0995']

def instantiate(p,library,exe):
    fields=(p.limit,len(p.seeds),*p.seeds)
    proc=subprocess.run([str(exe),str(library)],input=' '.join(map(str,fields))+'\n',text=True,capture_output=True,check=True)
    first,*rows=proc.stdout.splitlines();attempts,valid,n=map(int,first.split());values={}
    for row in rows:
        v,c,ix,*bind=map(int,row.split());values[v]=(ix,tuple(bind),c)
    assert len(values)==n
    return values,{'attempted':attempts,'valid':valid,'unique':n}

def instantiate_lifted(p,library,exe,wanted):
    with subprocess.Popen([str(exe),str(library),'--lift-select'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True) as proc:
        proc.stdin.write(' '.join(map(str,(p.limit,len(p.seeds),*p.seeds)))+'\n');proc.stdin.flush()
        # Native publishes complete search counts before seeing the readback queries.
        attempted,valid,n=map(int,proc.stdout.readline().split())
        qs=sorted(wanted);proc.stdin.write(' '.join(map(str,(len(qs),*qs)))+'\n');proc.stdin.close()
        matched=int(proc.stdout.readline());values={}
        for row in proc.stdout:
            v,c,ix,*bind=map(int,row.split());values[v]=(ix,tuple(bind),c)
        assert len(values)==matched and proc.wait()==0
    return values,{'attempted':attempted,'valid':valid,'unique':n,'readback':matched}

@lru_cache(maxsize=128)
def extended(p):
    roots=set(p.seeds);extra={}
    for x in p.seeds:
        for y in p.seeds:
            for op in '+-*/':
                if op=='/' and x%y:continue
                v=arithmetic(op,x,y)
                if 0<v<=p.limit and v not in roots:extra.setdefault(v,(op,x,y))
    return tuple([*p.seeds,*sorted(extra)]),extra

def decode(p,v,info,lib):
    ix,bind,cost=info;entry=lib[ix];known=set(p.seeds);values=[];graph={}
    domain=p.seeds
    if max(bind)>=len(domain):
        domain,extra=extended(p)
        for i in bind:
            if i>=len(p.seeds):
                q=domain[i];known.add(q);graph[q]=extra[q]
    def get(i):return domain[bind[-1-i]] if i<0 else values[i]
    for op,l,r in entry['steps']:
        a,b=get(l),get(r);x=arithmetic(op,a,b)
        assert 0<x<=p.limit
        if x not in known:graph[x]=op,a,b;known.add(x)
        values.append(x)
    assert values[-1]==v and len(graph)==cost
    return graph

def inverse(t,x,cap):
    if t>x:yield t-x,('+',t-x,x)
    if x>t:yield x-t,('-',x,x-t)
    if t<=cap-x:yield t+x,('-',t+x,x)
    if t%x==0:yield t//x,('*',t//x,x)
    if t<=cap//x:yield t*x,('/',t*x,x)
    if x%t==0:yield x//t,('/',x,x//t)

def old_options(p,g):
    known=set(g)|set(p.seeds);bank=[]
    for v in g:
        for a in known:
            for b,e in inverse(v,a,p.limit):
                if b in known and v not in (a,b) and e!=g[v]:bank.append({v:e})
    return bank

def rank_options(p,g,values,lib):
    result=[];direct=large=touch=0;term=set(p.targets)
    @lru_cache(maxsize=4096)
    def route(v):return decode(p,v,values[v],lib)
    for v in g:
        if v in values:direct+=1;large+=int(v>4096)
        keep,free=cut_many(p,g,{v});ground=set(p.seeds)|set(free);removed=len(g)-len(keep)
        choices={}
        def add(w,outer):
            if w not in values or w in ground:return
            body=route(w)
            if outer and v in body:return
            patch={x:e for x,e in body.items() if x not in ground}
            if outer:patch[v]=outer
            # Allow neutral and one-costlier alternatives so joint selection can reuse recipes.
            if len(patch)>removed+1:return
            key=frozenset(patch.items());choices.setdefault(key,patch)
        if v in values:add(v,None)
        for x in ground:
            for w,e in inverse(v,x,p.limit):
                if w not in (v,x):add(w,e)
        if choices:
            touch+=1
            items=sorted(choices.values(),key=lambda z:(len(z),tuple(z.items())))[:12]
            result.extend(items)
    return result,{'parent_nodes_exact':direct,'parent_large_exact':large,'nodes_with_competitive_menu':touch}

def select(p,t,original,common,extra):
    options=common+extra
    scored=[]
    for patch in options:
        try:g=active_graph(p,original|patch)
        except (KeyError,ValueError):continue
        if len(g)<len(t):scored.append((len(g),patch))
    best=t
    for _,patch in sorted(scored,key=lambda x:x[0])[:48]:
        cur=first_recipes(p,best)
        try:g=active_graph(p,cur|patch)
        except (KeyError,ValueError):continue
        if len(g)>=len(best):continue
        ns=[schedule_like(p,best,g),compile_graph(p,g,attempts=3,recompute=True,schedule_width=4)]
        for trial in ns:
            if trial and check(p,trial)<len(best):best=trial
    primary=first_recipes(p,best);active=active_graph(p,primary);primary={k:v for k,v in primary.items() if k in active}
    stats,after=compile_selection(p,best,primary,[original,*options],False)
    assert check(p,after)<=len(best)
    return after,{'greedy':len(best),'selection':stats}

def one(p,library,book,exe,gen,parent,split,out,lift):
    arms=['frequent','rare','scrambled']
    represented={} if lift else {arm:instantiate(p,library/(arm+'.txt'),exe) for arm in arms}
    tape=generate(p,p.targets,gen) if split=='practice' else parent[p.id]
    g=first_recipes(p,tape);active=active_graph(p,g);g={k:v for k,v in g.items() if k in active}
    if lift:
        wanted=set(g)|set(p.targets);known=set(g)|set(p.seeds)
        for t in wanted.copy():
            for x in known:wanted.update(w for w,_ in inverse(t,x,p.limit))
        represented={arm:instantiate_lifted(p,library/(arm+'.txt'),exe,wanted) for arm in arms}
    common=old_options(p,g)
    before,st=select(p,tape,g,common,[])
    r={'id':p.id,'before':len(tape),'old_only':len(before),'old_selection':st,'goals':len(set(p.targets)-set(p.seeds)),'arms':{}}
    if len(before)<len(tape):write_submission(out/(p.id+'-old.csv'),[p],{p.id:before})
    for arm,(values,stats) in represented.items():
        exact=set(p.targets)&values.keys()
        near={t for t in p.targets if any(w in values for x in p.seeds for w,e in inverse(t,x,p.limit))}
        extra,matches=rank_options(p,g,values,book['vocabulary'][arm])
        after,d=select(p,tape,g,common,extra)
        trial=min((before,after),key=len)
        r['arms'][arm]={**stats,**matches,'exact_goals':len(exact),'large_exact_goals':sum(x>4096 for x in exact),'with_seed_edge':len(near|exact),'extra_candidates':len(extra),'score':len(trial),**d}
        if len(trial)<len(tape):write_submission(out/(p.id+'-'+arm+'.csv'),[p],{p.id:trial})
    (out/(p.id+'.json')).write_text(json.dumps(r,separators=(',',':'))+'\n',encoding='utf8')
    print(p.id,len(tape),len(before),*[(v['score'],v['large_exact_goals']) for v in r['arms'].values()],flush=True)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('puzzles',type=Path);ap.add_argument('library',type=Path);ap.add_argument('exe',type=Path);ap.add_argument('out',type=Path)
    ap.add_argument('--split',choices=['practice','pilot','holdout'],required=True);ap.add_argument('--generator',type=Path);ap.add_argument('--parent',type=Path);ap.add_argument('--jobs',type=int,default=2);ap.add_argument('--lift',action='store_true')
    a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=True);book=json.loads((a.library/'library.json').read_bytes())
    ps={p.id:p for p in read_puzzles(a.puzzles)}
    ids=book['held_practice'] if a.split=='practice' else ['scored_'+i for i in (PILOT if a.split=='pilot' else HOLDOUT)]
    parent=None if a.split=='practice' else read_submission(a.parent)
    with ThreadPoolExecutor(a.jobs) as pool:
        tasks=[pool.submit(one,ps[i],a.library,book,a.exe.resolve(),a.generator.resolve() if a.generator else None,parent,a.split,a.out,a.lift) for i in ids]
        for task in tasks:task.result()

if __name__=='__main__':main()
