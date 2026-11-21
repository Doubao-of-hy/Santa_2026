"""Compile a fixed value set with dynamic recipe choices and checked evictions."""
from pathlib import Path
import subprocess
from elf import check
from graph import _allocate,active_graph

def solve(p,ordered,rounds,seed,primary=None,upper=0):
    exe=Path(__file__).resolve().parents[2]/'work/gpu'/('live-menu.exe' if upper else 'live-bank.exe')
    lines=[' '.join(map(str,(p.id,p.limit,p.registers,len(p.seeds),len(p.targets),len(ordered),*p.seeds,*p.targets)))]
    lines.extend(f'{v} {op} {a} {b}' for v,(op,a,b) in ordered.items())
    if upper:lines.append(' '.join(map(str,(len(primary),*primary))))
    run=subprocess.run([str(exe),str(rounds),str(seed),str(upper)],input='\n'.join(lines)+'\n',text=True,capture_output=True,check=True)
    out=iter(run.stdout.splitlines());attempts,longest,hits,n=map(int,next(out).split())
    if not n:return None,(attempts,longest,hits)
    g={}
    for _ in range(n):
        v,op,a,b=next(out).split();g[int(v)]=(op,int(a),int(b))
    if len(g)!=n:raise ValueError('unexpected recomputation in no-repeat run')
    need=active_graph(p,g);tape=_allocate(p,{v:r for v,r in g.items() if v in need},False,0,True)
    if tape is None or check(p,tape)!=len(need):raise ValueError('live-bank allocation mismatch')
    return tape,(attempts,longest,hits)
