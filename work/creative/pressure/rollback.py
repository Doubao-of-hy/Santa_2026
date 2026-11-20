"""Revert neutral recipe substitutions in rejected DAGs and retry 48-register allocation."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations
import json
from pathlib import Path
import random

from reorder import HERE,ROOT,rejected,schedule,peak
from operand_allocation import synthesize
from elf import check,read_puzzles,read_submission,write_submission
from graph import active_graph,compile_graph,first_recipes,_allocate

def normal(r):
    op,a,b=r
    return (op,min(a,b),max(a,b)) if op in '+*' else r

def masks(items):
    if len(items)<=13:
        for size in range(len(items)+1):yield from combinations(items,size)
    else:
        rng=random.Random(9231)
        for size in (0,1,2,len(items)-1,len(items)):
            yield from combinations(items,size)
        for _ in range(1200):yield rng.sample(items,rng.randint(3,len(items)-2))

def optimize(p,old,graphs):
    original=first_recipes(p,old);best=old;best_mode=None;counts=Counter();unique=set();pending=[]
    for k,(_,_,__,new) in enumerate(graphs):
        changes=sorted(v for v in new.keys()&original.keys() if normal(new[v])!=normal(original[v]))
        supergraph=new|original
        for keep in masks(changes):
            if not keep:continue
            proposal=supergraph.copy();proposal.update({v:new[v] for v in keep})
            try:trimmed=active_graph(p,proposal)
            except (KeyError,ValueError):continue
            if len(trimmed)>=len(old):continue
            key=frozenset((v,normal(r)) for v,r in trimmed.items())
            if key in unique:continue
            unique.add(key);counts['shorter_graphs']+=1
            if len(trimmed)>=len(best):continue
            hint=tuple(v for v in original if v in trimmed)+p.targets
            anchored=active_graph(p,trimmed,hint)
            program=compile_graph(p,anchored,attempts=4)
            if program is not None and len(program)<len(best):
                check(p,program);best=program;best_mode={'rejected_graph_index':k,'selected_substitutions':keep,'total_substitutions':len(changes),'method':'restore neutral edges then reorder','logical':len(trimmed)}
                counts['feasible']+=1
            else:pending.append((len(trimmed),len(keep),k,keep,len(changes),anchored))
    for logic,_,k,keep,total,graph in sorted(pending,key=lambda x:x[:3])[:10]:
        if logic>=len(best):continue
        tape=compile_graph(p,graph,attempts=16,schedule_width=20,operation_width=64,recompute=True)
        if tape is not None and len(tape)<len(best):
            check(p,tape);best=tape;counts['feasible']+=1;best_mode={'rejected_graph_index':k,'selected_substitutions':keep,'total_substitutions':total,'method':'beam and rematerialization','logical':logic}
    def block(item):
        logic,_,k,keep,total,graph=item;start=peak(p,graph)
        _,tape,result=schedule((f'rollback-{p.id}',p,old,start,start,graph,.24,1183+k+sum(keep)%100000))
        method='roll back operands then move dependent blocks'
        if tape is None or len(tape)>=len(old):
            values=list(graph);order=result['ordered_node_indices'];seq={values[i]:graph[values[i]] for i in order}
            tape,_,__,___=synthesize(p,seq,.5);method='roll back operands and reselect legal register lifetimes'
        return tape,{'rejected_graph_index':k,'selected_substitutions':keep,'total_substitutions':total,'method':method,'logical':logic}
    candidates=[e for e in pending if e[0]<len(best)];random.Random(89271).shuffle(candidates)
    candidates=sorted(candidates,key=lambda x:x[0])[:100]
    if candidates:
        with ThreadPoolExecutor(4) as executor:
            for tape,method in executor.map(block,candidates):
                if tape is not None and len(tape)<len(best):
                    check(p,tape);best=tape;counts['feasible']+=1;best_mode=method
    return best,best_mode,counts

def main():
    ps=read_puzzles(ROOT/'data/puzzles.csv');by={p.id:p for p in ps};old=read_submission(next(HERE.glob('public-????????????.csv')));out={};log={}
    for path in sorted(HERE.glob('rejected-*.txt')):
        graph_list=list(rejected(path));i=graph_list[0][0];b,why,c=optimize(by[i],old[i],graph_list)
        log[i]={'before':len(old[i]),'after':len(b),'graphs':len(graph_list),'source':path.name,'method':why,'counts':c};print(i,log[i],flush=True)
        if len(b)<len(old[i]):out[i]=b
    (HERE/'rollback-report.json').write_text(json.dumps(log),encoding='ascii')
    if out:write_submission(HERE/'rollback-recovery.csv',[p for p in ps if p.id in out],out)

if __name__=='__main__':main()
