"""Recover rejected arithmetic candidates using block reordering and operand rollback."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from elf import check,read_puzzles,read_submission,sha256,write_submission
from graph import active_graph,first_recipes

ROOT=Path(__file__).resolve().parents[2]
PRESSURE=ROOT/'work/creative/pressure'
sys.path.insert(0,str(PRESSURE))
from reorder import peak,schedule
from operand_allocation import synthesize
from rollback import optimize

def regenerate(p,old,donor,exe):
    graph_list=[active_graph(p,first_recipes(p,old))]
    if donor is not None:graph_list.append(active_graph(p,first_recipes(p,donor)))
    lines=[' '.join(map(str,(p.id,p.limit,len(p.seeds),len(p.targets),*map(len,graph_list),*p.seeds,*p.targets)))]
    for g in graph_list:lines.extend(f'{v} {o} {l} {r}' for v,(o,l,r) in g.items())
    params=['6','4','3'] if donor is not None else ['6','3','7']
    call=subprocess.run([str(exe),*params],input='\n'.join(lines)+'\n',text=True,capture_output=True,check=True)
    out=iter(call.stdout.splitlines());n=int(next(out).split()[-1]);graphs=[];seen=set()
    for _ in range(n):
        g={}
        for _ in range(int(next(out))):
            v,o,l,r=next(out).split();g[int(v)]=(o,int(l),int(r))
        g=active_graph(p,g);signature=frozenset(g.items())
        if signature in seen:continue
        seen.add(signature);pressure=peak(p,g);graphs.append((p.id,pressure,pressure,g))
    return graphs

def run(item):
    p,old,donor,exe,seconds,mode,physical,window,partition,duplicate,bank_rounds=item;graphs=regenerate(p,old,donor,exe)
    best=old;method=None;lowest=min((len(g) for _,_,_,g in graphs),default=len(old))
    failures=[];arrangements=[]
    for i,(_,start,_,g) in enumerate(graphs):
        _,tape,out=schedule((p.id,p,old,start,start,g,seconds,1867+41*i))
        if tape is not None and len(tape)<len(best):best=tape;method='reordered blocks'
        if len(best)<=lowest:break
        values=list(g);arranged={values[j]:g[values[j]] for j in out['ordered_node_indices']}
        arrangements.append(arranged)
        tape,_,__,___=synthesize(p,arranged,.6)
        if tape is not None and len(tape)<len(best):best=tape;method='reordered blocks and reselected operands'
        if len(best)<=lowest:break
        failures.append((out['reordered_peak'],i))
    if mode and len(best)>lowest and failures:
        ranked=sorted(failures);chosen=[graphs[i] for _,i in ranked[:mode]]
        tape,how,_=optimize(p,old,chosen)
        if len(tape)<len(best):best=tape;method=how
    if physical and len(best)>lowest:
        from solvers.registers.physical_subprogram import arrangement,bank,skeleton,solve
        original=skeleton(p,old);supplied={}
        for _,_,_,g in graphs:supplied.update(g)
        ways=bank(p,original,supplied)
        raw=original|supplied;seen=set()
        for guide in [original,*arrangements]:
            for variant in (0,1):
                order=arrangement(p,guide,raw,ways,variant)
                if tuple(order) in seen:continue
                seen.add(tuple(order))
                tape,status,_=solve(p,best,guide,ways,order,physical)
                if len(tape)<len(best):best=tape;method='optional values and register lifetimes'
                if len(best)<=lowest:break
            if len(best)<=lowest:break
    if window and len(best)>lowest:
        from solvers.registers.register_windows import optimize as reorder_windows
        for graph in arrangements:
            if len(graph)>=len(best):continue
            tape,_=reorder_windows(p,graph,window,rounds=4)
            if tape is not None and len(tape)<len(best):best=tape;method='exact local register cuts'
            if len(best)<=lowest:break
    if partition and len(best)>lowest:
        from solvers.registers.register_partition import hierarchical
        for k,graph in enumerate(arrangements):
            if len(graph)>=len(best):continue
            for h in range(3):
                sequence=hierarchical(p,graph,partition,1841+3*k+h)
                initial=peak(p,sequence)
                _,tape,layout=schedule((p.id,p,old,initial,initial,sequence,1.5,7901+19*k+h))
                if tape is None or len(tape)>len(sequence):
                    values=list(sequence);reordered={values[i]:sequence[values[i]] for i in layout['ordered_node_indices']}
                    changed,*_=synthesize(p,reordered,.9)
                    if changed is not None and (tape is None or len(changed)<len(tape)):tape=changed
                if tape is not None and len(tape)<len(best):best=tape;method='recursive minimum-register cuts'
                if len(best)<=lowest:break
            if len(best)<=lowest:break
    if duplicate and len(best)>lowest+1:
        from solvers.registers.register_recompute import optimize as split_ranges
        for k,graph in enumerate(sorted(arrangements,key=lambda g:peak(p,g))[:4]):
            tape=split_ranges(p,graph,len(best),duplicate,30901+137*k)
            if tape is not None and len(tape)<len(best):best=tape;method='duplicate and jointly reorder live ranges'
            if len(best)<=lowest+1:break
    if bank_rounds and len(best)>lowest:
        from solvers.registers.register_livebank import solve as living
        for k,graph in enumerate(sorted(arrangements,key=lambda g:peak(p,g))):
            if len(graph)>=len(best):continue
            tape,_=living(p,graph,bank_rounds,24799+131*k)
            if tape is not None and len(tape)<len(best):best=tape;method='flexible recipes under checked evictions'
            if len(best)<=lowest:break
    check(p,best)
    return p.id,best,dict(before=len(old),after=len(best),minimum_captured_graph=lowest,unique_graphs=len(graphs),method=method)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('lane',choices=['trusted','independent']);ap.add_argument('output',type=Path)
    ap.add_argument('--jobs',type=int,default=2);ap.add_argument('--seconds',type=float,default=.6)
    ap.add_argument('--rollback',type=int,default=1,help='Number of the most promising remaining graphs')
    ap.add_argument('--physical',type=float,default=0,help='Seconds per joint value and register-lifetime model')
    ap.add_argument('--window',type=float,default=0,help='Seconds per exact chronological register window')
    ap.add_argument('--partition',type=float,default=0,help='Seconds per hierarchical cut')
    ap.add_argument('--duplicate',type=float,default=0,help='Seconds per duplicated live-range candidate')
    ap.add_argument('--bank-rounds',type=int,default=0,help='Randomized live-bank schedules per rejected value graph')
    ap.add_argument('--prior',type=Path,help='Retrieve only puzzles still above their captured logic minimum')
    ap.add_argument('--experiment',choices=['graft-walk','forced-active'],default='graft-walk')
    args=ap.parse_args();lane=args.lane;graft=args.experiment=='graft-walk'
    tag='lineage-final' if graft else 'graft-final';base=ROOT/f'work/gpu/domain-base/{tag}-{lane}.csv'
    donor=(ROOT/'work/gpu/domain-base'/('lineage-final-independent.csv' if lane=='trusted' else 'independent.csv')) if graft else None
    exe=ROOT/'work/gpu'/('donor-walk.exe' if graft else 'neutral-active.exe');src=ROOT/f'work/gpu/{args.experiment}-{lane}.sqlite'
    receipts=json.loads(src.with_suffix('.json').read_text())
    donor_sha=sha256(donor) if donor else None
    assert receipts['base_sha']==sha256(base) and receipts.get('donor_sha')==donor_sha
    with sqlite3.connect(src) as db:
        data={k:json.loads(r) for k,r in db.execute('select id,stats from trials')}
    metric='shorter_derivations' if graft else 'strict_logical_candidates'
    rows={i for i,stats in data.items() if stats.get(metric) and not stats['saved']}
    if args.prior:
        previous=json.loads(args.prior.read_text())['results']
        rows={i for i in rows if i in previous and previous[i]['after']>previous[i]['minimum_captured_graph']}
    ps=read_puzzles(ROOT/'data/puzzles.csv');parents=read_submission(base);donors=read_submission(donor) if donor else {}
    selected=[p for p in ps if p.id in rows];out={};report={}
    with ThreadPoolExecutor(args.jobs) as pool:
        for i,tape,info in pool.map(run,[(p,parents[p.id],donors.get(p.id),exe,args.seconds,args.rollback,args.physical,args.window,args.partition,args.duplicate,args.bank_rounds) for p in selected]):
            out[i]=tape;report[i]=info
            write_submission(args.output,[p for p in selected if p.id in out],out)
            args.output.with_suffix('.json').write_text(json.dumps(dict(base_sha=sha256(base),donor_sha=donor_sha,
                rows=len(report),wins=sum(v['before']>v['after'] for v in report.values()),
                saved=sum(v['before']-v['after'] for v in report.values()),results=report),indent=2))
            print(i,info['before'],info['minimum_captured_graph'],info['after'],flush=True)
if __name__=='__main__':main()
