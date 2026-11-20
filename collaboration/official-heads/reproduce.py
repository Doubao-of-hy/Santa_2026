"""Build free CPU engines and repeat a chosen subset of the archived construction experiments."""
from pathlib import Path
import argparse,os,json,subprocess,sys
from measure import PILOT,HOLDOUT,ROOT,HERE
from finish_fresh import build

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--puzzles',type=Path,default=ROOT/'data/puzzles.csv')
    ap.add_argument('--good-source',type=Path,required=True)
    ap.add_argument('--cxx',default='g++');ap.add_argument('--git-root',type=Path,default=ROOT)
    ap.add_argument('--work',type=Path,required=True);ap.add_argument('--jobs',type=int,default=2)
    ap.add_argument('--ids',nargs='+',default=['all'])
    a=ap.parse_args();work=a.work.resolve();work.mkdir(parents=True,exist_ok=True)
    suffix='.exe' if os.name=='nt' else ''
    rud=work/('rudolph'+suffix);good=work/('good-evals'+suffix)
    flags=['-static','-Wl,--no-insert-timestamp'] if os.name=='nt' else []
    env={**os.environ,**{k:str(work) for k in ('TMP','TEMP','TMPDIR')}}
    subprocess.run([a.cxx,'-O3','-std=c++17',*flags,str(ROOT/'generative/rudolph.cpp'),'-o',str(rud)],env=env,check=True)
    build(a.good_source.resolve(),good,a.cxx)
    screened=json.loads((HERE/'screen-design.json').read_bytes())['ids']
    want=set(PILOT+HOLDOUT+tuple(screened)) if 'all' in a.ids else {s.zfill(4) for s in a.ids}
    if not want<=set(PILOT+HOLDOUT+tuple(screened)):raise ValueError('id outside archived experiment')
    def run(script,*args):
        subprocess.run([sys.executable,'-B',str(HERE/script),*map(str,args)],env=env,check=True)
    for tag,selected,script in [('pilot',PILOT,'reorder.py'),('head-pilot',PILOT,'headers.py'),('head-holdout',HOLDOUT,'headers.py')]:
        ids=[k for k in selected if k in want]
        if not ids:continue
        out=work/tag
        run(script,a.puzzles,rud,out,*ids,'--jobs',a.jobs)
        if tag=='pilot':run('finish_fresh.py','run',a.puzzles,good,out,*ids,'--jobs',a.jobs)
        arms=['random','adaptive' if tag=='pilot' else 'directed']
        run('finish_fresh.py','run',a.puzzles,good,out,*ids,'--jobs',a.jobs,'--evaluations',2400,'--tag','confirmed','--arms',*arms)
    for tag,selected in [('common',PILOT+HOLDOUT),('screen',screened)]:
        ids=[i for i in selected if i in want]
        if ids:run('common.py',a.puzzles,rud,good,work/tag,*ids,'--jobs',a.jobs)
    run('measure.py',a.puzzles,work/'results','--run-root',work,'--git-root',a.git_root)

if __name__=='__main__':main()
