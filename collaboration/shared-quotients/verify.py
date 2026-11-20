"""Verify archived improvements against immutable Git parents and optionally rerun native searches."""
import argparse,csv,gzip,hashlib,json,os,subprocess,sys,tempfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=next(p for p in HERE.parents if (p/'elf.py').is_file())
sys.path.insert(0,str(ROOT))
from checkpoint import independent_score
from elf import check,read_puzzles,read_submission,sha256,write_submission
from compare import planted,search

def load_parent(lane,gitroot,work,design):
    rel='submission.csv' if lane=='own' else 'public-assisted/submission.csv'
    b=subprocess.check_output(['git','-C',str(gitroot),'show',design['baseline_commit']+':'+rel])
    if hashlib.sha256(b).hexdigest()!=design['parents'][lane]:raise ValueError('parent bytes differ')
    path=work/(lane+'-parent.csv');path.write_bytes(b)
    return read_submission(path)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--puzzles',type=Path,default=ROOT/'data/puzzles.csv')
    ap.add_argument('--git-root',type=Path,default=ROOT)
    ap.add_argument('--work',type=Path,default=ROOT/'work/long-target-verification')
    ap.add_argument('--cxx',default='g++');ap.add_argument('--ids',nargs='+',help='repeat native searches for these puzzle numbers, or all')
    ap.add_argument('--lanes',nargs='+',choices=('own','assisted'),default=['own','assisted'])
    ap.add_argument('--engines',nargs='+',choices=('quotient','factor_join'),default=['quotient','factor_join'])
    a=ap.parse_args();a.work.mkdir(parents=True,exist_ok=True);s=json.loads((HERE/'design.json').read_bytes());v=json.loads((HERE/'validation.json').read_bytes())
    if sha256(a.puzzles)!=s['official']:raise ValueError('official data hash differs')
    ps=read_puzzles(a.puzzles);by={p.id:p for p in ps}
    with tempfile.TemporaryDirectory(dir=a.work) as tmp:
        t=Path(tmp);parents={}
        for lane in a.lanes:
            parents[lane]=load_parent(lane,a.git_root,t,s)
            path=HERE/(lane+'-combined.csv');patch=read_submission(path);meta=v[lane]
            assert sha256(path)==meta['output_sha256']
            for i,row in patch.items():assert check(by[i],row)==meta['rows'][i]['after']<len(parents[lane][i])
            f=t/(lane+'.csv');n=write_submission(f,ps,parents[lane]|patch)
            assert n==meta['total'] and sha256(f)==meta['full_sha256'] and sum(independent_score(a.puzzles,f))==n
            print(lane,'full replay:',n,flush=True)
        if not a.ids:return
        env={**os.environ,'TEMP':str(t),'TMP':str(t),'TMPDIR':str(t)}
        expected=[json.loads(line) for line in gzip.decompress((HERE/'windows.jsonl.gz').read_bytes()).decode().splitlines()]
        want=set(s['pilot']+s['holdout']) if 'all' in a.ids else {i if i.startswith('scored_') else 'scored_'+i.zfill(4) for i in a.ids}
        if not want<=set(s['pilot']+s['holdout']):raise ValueError('puzzle outside this experiment')
        for engine in a.engines:
            exe=t/(engine+('.exe' if os.name=='nt' else ''));flags=['-static','-Wl,--no-insert-timestamp'] if os.name=='nt' else []
            subprocess.run([a.cxx,'-O3','-std=c++17',*flags,'-I'+str(ROOT),str(HERE/(engine+'.cpp')),'-o',str(exe)],check=True,env=env)
            if engine=='quotient':
                sample=t/'positive-control.json'
                planted(exe,sample)
                assert json.loads(sample.read_bytes())==json.loads((HERE/'planted.json').read_bytes())
                print('planted pairs: all 80 matched',flush=True)
            for lane in a.lanes:
                for i in sorted(want):
                    row,_=search(by[i],parents[lane][i],exe)
                    old=next(r for r in expected if r['id']==i and r['lane']==lane and r['engine']==engine)
                    assert (row['before'],row['direct'],row['mixed'])==(old['before'],old['direct'],old['mixed'])
                    assert row['groups']==old['groups']
                    print(lane,engine,i,'matched',len(row['groups']),'group decisions',flush=True)
if __name__=='__main__':main()
