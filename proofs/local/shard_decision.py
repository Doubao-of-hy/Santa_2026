"""Checkpoint each exact helper-budget decision and any replayable witness."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess

from elf import check, read_puzzles, sha256, write_submission
from checkpoint import atomic_text
from tiny import encode


def decide(exe,p,h,limit,i,n,j,m,incremental=False,third=0,third_total=1,pair_bound=False):
    stream=' '.join(map(str,(p.limit,len(p.seeds),len(p.targets),h,limit,*p.seeds,*p.targets)))+'\n'
    mode=["--pair-bound"] if pair_bound else ["--incremental"] if incremental else []
    args=[str(exe),*mode,str(i),str(n)]
    if m>1 or third_total>1:args.extend((str(j),str(m)))
    if third_total>1:args.extend((str(third),str(third_total)))
    rows=subprocess.run(args,input=stream,text=True,check=True,capture_output=True).stdout.splitlines()
    status,nodes,terminal=rows[0].split()
    if status not in ('UNSAT','FOUND','UNKNOWN'):raise ValueError(rows)
    witness=None
    if status=='FOUND':
        seq=tuple(map(int,rows[1].split()))
        seeds=tuple(dict.fromkeys(p.seeds))
        if seq[:len(seeds)]!=seeds:raise ValueError('bad initial values')
        witness=encode(p,seq[len(seeds):])
        if check(p,witness)>len(set(p.targets)-set(p.seeds))+h:raise ValueError('bad witness')
    elif len(rows)!=1:raise ValueError('extra native output')
    return status,int(nodes),int(terminal),witness


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('exe',type=Path);ap.add_argument('out',type=Path);ap.add_argument('tasks',nargs='+')
    ap.add_argument('--shards',type=int,default=12);ap.add_argument('--subshards',type=int,default=1)
    ap.add_argument('--nodes',type=int,default=50000000);ap.add_argument('--jobs',type=int,default=4)
    ap.add_argument('--incremental',action='store_true',help="Use reversible incremental one-step reachability")
    ap.add_argument('--pair-bound',action='store_true',help="Check the combined coverage of the last two helpers")
    a=ap.parse_args();binary=a.exe.resolve();data=Path('data/puzzles.csv');puzzles=read_puzzles(data)
    input_hash=sha256(data)
    ps={p.id:p for p in puzzles};wanted={k:int(h) for k,h in (x.split(':') for x in a.tasks)}
    settings=(sha256(binary),a.shards,a.subshards,a.nodes)
    if a.incremental:settings+=('incremental',)
    if a.pair_bound:settings+=('pair-bound',)
    db=sqlite3.connect(a.out.with_suffix('.sqlite'))
    db.execute('CREATE TABLE IF NOT EXISTS branches(k TEXT PRIMARY KEY,result TEXT)')
    done={pid:{} for pid in wanted}
    def summary():
        record={};programs={}
        for pid,branches in done.items():
            if not branches:continue
            statuses=[r[0] for r in branches.values()]
            complete=len(statuses)==a.shards*a.subshards and all(x=='UNSAT' for x in statuses)
            h=wanted[pid];p=ps[pid]
            outcome='UNSAT' if complete else ('FOUND' if 'FOUND' in statuses else 'INCOMPLETE')
            record[pid]={'helpers':h,'status':outcome,'finished':len(statuses),'unknown':statuses.count('UNKNOWN'),
                         'total_branches':a.shards*a.subshards,'nodes':sum(r[1] for r in branches.values()),
                         'terminal_candidates':sum(r[2] for r in branches.values()),
                         'certified_lower':len(set(p.targets)-set(p.seeds))+h+1 if complete else None,
                         'branches':[{'first':i,'second':j,'status':r[0],'nodes':r[1],'terminals':r[2]}
                                     for (i,j),r in sorted(branches.items())]}
            if 'FOUND' in statuses:
                candidates=[tuple(map(tuple,r[3])) for r in branches.values() if r[3] is not None]
                programs[pid]=min(candidates,key=len);check(p,programs[pid])
        if programs:write_submission(a.out.with_suffix('.csv'),[p for p in puzzles if p.id in programs],programs)
        atomic_text(a.out,json.dumps({'puzzles_sha256':input_hash,'binary_sha256':settings[0],
                                     'shards':a.shards,'subshards':a.subshards,
                                     'node_limit_per_shard':a.nodes,'incremental':a.incremental or a.pair_bound,
                                     'pair_bound':a.pair_bound,'instances':record},indent=2)+'\n')
    with ThreadPoolExecutor(a.jobs) as pool:
        jobs={}
        for i in range(a.shards):
            for j in range(a.subshards):
                for pid,h in wanted.items():
                    key=hashlib.sha256(repr((ps[pid],h,settings,i,j)).encode()).hexdigest()
                    old=db.execute('SELECT result FROM branches WHERE k=?',(key,)).fetchone()
                    if old:done[pid][i,j]=json.loads(old[0]);continue
                    future=pool.submit(decide,binary,ps[pid],h,a.nodes,i,a.shards,j,a.subshards,a.incremental,pair_bound=a.pair_bound)
                    jobs[future]=(pid,i,j,key)
        for future in as_completed(jobs):
            pid,i,j,key=jobs[future];res=future.result();done[pid][i,j]=res
            db.execute('INSERT OR REPLACE INTO branches VALUES(?,?)',(key,json.dumps(res)));db.commit()
            summary()
    summary();db.close()
    print(a.out.read_text(encoding='utf8'))


if __name__=='__main__':main()
