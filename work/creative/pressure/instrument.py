"""Instrument the licensed native solver's register fallback and compile a temporary translation unit."""
from pathlib import Path
import os
import subprocess
from tempfile import TemporaryDirectory

here=Path(__file__).resolve().parent
src=here.parent/'current-methods/good-elfopt.cpp'
engine=src.read_text(encoding='utf8')
needle='if (c.pressure() <= P->regs) { *this = c; return true; }\n        return false;'
assert engine.count(needle)==1
extra='''if (c.pressure() <= P->regs) { *this = c; return true; }
        const char* path=getenv("ELF_PRESSURE_FILE");
        static set<unsigned long long> seen;
        if(path && count() < int(P->prog.size()) && seen.size() < 24) {
            vector<tuple<u64,int,u64,u64>> edges;
            for(const Node& x:N)if(x.op) {
                u64 a=N[x.a].v,b=N[x.b].v;
                if((x.op==1 || x.op==3)&&a>b)swap(a,b);
                edges.emplace_back(x.v,x.op,a,b);
            }
            auto sorted=edges;sort(sorted.begin(),sorted.end());
            u64 hash=1469598103934665603ULL;
            for(auto [v,op,a,b]:sorted)for(u64 n:{v,(u64)op,a,b})hash=(hash^n)*1099511628211ULL;
            if(seen.insert(hash).second) {
                ofstream f(path,ios::app);
                f<<"R "<<P->id<<' '<<count()<<' '<<pressure()<<' '<<c.pressure()<<'\\n';
                for(auto [v,op,a,b]:edges)f<<v<<' '<<OPC[op]<<' '<<a<<' '<<b<<'\\n';
            }
        }
        // The exploratory run may traverse basins that require extra registers.
        // Every exported result independently encounters the real cap first.
        const char* relax=getenv("ELF_PRESSURE_EXTRA");
        return relax && min(pressure(),c.pressure()) <= P->regs+atoi(relax);'''
out=engine.replace(needle,extra)
root=here.parents[2];compiler=root/'work/gen/toolchain/mingw64/bin/g++.exe'
env=os.environ.copy();env.update(TEMP=str(here),TMP=str(here))
with TemporaryDirectory(dir=here) as folder:
    file=Path(folder)/'instrumented.cpp';file.write_text(out,encoding='utf8')
    subprocess.run([str(compiler),'-std=c++17','-O3','-static','-march=x86-64',str(file),'-o',str(here/'probe.exe')],env=env,check=True)
