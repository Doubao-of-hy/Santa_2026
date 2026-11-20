"""Replay E-Max AI's published 942 case from its pinned input bundle and C++ source."""
import argparse
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
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))
from elf import check, read_puzzles, read_submission

def sha(data):
    return hashlib.sha256(data).hexdigest()

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ('puzzles','inputs','source','scratch'):
        ap.add_argument('--'+name, required=True, type=Path)
    ap.add_argument('--compiler', default='g++')
    a = ap.parse_args()
    i = 'scored_0942'
    p = next(p for p in read_puzzles(a.puzzles) if p.id == i)
    audit = json.loads((HERE/'audit.json').read_bytes())
    assert sha(a.inputs.read_bytes()) == audit['emax_archive_sha256']
    with zipfile.ZipFile(a.inputs) as z:
        cfg = json.loads(z.read('retained_experiment.json'))
        def get_rows(name):
            return [r for r in csv.DictReader(io.StringIO(z.read(name).decode('utf-8-sig'))) if r['id'] == i]
        front = [json.loads(get_rows(n)[0]['program']) for n in ('baseline_v48_134183.csv','roman_134125.csv','asterios_134185.csv')]
        donors = sorted(get_rows('search_archives.csv'), key=lambda r: int(r['rank']))
        tapes = [min(front, key=len), *(json.loads(r['program']) for r in donors)]
    for tape in tapes:
        check(p, tape)
    batch, = cfg['batches']
    strategy, = batch['jobs']
    assert strategy == {'strategy':'anneal_diverse', 'ids':[i]}
    seed = (batch['seed'] + int(i[-4:])) % (2**32)
    src = a.source.resolve()
    for file in ('anneal_diverse.cpp','common.inc','compact.inc','cross.inc','recipe_lookup.inc','fast_perturb.inc','main.inc','cache_lookup.inc','cache_perturb.inc'):
        assert sha((src/file).read_bytes()) == cfg['source_files_sha256'][file]
    fields = [[1], [p.limit,p.registers,batch['rounds'],0,seed], [len(p.seeds),*p.seeds], [len(p.targets),*sorted(p.targets)], [len(tapes)]]
    for tape in tapes:
        fields.append([len(tape)])
        fields.extend(tape)
    wire = '\n'.join(' '.join(map(str,row)) for row in fields)+'\n'
    with tempfile.TemporaryDirectory(dir=a.scratch.resolve()) as tmp:
        dest = Path(tmp)/('search.exe' if os.name=='nt' else 'search')
        subprocess.run([a.compiler,'-std=c++17','-O3',*(['-static'] if os.name=='nt' else []),str(src/'anneal_diverse.cpp'),'-o',str(dest)],env=dict(os.environ,TMP=tmp,TEMP=tmp,TMPDIR=tmp),check=True)
        words = subprocess.check_output([str(dest)],input=wire,text=True,timeout=300).split()
    tape = tuple((words[k],*map(int,words[k+1:k+4])) for k in range(1,len(words),4))
    assert 4*int(words[0])+1 == len(words)
    assert check(p,tape) == int(words[0]) == 111
    assert tape == read_submission(HERE/'wins.csv')[i]
    print(i,len(tapes[0]),len(tape),sha(json.dumps(tape,separators=(',',':')).encode()))

if __name__=='__main__':
    main()
