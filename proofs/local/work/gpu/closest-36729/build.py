from pathlib import Path
import json
import os
import subprocess
import sys

D=Path(__file__).resolve().parent;H=D.parent;ROOT=H.parents[1]
sys.path.insert(0,str(ROOT))
from elf import sha256

def changed(text,before,after):
    assert text.count(before)==1,before
    return text.replace(before,after)

def main():
    settings=[(ROOT/'exact_frontier.hpp','IncrementalSearch','DenseStar','dense_star.hpp'),
              (H/'sparse_frontier.hpp','SparseFrontier','SparseStar','sparse_star.hpp')]
    for source,old,new,filename in settings:
        text=changed(source.read_text(),'struct '+old+' :','struct '+new+' :')
        point='    bool visit_frontier('
        text=changed(text,point,'    #include "three.inc"\n'+point)
        point='        ++nodes;\n        if (pair_bound'
        text=changed(text,point,'        ++nodes;\n        if (enable_star && remaining==3 && !three_possible(all&~supported,helpers)) return false;\n        if (pair_bound')
        if new=='SparseStar':
            text=changed(text,'if(!dense_unary.empty() || !dense_goals.empty())throw std::runtime_error("requires sparse domain");','// Sparse ordered reachability also permits dense unary lookups.')
            text=changed(text,'Mask goal_mask(Num x) const {auto','Mask goal_mask(Num x) const {if(!dense_goals.empty())return dense_goals[x];auto')
        (D/filename).write_bytes(text.encode())
    cc=ROOT/'work/gen/toolchain/mingw64/bin/g++.exe'
    flags=['-O3','-std=c++17','-static','-Wl,--no-insert-timestamp']
    binary=D/'star.exe'
    subprocess.run([str(cc),*flags,str(D/'star.cpp'),'-o',str(binary)],env={**os.environ,'TMP':str(D),'TEMP':str(D)},check=True)
    paths=[ROOT/'exact_helpers.cpp',ROOT/'exact_frontier.hpp',H/'sparse_frontier.hpp',H/'sparse_reachable.hpp',
           D/'three.inc',D/'star.cpp',D/'dense_star.hpp',D/'sparse_star.hpp',Path(__file__)]
    info={'sources':{p.relative_to(ROOT).as_posix():sha256(p) for p in paths},'binary_sha256':sha256(binary),'flags':flags}
    (D/'build.json').write_bytes((json.dumps(info,indent=2)+'\n').encode());print(sha256(binary))

if __name__=='__main__':main()
