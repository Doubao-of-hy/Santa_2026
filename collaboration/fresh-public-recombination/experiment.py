"""Freeze the public merge cohort, compare the same incremental search with alternate original tapes."""
import argparse
import csv
import hashlib
import io
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE=Path(__file__).resolve().parent
PROJECT=Path(os.getenv('SANTA_PROJECT','E:/Codex/Santa2026'))
CHECKOUT=Path(os.getenv('SANTA_CHECKOUT','E:/Codex/Santa2026-GitHub'))
DONORS=Path(os.getenv('SANTA_DONORS',PROJECT/'work/creative/resume-135077'))
BIN=Path(os.getenv('SANTA_BIN',PROJECT/'work/virtual/good10-wang-diff'))
sys.path.insert(0,str(PROJECT))
from elf import check,read_puzzles,replay,write_submission
from checkpoint import independent_score

CURRENT='62378d6b929bb436f46cb85c2cff80764c58af2d'
EARLIER='472b715858b74910ca9b1eafcbea4d64183fa09d'
ROUNDS=360
LABELS=['62378d6 public','GoodPJW v10 our_programs','GoodPJW v10 public_frontier','Hanif v24','Asterios v119','Rudolph v68','472b715 public']
FILES=[None,'good10/our_programs-normalized.csv','good10/public_frontier-normalized.csv','hanif24/programs.csv','asterios119/programs.csv','rudolph68/programs.csv',None]
MODES=['single','multi']
EXES=[BIN/('inc-local.exe' if os.name=='nt' else 'inc-local'),BIN/('inc-good.exe' if os.name=='nt' else 'inc-good')]
def digest(blob):
    return hashlib.sha256(blob).hexdigest()
def gitfile(rev,name):
    return subprocess.check_output(['git','-C',str(CHECKOUT),'show',f'{rev}:{name}'])
def donor_blob(rel):
    normalized=DONORS/rel
    if normalized.is_file():
        return normalized.read_bytes()
    raw={
        'good10/our_programs-normalized.csv':'good10/our_programs.csv',
        'good10/public_frontier-normalized.csv':'good10/public_frontier.csv',
        'hanif24/programs.csv':'hanif24/submission.csv',
        'asterios119/programs.csv':'asterios119/best_programs.csv',
        'rudolph68/programs.csv':'rudolph68/rudolph_programs.csv',
    }
    with (DONORS/raw[rel]).open(encoding='utf-8-sig',newline='') as source:
        rows={r['id']:json.loads(r['program']) for r in csv.DictReader(source)}
    out=io.StringIO(newline='')
    writer=csv.writer(out,lineterminator='\n');writer.writerow(['id','program'])
    for i,t in sorted(rows.items()):
        writer.writerow([i,json.dumps(t,separators=(',',':'))])
    return out.getvalue().encode('utf8')


def records(blob):
    return {row['id']:row for row in csv.DictReader(io.StringIO(blob.decode('utf-8-sig')))}
def canon(p,t):
    return frozenset((w,op,min(a,b),max(a,b)) if op in '+*' else (w,op,a,b) for w,op,a,b in replay(p,t))
def compact(rows,p):
    b=rows[p.id]['program']
    return tuple(tuple(x) for x in json.loads(b))
