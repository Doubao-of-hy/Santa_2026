"""Apply the same fixed-count rewrite pass to two entirely freshly generated programs."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse,hashlib,json,os,subprocess,sys
HERE=Path(__file__).resolve().parent
ROOT=next(p for p in HERE.parents if (p/'elf.py').is_file())
sys.path.insert(0,str(ROOT))
from elf import check,read_puzzles,read_submission,sha256,write_submission

SOURCE='16f12d4963acfe795f89f9632e941fb1aea9d8d8de55ac958a45b17a02881db2'


def build(source,dest,cxx):
    if sha256(source)!=SOURCE:raise ValueError('source mismatch')
    text=source.read_text(encoding='utf8')
    assert text.count('now() - t0 < tlimit')==2 and text.count('now() - t0 > tlimit')==2
    text=text.replace('now() - t0 < tlimit','evals < tlimit').replace('now() - t0 > tlimit','evals >= tlimit')
    cpp=dest.with_suffix('.cpp');cpp.write_text(text,encoding='utf8',newline='\n')
    flags=['-static','-Wl,--no-insert-timestamp'] if os.name=='nt' else []
    env={**os.environ,**{k:str(dest.parent.resolve()) for k in ('TMP','TEMP','TMPDIR')}}
    subprocess.run([cxx,'-O3','-std=c++17',*flags,str(cpp),'-o',str(dest)],env=env,check=True)


def improve(p,parent,exe,seed,evaluations):
    def line(items):return ' '.join(map(str,items))
    header=('P',p.id,len(p.seeds),*p.seeds,len(p.targets),*p.targets,p.limit,p.registers,len(parent))
    data='\n'.join([line(header)]+[line(step) for step in parent])+'\n'
    proc=subprocess.run([str(exe),'--seed',str(seed),'--time',str(evaluations),'--helpers','1','--pairs','1','--kicks','2'],
                        input=data,capture_output=True,text=True,check=True)
    tape=parent
    if proc.stdout.strip():
        first,*rest=proc.stdout.strip().splitlines();tag,i,old,n=first.split()
        assert (tag,i,int(old),len(rest))==('R',p.id,len(parent),int(n))
        tape=tuple((s[0],*map(int,s[1:])) for s in (row.split() for row in rest))
    assert check(p,tape)<=len(parent)
    return tape,proc.stderr.splitlines()[-1].split(' t ')[0]


def main():
    a=argparse.ArgumentParser(description=__doc__)
    sub=a.add_subparsers(dest='action',required=True)
    b=sub.add_parser('build');b.add_argument('source',type=Path);b.add_argument('exe',type=Path);b.add_argument('cxx')
    r=sub.add_parser('run');r.add_argument('puzzles',type=Path);r.add_argument('exe',type=Path);r.add_argument('out',type=Path)
    r.add_argument('ids',nargs='+');r.add_argument('--evaluations',type=int,default=180)
    r.add_argument('--tag',default='finished')
    r.add_argument('--arms',nargs='+',default=['random','adaptive'])
    r.add_argument('--seed',type=int,default=2026112047);r.add_argument('--jobs',type=int,default=2)
    args=a.parse_args()
    if args.action=='build':return build(args.source,args.exe,args.cxx)
    puzzles={p.id:p for p in read_puzzles(args.puzzles)}
    def run(i):
        p=puzzles['scored_'+i.zfill(4)];results={}
        for arm in args.arms:
            parent=read_submission(args.out/(p.id+'-'+arm+'.csv'))[p.id]
            tape,stats=improve(p,parent,args.exe.resolve(),args.seed+int(i),args.evaluations)
            dest=args.out/(p.id+'-'+arm+'-'+args.tag+'.csv')
            write_submission(dest,[p],{p.id:tape})
            results[arm]={'before':len(parent),'after':len(tape),'engine':stats,'sha256':sha256(dest)}
        (args.out/(p.id+'-'+args.tag+'.json')).write_text(json.dumps(results,indent=2)+'\n',encoding='utf8')
        print(p.id,[(arm,v['before'],v['after']) for arm,v in results.items()],flush=True)
    with ThreadPoolExecutor(args.jobs) as pool:list(pool.map(run,args.ids))

if __name__=='__main__':main()
