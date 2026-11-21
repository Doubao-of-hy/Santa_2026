"""Replace two or more in-use constants with one previously unobserved integer."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import random
import sqlite3
import subprocess
import sys
import time
from elf import check,read_puzzles,read_submission,sha256,write_submission
from solvers.gpu.gpu_schedule import schedule_like
from graph import active_graph,compile_graph,first_recipes


def run_row(p,old,exe,tests,pairs,rounds,look,donor=None,reschedule=0):
    best=old;statistics=Counter()
    for _ in range(rounds):
        trace=active_graph(p,first_recipes(p,best))
        extra_trace=None if donor is None else active_graph(p,first_recipes(p,donor))
        counts=(len(trace),) if extra_trace is None else (len(trace),len(extra_trace))
        header=(p.id,p.limit,len(p.seeds),len(p.targets),*counts,*p.seeds,*p.targets)
        lines=[' '.join(map(str,header))]
        lines.extend(f"{v} {op} {a} {b}" for v,(op,a,b) in trace.items())
        if extra_trace is not None:
            lines.extend(f"{v} {op} {a} {b}" for v,(op,a,b) in extra_trace.items())
        run=subprocess.run([str(exe),str(tests),str(pairs),str(look)],input='\n'.join(lines)+'\n',text=True,capture_output=True,check=True)
        output=iter(run.stdout.splitlines());pid,candidates,offers,checked,n=next(output).split()
        if pid!=p.id:raise ValueError('unexpected native id')
        keys=(('clusters','grounded_searches','cluster_witnesses') if 'cluster' in exe.stem
              else ('computed_candidates','rescued_pairs_candidates','pairs_checked'))
        if 'staged' in exe.stem:keys=('optimistic_tips','tested_chains','triple_lanes')
        if 'pivot' in exe.stem:keys=('repairable_pivots','rooted_cases','rebuilt_pivots')
        if 'neutral' in exe.stem:keys=('expanded_states','distinct_sets','uphill_expansions')
        if 'donor' in exe.stem:keys=('deletion_waves','tested_bans','shorter_derivations')
        if 'labels' in exe.stem:keys=('forbidden_sets','grounded_sets','shorter_derivations')
        if 'donor-walk' in exe.stem:keys=('hybrid_starts','expanded_hybrids','shorter_derivations')
        if 'cooperative' in exe.stem:keys=('neutral_helpers','complementary_pairs','triple_lanes')
        if 'adaptive' in exe.stem:keys=('forbidden_triples','first_helpers','rooted_bridges')
        if 'monomial' in exe.stem:keys=('proposed_factors','cuts_considered','cuts_searched')
        for key,v in zip(keys,(candidates,offers,checked)):
            statistics[key]+=int(v)
        before=len(best)
        examined=set()
        for index in range(int(n)):
            g={}
            for k in range(int(next(output))):
                v,op,a,b=next(output).split();g[int(v)]=(op,int(a),int(b))
            key=frozenset(g.items())
            if key in examined or len(g)>=len(best):continue
            examined.add(key);statistics['strict_logical_candidates']+=1
            g=active_graph(p,g);tape=schedule_like(p,best,g)
            if tape is None or len(tape)>len(g):
                other=compile_graph(p,g,attempts=5,recompute=True,schedule_width=8)
                if other is not None and (tape is None or len(other)<len(tape)):tape=other
            if reschedule and (tape is None or len(tape)>len(g)):
                from reorder import peak,schedule
                pressure=peak(p,g)
                _,moved,layout=schedule((p.id,p,best,pressure,pressure,g,reschedule,1051+index*59))
                if moved is not None and (tape is None or len(moved)<len(tape)):tape=moved
                if tape is None or len(tape)>len(g):
                    from operand_allocation import synthesize
                    values=list(g);ordered={values[i]:g[values[i]] for i in layout['ordered_node_indices']}
                    alternative,*_=synthesize(p,ordered,reschedule)
                    if alternative is not None and (tape is None or len(alternative)<len(tape)):tape=alternative
                statistics['reordered_candidates']+=1
                statistics['schedule_recoveries']+=int(tape is not None and len(tape)<len(best))
            if tape is not None and len(tape)<len(best):check(p,tape);best=tape
        if next(output,None) is not None:raise ValueError("trailing native trace")
        if before==len(best):break
    statistics['saved']=len(old)-len(best);statistics['wins']=int(len(old)>len(best))
    return p.id,best,dict(statistics)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('base',type=Path);ap.add_argument('output',type=Path)
    ap.add_argument('--exe',type=Path,default=Path('work/gpu/value-exchange.exe'))
    ap.add_argument('--donor',type=Path,help='Second derivation per puzzle for donor-delete mode')
    ap.add_argument('--reschedule',type=float,default=0,help='Seconds per rejected candidate for dependency-block reordering')
    ap.add_argument('--rows',type=int,default=0);ap.add_argument('--jobs',type=int,default=3)
    ap.add_argument('--tests','--groups',type=int,default=48);ap.add_argument('--pairs','--width',type=int,default=24)
    ap.add_argument('--rounds',type=int,default=2);ap.add_argument('--seed',type=int,default=41993)
    ap.add_argument('--look','--depth',type=int,default=0,help='Number of neighboring graphs, or helper depth in cluster mode')
    a=ap.parse_args();puzzles=read_puzzles('data/puzzles.csv');pg=read_submission(a.base)
    if a.reschedule:
        source=Path(__file__).resolve().parents[2]/'work/creative/pressure'
        if not (source/'order-search.exe').is_file():raise ValueError('missing pressure solver')
        sys.path.insert(0,str(source))
    select=[p for p in puzzles if p.id in pg];random.Random(a.seed).shuffle(select)
    if a.rows:select=select[:a.rows]
    donor_sha=sha256(a.donor) if a.donor else None
    donors=read_submission(a.donor) if a.donor else {}
    if a.donor and any(p.id not in donors for p in select):raise ValueError('donor missing a selected puzzle')
    cfg=','.join(map(str,(sha256(a.exe),sha256(Path(__file__)),a.tests,a.pairs,a.rounds,a.look,donor_sha,a.reschedule)))
    db=sqlite3.connect(a.output.with_suffix('.sqlite'))
    db.execute('create table if not exists trials (digest text primary key,id text,tape text,stats text)')
    out={};total=Counter();t0=time.monotonic()
    import hashlib
    def save():
        if not out:return
        write_submission(a.output,[p for p in puzzles if p.id in out],out)
        r=dict(total,rows=len(out),base_sha=sha256(a.base),seconds=round(time.monotonic()-t0,3),config=cfg)
        if donor_sha:r['donor_sha']=donor_sha
        a.output.with_suffix('.json').write_text(json.dumps(r,indent=2));print(len(out),len(select),total['saved'],flush=True)
    with ThreadPoolExecutor(a.jobs) as pool:
        tasks={}
        for p in select:
            key=hashlib.sha256(repr((cfg,p,pg[p.id])).encode()).hexdigest()
            hit=db.execute('select tape,stats from trials where digest=?',(key,)).fetchone()
            if hit:
                out[p.id]=tuple(map(tuple,json.loads(hit[0])));total.update(json.loads(hit[1]))
            else:
                task=pool.submit(run_row,p,pg[p.id],a.exe.resolve(),a.tests,a.pairs,a.rounds,a.look,donors.get(p.id),a.reschedule)
                tasks[task]=key
        for task in as_completed(tasks):
            pid,tape,st=task.result();out[pid]=tape;total.update(st)
            db.execute('insert or replace into trials values(?,?,?,?)',(tasks[task],pid,json.dumps(tape),json.dumps(st)));db.commit()
            if len(out)%12==0:save()
    save();db.close()


if __name__=='__main__':main()
