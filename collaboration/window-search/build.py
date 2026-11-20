"""Build the two exact search executables from the sources in this repository."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

HERE=Path(__file__).resolve().parent
PROOFS=HERE.parents[1]/'proofs/local'
NATIVE=PROOFS/'work/gpu'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    parser.add_argument('--compiler',default='g++')
    args=parser.parse_args()
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    flags=['-O3','-std=c++17']
    if os.name=='nt':flags.extend(['-static','-Wl,--no-insert-timestamp'])
    def compile_source(source,target,includes):
        command=[args.compiler,*flags]
        for folder in includes:command.extend(['-I',str(folder)])
        subprocess.run([*command,str(source),'-o',str(output/target)],check=True,
            env=dict(os.environ,TEMP=str(output),TMP=str(output),TMPDIR=str(output)))
    compile_source(NATIVE/'wave10/sparse_all_limits.cpp','sparse-all.exe',[NATIVE])
    with tempfile.TemporaryDirectory(dir=output) as folder:
        helper=(PROOFS/'exact_helpers.cpp').read_text(encoding='utf8')
        needle='if (limit <= 4000000) {'
        if helper.count(needle)!=1:raise ValueError('Changed dense lookup initialization')
        (Path(folder)/'sparse_core.inc').write_text(helper.replace(needle,'if (limit <= 16384) {'),encoding='utf8')
        compile_source(HERE/'batch.cpp','retained-batch.exe',[folder,PROOFS])

if __name__=='__main__':main()
