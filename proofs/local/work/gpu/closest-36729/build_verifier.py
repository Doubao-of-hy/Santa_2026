"""Specialize the original generic traversal, independent of the incremental star solver."""
from build import D,ROOT,changed,sha256
import json
import os
import subprocess


def main():
    original=ROOT/'exact_helpers.cpp'
    src=original.read_text()
    src=changed(src,'    void prepare() {','    #include "verify3.inc"\n    void prepare() {')
    src=changed(src,'        exceptional_pairs();','''        exceptional_pairs();
        if (verify_tail) {
            for (const auto& entry:unary) if (entry.second & (entry.second-1)) candidates_with_two.push_back(entry.first);
            for (const auto& entry:exceptional) for (Num b:entry.second) if(entry.first<b) joints.push_back({entry.first,b,hits(entry.first,b)});
            prepare_networks();
        }''')
    src=changed(src,'                    edits.push_back({x, j, old});','''                    if (verify_tail && old && !(old&(old-1))) candidates_with_two.push_back(x);
                    edits.push_back({x, j, old});''')
    src=changed(src,'            partners[i->goal].pop_back();','''            if (verify_tail && i->before && !(i->before&(i->before-1))) {
                if (candidates_with_two.back()!=i->value) throw std::logic_error("multi undo");
                candidates_with_two.pop_back();
            }
            partners[i->goal].pop_back();''')
    src=changed(src,'        ++nodes;\n        Values options;','''        ++nodes;
        if (verify_tail && remaining==3 && !can_finish_three(active,seen,all&~supported,forbidden)) return false;
        Values options;''')
    src=changed(src,'    s.prepare();','    s.verify_tail=true;\n    s.prepare();')
    src=changed(src,'            if (remaining > 2) extend_index(v, edits);\n            helpers.push_back(v);',
                '            if (remaining > 2) {extend_index(v, edits); if(verify_tail)ground_with(v,true);}\n            helpers.push_back(v);')
    src=changed(src,'            bool found = visit(next, covered, sup, helpers, forbidden, remaining - 1);\n            helpers.pop_back();',
                '            bool found = visit(next, covered, sup, helpers, forbidden, remaining - 1);\n            helpers.pop_back();\n            if(remaining>2 && verify_tail)ground_with(v,false);')
    source=D/'generic_verifier.cpp'
    source.write_bytes(src.encode())
    cc=ROOT/'work/gen/toolchain/mingw64/bin/g++.exe'
    exe=D/'generic-verifier.exe'
    flags=['-O3','-std=c++17','-static','-Wl,--no-insert-timestamp']
    subprocess.run([str(cc),*flags,'-I',str(ROOT),str(source),'-o',str(exe)],env={**os.environ,'TMP':str(D),'TEMP':str(D)},check=True)
    paths=[original,ROOT/'exact_frontier.hpp',D/'verify3.inc',source,D/'build_verifier.py']
    log={'sources':{p.relative_to(ROOT).as_posix():sha256(p)for p in paths},'binary_sha256':sha256(exe),'flags':flags}
    (D/'verifier-build.json').write_bytes((json.dumps(log,indent=2)+'\n').encode());print(sha256(exe))


if __name__=='__main__':main()
