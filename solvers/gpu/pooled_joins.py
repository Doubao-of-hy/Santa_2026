"""Use one two-operation arithmetic dictionary for many removable subprograms."""
import argparse
from collections import Counter, defaultdict
from importlib.util import module_from_spec, spec_from_file_location
import json
from math import isqrt
from pathlib import Path
import random
from time import monotonic

import numpy as np

from solvers.arithmetic.carry_routes import cases
from checkpoint import atomic_text
from elf import arithmetic, check, read_puzzles, read_submission, sha256, write_submission
from solvers.gpu.gpu_join import GPUJoin, make_table, OPERATORS, cut_many
from solvers.gpu.gpu_schedule import schedule_like
from graph import active_graph, compile_graph, first_recipes

ROOT=Path(__file__).resolve().parents[2]


def inverse(t, x, cap):
    if t>x: yield t-x, ('+',x,t-x)
    if x>t: yield x-t, ('-',x,x-t)
    if x+t<=cap: yield x+t, ('-',x+t,x)
    if t%x==0: yield t//x, ('*',x,t//x)
    if x%t==0: yield x//t, ('/',x,x//t)
    if x*t<=cap: yield x*t, ('/',x*t,x)


def repeated_paths(value, limit, paid=frozenset()):
    """Invert a suffix of additions or products of an intermediate with itself."""
    layer = [(value, ())]
    seen = {value}
    if value in paid:
        return
    for _ in range(limit):
        next_layer = []
        for out, suffix in layer:
            root = isqrt(out)
            choices = []
            if out % 2 == 0:
                choices.append((out // 2, '+'))
            if root * root == out:
                choices.append((root, '*'))
            for x, op in choices:
                if x in seen or x in paid:
                    continue
                seen.add(x)
                path = ((out, (op, x, x)),) + suffix
                yield x, path
                next_layer.append((x, path))
        layer = next_layer


def query_set(p, graph, regions, width, tails, two_tails=0,min_suffix_steps=5, repeated=0):
    paid_sets=[set(paid) for _,_,paid,_ in regions]
    use=Counter(x for _,a,b in graph.values() for x in {a,b})
    coverage=Counter(v for paid in paid_sets for v in paid)
    # Include frequently useful large anchors as well as universal small ones.
    featured=sorted(coverage,key=lambda v:(-min(use[v],6),-coverage[v],v))
    universal=sorted(coverage,key=lambda v:(-coverage[v],-min(use[v],5),v))
    anchors=set(p.seeds)|set(featured[:width//4])
    for x in universal:
        if len(anchors)>=width: break
        anchors.add(x)
    anchors=sorted(anchors)
    masks=np.array([sum(1<<i for i,s in enumerate(paid_sets) if v in s)
                    for v in anchors],dtype=np.uint32)
    queries=[]
    for i,(root,private,_,_) in enumerate(regions):
        queries.append((i,root,()))
        if repeated and len(private)>=3:
            # Either side of a paid-operand terminal operation may contain the
            # repeated operand. Reverse both orders and count every instruction.
            budget=min(4,len(private)-2)
            extra={}
            def offer(v,path):
                if v in paid_sets[i] or any(out in paid_sets[i] or out==v for out,_ in path):return
                price=(len(path),v.bit_length(),v,path)
                if v not in extra or price<extra[v][0]:extra[v]=(price,path)
            doubled=list(repeated_paths(root,budget,paid_sets[i]))
            for y,path in doubled:
                offer(y,path)
            for x in sorted(paid_sets[i]):
                for y,path in doubled:
                    if len(path)>=budget or x==y:continue
                    for z,edge in inverse(y,x,p.limit):
                        offer(z,((y,edge),)+path)
                for y,edge in inverse(root,x,p.limit):
                    if y in (root,x) or y in paid_sets[i]:continue
                    for z,prefix in repeated_paths(y,budget-1,paid_sets[i]):
                        offer(z,prefix+((root,edge),))
            for z,(_,path) in sorted(extra.items(),key=lambda item:item[1][0])[:repeated]:
                queries.append((i,z,path))
        if (not tails and not two_tails) or len(private)<min_suffix_steps: continue
        old_inputs=set(graph[root][1:])
        options=[]
        for x in paid_sets[i]:
            for y,rec in inverse(root,x,p.limit):
                if y in (x,root) or y in paid_sets[i]: continue
                # Exact large factors are promising, as are close differences
                # to reused values and alternatives to the original last step.
                score=(y.bit_length()-.8*min(5,use[x])-
                       (2.5 if rec[0]=='*' else 0)-(3 if x in old_inputs else 0))
                options.append((score,y,rec))
        chosen=set()
        ranked=sorted(options)
        for _,y,rec in (ranked if tails else ()):
            if y in chosen: continue
            queries.append((i,y,((root,rec),)));chosen.add(y)
            if len(chosen)>=tails: break
        if not two_tails or len(private)<6: continue
        # Price a two-operation suffix exactly. Retain both small residuals
        # and factorizable offsets whose quotient may be much easier to build.
        shortlist=[]
        by_kind=Counter()
        for _,y,r in ranked:
            if by_kind[r[0]]>=7:continue
            shortlist.append((y,r));by_kind[r[0]]+=1
        # Division by a paid value may be possible after *adding* a larger
        # paid offset. Consider more distinct terminal offsets in this shape.
        shortlist.extend((y,r) for _,y,r in ranked[:45])
        twos={};old_edges={graph[v] for v in private};old_values=set(private)
        for y,outer in dict.fromkeys(shortlist):
            for a in paid_sets[i]:
                for z,inner in inverse(y,a,p.limit):
                    if z in (root,y,a) or z in paid_sets[i] or z in chosen:continue
                    if root in inner[1:]:continue
                    if z==outer[1] or z==outer[2]:continue
                    price=(z.bit_length()-.6*min(6,use[a])-
                           (1.7 if inner[0]=='*' else 0)-
                           (3.5 if inner in old_edges and z in old_values else 0))
                    if z not in twos or price<twos[z][0]:
                        twos[z]=(price,((y,inner),(root,outer)))
        for z,(_,path) in sorted(twos.items(),key=lambda kv:(kv[1][0],kv[0]))[:two_tails]:
            queries.append((i,z,path))
    return anchors,masks,queries


class PooledEngine:
    def __init__(self,directory,hubs=0):
        self.gpu=GPUJoin(directory)
        self.hubs=hubs
        source=(ROOT/'solvers/gpu/gpu_join.cl').read_text().split('inline void record_match')[0]
        source+=(ROOT/'solvers/gpu/pooled_joins.cl').read_text()
        self.program=self.gpu.cl.Program(self.gpu.context,source).build(
            options=['-cl-std=CL1.2'],cache_dir=str(directory/'cl-cache'))
        self.kernel=self.gpu.cl.Kernel(self.program,'pooled_join')
        self.extend=self.gpu.cl.Kernel(self.program,'allowable')
        self.focused=self.gpu.cl.Kernel(self.program,'focused_joins')

    def run(self,table,masks,queries,cap,capacity,alternate=False,budgets=None,shallow_first=False):
        gpu=self.gpu;cl=gpu.cl;flags=cl.mem_flags
        n=len(table.values);count=len(queries)
        def uploaded(data):
            return cl.Buffer(gpu.context,flags.READ_ONLY|flags.COPY_HOST_PTR,hostbuf=data)
        values=uploaded(table.values)
        goals=uploaded(np.array([v for _,v,_ in queries],dtype=np.uint64))
        bits=uploaded(np.array([1<<i for i,_,_ in queries],dtype=np.uint32))
        slots=1<<(2*n-1).bit_length()
        hashed=cl.Buffer(gpu.context,flags.READ_WRITE,size=4*slots)
        cl.enqueue_fill_buffer(gpu.queue,hashed,np.uint32(0),0,4*slots)
        build=gpu.insert(gpu.queue,(gpu.rounded(n),),None,values,np.uint32(n),np.uint32(slots-1),hashed)
        times=[]
        if alternate:
            # OR the valid cut bits for every recipe of a value before the
            # next layer reads them. A cut can regenerate a removed anchor.
            zero=uploaded(masks);previous=zero
            for depth,(layer,dest_size) in enumerate(((table.n0,table.n1),(table.n1,n))):
                buf=cl.Buffer(gpu.context,flags.READ_WRITE,size=4*dest_size)
                cl.enqueue_fill_buffer(gpu.queue,buf,np.uint32(0),0,4*dest_size)
                cl.enqueue_copy(gpu.queue,buf,previous,byte_count=4*layer)
                times.append(self.extend(gpu.queue,(gpu.rounded(layer*(table.n0+1)),),None,
                    values,hashed,zero,previous,buf,np.uint32(slots-1),np.uint32(table.n0),
                    np.uint32(layer),np.uint64(cap)))
                if depth==0: one=buf
                previous=buf
            access=previous
        else:
            allowed=np.empty(n,dtype=np.uint32);allowed[:table.n0]=masks
            for lo,hi in ((table.n0,table.n1),(table.n1,n)):
                allowed[lo:hi]=allowed[table.left[lo:hi]] & allowed[table.right[lo:hi]]
            access=uploaded(allowed);zero=one=access
        counts=np.zeros((count,6),dtype=np.uint32)
        records=np.zeros((count,6,capacity,3),dtype=np.uint32)
        countbuf=cl.Buffer(gpu.context,flags.READ_WRITE|flags.COPY_HOST_PTR,hostbuf=counts)
        outbuf=cl.Buffer(gpu.context,flags.WRITE_ONLY,size=records.nbytes)
        scanned=table.n1 if shallow_first else n
        fields=tuple(map(np.uint32,(slots-1,table.n0,table.n1,scanned)))
        track=bool(self.hubs and budgets is not None)
        budgetsbuf=uploaded(np.asarray(budgets,dtype=np.uint32)) if track else bits
        demand=cl.Buffer(gpu.context,flags.READ_WRITE,size=(n if track else 1)*4)
        if track:cl.enqueue_fill_buffer(gpu.queue,demand,np.uint32(0),0,n*4)
        event=self.kernel(gpu.queue,(gpu.rounded(scanned),count),(128,1),values,hashed,access,zero,one,
                          np.uint32(alternate),goals,bits,*fields,np.uint64(cap),np.uint32(capacity),
                          countbuf,outbuf,np.uint32(track),budgetsbuf,demand)
        cl.enqueue_copy(gpu.queue,counts,countbuf)
        cl.enqueue_copy(gpu.queue,records,outbuf).wait()
        hits=[[(int(a),int(b),int(op)) for tier in range(6)
               for a,b,op in records[q,tier,:min(capacity,int(counts[q,tier]))]]
              for q in range(count)]
        hub_stats={}
        if track:
            demand_host=np.empty(n,dtype=np.uint32)
            cl.enqueue_copy(gpu.queue,demand_host,demand).wait()
            ids=np.flatnonzero(demand_host & (demand_host-np.uint32(1)))
            if len(ids):
                support=np.bitwise_count(demand_host[ids])
                ranked=ids[np.argsort(-support.astype(np.int8),kind='stable')]
                # Sample distinct sets of beneficiary cuts before filling in
                # repeated sets. Small and large values may cover the same cuts.
                chosen=[];seen=set();levels=set()
                for i in ranked:
                    key=(int(demand_host[i]),int(i>=table.n1))
                    if key not in levels:
                        chosen.append(int(i));seen.add(int(i));levels.add(key)
                        if len(chosen)==self.hubs:break
                if len(chosen)<self.hubs:
                    for i in ranked:
                        if int(i) not in seen:chosen.append(int(i))
                        if len(chosen)==self.hubs:break
                focus=uploaded(np.asarray(chosen,dtype=np.uint32))
                out=np.zeros((count,len(chosen),6),dtype=np.uint32)
                out_dev=cl.Buffer(gpu.context,flags.READ_WRITE|flags.COPY_HOST_PTR,hostbuf=out)
                self.focused(gpu.queue,(len(chosen),count),None,values,hashed,access,goals,bits,
                             focus,np.uint32(len(chosen)),np.uint32(slots-1),np.uint64(cap),out_dev)
                cl.enqueue_copy(gpu.queue,out,out_dev).wait()
                extras=0
                for q,row in enumerate(out):
                    known=set(hits[q])
                    for i,op in zip(*row.nonzero()):
                        a,b,k=chosen[i],int(row[i,op])-1,int(op)
                        if k in (0,3) and a>b:a,b=b,a
                        match=(a,b,k)
                        if match not in known:
                            hits[q].append(match);known.add(match);extras+=1
                hub_stats.update(shared_values=len(ids),focused_values=len(chosen),extra_matches=extras)
        return hits,dict(**hub_stats,dictionary=n,queries=count,probes=scanned*count,
                         kernel_seconds=gpu.duration(event),hash_seconds=gpu.duration(build),
                         mask_seconds=sum(gpu.duration(x) for x in times))


class LocalRecipes:
    """Rebuild an arithmetic witness using anchors available to a specific cut."""
    def __init__(self,anchors,paid,cap):
        self.anchors=[int(v) for v in anchors if v in paid]
        self.paid=paid
        self.cap=cap
        self.first=None
        self.cache={}
        self.cheaper={}
        self.second={}

    def get(self,v):
        if v in self.paid:return {}
        if v in self.cache:return self.cache[v]
        if self.first is None:
            self.first={}
            for i,a in enumerate(self.anchors):
                for b in self.anchors[:i+1]:
                    if a+b<=self.cap:self.first.setdefault(a+b,('+',a,b))
                    if a>b:self.first.setdefault(a-b,('-',a,b))
                    if a*b<=self.cap:self.first.setdefault(a*b,('*',a,b))
                    if a%b==0:self.first.setdefault(a//b,('/',a,b))
        if v in self.first:
            patch={v:self.first[v]}
        else:
            choices=[]
            if v%2==0:choices.append((v//2,('+',v//2,v//2)))
            root=isqrt(v)
            if root*root==v:choices.append((root,('*',root,root)))
            for a in self.anchors:choices.extend(inverse(v,a,self.cap))
            for x,edge in choices:
                if x!=v and (x in self.paid or x in self.first):
                    patch={} if x in self.paid else {x:self.first[x]}
                    patch[v]=edge;break
            else:
                raise ValueError(f'GPU marked unreachable value {v} as reachable')
        self.cache[v]=patch
        return patch

    def cheapest(self,v):
        if v in self.cheaper:return self.cheaper[v]
        plan=self.get(v)
        if len(plan)>1:
            for a in self.paid:
                edge=next((edge for b,edge in inverse(v,a,self.cap) if b in self.paid),None)
                if edge is not None:
                    plan={v:edge}
                    break
        self.cheaper[v]=plan
        return plan

    def intermediates(self,v):
        if v not in self.second:
            options={}
            for a in self.paid:
                for h,edge in inverse(v,a,self.cap):
                    if h!=v and h in self.first and h not in self.paid:
                        options.setdefault(h,edge)
            for h,op in ((v//2,'+'),(isqrt(v),'*')):
                if arithmetic(op,h,h)==v and h in self.first and h not in self.paid:
                    options.setdefault(h,(op,h,h))
            self.second[v]=options
        return self.second[v]

    def join_plan(self,x,y):
        left=self.cheapest(x);right=self.cheapest(y)
        best=left|right
        if x==y or len(best)<2:return best
        # Charge each new value once across the two input branches.
        for u,base,v,tail in ((x,left,y,right),(y,right,x,left)):
            if not tail or not base or v in base:continue
            for h in base:
                edge=next((e for b,e in inverse(v,h,self.cap) if b in self.paid or b in base),None)
                if edge and len(base)+1<len(best):best=base|{v:edge}
        if len(best)==4:
            lx=self.intermediates(x);ry=self.intermediates(y)
            h=next((v for v in lx if v in ry and v not in (x,y)),None)
            if h is not None:
                best={h:self.first[h],x:lx[h],y:ry[h]}
        return best


def recover(table,target,match,paid,local=None,reprice=False):
    a,b,mode=match;patch={}
    def get(idx):
        v=int(table.values[idx])
        if v in paid or v in patch: return v
        if local is not None:
            for out,edge in local.get(v).items():
                patch.setdefault(out,edge)
            return v
        if idx<table.n0: raise ValueError('unpaid anchor in witness')
        l=get(int(table.left[idx]));r=get(int(table.right[idx]))
        op=OPERATORS[int(table.operators[idx])]
        if arithmetic(op,l,r)!=v: raise ValueError('invalid table witness')
        patch[v]=op,l,r
        return v
    if reprice and local is not None:
        x=int(table.values[a])
        y=int(table.values[b])
        patch=local.cheapest(x).copy() if mode==6 else local.join_plan(x,y)
    else:
        x=get(a)
    if mode!=6:
        if not reprice or local is None:y=get(b)
        edge=(('+',x,y),('-',x,y),('-',y,x),('*',x,y),('/',x,y),('/',y,x))[mode]
        if arithmetic(*edge)!=target: raise ValueError('invalid join witness')
        if target not in paid:patch.setdefault(target,edge)
    elif x!=target: raise ValueError('invalid direct hit')
    return patch


def retain_inputs(graph,regions,number):
    prepared=[]
    for root,private,paid,states in regions:
        expenses={};parents=set(graph[root][1:])
        for i,v in enumerate(private):
            _,a,b=graph[v]
            expenses[v]=(1<<i)|expenses.get(a,0)|expenses.get(b,0)
        # Retain private ancestors at different depths. Their entire actual
        # cost is charged when the completed graph is reduced below.
        candidates=[v for v in private if v!=root and expenses[v].bit_count()<=len(private)-3]
        picked=[]
        for level in range(1,number+1):
            if not candidates:break
            target=max(1,(len(private)-2)*level/(number+1))
            v=min(candidates,key=lambda x:(abs(expenses[x].bit_count()-target),
                       x not in parents,-x.bit_length(),x))
            picked.append(v);candidates.remove(v)
        prepared.append((root,private,sorted(set(paid)|set(picked)),states))
    return prepared


def joint_rewrites(p,graph,offers,proposals,group_limit=32):
    uses=Counter(v for _,a,b in graph.values() for v in {a,b})
    groups=defaultdict(list)
    for root,size,edits,removed in offers.values():
        changes=Counter()
        for v in removed|edits.keys():
            if v in graph:
                changes.subtract(set(graph[v][1:]))
            if v in edits:
                changes.update(set(edits[v][1:]))
        keys={(1,v) for v in edits if v not in graph}
        keys.update((2,v) for v,n in changes.items() if -uses[v]<n<0 and v not in p.seeds)
        for key in keys:groups[key].append((root,size,edits))
    checked=set()
    for group in groups.values():
        selected=[]
        per_root=Counter()
        for item in sorted(group,key=lambda e:(e[1],len(e[2]),e[0])):
            root=item[0]
            if per_root[root]>=6:continue
            selected.append(item)
            per_root[root]+=1
            if len(selected)>=group_limit:break
        for i,(root,_,left) in enumerate(selected):
            for other,_,right in selected[:i]:
                token=tuple(sorted((id(left),id(right))))
                if root==other or token in checked:continue
                checked.add(token)
                combined=[left|right]
                if any(v in right and right[v]!=edge for v,edge in left.items()):
                    combined.append(right|left)
                for patch in combined:
                    try:new=active_graph(p,graph|patch)
                    except (KeyError,ValueError):continue
                    if len(new)<len(graph):
                        proposals[tuple(sorted(patch.items()))]=len(new),patch
    return len(checked)


def private_regions(p,graph,maximum):
    if not maximum:return []
    pending=list(cases(p,graph,len(graph),0,True))
    # Deep cuts on the same chain can be almost identical. Price each
    # additional cut by its as-yet uncovered internal operations.
    covered=set()
    regions=[]
    while pending and len(regions)<maximum:
        chosen=max(range(len(pending)),key=lambda i:(
            len(set(pending[i][1])-covered)+.3*min(len(pending[i][1]),16),-i))
        region=pending.pop(chosen)
        regions.append(region)
        covered.update(region[1])
    return regions


def retired_regions(p,graph,maximum):
    """Remove every consumer of one previously shared, non-target value."""
    users=defaultdict(set)
    for out,(_,a,b) in graph.items():
        for v in {a,b}:users[v].add(out)
    choices=[]
    for h in graph.keys()-set(p.targets):
        roots=users[h]
        if not 2<=len(roots)<=min(6,maximum):continue
        kept,free=cut_many(p,graph,roots)
        removed=graph.keys()-kept.keys()
        paid=set(p.seeds)|free.keys()
        if h in paid:continue
        gain=len(removed)-len(roots)
        if gain<1:continue
        choices.append((gain/len(roots),h,roots,removed,paid))
    ranked=[]
    for score,h,roots,removed,paid in sorted(choices,key=lambda g:(-g[0],g[1]))[:48]:
        direct=sum(any(b in paid for a in paid for b,_ in inverse(t,a,p.limit)) for t in roots)
        ranked.append((score+direct/len(roots),h,roots,removed,paid))
    regions=[];used=set()
    for _,_,roots,removed,paid in sorted(ranked,key=lambda g:(-g[0],g[1])):
        if roots&used or len(regions)+len(roots)>maximum:continue
        for t in sorted(roots):
            cone=active_graph(p,graph,(t,))
            private=[v for v in cone if v in removed]
            regions.append((t,private,sorted(paid),{}))
        used.update(roots)
    return regions


def optimize(p,tape,engine,width,cuts,tails,capacity,alternate=False,two_tails=0,retain=0,table_builder=make_table,share=False,interior=0,reprice=False,witnesses=None,retire=0,shallow_first=False,repeated=0,quadratic=0,quadratic_offsets=0):
    graph=active_graph(p,first_recipes(p,tape))
    regions=list(cases(p,graph,cuts,0)) if cuts else []
    if interior:regions+=private_regions(p,graph,interior)
    if retire:regions+=retired_regions(p,graph,retire)
    if not regions:return tape,{}
    if retain:regions=retain_inputs(graph,regions,retain)
    anchors,masks,queries=query_set(p,graph,regions,width,tails,two_tails,4 if shallow_first else 5,repeated)
    ordinary_count=len(queries)
    if quadratic:
        from solvers.arithmetic.quadratic_suffix import additional_queries
        queries.extend(additional_queries(p,regions,queries,quadratic,quadratic_offsets))
    start=monotonic()
    table=table_builder(tuple(anchors),p.limit)
    table_seconds=monotonic()-start
    budgets=[max(0,len(regions[i][1])-len(path)-1) for i,_,path in queries] if engine.hubs else None
    hits,stats=engine.run(table,masks,queries,p.limit,capacity,alternate,budgets,shallow_first)
    stats.update(cuts=len(regions),anchors=len(anchors),table_seconds=table_seconds)
    paid=[set(row[2]) for row in regions];proposals={};offers={};tested=set()
    local=[LocalRecipes(anchors,s,p.limit) if alternate else None for s in paid]
    stats['quadratic_queries']=len(queries)-ordinary_count
    for index,((i,t,path),matches) in enumerate(zip(queries,hits)):
        root,private,_,_=regions[i]
        if index>=ordinary_count and t in paid[i]:matches=[None]
        for match in matches:
            patch={} if match is None else recover(table,t,match,paid[i],local[i],reprice)
            for out,edge in path:
                if out not in paid[i]:patch.setdefault(out,edge)
            if witnesses is not None:
                for out,(op,x,y) in patch.items():
                    if op in '+*' and x>y:x,y=y,x
                    witnesses.setdefault(out,set()).add((op,x,y))
            if root not in patch or len(patch)>=len(private)+(2 if share else 0): continue
            signature=tuple(sorted(patch.items()))
            if (root,signature) in tested:continue
            tested.add((root,signature))
            try: new=active_graph(p,graph|patch)
            except (ValueError,KeyError): continue
            if len(new)<len(graph):
                proposals[signature]=len(new),patch
            if share and len(new)<=len(graph)+1:
                edits={v:r for v,r in patch.items() if v in new and graph.get(v)!=r}
                if edits:
                    offers[(root,tuple(sorted(edits.items())))]=(root,len(new),edits,graph.keys()-new.keys())
    if share:
        singles=len(proposals)
        stats['joint_pairs']=joint_rewrites(p,graph,offers,proposals)
        stats.update(neutral_and_near_offers=len(offers),joint_additions=len(proposals)-singles)
    best=tape;current=graph
    for _,patch in sorted(proposals.values(),key=lambda e:e[0]):
        try: new=active_graph(p,current|patch)
        except (ValueError,KeyError):continue
        if len(new)>=len(best):continue
        candidate=schedule_like(p,best,new)
        if candidate is None or len(candidate)>len(new):
            alternate=compile_graph(p,new,attempts=3,recompute=True,schedule_width=4)
            if alternate is not None and (candidate is None or len(alternate)<len(candidate)):
                candidate=alternate
        if candidate is not None and len(candidate)<len(best):
            check(p,candidate);current=new;best=candidate
    stats.update(logical_candidates=len(proposals),saved=len(tape)-len(best))
    return best,stats


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for key in ('base','output'):ap.add_argument(key,type=Path)
    for key,n in [('width',80),('cuts',12),('interior',0),('tails',3),('two-tails',0),('retain',0),('capacity',10),('rows',32),('seed',81223)]:
        ap.add_argument('--'+key,type=int,default=n)
    ap.add_argument('--ids',type=Path)
    ap.add_argument('--alternate',action='store_true')
    ap.add_argument('--share',action='store_true',help='Combine repairs at distinct roots sharing intermediate work')
    ap.add_argument('--reprice',action='store_true',help='Choose a common intermediate for both sides of a join')
    ap.add_argument('--repeat-wins',action='store_true',help='Rebuild the table after each strict improvement until a pass ties')
    ap.add_argument('--native',action='store_true',help='Use the compiled two-step dictionary builder')
    a=ap.parse_args()
    if a.reprice and not a.alternate:ap.error('--reprice requires --alternate')
    if not 0<a.cuts+a.interior<=32 or min(a.width,a.capacity)<1 or min(a.cuts,a.interior,a.tails,a.two_tails,a.retain,a.rows)<0:ap.error('invalid search sizes')
    table_builder=make_table
    if a.native:
        native_path=ROOT/'work/creative/native-bank/native_table.py'
        if not native_path.with_suffix('.dll').is_file():ap.error('Build native_table.dll beside native_table.py first')
        spec=spec_from_file_location('native_table',native_path)
        module=module_from_spec(spec)
        spec.loader.exec_module(module)
        table_builder=module.native_table
    puzzles=read_puzzles('data/puzzles.csv');base=read_submission(a.base)
    if a.ids:
        ids=set(a.ids.read_text().split());selected=[p for p in puzzles if p.id in ids]
    else:
        selected=[p for p in puzzles if len(base[p.id])>=100]
        random.Random(a.seed).shuffle(selected)
    if a.rows:selected=selected[:a.rows]
    engine=PooledEngine(a.output.parent);stats={};wins={};start=monotonic()
    for p in selected:
        prog,r=optimize(p,base[p.id],engine,a.width,a.cuts,a.tails,a.capacity,a.alternate,a.two_tails,a.retain,table_builder,a.share,a.interior,a.reprice)
        if a.repeat_wins:
            last=len(base[p.id])
            totals=Counter(r)
            passes=1
            while len(prog)<last:
                last=len(prog)
                prog,more=optimize(p,prog,engine,a.width,a.cuts,a.tails,a.capacity,a.alternate,a.two_tails,a.retain,table_builder,a.share,a.interior,a.reprice)
                totals.update(more)
                passes+=1
            r=dict(totals,passes=passes)
        stats[p.id]=r
        if len(prog)<len(base[p.id]):
            wins[p.id]=prog;print(p.id,len(base[p.id])-len(prog),flush=True)
    write_submission(a.output,[p for p in puzzles if p.id in wins],wins)
    totals=dict(sum(map(Counter,stats.values()),Counter()))
    report=dict(parent=sha256(a.base),device=engine.gpu.device.name,width=a.width,tails=a.tails,two_tails=a.two_tails,retain=a.retain,alternate=a.alternate,native=a.native,share=a.share,
                cuts=a.cuts,interior=a.interior,reprice=a.reprice,repeat_wins=a.repeat_wins,capacity=a.capacity,seconds=monotonic()-start,totals=totals,rows=stats)
    atomic_text(a.output.with_suffix('.json'),json.dumps(report,indent=2)+'\n')
    print(len(stats),totals,flush=True)


if __name__=='__main__':main()
