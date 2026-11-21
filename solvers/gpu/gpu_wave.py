"""Synthesize all remaining calculator goals in pooled backward waves on the GPU."""
from __future__ import annotations

import argparse
import csv
import ctypes
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
import random
from time import perf_counter

import numpy as np

from solvers.construction.construct import Constructor
from elf import Puzzle, arithmetic, check, read_puzzles, read_submission, write_submission
from solvers.gpu.gpu_join import GPUJoin, OPERATORS, Table, anchors_for, make_table, triple_pair
from solvers.gpu.gpu_schedule import schedule_like
from graph import active_graph, compile_graph, first_recipes

NONE = 0xffffffff
RAW = 0x80000000
ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class State:
    goal: int
    residual: int
    spent: int
    path: tuple
    mask: int=0


def scaffold_masks(table,unpaid):
    masks=np.zeros(len(table.values),dtype=np.uint64)
    masks[:table.n0]=[unpaid.get(int(v),0) for v in table.values[:table.n0]]
    for lo,hi in ((table.n0,table.n1),(table.n1,len(masks))):
        masks[lo:hi]=masks[table.left[lo:hi]]|masks[table.right[lo:hi]]
    return masks


class NativeTable:
    def __init__(self,path):
        self.library=ctypes.CDLL(str(path.resolve()))
        ptr=ctypes.POINTER
        self.u64=ptr(ctypes.c_uint64); self.u32=ptr(ctypes.c_uint32);self.u8=ptr(ctypes.c_uint8)
        self.library.gpu_build.argtypes=(self.u64,self.u64,ctypes.c_uint32,ctypes.c_uint64)
        self.library.gpu_build.restype=ctypes.c_void_p
        self.library.gpu_views.argtypes=(ctypes.c_void_p,self.u32,ptr(self.u64),ptr(self.u8),
                                         ptr(self.u32),ptr(self.u32))
        self.library.gpu_free.argtypes=(ctypes.c_void_p,)

    def build(self,anchors,limit,unpaid):
        seeds=np.array(sorted(set(anchors)),dtype=np.uint64)
        masks=np.array([unpaid.get(int(v),0) for v in seeds],dtype=np.uint64)
        handle=self.library.gpu_build(seeds.ctypes.data_as(self.u64),masks.ctypes.data_as(self.u64),
                                      len(seeds),limit)
        try:
            sizes=(ctypes.c_uint32*3)()
            values,operators,left,right=self.u64(),self.u8(),self.u32(),self.u32()
            self.library.gpu_views(handle,sizes,ctypes.byref(values),ctypes.byref(operators),
                                   ctypes.byref(left),ctypes.byref(right))
            arrays=[np.ctypeslib.as_array(arr,shape=(sizes[2],)).copy()
                    for arr in (values,operators,left,right)]
            return Table(*arrays,sizes[0],sizes[1])
        finally:
            self.library.gpu_free(handle)


def atom_graph(table, identifier, graph, raw_table=None):
    if identifier & RAW:
        table = table if raw_table is None else raw_table
        op,i,j=triple_pair(table,identifier & (RAW-1))
        a=atom_graph(table,i,graph)
        b=atom_graph(table,j,graph)
        value=arithmetic(OPERATORS[op],a,b)
        graph.setdefault(value,(OPERATORS[op],a,b))
        return value
    value=int(table.values[identifier])
    if identifier>=table.n0 and value not in graph:
        a=atom_graph(table,int(table.left[identifier]),graph)
        b=atom_graph(table,int(table.right[identifier]),graph)
        graph[value]=(OPERATORS[table.operators[identifier]],a,b)
    return value


def render(table,terminal,path,goal,raw_table=None,start=None):
    graph={} if start is None else start[1]
    def atom(i):
        return atom_graph(table,i,graph,raw_table)
    value=atom(terminal) if start is None else start[0]
    def put(op,a,b):
        result=arithmetic(op,a,b)
        graph.setdefault(result,(op,a,b))
        return result
    for op,i,j in reversed(path):
        if op==0:
            continue
        a=atom(i)
        if op==1: value=put("+",value,a)
        elif op==2: value=put("-",a,value)
        elif op==3: value=put("-",value,a)
        elif op==4: value=put("*",value,a)
        elif op in (5,6):
            value=put("+" if op==5 else "-",put("*",value,a),atom(j))
        elif op==7:
            value=put("-",atom(j),put("*",value,a))
        elif op in (8,9):
            v=put("*",a,atom(j))
            value=put("+" if op==8 else "-",v,value)
        elif op==10: value=put("/",value,a)
        elif op==11: value=put("/",a,value)
        else: raise ValueError(op)
    if value!=goal:
        raise ValueError(f"bad reconstruction for {goal}: {value}")
    return graph


