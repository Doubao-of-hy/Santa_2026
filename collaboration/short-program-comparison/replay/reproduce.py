"""Rebuild the published solvers, repeat selected paired searches, and compare witness byte digests."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE=Path(__file__).resolve().parent


def command(args,temp=None):
    env={**os.environ,'TMP':str(temp),'TEMP':str(temp),'TMPDIR':str(temp)} if temp else None
    subprocess.run([str(a) for a in args],check=True,env=env)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,required=True,help='Santa_2026 checkout with the first public 80-puzzle study')
    parser.add_argument('--puzzles',type=Path,required=True);parser.add_argument('--temp-dir',type=Path,required=True)
    parser.add_argument('--cxx',default='g++');parser.add_argument('--jobs',type=int,default=2)
    parser.add_argument('--ids',nargs='+',help='suffixes such as 0029, or omit to repeat all 18')
    a=parser.parse_args();src=a.repo/'collaboration/puzzle-0711';a.temp_dir.mkdir(exist_ok=True,parents=True)
    expected=json.loads((HERE/'expected.json').read_bytes());study=HERE/'study.json'
    assert sha256(study.read_bytes()).hexdigest()==expected['protocol_sha256']
    with tempfile.TemporaryDirectory(dir=a.temp_dir) as temp:
        temp=Path(temp);paths=[temp/'sparse.cpp',temp/'large.cpp']
        command([sys.executable,'-B',src/'make_sparse.py',paths[0]])
        command([sys.executable,'-B',src/'wide/make_large.py',*paths])
        programs=[]
        for path in paths:
            exe=temp/(path.stem+('.exe' if os.name=='nt' else ''));programs.append(exe)
            flags=['-static','-Wl,--no-insert-timestamp'] if os.name=='nt' else []
            command([a.cxx,'-O3','-std=c++17',*flags,path,'-o',exe],temp)
        out=temp/'run';args=['--ids',*a.ids] if a.ids else []
        command([sys.executable,'-B',HERE/'paired.py','--study',study,'--puzzles',a.puzzles,'--out',out,
                 '--sparse-binary',programs[0],'--large-binary',programs[1],'--jobs',a.jobs,*args])
        seen=set()
        for file in (out/'records').glob('*/*.json'):
            r=json.loads(file.read_bytes());pid=r['run']['puzzle'];arm=r['run']['arm'];w=expected['cases'][pid][arm]
            assert r['end_steps']==w['steps'] and [(x['iteration'],x['csv_sha256']) for x in r['wins']]==[(j,h) for j,h in w['hits']]
            seen.add((pid,arm))
        ids=set(expected['cases']) if not a.ids else {s if s.startswith('scored_') else 'scored_'+s for s in a.ids}
        assert seen=={(i,k) for i in ids for k in expected['cases'][i]}
        print('Matched',len(seen),'paired arm records, including every winning program.')


if __name__=='__main__':main()
