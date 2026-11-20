"""Run Rudolph's audited, seed-only stream entry point to generate practice traces."""
import json,subprocess
from elf import check

def generate(p,order,exe):
    config=('12','.18','60','80','16','40','1','0','0','0','2','2')
    data=' '.join(map(str,(p.id,p.limit,len(p.seeds),len(order),*p.seeds,*order)))+'\n'
    proc=subprocess.run([str(exe),*config],input=data,text=True,capture_output=True,check=True)
    identifier,body=proc.stdout.strip().split(' ',1)
    if identifier!=p.id:raise ValueError(identifier)
    program=tuple(map(tuple,json.loads(body)));check(p,program)
    return program
