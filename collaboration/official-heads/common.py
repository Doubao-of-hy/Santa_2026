"""Single ordinary-generation control with the same recipe selection and final operation budget."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse,json
from reorder import SEED,generate,opt,read_puzzles,write_submission
from finish_fresh import improve

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('puzzles',type=Path);ap.add_argument('exe',type=Path);ap.add_argument('finish',type=Path)
    ap.add_argument('out',type=Path);ap.add_argument('ids',nargs='+');ap.add_argument('--jobs',type=int,default=2)
    a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=True);ps={p.id:p for p in read_puzzles(a.puzzles)}
    def run(i):
        p=ps['scored_'+i.zfill(4)]
        t=generate(p,p.targets,a.exe.resolve());raw=len(t)
        mixed,t,stats=opt(p,[t])
        t,log=improve(p,t,a.finish.resolve(),SEED+int(i),2400)
        row={'raw':raw,'mixed':mixed,'after':len(t),'engine':log}
        write_submission(a.out/(p.id+'.csv'),[p],{p.id:t})
        (a.out/(p.id+'.json')).write_text(json.dumps(row,indent=2)+'\n',encoding='utf8')
        print(p.id,raw,mixed,len(t),flush=True)
    with ThreadPoolExecutor(a.jobs) as pool:list(pool.map(run,a.ids))

if __name__=='__main__':main()