def get():
    source_blobs=[gitfile(CURRENT,'public-assisted/submission.csv')]+[donor_blob(f) for f in FILES[1:-1]]+[gitfile(EARLIER,'public-assisted/submission.csv')]
    attrs=[records(gitfile(r,'public-assisted/origins.csv')) for r in [CURRENT,EARLIER]]
    parents=[records(b) for b in source_blobs]
    ab=records((DONORS/'asterios119/best_programs.csv').read_bytes())
    docs=json.loads(gitfile(CURRENT,'collaboration/evidence/four-source-134325.json'))
    # Use the earlier and merged programs to recover this exact published cohort.
    # Recombination row 0152 is a separate contribution from another experiment.
    ids=sorted(i for i in parents[0] if i!='scored_0152' and len(json.loads(parents[0][i]['program']))<len(json.loads(parents[-1][i]['program'])))
    assert len(ids)==50
    ps={p.id:p for p in read_puzzles(PROJECT/'data/puzzles.csv')}
    all_s={}; groups={}
    def credit(j,i):
        if j in (0,6):return attrs[0 if j==0 else 1][i]['upstream_source']
        if j in (1,2):return f'{LABELS[j]}, by goodpjw2008. Apache-2.0. Includes public portfolio contributors, Wang Jakie and E-Max AI (RoyalAceCat). No per-row upstream author is supplied. See GoodPJW-v10-NOTICE.md and GoodPJW-v10-public-sources.json.'
        if j==3:return 'Hanif Noer Rofiq, Kaggle release 24 (Apache-2.0); includes credited public portfolio solvers; see Hanif-v24-NOTICE.md.'
        if j==4:return 'Asterios Panoras, Kaggle release 119 (Apache-2.0). Original row credit: '+ab[i]['source']
        return 'Alex Chilton, Rudolph Kaggle release 68 (CC0), and its cited public portfolio contributors. No row-specific upstream author is supplied.'
    for i in ids:
        p=ps[i];tapes=[compact(t,p) for t in parents]
        keys=[canon(p,t) for t in tapes]
        seen={keys[0]}
        # At most four distinct donor DAGs, ordered by their difference from the fresh merged trace.
        ix=[0]
        for j in sorted(range(1,len(tapes)),key=lambda j:(-len(keys[j]^keys[0]),len(tapes[j]),j)):
            if len(tapes[j])<=len(tapes[0])+6 and keys[j] not in seen and len(ix)<5:
                seen.add(keys[j]);ix.append(j)
        all_s[i]=[tapes[j] for j in ix]
        groups[i]=[{'source':LABELS[j],'length':len(tapes[j]),'credit':credit(j,i),'program_sha256':digest(json.dumps(tapes[j],separators=(',',':')).encode())} for j in ix]
    design={'frozen_commit':CURRENT,'frozen_score':134324,'cohort':'All 50 four-source release improvements over 472b715 in 62378d6. Exclude separately acquired 0152. No length filtering on this cohort.',
            'rows':groups,'program_files_sha256':dict(zip(LABELS,map(digest,source_blobs))),'public_origins_sha256':digest(gitfile(CURRENT,'public-assisted/origins.csv')),'official_sha256':digest((PROJECT/'data/puzzles.csv').read_bytes()),'sources':docs['sources'],
            'arms':{'single':'Wang Jakie original incremental, merged public row only.','multi':'Same incremental algorithm with at most four distinct external original tapes admitted into the crossover pool, per E-Max AI and GoodPJW.'},
            'donor_selection':'Among the five current credited source files and the pre-merge public row, keep at most four distinct canonical arithmetic graphs of length at most incumbent + 6, preferring maximal symmetric edge difference versus incumbent, then shortest length, then listed source order.',
            'primary':'Count physically replayed shorter programs per arm, paired per row, and summed savings. Use one shorter valid program per row; ties go to single. Record CPU wall time separately; allocation is equal in algorithmic round counts.',
            'budget':'360 rounds per row and arm, seed 3047830 + integer scored suffix, max_neighbors 0; all 50 rows both arms. When no alternative exists, multi is the identical-input implementation check.',
            'binary_sha256':{m:digest(f.read_bytes()) for m,f in zip(MODES,EXES)}}
    return design,all_s,ps

from functools import lru_cache
@lru_cache(maxsize=2)
def origin_table(revision):
    return records(gitfile(revision,'public-assisted/origins.csv'))


