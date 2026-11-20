"""Compare two orders of Atakan frontier and Wang incremental against independent starts."""
import csv
import gzip
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
PROJECT=Path(os.getenv('SANTA_PROJECT','E:/Codex/Santa2026'))
CHECKOUT=Path(os.getenv('SANTA_CHECKOUT','E:/Codex/Santa2026-GitHub'))
OFFICIAL=Path(os.getenv('SANTA_PUZZLES',PROJECT/'data/puzzles.csv'))
PREV=Path(os.getenv('SANTA_AT_FRONTIER',HERE.parent/'atakan134311'))
AEXE=Path(os.getenv('SANTA_ATAKAN_EXE',PREV/'scratch/v30/frontier.exe'))
WEXE=Path(os.getenv('SANTA_WANG_EXE',PROJECT/'work/virtual/good10-wang-diff/inc-local.exe'))
sys.path.insert(0,str(PROJECT))
from elf import check,read_puzzles,write_submission
from checkpoint import independent_score

CFG=json.loads((HERE/'design.json').read_bytes())
def hash_bytes(b):return hashlib.sha256(b).hexdigest()
def digest_tape(t):
    return hash_bytes(json.dumps(t,separators=(',',':')).encode())
def git(rev,f):
    return subprocess.check_output(['git','-C',str(CHECKOUT),'show',rev+':'+f])
def table(b):
    return {r['id']:r for r in csv.DictReader(io.StringIO(b.decode('utf-8-sig')))}
def decode(s):
    return tuple(tuple(op) for op in json.loads(s))
def get_history():
    candidates=[HERE/'previous-controls.json',PREV/'details.json',PREV/'details.json.gz']
    file=next(f for f in candidates if f.exists())
    data=file.read_bytes()
    if file.suffix=='.gz':data=gzip.decompress(data)
    rows=json.loads(data)
    return {r['id']:r for r in rows.values() if r['lane']=='independent' and r['arm']=='v30-13'}

def atakan(p,t):
    head=[p.id,p.limit,len(p.seeds),len(p.targets),len(t),*p.seeds,*p.targets]
    stream=[' '.join(map(str,head))]+[' '.join(map(str,op)) for op in t]
    out=subprocess.run([str(AEXE),*map(str,CFG['A']['configuration'])],input='\n'.join(stream)+'\n',text=True,capture_output=True,check=True,timeout=370).stdout.splitlines()
    data=out[0].split();assert data[0]==p.id
    result=tuple((v[0],*map(int,v[1:])) for line in out[1:] for v in [line.split()])
    assert check(p,result)==int(data[1])<=len(t)
    return result

def wang(p,t):
    seed=6417300+int(p.id[-4:])
    fields=[[1],[p.limit,p.registers,CFG['W']['rounds'],0,seed],[len(p.seeds),*p.seeds],[len(p.targets),*sorted(p.targets)],[1],[len(t)],*t]
    stream='\n'.join(' '.join(map(str,r)) for r in fields)+'\n'
    bits=subprocess.run([str(WEXE)],input=stream,text=True,capture_output=True,check=True,timeout=370).stdout.split()
    n=int(bits[0]);assert len(bits)==1+4*n
    result=tuple((bits[k],int(bits[k+1]),int(bits[k+2]),int(bits[k+3])) for k in range(1,len(bits),4))
    assert check(p,result)==n<=len(t)
    return result

def compare(p,parent,previous_input,old):
    cache={}
    stages={'parent':parent}
    jobs=[]
    def evaluate(label,method,seed):
        t=stages[seed];key=(method,digest_tape(t))
        if key in cache:
            source='reused '+cache[key][0];output=cache[key][1];sec=0
        elif method=='A' and t==previous_input and old and old['before']==old['after']==len(t):
            # Both checked frontier versions initialize best=old and only replace best on strict savings.
            # This old result therefore certifies this exact physical tape.
            source='prior registered Atakan run';output=t;sec=0
        else:
            start=time.monotonic()
            output=(atakan if method=='A' else wang)(p,t)
            source='new launch';sec=round(time.monotonic()-start,3)
        check(p,output)
        cache[key]=(label,output)
        stages[label]=output
        jobs.append({'label':label,'method':method,'input':seed,'input_sha256':key[1],'output_sha256':digest_tape(output),'steps':len(output),'execution':source,'seconds':sec})
    evaluate('A','A','parent');evaluate('W','W','parent')
    evaluate('AW','W','A');evaluate('WA','A','W')
    separate=min(['A','W'],key=lambda k:len(stages[k]))
    stages['separate']=stages[separate]
    selected=min(['separate','AW','WA'],key=lambda k:len(stages[k]))
    return {'before':len(parent),'stages':jobs,'separate_selected':separate,'selected':selected,'after':len(stages[selected]),'sequence_advantage':len(stages[separate])-len(stages[selected])},stages

