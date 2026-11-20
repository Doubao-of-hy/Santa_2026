"""Test collective rejection of groups of complete legal first helpers in a four-helper tail."""
from build import D,ROOT,changed,sha256
import json
import os
import subprocess


def main():
    for tag in ('dense','sparse'):
        base=D/(tag+'_star.hpp');src=base.read_text()
        src=changed(src,'    #include "three.inc"','    #include "three.inc"\n    #include "groups.inc"')
        src=changed(src,'        Values excluded;','''        Set group_rejected;
        if (enable_star && remaining==4 && !partitioned) group_filter(active,helpers,all&~supported,group_rejected);
        if (!group_rejected.empty()) {
            for(Num v:group_rejected)bans.insert(v);
        }
        Values excluded;''')
        src=changed(src,'        for (Num v:excluded) bans.erase(v);','''        for (Num v:excluded) bans.erase(v);
        for (Num v:group_rejected)bans.erase(v);''')
        (D/(tag+'_groups.hpp')).write_bytes(src.encode())
    driver=(D/'star.cpp').read_text().replace('_star.hpp"','_groups.hpp"')
    driver=changed(driver,'    s.limit=limit;','    s.limit=limit; if(const char* width=std::getenv("SANTA_GROUP_WIDTH"))s.group_width=std::max(2,std::atoi(width));')
    driver=changed(driver,'<<s.tested_stars<<" "<<s.rejected_stars','<<s.tested_stars<<" "<<s.rejected_stars<<" "<<s.grouped_calls<<" "<<s.grouped_rejections<<" "<<s.removed_next')
    source=D/'groups.cpp';source.write_bytes(driver.encode())
    cc=ROOT/'work/gen/toolchain/mingw64/bin/g++.exe'
    exe=D/'groups.exe';flags=['-O3','-std=c++17','-static','-Wl,--no-insert-timestamp']
    subprocess.run([str(cc),*flags,str(source),'-o',str(exe)],env={**os.environ,'TMP':str(D),'TEMP':str(D)},check=True)
    fs=[D/'build.json',D/'dense_groups.hpp',D/'sparse_groups.hpp',D/'three.inc',D/'groups.inc',source,D/'build_groups.py']
    log={'sources':{p.name:sha256(p)for p in fs},'binary_sha256':sha256(exe),'flags':flags}
    (D/'groups-build.json').write_bytes((json.dumps(log,indent=2)+'\n').encode());print(sha256(exe))


if __name__=='__main__':main()