def repriced_routes(winners,best,table,raw_table,anchors,unpaid,pricing,budget):
    """Rank finished routes by the generated value set, then by cross-target sharing."""
    pools={}
    support=Counter()
    literals=set(anchors)
    for target,plans in winners.items():
        ordered=sorted(set(plans))
        valid=[route for route in ordered if route[0]<=best[target]+3]
        # Retain cost leaders and a stratified sample of near ties.
        if len(valid)>budget:
            front=budget//2
            step=(len(valid)-front)/(budget-front)
            valid=valid[:front]+[valid[front+int(i*step)] for i in range(budget-front)]
        variants={}
        for _,final,path in valid:
            full=render(table,final,path,target,raw_table)
            visited={}
            debt=0;stack=[target]
            while stack:
                v=stack.pop()
                if v in literals:
                    debt|=unpaid.get(v,0)
                elif v not in visited:
                    recipe=full[v];visited[v]=recipe;stack.extend(recipe[1:])
            signature=frozenset(visited)
            cost=len(visited)+pricing*debt.bit_count()/100
            previous=variants.get(signature)
            if previous is None or cost<previous[0]:variants[signature]=(cost,visited)
        values=sorted(variants.values(),key=lambda x:x[0])
        pools[target]=values
        if values:
            used=set()
            for cost,g in values:
                if cost>values[0][0]+1:break
                used.update(g)
            support.update(used)
    answer={}
    for target,rows in pools.items():
        if not rows:continue
        cutoff=rows[0][0]+2
        rows=[(c,g) for c,g in rows if c<=cutoff]
        def quality(item):
            cost,g=item
            return cost-.17*sum(min(4,support[v]-1) for v in g if support[v]>1)
        base=[g for _,g in rows[:3]]
        for _,g in sorted(rows,key=quality):
            if not any(g.keys()==other.keys() for other in base):base.append(g)
            if len(base)>=14:break
        answer[target]=base
    return answer


