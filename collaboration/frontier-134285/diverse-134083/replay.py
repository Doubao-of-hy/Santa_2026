"""Rebuild the seven published E-Max AI cases against the three fixed public banks."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
from elf import check, read_puzzles, write_submission, sha256
from checkpoint import independent_score

def archive_rows(bundle, name):
    return csv.DictReader(io.StringIO(bundle.read(name).decode('utf-8-sig')))

def program(raw):
    return tuple(tuple(step) for step in json.loads(raw))

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ('puzzles','inputs','source','out'):
        ap.add_argument('--'+name, type=Path, required=True)
    ap.add_argument('--compiler',default='g++')
    ap.add_argument('--jobs',type=int,default=4)
    a = ap.parse_args()
    a.out.mkdir(parents=True,exist_ok=True)
    meta = json.loads((HERE/'sources.json').read_bytes())
    ps = read_puzzles(a.puzzles)
    by = {p.id:p for p in ps}
    assert sha256(a.inputs)==meta['input_archive_sha256']
    with zipfile.ZipFile(a.inputs) as z:
        cfg = json.loads(z.read('retained_experiment.json'))
        banks = []
        for prefix, label in [('baseline_v49','baseline'),('goodpjw','public'),('asterios','extra')]:
            name, = [n for n in z.namelist() if n.startswith(prefix) and n.endswith('.csv')]
            assert hashlib.sha256(z.read(name)).hexdigest()==cfg[label+'_sha256']
            bank = {r['id']:program(r['program']) for r in archive_rows(z,name)}
            assert bank.keys()==by.keys() and sum(check(p,bank[p.id]) for p in ps)==cfg[label+'_score']
            banks.append(bank)
        base = {i:min((b[i] for b in banks), key=len) for i in by}
        assert sum(map(len,base.values()))==cfg['expected_union_score']
        archives = {}
        for row in archive_rows(z,'search_archives.csv'):
            tape=program(row['program'])
            check(by[row['id']], tape)
            archives.setdefault((int(row['batch']),row['id']),[]).append((int(row['rank']),tape))
    tasks = [(j,job['strategy'],i,b['seed']+int(i[-4:]),b['rounds']) for j,b in enumerate(cfg['batches'],1) for job in b['jobs'] for i in job['ids']]
    assert len(tasks)==len({t[2] for t in tasks})
    src = a.source.resolve()
    modes = sorted({t[1] for t in tasks})
    deps = {mode+'.cpp' for mode in modes}|{n for n in cfg['source_files_sha256'] if n.endswith('.inc')}
    for name in deps:
        assert sha256(src/name)==cfg['source_files_sha256'][name]
    with tempfile.TemporaryDirectory(dir=a.out) as tmp:
        bins={}
        for mode in modes:
            exe = Path(tmp)/(mode+('.exe' if os.name=='nt' else ''))
            subprocess.run([a.compiler,'-std=c++17','-O3',*(['-static'] if os.name=='nt' else []),str(src/(mode+'.cpp')),'-o',str(exe)],env=dict(os.environ,TEMP=tmp,TMP=tmp,TMPDIR=tmp),check=True)
            bins[mode]=exe
        def search(task):
            j,mode,i,seed,rounds=task
            p=by[i];parents=sorted(archives.get((j,i),[]))
            assert [n for n,t in parents]==list(range(1,len(parents)+1))
            tapes=[base[i],*(t for n,t in parents)]
            rows=[[1],[p.limit,p.registers,rounds,0,seed],[len(p.seeds),*p.seeds],[len(p.targets),*sorted(p.targets)],[len(tapes)]]
            for t in tapes:
                rows.append([len(t)])
                rows.extend(t)
            out=subprocess.check_output([str(bins[mode])],input='\n'.join(' '.join(map(str,row)) for row in rows)+'\n',text=True,timeout=480).split()
            result=tuple((out[k],*map(int,out[k+1:k+4])) for k in range(1,len(out),4))
            assert len(out)==4*int(out[0])+1 and check(p,result)==int(out[0])
            return i,result
        with ThreadPoolExecutor(a.jobs) as pool:
            output=dict(pool.map(search,tasks))
        merged=base|{i:t for i,t in output.items() if len(t)<len(base[i])}
        full=Path(tmp)/'full.csv'
        total=write_submission(full,ps,merged)
        assert total==sum(independent_score(a.puzzles,full))==cfg['expected_output_score']
        digest=sha256(full)
    winning={i:t for i,t in output.items() if len(t)<len(base[i])}
    write_submission(a.out/'wins.csv',[p for p in ps if p.id in winning],winning)
    audit={'union':cfg['expected_union_score'],'reconstructed':total,'sha256':digest,
           'cases':{i:{'base':len(base[i]),'output':len(t),'canonical_sha256':hashlib.sha256(json.dumps(t,separators=(',',':')).encode()).hexdigest()} for i,t in output.items()}}
    (a.out/'replayed.json').write_bytes((json.dumps(audit,indent=2)+'\n').encode())
    print(total,digest,{i:len(base[i])-len(t) for i,t in winning.items()},flush=True)
if __name__=='__main__':
    main()