def parent_label(info,key):
    source=info['source']
    if source in (LABELS[0],LABELS[-1]):
        revision=CURRENT if source==LABELS[0] else EARLIER
        published=origin_table(revision)[key]
        return source+' / '+published['source']+' — '+info['credit']
    return source+' — '+info['credit']


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['register','run'])
    parser.add_argument('--jobs',type=int,default=3)
    parser.add_argument('--rebuilt',action='store_true',help='Accept recompiled native code with a different binary hash; keep every input fingerprint and search parameter fixed.')
    args=parser.parse_args()
    design,ts,ps=get(); config=HERE/'design.json'
    if args.action=='register':
        assert not config.exists()
        config.write_text(json.dumps(design,indent=1,ensure_ascii=False)+'\n',encoding='utf8')
        print('design',digest(config.read_bytes()),'multi rows',sum(len(v)>1 for v in ts.values()), 'sources',design['program_files_sha256']);return
    expected=json.loads(config.read_bytes())
    if args.rebuilt:
        print('Recompiled executables:',design['binary_sha256'],flush=True)
        expected['binary_sha256']=design['binary_sha256']
    assert expected==design
    def trial(key,arm):
        idx=MODES.index(arm);p=ps[key];plans=ts[key] if idx else ts[key][:1]
        seed=3047830+int(key[-4:])
        fields=[[1],[p.limit,p.registers,ROUNDS,0,seed],[len(p.seeds),*p.seeds],[len(p.targets),*sorted(p.targets)],[len(plans)]]
        for t in plans:fields.append([len(t)]);fields.extend(t)
        data='\n'.join(' '.join(map(str,r)) for r in fields)+'\n';start=time.monotonic()
        words=subprocess.run([str(EXES[idx])],input=data,text=True,check=True,capture_output=True,timeout=500).stdout.split()
        n=int(words[0])
        assert len(words)==1+4*n
        t=tuple((words[k],int(words[k+1]),int(words[k+2]),int(words[k+3])) for k in range(1,len(words),4))
        assert check(p,t)==n<=len(ts[key][0])
        return {'id':key,'arm':arm,'seed':seed,'before':len(ts[key][0]),'after':n,'seconds':round(time.monotonic()-start,3),'parents':len(plans)},t
    best={};outcomes=[]
    def publish():
        winprog={k:t for k,(r,t) in sorted(best.items())}
        write_submission(HERE/'shorter.csv',[ps[k] for k in winprog],winprog)
        with (HERE/'shorter.origins.csv').open('w',encoding='utf8',newline='') as f:
            w=csv.writer(f);w.writerow(['id','source','upstream_source','instructions'])
            for k,(r,t) in sorted(best.items()):
                refs=design['rows'][k][:r['parents']]
                tool='Wang Jakie, original incremental recipe search (Apache-2.0), Kaggle kernel 371736767'
                if r['arm']=='multi':tool+='; E-Max AI (RoyalAceCat) external parent crossover implemented in GoodPJW v10 (Apache-2.0)'
                inputs=' | '.join(parent_label(v,k) for v in refs)
                w.writerow([k,'Local post-merge '+r['arm'], tool+'. Input programs: '+inputs,len(t)])
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        order=[(i,arm) for i in ts for arm in MODES]
        fs={ex.submit(trial,i,a):(i,a) for i,a in order}
        for f in as_completed(fs):
            r,t=f.result();k=r['id'];outcomes.append(r)
            if r['after']<r['before'] and (k not in best or (len(t),MODES.index(r['arm']))<(len(best[k][1]),MODES.index(best[k][0]['arm']))):
                best[k]=r,t;publish();print('WIN',k,r['arm'],r['before'],r['after'],flush=True)
            if len(outcomes)%10==0:print('progress',len(outcomes),flush=True)
    publish()
    outcomes.sort(key=lambda r:(r['id'],r['arm']))
    (HERE/'rows.json').write_text(json.dumps(outcomes,indent=1)+'\n',encoding='utf8')
    print({arm:(sum(r['before']-r['after'] for r in outcomes if r['arm']==arm),sum(r['seconds'] for r in outcomes if r['arm']==arm)) for arm in MODES},flush=True)
if __name__=='__main__': main()