def main():
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('--jobs',type=int,default=4);ap.add_argument('--rebuilt',action='store_true');args=ap.parse_args()
    assert hash_bytes(OFFICIAL.read_bytes())==CFG['official_sha256']
    if not args.rebuilt:
        assert hash_bytes(AEXE.read_bytes())==CFG['A']['binary_sha256']
        assert hash_bytes(WEXE.read_bytes())==CFG['W']['binary_sha256']
    blobs=[git(CFG['frozen'],f) for f in ['submission.csv','origins.csv']]
    assert [hash_bytes(b) for b in blobs]==[CFG['submission_sha256'],CFG['origins_sha256']]
    full,credits=map(table,blobs)
    prior=table(git('aca4989','submission.csv'));previous=get_history()
    puzzles=read_puzzles(OFFICIAL);ps={p.id:p for p in puzzles}
    ids=[pair[k] for pair in CFG['groups'] for k in ['positive','matched']]
    mainrun={};interms={};wins={}
    with ThreadPoolExecutor(args.jobs) as ex:
        jobs={ex.submit(compare,ps[k],decode(full[k]['program']),decode(prior[k]['program']),previous.get(k)):k for k in ids}
        for f in as_completed(jobs):
            k=jobs[f];r,s=f.result();mainrun[k]=r;interms[k]=s
            if r['after']<r['before']:
                wins[k]=s[r['selected']]
                print('WIN',k,r['before'],r['after'],r['selected'],r['sequence_advantage'],flush=True)
    write_submission(HERE/'shorter.csv',[ps[k] for k in sorted(wins)],wins)
    with (HERE/'shorter.origins.csv').open('w',newline='',encoding='utf8') as f:
        w=csv.writer(f);w.writerow(['id','source','upstream_source','instructions'])
        for k,t in sorted(wins.items()):
            r=mainrun[k];steps=r['separate_selected'] if r['selected']=='separate' else r['selected']
            methods={'A':'Atakan Aldemir v30 (kernel 371505096, inherited v15 whole-graph file)','W':'Wang Jakie incremental (kernel 371736767)'}
            credit=' then '.join(methods[c] for c in steps)+'; input 243776e: '+credits[k]['source']
            extra=json.loads((HERE/'parent-winner-credits.json').read_bytes()).get(k)
            if extra:
                credit+='; frozen upstream: '+extra['parent']['upstream_source']
            w.writerow([k,'Independent fixed two-method order trial',credit,len(t)])
    (HERE/'stages.json.gz').write_bytes(gzip.compress(json.dumps(dict(sorted(interms.items())),separators=(',',':')).encode(),compresslevel=9,mtime=0))
    (HERE/'rows.json').write_text(json.dumps(dict(sorted(mainrun.items())),indent=1)+'\n',encoding='utf8')
    programs={k:decode(r['program']) for k,r in full.items()}
    with tempfile.TemporaryDirectory(dir=HERE) as td:
        file=Path(td)/'merged.csv'
        final=write_submission(file,puzzles,programs|wins)
        second=independent_score(OFFICIAL,file);assert len(second)==1000 and sum(second)==final
        result={'frozen':CFG['frozen'],'before':sum(map(len,programs.values())),'after':final,'merged_sha256':hash_bytes(file.read_bytes()),'sequential_advantage':sum(r['sequence_advantage'] for r in mainrun.values()),'cases':len(mainrun),'wins':{k:[mainrun[k]['before'],len(t)] for k,t in sorted(wins.items())},
                'stages_sha256':hash_bytes((HERE/'stages.json.gz').read_bytes()),'origins_sha256':hash_bytes((HERE/'shorter.origins.csv').read_bytes()),'new_calls':sum(q['execution']=='new launch' for r in mainrun.values() for q in r['stages']),'prior_reuse':sum(q['execution'].startswith('prior') for r in mainrun.values() for q in r['stages'])}
    (HERE/'verification.json').write_text(json.dumps(result,indent=1)+'\n',encoding='utf8')
    print(result)
if __name__=='__main__':main()