class WaveEngine:
    def __init__(self, directory, native=False):
        self.join=GPUJoin(directory)
        self.table=NativeTable(directory/"gpu_table.dll") if native else None
        cl=self.join.cl
        source=(ROOT/"solvers/gpu/gpu_join.cl").read_text()+(ROOT/"solvers/gpu/gpu_wave.cl").read_text()
        program=cl.Program(self.join.context,source).build(
            options=("-cl-std=CL1.2",),cache_dir=str(directory.resolve()/"cl-cache"))
        self.kernel=cl.Kernel(program,"backward_wave")
        self.index_nearest=cl.Kernel(program,"index_nearest")
        self.index_residue=cl.Kernel(program,"index_residue")
        self.bridge=cl.Kernel(program,"bridge_demands")
        self.sweep=cl.Kernel(program,"sweep_wave")
        self.context=None

    def solutions(self,anchors,puzzle,targets,width,depth,stats,core,unpaid,pricing,neighbor_bits,
                  mod_banks,sweep_step=0,sweep_levels=1,landmarks=0,exact_routes=0):
        self.context=None
        begin=perf_counter()
        def create(leaves):
            return self.table.build(leaves,puzzle.limit,unpaid) if self.table else make_table(leaves,puzzle.limit)
        table=create(anchors)
        raw_table=table if anchors==core else create(core)
        pool,timing=self.join.prepare_pool(table,puzzle.limit,raw_table)
        masks=scaffold_masks(table,unpaid)
        raw_masks=masks if raw_table is table else scaffold_masks(raw_table,unpaid)
        extra_cache={}
        def toll(i):
            if i==NONE: return 0
            if not i&RAW: return int(masks[i])
            if i not in extra_cache:
                _,a,b=triple_pair(raw_table,i&(RAW-1))
                extra_cache[i]=int(raw_masks[a]|raw_masks[b])
            return extra_cache[i]
        stats["bank_wall"]+=perf_counter()-begin
        stats.update(timing)
        cl=self.join.cl
        mf=cl.mem_flags
        digits=neighbor_bits if pool.raw_count else 0
        fine=coarse=pool.short_slots
        if digits:
            arrays=[]
            for bits in (digits,8):
                size=8*(65-bits)*(1<<bits)
                arr=cl.Buffer(self.join.context,mf.READ_WRITE,size)
                cl.enqueue_fill_buffer(self.join.queue,arr,np.uint32(0),0,size)
                arrays.append(arr)
            fine,coarse=arrays
            for offset in range(0,pool.raw_count,1<<21):
                work=self.join.rounded(min(1<<21,pool.raw_count-offset))
                event=self.index_nearest(self.join.queue,(work,),None,pool.raw,np.uint32(pool.raw_count),
                        np.uint32(digits),np.uint32(offset),fine,coarse)
            event.wait()
        mod_parameters=[]
        for m,bits in ((256,7),(1024,5))[:mod_banks if pool.raw_count else 0]:
            if m not in table.values[:table.n1]:
                continue
            size=8*(65-bits)*(1<<bits)*m
            buf=cl.Buffer(self.join.context,mf.READ_WRITE,size)
            cl.enqueue_fill_buffer(self.join.queue,buf,np.uint32(0),0,size)
            for offset in range(0,pool.raw_count,1<<21):
                work=self.join.rounded(min(1<<21,pool.raw_count-offset))
                event=self.index_residue(self.join.queue,(work,),None,pool.raw,
                     np.uint32(pool.raw_count),np.uint32(bits),np.uint32(m),np.uint32(offset),buf)
            event.wait()
            mod_parameters.extend((np.uint32(m),np.uint32(bits),buf))
        while len(mod_parameters)<6: mod_parameters.extend((np.uint32(0),np.uint32(0),fine))
        indices=np.arange(table.n1,dtype=np.uint32)
        stride=((len(indices)+127)//128)*128
        scale_buffer=cl.Buffer(self.join.context,mf.READ_ONLY|mf.COPY_HOST_PTR,hostbuf=indices)
        frontier=[State(t,t,0,()) for t in targets]
        traces=[]
        best={t:99 for t in targets}
        winners=defaultdict(list)
        def special_states(current):
            # An inverse exact division climbs to a larger numerator. Such a
            # move pays off when that numerator lies close to a cheap value.
            # Rank the resulting differences against each sorted cost tier.
            extra=defaultdict(dict)
            tiers=[table.values[:table.n0],table.values[table.n0:table.n1],
                   table.values[table.n1:]]
            offsets=(0,table.n0,table.n1)
            for state in current:
                t=state.residual
                scale_ids=[j for j in range(table.n0) if 1<int(table.values[j])<=puzzle.limit//t]
                scale_ids.sort(key=lambda j:(toll(j).bit_count(),int(table.values[j])))
                # The direct centre also admits signed differences against
                # nearby values that the parent-oriented beam did not retain.
                points=[(t,None),*((t*int(table.values[j]),j) for j in scale_ids[:12])]
                for tier,values in enumerate(tiers):
                    if not len(values): continue
                    at=np.searchsorted(values,np.asarray([v for v,_ in points],dtype=np.uint64))
                    for (num,scale),index in zip(points,at):
                        for k in (int(index)-1,int(index)):
                            if not 0<=k<len(values): continue
                            v=int(values[k])
                            if v==num or t==abs(v-num): continue
                            child=abs(v-num)
                            if child>=t or child>puzzle.limit: continue
                            op=1 if num>v else 2
                            leaf=offsets[tier]+k
                            mask=state.mask|toll(leaf)
                            path=state.path
                            cost=state.spent+tier+1
                            if scale is not None:
                                path+=((10,scale,NONE),)
                                mask|=toll(scale)
                                cost+=1
                            if cost+1>best[state.goal]+1: continue
                            # Compare the remaining distance to the nearest
                            # affordable centre after charging original cones.
                            quality=cost+pricing*mask.bit_count()/100+.17*child.bit_length()
                            previous=extra[state.goal].get(child)
                            if previous is None or quality<previous[0]:
                                extra[state.goal][child]=(quality,State(state.goal,child,cost,
                                    path+((op,leaf,NONE),),mask))
            return [state for group in extra.values() for _,state in
                    sorted(group.values(),key=lambda v:(v[0],v[1].residual))[:landmarks]]
        def sweep_frontier(frontier):
            columns=(len(table.values)-table.n1+sweep_step-1)//sweep_step
            if not columns: return
            padded=((columns+127)//128)*128
            batch=max(1,min(16,(1<<21)//padded))
            for offset in range(0,len(frontier),batch):
                states=frontier[offset:offset+batch]
                values=np.asarray([s.residual for s in states],np.uint64)
                buf=cl.Buffer(self.join.context,mf.READ_ONLY|mf.COPY_HOST_PTR,hostbuf=values)
                host=np.empty((len(states),padded//64,8),np.uint32)
                out=cl.Buffer(self.join.context,mf.WRITE_ONLY,host.nbytes)
                event=self.sweep(self.join.queue,(len(states)*padded,),(128,),pool.buffers[0],
                        pool.short_slots,np.uint32(pool.short_mask),pool.raw,pool.long_slots,
                        np.uint32(pool.long_mask),np.uint32(table.n0),np.uint32(table.n1),
                        np.uint32(len(table.values)),np.uint64(puzzle.limit),buf,
                        np.uint32(sweep_step),np.uint32(columns),np.uint32(padded),out)
                cl.enqueue_copy(self.join.queue,host,out).wait()
                stats["sweep_device"]+=self.join.duration(event)
                stats["sweep_scales"]+=len(states)*columns
                for s,records in zip(states,host):
                    scores=records[:,6]
                    below=np.flatnonzero(scores+s.spent<=min(12,best[s.goal]+2))
                    if len(below)>100:
                        idx=below[np.argsort(scores[below],kind="stable")]
                        below=np.concatenate((idx[:40],idx[40::max(1,(len(idx)-40)//60)][:60]))
                    for j in below:
                        row=records[j]
                        op,a,b,terminal=map(int,row[2:6])
                        mask=s.mask|toll(a)|toll(b)|toll(terminal)
                        cost=s.spent+int(row[6])+pricing*mask.bit_count()/100
                        if cost<=best[s.goal]+(3 if exact_routes else 1):
                            best[s.goal]=min(best[s.goal],cost)
                            winners[s.goal].append((cost,terminal,s.path+((op,a,b),)))
                            stats["sweep_plans"]+=1
        for level in range(depth):
            if not frontier:
                break
            if landmarks and level<2:
                # Account for these extra paths in the same round, including
                # exact device hash matches against the three-operation table.
                extra=special_states(frontier)
                frontier=[*frontier,*extra]
                stats["landmark_probes"]+=len(extra)
            traces.extend(frontier)
            if sweep_step and level<sweep_levels:
                by_goal=defaultdict(list)
                for state in frontier:
                    if len(by_goal[state.goal])<2:
                        by_goal[state.goal].append(state)
                sweep_frontier([s for group in by_goal.values() for s in group])
            advances=defaultdict(dict)
            for offset in range(0,len(frontier),32):
                group=frontier[offset:offset+32]
                values=np.array([s.residual for s in group],np.uint64)
                buf=cl.Buffer(self.join.context,mf.READ_ONLY|mf.COPY_HOST_PTR,hostbuf=values)
                result=np.empty((len(group),stride//16,2,8),dtype=np.uint32)
                result_buffer=cl.Buffer(self.join.context,mf.WRITE_ONLY,result.nbytes)
                event=self.kernel(self.join.queue,(len(group)*stride,),(128,),
                    pool.buffers[0],pool.short_slots,np.uint32(pool.short_mask),pool.raw,
                    pool.long_slots,np.uint32(pool.long_mask),np.uint32(table.n0),
                    np.uint32(table.n1),np.uint32(len(table.values)),np.uint64(puzzle.limit),buf,np.uint32(len(group)),
                    scale_buffer,np.uint32(len(indices)),np.uint32(stride),np.uint32(digits),
                    fine,coarse,*mod_parameters,result_buffer)
                cl.enqueue_copy(self.join.queue,result,result_buffer).wait()
                stats["wave_device"]+=self.join.duration(event)
                stats["states"]+=len(group)
                for state,items in zip(group,result):
                    closed=items[:,1]
                    costs=closed[:,6]
                    pick=np.flatnonzero(costs+state.spent<=best[state.goal]+2)
                    if len(pick):
                        if len(pick)>40:
                            sorted_indices=pick[np.argsort(costs[pick],kind="stable")]
                            pick=np.concatenate((sorted_indices[:16],sorted_indices[16::max(1,(len(pick)-16)//24)][:24]))
                        for j in pick:
                            row=closed[j]
                            i,b,final=map(int,row[3:6])
                            mask=state.mask|toll(i)|toll(b)|toll(final)
                            cost=int(row[6])+state.spent+pricing*mask.bit_count()/100
                            if cost>best[state.goal]+(3 if exact_routes else 1):
                                continue
                            if cost<best[state.goal]:
                                best[state.goal]=cost
                            pair=tuple(map(int,row[2:5]))
                            winners[state.goal].append((cost,int(row[5]),state.path+(pair,)))
                    open_rows=items[:,0]
                    cap=best[state.goal]+1
                    pick=np.flatnonzero(open_rows[:,6]+state.spent+3<=cap)
                    if not len(pick):
                        continue
                    ranks=open_rows[pick,7].astype(np.int64)+state.spent*256
                    if len(pick)>width*6:
                        use=np.argpartition(ranks,width*6-1)[:width*6]
                        pick=pick[use]
                        ranks=ranks[use]
                    candidates=advances[state.goal]
                    for j,rank in zip(pick,ranks):
                        row=open_rows[j]
                        value=(int(row[1])<<32)|int(row[0])
                        mask=state.mask|toll(int(row[3]))|toll(int(row[4]))
                        rank+=round(256*pricing*mask.bit_count()/100)
                        if value in candidates and candidates[value][0]<=rank:
                            continue
                        candidates[value]=(int(rank),State(state.goal,value,state.spent+
                            int(row[6]),state.path+(tuple(map(int,row[2:5])),),mask))
            frontier=[s for byvalue in advances.values()
                      for rank,s in sorted(byvalue.values(),key=lambda x:(x[0],x[1].residual))[:width]]
        answer={}
        for t,plans in winners.items():
            chosen=[]
            signatures=set()
            for cost,final,path in sorted(plans):
                if cost>best[t]+1:
                    break
                graph=render(table,final,path,t,raw_table)
                key=tuple(graph.items())
                if key not in signatures:
                    signatures.add(key)
                    chosen.append(graph)
                if len(chosen)==10:
                    break
            answer[t]=chosen
        self.context=(table,raw_table,pool,traces,puzzle.limit)
        if exact_routes:
            return repriced_routes(winners,best,table,raw_table,anchors,unpaid,pricing,exact_routes)
        return answer

    def bridges(self,helpers):
        table,raw_table,pool,traces,limit=self.context
        cl=self.join.cl
        mf=cl.mem_flags
        numerical=np.array(helpers,np.uint64)
        residuals=np.array([s.residual for s in traces],np.uint64)
        result=np.empty((len(traces),len(helpers),2),np.uint32)
        inputs=[cl.Buffer(self.join.context,mf.READ_ONLY|mf.COPY_HOST_PTR,hostbuf=a)
                for a in (residuals,numerical)]
        output=cl.Buffer(self.join.context,mf.WRITE_ONLY,result.nbytes)
        self.bridge(self.join.queue,(self.join.rounded(len(helpers)*len(traces)),),None,
                    pool.buffers[0],pool.short_slots,np.uint32(pool.short_mask),
                    pool.raw,pool.long_slots,np.uint32(pool.long_mask),np.uint32(table.n0),
                    np.uint32(table.n1),np.uint64(limit),inputs[0],np.uint32(len(traces)),
                    inputs[1],np.uint32(len(helpers)),output)
        cl.enqueue_copy(self.join.queue,result,output).wait()
        costs=(result[:,:,0]&255)+np.array([s.spent for s in traces],np.uint32)[:,None]
        return costs,result

    def render_bridge(self,state,helper,record):
        table,raw_table,_,_,_=self.context
        op=int(record[0])>>8
        graph={}
        if op:
            a=atom_graph(table,int(record[1]),graph,raw_table)
            symbol={1:"+",2:"-",3:"-",4:"*",10:"/",11:"/"}[op]
            x,y=(a,helper) if op in (3,10) else (helper,a)
            if arithmetic(symbol,x,y)!=state.residual:
                raise ValueError("bad bridge witness")
            if state.residual not in (helper,a):
                graph[state.residual]=(symbol,x,y)
        return render(table,None,state.path,state.goal,raw_table,(state.residual,graph))


def scaffolding(puzzle,mode=0):
    constructor=Constructor(puzzle,16,True,False)
    if mode:
        def power_first(k):
            v=1<<k
            if v not in constructor.known:
                if v in constructor.dictionary or k<=1:
                    constructor.constant(v)
                else:
                    a=power_first(k//2)
                    b=power_first(k-k//2)
                    constructor.add(v,("*",a,b))
            return v
        for k in (0,1,2,3,4,5,6,7,8,10,12,16,20,24,32,40):
            if 1<<k<=puzzle.limit: power_first(k)
    for v in (1,2,3,4,5,7,8,11,13,16,32,64,128,256):
        if v<=puzzle.limit:
            constructor.constant(v)
    def power(k):
        v=1<<k
        if v not in constructor.known:
            a=power(k//2)
            b=power(k-k//2)
            constructor.add(v,("*",a,b))
        return v
    for k in (10,12,16,20,24,32,40):
        if (1<<k)<=puzzle.limit:
            power(k)
    if mode>=2 and puzzle.targets:
        simple=sorted(constructor.known)
        elective={}
        for i,a in enumerate(simple):
            for b in simple[i:]:
                for v,op,x,y in ((a+b,"+",a,b),(b-a,"-",b,a),(a*b,"*",a,b),
                             (b//a if not b%a else 0,"/",b,a)):
                    if 0<v<=puzzle.limit and v not in constructor.known:
                        elective.setdefault(v,(op,x,y))
        free=constructor.known
        targets=puzzle.targets
        ranked=[]
        for m,recipe in elective.items():
            if not (16<=m<=max(targets)//2): continue
            strength=0
            for t in targets:
                q,r=divmod(t,m)
                if not q: continue
                # Score actual balanced digits and their quotient over the
                # entire target set. A long radix with rare cheap digits can
                # win alongside a smaller scale that helps most goals.
                neg=m-r if (q+1)*m<=puzzle.limit else 0
                if not r:
                    strength+=m.bit_length()*2.5
                elif r in free or neg in free:
                    strength+=m.bit_length()
                elif r in elective or neg in elective:
                    strength+=.42*m.bit_length()
                if q in free or q+1 in free: strength+=.6*q.bit_length()
            if strength: ranked.append((strength,m,recipe))
        buckets=Counter()
        for _,m,recipe in sorted(ranked,reverse=True):
            b=m.bit_length()//4
            if buckets[b]>=3: continue
            if sum(buckets.values())>=17 or len(constructor.graph)>=58: break
            constructor.add(m,recipe)
            buckets[b]+=1
    return constructor.graph


def conditional_clusters(puzzle,beam,pending,done,base,graph,options,stats):
    """Grow two- and three-goal trees using unsolved targets as conditional operands."""
    direct=defaultdict(list)
    for t,plan,extra in options:
        direct[t].append((len(extra),plan))
    for t in direct:
        direct[t].sort(key=lambda entry:entry[0])
    if len(direct)<2: return []
    costs,records=beam.bridges(pending)
    traces=beam.context[3]
    by_goal=defaultdict(list)
    for i,s in enumerate(traces):
        by_goal[s.goal].append(i)
    links=defaultdict(list)
    for t,rows in by_goal.items():
        if t not in direct: continue
        rows=np.asarray(rows,np.intp)
        subset=costs[rows]
        low=subset.argmin(axis=0)
        for j,h in enumerate(pending):
            i=rows[low[j]]
            price=int(costs[i,j])
            if h==t or h not in direct or price>direct[t][0][0]: continue
            route=beam.render_bridge(traces[i],h,records[i,j])
            links[h].append((price-direct[t][0][0],t,route))
    result=[]
    def grow(h,plan,solved):
        next_nodes=[]
        for delta,t,route in sorted(links[h],key=lambda item:(item[0],item[1]))[:8]:
            if t in solved: continue
            try:
                merged=active_graph(puzzle,(base|route)|plan,targets=(*done,*solved,t))
            except (KeyError,ValueError):
                continue
            extra=frozenset(merged.keys()-graph.keys())
            next_nodes.append((t,merged,extra))
        return next_nodes
    for h,root_options in direct.items():
        for _,plan in root_options[:2]:
            pairs=grow(h,plan,(h,))
            result.extend(pairs)
            pairs.sort(key=lambda row:len(row[2])-direct[row[0]][0][0])
            for t,merged,_ in pairs[:2]:
                result.extend(grow(t,merged,(h,t))[:3])
                result.extend(grow(h,merged,(h,t))[:3])
    stats["conditional_clusters"]+=len(result)
    return result


def warm_macros(puzzle,warm,pending,scaffold,graph,quota):
    seeded=set(puzzle.seeds)
    prices=set(scaffold)-set(graph)
    positions={}
    for t in pending:
        fringe={t}
        for distance in range(1,5):
            fringe={v for child in fringe if child in warm for v in warm[child][1:]
                    if v not in graph and v not in seeded}
            for v in fringe:
                frequency,depth=positions.get(v,(0,9))
                positions[v]=(frequency+1,min(depth,distance))
    ranked=sorted(positions,key=lambda v:(-positions[v][0],positions[v][1],v))
    optional={}
    selected=[]
    for v in ranked:
        if v in pending: continue
        branch=active_graph(puzzle,warm,targets=(v,))
        extra=branch.keys()-graph.keys()
        if any(t in extra for t in pending) or len(prices|extra)>63: continue
        optional.update((k,branch[k]) for k in branch if k in extra)
        prices.update(extra)
        selected.append(v)
        if len(selected)==quota: break
    return optional,selected


def solve(puzzle,beam,settings,old=None,freeze=None,prepared=None):
    stats=Counter()
    all_targets=tuple(dict.fromkeys(puzzle.targets))
    if old is None:
        graph=dict(prepared or {})
        done=(set(puzzle.seeds)|graph.keys())&set(all_targets)
    else:
        warm=first_recipes(puzzle,old)
        if freeze is not None:
            graph=active_graph(puzzle,warm,targets=freeze)
        elif settings.tail:
            order=[v for v in warm if v in all_targets]
            frozen=order[:max(0,len(order)-settings.tail)]
            graph=active_graph(puzzle,warm,targets=frozen)
        else:
            graph={}
        done=set(all_targets)&(set(graph)|set(puzzle.seeds))
    scaffold=scaffolding(puzzle,settings.ladder)
    while len(done)<len(all_targets):
        pending=[t for t in all_targets if t not in done]
        macros,required=({},[])
        if old is not None and settings.warm_macros:
            macros,required=warm_macros(puzzle,warm,pending,scaffold,graph,settings.warm_macros)
        base=scaffold|macros|graph
        anchors=anchors_for(puzzle,base,base,pending[len(pending)//2],settings.quantity,required)
        chosen_core=anchors_for(puzzle,base,base,pending[len(pending)//2],settings.core,required)
        core=tuple(x for x in chosen_core if x in anchors)
        unpaid={}
        def debt(v):
            if v in graph or v in puzzle.seeds: return 0
            if v not in unpaid:
                _,a,b=base[v]
                inherited=debt(a)|debt(b)
                unpaid[v]=(1<<len(unpaid))|inherited
            return unpaid[v]
        for v in (*scaffold,*macros): debt(v)
        families=beam.solutions(anchors,puzzle,pending,settings.width,settings.depth,stats,core,
                                unpaid,settings.pricing,settings.neighbor_bits,settings.mod_banks,
                                settings.sweep,settings.sweep_levels,settings.landmarks,settings.exact_routes)
        stats["epochs"]+=1
        options=[]
        for t in pending:
            raw=families.get(t,[])
            if raw: stats["covered"]+=1
            if old is not None:
                raw=[*raw,warm]
            for route in raw:
                try:
                    merged=active_graph(puzzle,(base|route)|graph,targets=(*done,t))
                except (KeyError,ValueError):
                    continue
                extra=frozenset(merged.keys()-graph.keys())
                options.append((t,merged,extra))
        if settings.cluster and len(pending)>1:
            options.extend(conditional_clusters(puzzle,beam,pending,done,base,graph,options,stats))
        if not options:
            t=min(pending)
            constructor=Constructor(puzzle,32,True,True)
            constructor.synthesize(t)
            graph=active_graph(puzzle,(base|constructor.graph)|graph,targets=(*done,t))
            if prepared:graph=prepared|graph
            done.update(set(all_targets)&(set(graph)|set(puzzle.seeds)))
            stats["fallback"]+=1
            continue
        # Choose several in one epoch; newly created expressions are immediately
        # charged just once in later choices and join the next device bank.
        for _ in range(settings.commit):
            relevant=[entry for entry in options if entry[0] not in done]
            if not relevant: break
            shortest={}
            for t,merged,original_extra in relevant:
                extra=original_extra-graph.keys()
                if t not in shortest or len(extra)<len(shortest[t]):
                    shortest[t]=extra
            benefits={}
            if settings.bridge and shortest:
                alternatives={v for extra in shortest.values() for v in extra}
                helpers=sorted(alternatives)
                if helpers:
                    helper_pos={h:j for j,h in enumerate(helpers)}
                    costs,records=beam.bridges(helpers)
                    traces=beam.context[3]
                    goals=np.array([s.goal for s in traces],np.uint64)
                    for t,extra in shortest.items():
                        columns=[helper_pos[h] for h in extra]
                        if not columns: continue
                        after=costs[:,columns].min(axis=1)
                        gain=0
                        for other,nodes in shortest.items():
                            if t!=other:
                                x=after[goals==other]
                                if len(x): gain+=max(0,len(nodes)-int(x.min()))
                        benefits[t]=gain
            def priority(entry):
                t,_,bits=entry
                extra=bits-graph.keys()
                shared=sum(min(3,len(extra&x)) for other,x in shortest.items() if other!=t)
                future=benefits.get(t,0) if extra==shortest[t] else 0
                if settings.cluster:
                    covered=extra.intersection(shortest)
                    if len(covered)>1:
                        single=sum(len(shortest[v]) for v in covered)
                        discount=.3*max(0,single-len(extra))
                        return (len(extra)-discount)/len(covered),len(extra),len(bits),t
                return len(extra)-settings.credit*max(shared,future),len(extra),len(bits),t
            t,choice,_=min(relevant,key=priority)
            new=set(choice)-set(graph)
            graph=active_graph(puzzle,choice|graph,targets=(*done,t))
            if prepared:graph=prepared|graph
            inferred=set(all_targets)&(set(graph)|set(puzzle.seeds))
            if t not in inferred:
                raise ValueError("target disappeared")
            done.update(inferred)
            if settings.bridge and new and len(done)<len(all_targets):
                helpers=sorted(new)
                costs,records=beam.bridges(helpers)
                traces=beam.context[3]
                for other in shortest.keys()-done:
                    rows=np.array([i for i,s in enumerate(traces) if s.goal==other],np.intp)
                    if not len(rows): continue
                    sub=costs[rows]
                    pick=np.flatnonzero(sub.ravel()<=len(shortest[other])+1)
                    if len(pick)>6:
                        pick=pick[np.argsort(sub.ravel()[pick],kind="stable")[:6]]
                    for where in pick:
                        local,j=divmod(int(where),len(helpers))
                        i=int(rows[local])
                        route=beam.render_bridge(traces[i],helpers[j],records[i,j])
                        try:
                            merged=active_graph(puzzle,(base|route)|graph,targets=(*done,other))
                        except (ValueError,KeyError):
                            continue
                        extra=frozenset(merged.keys()-graph.keys())
                        options.append((other,merged,extra))
                        stats["bridge_plans"]+=1
    program=compile_graph(puzzle,graph,recompute=True,schedule_width=12)
    if old is not None and settings.warm_schedule:
        candidate=schedule_like(puzzle,old,graph)
        if candidate is not None and (program is None or len(candidate)<len(program)):
            program=candidate
    if program is None:
        raise ValueError(f"cannot schedule {puzzle.id}")
    check(puzzle,program)
    return program,stats


def neighborhoods(puzzle,beam,settings,original):
    """Rebuild a group whose exclusive ancestors can be saved together."""
    rng=random.Random(f"{puzzle.id}-{settings.seed}")
    incumbent=original
    best_raw=None
    stats=Counter()
    used=Counter()
    targets=set(puzzle.targets).difference(puzzle.seeds)
    if not targets: return original,stats
    for _ in range(settings.rounds):
        warm=first_recipes(puzzle,incumbent)
        chains={t:set(active_graph(puzzle,warm,targets=(t,))) for t in targets}
        count=Counter(v for chain in chains.values() for v in chain)
        size=min(settings.neighborhood,len(targets))
        chosen=set()
        missing=Counter(count)
        while len(chosen)<size:
            def weight(t):
                exclusive=sum(1 for v in chains[t] if missing[v]==1)
                shared=sum(1 for v in chains[t] if 1<missing[v]<count[v])
                novelty=1/(1+used[t])
                return (exclusive+.4*min(10,shared)+1)*novelty*(.82+.36*rng.random())
            t=max(sorted(targets-chosen),key=weight)
            chosen.add(t)
            missing.subtract(chains[t])
        used.update(chosen)
        program,current=solve(puzzle,beam,settings,incumbent,targets-chosen)
        stats.update(current)
        if best_raw is None or len(program)<len(best_raw): best_raw=program
        if len(program)<=len(incumbent): incumbent=program
    return best_raw,stats


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("data",type=Path)
    ap.add_argument("reference",type=Path)
    ap.add_argument("output",type=Path)
    ap.add_argument("--rows",type=int,default=12)
    ap.add_argument("--ids",type=Path)
    ap.add_argument("--quantity",type=int,default=43)
    ap.add_argument("--core",type=int,default=43)
    ap.add_argument("--width",type=int,default=9)
    ap.add_argument("--depth",type=int,default=4)
    ap.add_argument("--commit",type=int,default=4)
    ap.add_argument("--credit",type=float,default=.19)
    ap.add_argument("--pricing",type=int,default=55)
    ap.add_argument("--neighbor-bits",type=int,choices=(0,10,12,14),default=0)
    ap.add_argument("--mod-banks",type=int,choices=(0,1,2),default=0)
    ap.add_argument("--native-table",action="store_true")
    ap.add_argument("--bridge",action="store_true")
    ap.add_argument("--cluster",action="store_true")
    ap.add_argument("--ladder",type=int,choices=(0,1,2),default=0)
    ap.add_argument("--sweep",type=int,default=0,
                    help="stride within the sorted two-operation operand class")
    ap.add_argument("--sweep-levels",type=int,default=1)
    ap.add_argument("--landmarks",type=int,default=0,
                    help="extra signed and exact-division continuations per goal")
    ap.add_argument("--exact-routes",type=int,default=0,
                    help="fully re-price this many complete routes per goal, retaining shared intermediates")
    ap.add_argument("--tail",type=int,default=0)
    ap.add_argument("--neighborhood",type=int,default=0)
    ap.add_argument("--rounds",type=int,default=3)
    ap.add_argument("--warm-schedule",action="store_true")
    ap.add_argument("--warm-macros",type=int,default=0)
    ap.add_argument("--seed",type=int,default=710)
    ap.add_argument("--resume",action="store_true")
    ap.add_argument("--directory",type=Path,default=ROOT/"work/gpu")
    args=ap.parse_args()
    puzzles=read_puzzles(args.data)
    incumbent=read_submission(args.reference)
    if args.ids:
        ids=set(args.ids.read_text(encoding="utf-8").split())
        subset=[p for p in puzzles if p.id in ids]
    else:
        subset=puzzles.copy()
        random.Random(args.seed).shuffle(subset)
    if args.rows: subset=subset[:args.rows]
    def digest(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    warm=bool(args.tail or args.neighborhood)
    manifest={"lineage":"warm_neighborhood" if args.neighborhood else
              "warm_tail" if args.tail else "fresh_from_seeds",
              "data":digest(args.data), "sources":{f: digest(ROOT/f) for f in
              ("solvers/gpu/gpu_wave.py","solvers/gpu/gpu_wave.cl","solvers/gpu/gpu_join.py","solvers/gpu/gpu_join.cl","solvers/gpu/gpu_table.cpp",
               "solvers/gpu/gpu_schedule.py")},
              "parameters":{k:v for k,v in vars(args).items()
                            if isinstance(v,(int,float)) and k!="resume"},
              "ids":[p.id for p in subset]}
    if warm: manifest["warm_input"]=digest(args.reference)
    stamp=args.output.with_suffix(".json")
    if args.resume and args.output.exists():
        if not stamp.exists() or json.loads(stamp.read_text(encoding="utf8"))!=manifest:
            raise ValueError("saved run uses different data, settings or solver")
        results=read_submission(args.output)
        for p in subset:
            if p.id in results: check(p,results[p.id])
    else:
        results={}
    stamp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf8")
    engine=WaveEngine(args.directory,args.native_table)
    totalstats=Counter()
    t0=perf_counter()
    for p in subset:
        if p.id in results: continue
        if args.neighborhood:
            program,stats=neighborhoods(p,engine,args,incumbent[p.id])
        else:
            program,stats=solve(p,engine,args,incumbent[p.id] if args.tail else None)
        results[p.id]=program
        totalstats.update(stats)
        if not args.resume or len(results)==1 or len(results)%8==0 or len(results)==len(subset):
            write_submission(args.output,[p for p in subset if p.id in results],results)
        print(f"{len(results)}/{len(subset)} {p.id} {len(incumbent[p.id])}->{len(program)} "
              f"gpu covers {stats['covered']} in {stats['epochs']} epochs; {perf_counter()-t0:.1f}s",
              flush=True)
    print(json.dumps(dict(totalstats)),flush=True)


if __name__=="__main__":
    main()
