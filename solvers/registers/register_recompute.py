"""Split a live range by duplicating its operation, then reorder both occurrences."""
from collections import defaultdict
from itertools import combinations
from pathlib import Path
import subprocess
from elf import check
from graph import _allocate
from solvers.registers.physical_subprogram import bank
from solvers.registers.register_windows import profile

ENGINE=Path(__file__).resolve().parents[2]/'work/creative/pressure/order-search.exe'

def possibilities(p,sequence):
    order=list(sequence);where={v:i for i,v in enumerate(order)}|{v:-1 for v in p.seeds}
    uses=defaultdict(list)
    for k,v in enumerate(order):
        for a in set(sequence[v][1:]):uses[a].append(k)
    pressure=profile(p,order,sequence);hottest=max(pressure)
    hot=[max(0,c-hottest+5)**2 for c in pressure]
    ways=bank(p,sequence,{})
    choices=[]
    for v,visits in uses.items():
        if v in p.seeds or len(visits)<2:continue
        for old,new in zip(visits,visits[1:]):
            if new-old<3:continue
            gain=sum(hot[old:new]);options=[]
            for r in ways[v]:
                operands=set(r[1:])
                if max(where.get(x,len(order)) for x in operands)>=new:continue
                extra=0
                for x in operands:
                    prior=uses.get(x,())
                    last=prior[-1] if prior else max(0,where[x])
                    if last<new:extra+=sum(hot[last:new])
                cost=max(0,extra);options.append((cost,r))
            if options and gain:
                options.sort();choices.append((gain-options[0][0],v,old,new,options[0][1]))
    choices.sort(reverse=True)
    return choices,hot

def duplicate(p,sequence,jobs,seconds,seed):
    keys=list(sequence);splits=defaultdict(list)
    for i,(_,v,prior,new,recipe) in enumerate(jobs):splits[new].append((-(i+1),v,recipe))
    active={};graph={}
    for idx,v in enumerate(keys):
        for symbol,original,(op,l,r) in splits[idx]:
            graph[symbol]=(op,active.get(l,l),active.get(r,r));active[original]=symbol
        op,l,r=sequence[v];graph[v]=(op,active.get(l,l),active.get(r,r))
    identifiers=list(graph);n=len(graph);ix={v:i for i,v in enumerate(identifiers)}
    ix.update({v:n+i for i,v in enumerate(p.seeds)})
    lines=[f'{n} {len(p.seeds)} {p.registers} {seconds} {seed}']
    for i,(_,l,r) in enumerate(graph.values()):lines.append(f'{ix[l]} {ix[r]} {i}')
    run=subprocess.run([str(ENGINE)],input='\n'.join(lines)+'\n',text=True,capture_output=True,check=True)
    header,raw=run.stdout.splitlines();peak=int(header.split()[0])
    if peak>p.registers:return None,peak
    slots=list(map(int,raw.split()));ordered={identifiers[i]:graph[identifiers[i]] for i in slots}
    tape=_allocate(p,ordered,False,0,True)
    if tape is None or check(p,tape)!=len(graph):raise ValueError('invalid physical recomputation')
    return tape,peak

def optimize(p,sequence,upper,seconds,seed):
    budget=upper-len(sequence)-1
    if budget<1:return None
    choices,hot=possibilities(p,sequence)
    first=[];represented=set()
    for item in choices:
        if item[1] in represented:continue
        first.append(item);represented.add(item[1])
        if len(first)==14:break
    candidates=[[a] for a in first]
    if budget>=2:
        pairs=[]
        for a,b in combinations(choices[:26],2):
            if a[1]==b[1]:continue
            # Distinct gaps can relieve either the same peak twice or
            # separated peaks in different portions of the chronology.
            overlap=sum(hot[max(a[2],b[2]):min(a[3],b[3])]) if max(a[2],b[2])<min(a[3],b[3]) else 0
            pairs.append((a[0]+b[0]+overlap//3,a,b))
        pairs.sort(reverse=True);candidates.extend([[a,b] for _,a,b in pairs[:25]])
    for i,trial in enumerate(candidates):
        tape,peak=duplicate(p,sequence,trial,seconds,seed+31*i)
        if tape is not None:return tape
    return None
