"""Run the registered Atakan fixed-kernel comparisons on two separate parent lineages."""
import argparse
import csv
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=Path(os.getenv('SANTA_PROJECT','E:/Codex/Santa2026'))
GIT=Path(os.getenv('SANTA_CHECKOUT','E:/Codex/Santa2026-GitHub'))
OFFICIAL=Path(os.getenv('SANTA_PUZZLES',ROOT/'data/puzzles.csv'))
sys.path.insert(0,str(ROOT))
from elf import check,read_puzzles,write_submission
from checkpoint import independent_score
D=json.loads((HERE/'design.json').read_bytes())
def sha(b):return hashlib.sha256(b).hexdigest()
def frozen(prefix,fn,h):
    b=subprocess.check_output(['git','-C',str(GIT),'show',D['frozen']+':'+prefix+fn])
    assert sha(b)==h
    return {row['id']:row for row in csv.DictReader(io.StringIO(b.decode('utf-8-sig')))}
def trial(p,tape,arm):
    name=arm.split('-')[0];binary=HERE/'scratch'/name/('frontier.exe' if os.name=='nt' else 'frontier')
    head=[p.id,p.limit,len(p.seeds),len(p.targets),len(tape),*p.seeds,*p.targets]
    rows=[' '.join(map(str,head))]+[' '.join(map(str,step)) for step in tape]
    start=time.monotonic()
    run=subprocess.run([str(binary),*map(str,D['arms'][arm])],input='\n'.join(rows)+'\n',capture_output=True,text=True,check=True,timeout=370)
    lines=run.stdout.splitlines();h=lines[0].split();assert h[0]==p.id
    n,*stats=map(int,h[1:])
    out=tuple((words[0],*map(int,words[1:])) for l in lines[1:] for words in [l.split()])
    assert check(p,out)==n<=len(tape)
    names=['expanded','improving_branches','equal_branches','joint_children','peak_width','fused_children','uphill','escaped','coalitions']
    return {'arm':arm,'id':p.id,'before':len(tape),'after':n,'counters':dict(zip(names,stats)),'seconds':round(time.monotonic()-start,3)},out

def main():
    ap=argparse.ArgumentParser();ap.add_argument('phase');ap.add_argument('--jobs',type=int,default=4);args=ap.parse_args()
    assert sha(OFFICIAL.read_bytes())==D['puzzles_sha256']
    puzzles=read_puzzles(OFFICIAL);P={p.id:p for p in puzzles}
    eligible={}
    for idx,(lane,prefix) in enumerate([('independent',''),('public','public-assisted/')]):
        fr=D['parents'][prefix]
        p=frozen(prefix,'submission.csv',fr['sha256'])
        a=frozen(prefix,'origins.csv',fr['origins_sha256'])
        f={k:tuple(tuple(x) for x in json.loads(r['program'])) for k,r in p.items()}
        assert sum(map(len,f.values()))==fr['count']
        eligible[lane]=(f,a)
    store=HERE/'details.json';wins=HERE/'winning-tapes.json'
    records=json.loads(store.read_bytes()) if store.exists() else {}
    tapes={k:tuple(tuple(op) for op in t) for k,t in json.loads(wins.read_bytes()).items()} if wins.exists() else {}
    if args.phase in ('dev','hold'):
        ids=D[args.phase]; arms={k:list(D['arms']) for k in eligible}
    else:
        block=int(args.phase)
        ids=D['expand'][(block-1)*32:block*32]
        prev={'dev','hold'} if block==1 else {str(block-1)}
        arms={lane:[arm for arm in D['arms'] if any(r['lane']==lane and r['arm']==arm and r['phase'] in prev and r['before']>r['after'] for r in records.values())] for lane in eligible}
    def output():
        for which,(base,source_rows) in eligible.items():
            elected={}
            for key,u in tapes.items():
                r=records[key];i=r['id']
                if r['lane']==which and (i not in elected or (len(u),list(D['arms']).index(r['arm']))<(len(elected[i][1]),list(D['arms']).index(elected[i][0]['arm']))):
                    elected[i]=(r,u)
            write_submission(HERE/(which+'-shorter.csv'),[P[k] for k in sorted(elected)],{k:u for k,(r,u) in elected.items()})
            filename=HERE/(which+'-origins.csv')
            with filename.open('w',encoding='utf8',newline='') as out:
                w=csv.writer(out);w.writerow(('id','source','upstream_source','instructions'))
                for k,(r,u) in sorted(elected.items()):
                    row=source_rows[k];v=r['arm'].split('-')[0][1:]
                    label='Atakan Aldemir multiplier frontier v'+v+' style '+r['arm'].split('-')[1]+', kernel '+str(D['kernels'][v]['run'])+'; frozen parent '+row['source']
                    if row.get('upstream_source'):label+=' — '+row['upstream_source']
                    if v=='30':label+='; Atakan v15 common whole-graph dependency'
                    w.writerow([k,'Local '+which+' Atakan frontier replay',label,len(u)])
        store.write_text(json.dumps(records,indent=1)+'\n',encoding='utf8')
        wins.write_text(json.dumps(tapes,separators=(',',':'))+'\n',encoding='utf8')
    completed=0
    with ThreadPoolExecutor(args.jobs) as ex:
        futures={}
        for lane in eligible:
            f=eligible[lane][0]
            for k in ids:
                for arm in arms[lane]:
                    key=':'.join([lane,k,arm])
                    if key in records:continue
                    z=ex.submit(trial,P[k],f[k],arm);futures[z]=(key,lane)
        for z in as_completed(futures):
            key,lane=futures[z];r,t=z.result();r.update(lane=lane,phase=args.phase);records[key]=r;completed+=1
            if r['before']>r['after']:
                tapes[key]=t;output();print('WIN',lane,r['id'],r['arm'],r['before'],r['after'],flush=True)
            if completed%12==0:output();print(args.phase,completed,'/',len(futures),flush=True)
    output()
    print('phase',args.phase,'done',completed,flush=True)
if __name__=='__main__':main()
