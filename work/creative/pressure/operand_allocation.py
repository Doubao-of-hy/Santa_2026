"""Choose numerically equivalent operands to make a fixed short value order schedulable."""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json

from reorder import HERE,ROOT,rejected,peak
from elf import check,read_puzzles,read_submission,write_submission
from graph import active_graph,_allocate
from crossover_lns import load_solver

def rewrites(p,seq):
    values=list(seq);seeds=set(p.seeds);times={v:i for i,v in enumerate(values)}|{v:-1 for v in seeds}
    choices={v:{frozenset(r[1:]):r} for v,r in seq.items()};atoms=list(seeds)+values
    for j,a in enumerate(atoms):
        for b in atoms[:j+1]:
            early=max(times[a],times[b]);small,large=sorted((a,b));operands=frozenset((a,b))
            for v,r in ((a+b,('+',a,b)),(large-small,('-',large,small)),(a*b,('*',a,b)),(large//small if large%small==0 else 0,('/',large,small))):
                if times.get(v,-1)>early:choices[v].setdefault(operands,r)
    return {v:list(opts.values()) for v,opts in choices.items()}

def synthesize(p,seq,seconds):
    cp=load_solver();m=cp.CpModel();vs=list(seq);where={v:i for i,v in enumerate(vs)}|{v:-1 for v in p.seeds}
    ways=rewrites(p,seq);flags={};possible=defaultdict(lambda:defaultdict(list));mandatory=defaultdict(set)
    for i,v in enumerate(vs):
        opts=ways[v];common=set.intersection(*(set(r[1:]) for r in opts))
        for a in common:mandatory[a].add(i)
        if len(opts)==1:continue
        bits=[m.new_bool_var('') for r in opts];m.add_exactly_one(bits);flags[v]=bits
        for ix,(r,b) in enumerate(zip(opts,bits)):
            m.add_hint(b,int(ix==0))
            for a in set(r[1:])-common:possible[a][i].append(b)
    constraints=[[] for _ in vs];constants=[1]*len(vs)
    for v,birth in where.items():
        last_mand=max(mandatory[v],default=-1);last_any=max([last_mand,*possible[v].keys()]);later=None
        # Count previously created operands that remain live after this write.
        # The current result always needs exactly one destination register.
        for t in range(last_any-1,birth,-1):
            if t<last_mand:constants[t]+=1;continue
            new=possible[v].get(t+1,[])
            if new:
                if later is not None:new=[*new,later]
                if len(new)==1:later=new[0]
                else:
                    fresh=m.new_bool_var('');m.add_max_equality(fresh,new);later=fresh
            if later is not None:constraints[t].append(later)
    for fixed,optional in zip(constants,constraints):
        if fixed>p.registers:return None,'forced-live',len(flags),max(constants)
        if fixed+len(optional)>p.registers:m.add(sum(optional)<=p.registers-fixed)
    solver=cp.CpSolver();solver.parameters.max_time_in_seconds=seconds;solver.parameters.num_search_workers=1;solver.parameters.stop_after_first_solution=True
    status=solver.solve(m)
    if status not in (cp.OPTIMAL,cp.FEASIBLE):return None,solver.status_name(status),len(flags),max(constants)
    graph={v:ways[v][next((ix for ix,bit in enumerate(flags.get(v,[])) if solver.value(bit)),0)] for v in vs}
    if peak(p,graph)>p.registers:raise ValueError('register model mismatch')
    trimmed=active_graph(p,graph);trimmed={v:r for v,r in graph.items() if v in trimmed}
    tape=_allocate(p,trimmed,False,0,fixed_order=True)
    if tape is None or check(p,tape)!=len(trimmed):raise ValueError('emission failure')
    return tape,'schedulable',len(flags),max(constants)

def run(job):
    p,graph,orig,order=job;vs=list(graph)
    seq={vs[ix]:graph[vs[ix]] for ix in order}
    return p.id,len(graph),orig,peak(p,seq),synthesize(p,seq,2.0)

def main():
    ps=read_puzzles(ROOT/'data/puzzles.csv');by={p.id:p for p in ps};base=read_submission(next(HERE.glob('public-????????????.csv')))
    suggestions=json.loads((HERE/'order-report.json').read_text());seqs={r['graph_sha256']:r.get('ordered_node_indices') for rows in suggestions.values() for r in rows};jobs=[]
    for path in sorted(HERE.glob('rejected-*.txt')):
        for i,orig,_,g in rejected(path):
            h=sha256(json.dumps(sorted(g.items())).encode()).hexdigest();orders=[list(range(len(g)))]
            if seqs.get(h):orders.append(seqs[h]);
            for o in orders:jobs.append((by[i],g,orig,o))
    out={};report=defaultdict(list)
    with ThreadPoolExecutor(3) as ex:
        for i,n,orig,final,(tape,method,count,forced) in ex.map(run,jobs):
            report[i].append([n,orig,final,method,count,forced,len(tape) if tape else None]);print(i,report[i][-1],flush=True)
            if tape and len(tape)<len(out.get(i,base[i])):out[i]=tape
    (HERE/'operand-report.json').write_text(json.dumps(report),encoding='ascii')
    if out:write_submission(HERE/'operand-recovery.csv',[p for p in ps if p.id in out],out)

if __name__=='__main__':main()
