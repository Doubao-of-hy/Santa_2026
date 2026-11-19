"""SPDX-License-Identifier: Apache-2.0
Original value-deletion search on an arithmetic AND/OR recipe hypergraph.
Forward closure proves feasibility without imposing an arbitrary value order.
Only strictly shorter replay-valid allocated programs replace the incumbent.
"""
import argparse
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
import csv,hashlib,heapq,json,random,time
from pathlib import Path
from recipe_milp import make_pool,read_graph,canonical,compile_graph,operation
from run_solver import replay


def prune(starts,targets,graph):
    result={};stack=list(targets);roots=set(starts)
    while stack:
        v=stack.pop()
        if v in roots or v in result:continue
        if v not in graph:return None
        result[v]=graph[v];stack.extend(graph[v][1:])
    # Keep topological order for valid subsequent hints and scheduling.
    return {v:r for v,r in graph.items() if v in result}


class Closure:
    def __init__(self,starts,targets,choices):
        self.starts=set(starts);self.targets=set(targets)
        self.values=sorted(self.starts|set(choices));self.idx={v:i for i,v in enumerate(self.values)}
        self.rules=[(v,r) for v in sorted(choices) for r in sorted(choices[v])]
        self.parents=[];self.users=defaultdict(list)
        for k,(v,r) in enumerate(self.rules):
            ps=set(r[1:])-self.starts;self.parents.append(len(ps))
            for a in ps:self.users[a].append(k)
        self.initial=[k for k,c in enumerate(self.parents) if not c]

    def solve(self,primary,banned,seed,allow_new):
        rng=random.Random(seed);rank={v:i for i,v in enumerate(primary)}
        permitted=set(primary)|self.starts if not allow_new else set(self.values)
        permitted-=set(banned)
        remaining=self.parents.copy();done=set(self.starts);plans={};masks={v:0 for v in self.starts};heap=[]
        noise={v:rng.random() for v in self.values} if seed else {}
        def push(k):
            v,r=self.rules[k]
            if v not in permitted or v in done:return
            a,b=r[1:];mask=masks[a]|masks[b]|(1<<self.idx[v])
            # Existing nodes are free for deletion trial; prefer old definitions,
            # then fewer alien helpers and a small actual ancestor footprint.
            foreign=(mask&external).bit_count()
            key=(foreign,rank.get(v,100000),int(primary.get(v)!=r),mask.bit_count(),k) if seed==0 else (foreign,mask.bit_count()+noise[v]*3,int(primary.get(v)!=r),rank.get(v,100000),k)
            heapq.heappush(heap,(key,k,mask))
        external=0
        for v in set(self.values)-set(primary)-self.starts:external|=1<<self.idx[v]
        for k in self.initial:push(k)
        missing=self.targets-done
        while heap and missing:
            _,k,mask=heapq.heappop(heap);v,r=self.rules[k]
            if v in done:continue
            done.add(v);masks[v]=mask;plans[v]=r;missing.discard(v)
            for j in self.users[v]:
                remaining[j]-=1
                if not remaining[j]:push(j)
        if missing:return None
        return prune(self.starts,self.targets,plans)


def improve(task):
    row,programs,helpers,rounds,seed=task
    for p in programs:replay(row,p)
    programs.sort(key=len);best=programs[0];starts=json.loads(row['starting_values']);targets=json.loads(row['targets'])
    choices,graphs=make_pool(starts,targets,programs,int(row['value_limit']),helpers)
    engine=Closure(starts,targets,choices);current=graphs[0];rng=random.Random(seed)
    goals=set(targets);wins=0
    for sweep in range(rounds):
        candidates=sorted(set(current)-goals)
        rng.shuffle(candidates);changed=False
        for value in candidates:
            if value not in current:continue
            for mode in range(2):
                plan=engine.solve(current,[value],0 if mode==0 else seed+sweep,mode==1)
                if plan is None or len(plan)>=len(current):continue
                current=plan;changed=True;wins+=1;break
        if not changed:break
    if len(current)<len(best):
        for schedule in range(32):
            p=compile_graph(starts,targets,current,schedule,len(best))
            if p is not None and len(p)<len(best):replay(row,p);best=p
    return row['id'],best,wins


def main():
    p=argparse.ArgumentParser();p.add_argument('inputs',nargs='+');p.add_argument('--puzzles',required=True)
    p.add_argument('--output',required=True);p.add_argument('--workers',type=int,default=4)
    p.add_argument('--helpers',type=int,default=200);p.add_argument('--rounds',type=int,default=2)
    p.add_argument('--seed',type=int,default=20261120);p.add_argument('--count',type=int,default=0);p.add_argument('--resume',action='store_true')
    a=p.parse_args();rows=list(csv.DictReader(open(a.puzzles)));rows=rows[:a.count] if a.count else rows
    sources=[{r['id']:json.loads(r['program']) for r in csv.DictReader(open(f))} for f in a.inputs]
    done={r['id']:json.loads(r['program']) for r in csv.DictReader(open(a.output))} if a.resume and Path(a.output).exists() else {}
    tasks=[(r,[s[r['id']] for s in sources],a.helpers,a.rounds,a.seed) for r in rows if r['id'] not in done]
    total=old=0;start=time.time();families=defaultdict(int)
    with open(a.output,'w') as f,ProcessPoolExecutor(a.workers) as pool:
        w=csv.writer(f);w.writerow(['id','program']);it=pool.map(improve,tasks)
        for i,r in enumerate(rows):
            pid=r['id']
            if pid in done:prog=done[pid]
            else:outid,prog,_=next(it);assert pid==outid
            total+=replay(r,prog);old+=min(len(s[pid]) for s in sources);families[r.get('family','scored')]+=len(prog)
            w.writerow([pid,json.dumps(prog,separators=(',',':'))]);f.flush()
            if (i+1)%10==0:print(i+1,total,'saved',old-total,'seconds',round(time.time()-start,1),flush=True)
    report={'instructions':total,'baseline':old,'seconds':time.time()-start,'args':vars(a),'families':dict(families),'input_hashes':{f:hashlib.sha256(Path(f).read_bytes()).hexdigest() for f in a.inputs},'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    Path(a.output).with_suffix('.report.json').write_text(json.dumps(report,indent=2));print(report)

if __name__=='__main__':main()
