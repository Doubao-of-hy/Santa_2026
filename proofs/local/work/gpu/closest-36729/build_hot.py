"""Use per-value cached inverse transitions and reversibly grounded full goal components."""
import json
import os
import subprocess
from build import D,ROOT,changed,sha256


def main():
    three=(D/'three.inc').read_text()
    start=three.index('        unsigned weight=__builtin_popcountll(subset);')
    end=three.index('    // Once x and y are fixed',start)
    three=three[:start]+'        return fast_weight(x,subset,missing);\n    }\n\n'+three[end:]
    (D/'hot_three.inc').write_bytes(three.encode())
    base=(D/'dense_groups.hpp').read_text()
    base=changed(base,'    #include "three.inc"','    #include "hot.inc"\n    #include "hot_three.inc"')
    base=changed(base,'                    undo_index(edits); multi.resize(previous_multi);','                    if(remaining>2)undo_index(edits); multi.resize(previous_multi);')
    (D/'hot_dense.hpp').write_bytes(base.encode())
    driver=(D/'groups.cpp').read_text().replace('#include "dense_groups.hpp"','#include "hot_dense.hpp"').replace('#include "sparse_groups.hpp"','')
    driver=changed(driver,'    if (s.enable_star) s.prepare_stars();','    if (s.enable_star) {s.prepare_stars();s.prepare_hot();}')
    driver=changed(driver,'    return cap<=4\'000\'000?solve<DenseStar>(cap,mode,argc,argv):solve<SparseStar>(cap,mode,argc,argv);',
                   '    if(cap>2\'000\'000 || mode!="star")return 2; return solve<DenseStar>(cap,mode,argc,argv);')
    src=D/'hot.cpp';src.write_bytes(driver.encode())
    cc=ROOT/'work/gen/toolchain/mingw64/bin/g++.exe'
    exe=D/'hot.exe';flags=['-O3','-std=c++17','-static','-Wl,--no-insert-timestamp']
    subprocess.run([str(cc),*flags,str(src),'-o',str(exe)],env={**os.environ,'TMP':str(D),'TEMP':str(D)},check=True)
    fs=[D/'groups-build.json',D/'hot.inc',D/'hot_three.inc',D/'hot_dense.hpp',src,D/'build_hot.py']
    log={'sources':{p.name:sha256(p)for p in fs},'binary_sha256':sha256(exe),'flags':flags}
    (D/'hot-build.json').write_bytes((json.dumps(log,indent=2)+'\n').encode());print(sha256(exe))


if __name__=='__main__':main()
