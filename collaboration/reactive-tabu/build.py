"""Build the original Wang engine and the common three-proposal extension."""
from pathlib import Path
import argparse,os,subprocess,tempfile
a=argparse.ArgumentParser();a.add_argument('--repo',type=Path,required=True);a.add_argument('--out',type=Path,required=True);a.add_argument('--cxx',default='g++');args=a.parse_args()
here=Path(__file__).resolve().parent;src=args.repo.resolve()/'generative/wang';out=args.out.resolve();out.mkdir(exist_ok=True,parents=True)
text=(src/'incremental.cpp').read_text(encoding='utf8')
i=text.index('    Tape improve(');j=text.index('\n};',i)
code='#include <tuple>\n#include <limits>\n'+text[:i]+(here/'trajectory.inc').read_text(encoding='utf8')+text[j:]
suffix='.exe' if os.name=='nt' else ''
with tempfile.TemporaryDirectory(dir=out) as d:
 temp=Path(d);local=temp/'trajectory.cpp';local.write_text(code,encoding='utf8')
 for file,name in [(src/'incremental.cpp','original'),(local,'three')]:
  flags=['-static'] if os.name=='nt' else []
  subprocess.run([args.cxx,'-std=c++17','-O3',*flags,'-I',str(src),str(file),'-o',str(out/(name+suffix))],check=True,env={**os.environ,'TMP':d,'TEMP':d,'TMPDIR':d})
