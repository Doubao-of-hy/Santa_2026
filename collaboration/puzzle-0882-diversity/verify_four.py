"""Build the archived native decision engines and replay the six-donor/four-free grid."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256 as digest
from itertools import combinations
import json
from math import comb
import os
from pathlib import Path
import re
import subprocess
import tempfile

from verify import HERE,ROOT,check,read_puzzles,replay,require,sha256


def build(engine,compiler,tmp):
    solver=ROOT/'proofs/local/work/gpu/closest-36729'
    source=solver/('star.cpp' if engine=='star' else 'generic_verifier.cpp')
    expected={'star':'fd1ebeac409df10a332e2de7c69b243f7838df7caf590d6def1aae61cbf3e61e',
              'generic':'bc0a9bcdae751581ca62a641853b44a0e87f102de5c3f826febaa635cf460d9d'}
    require(sha256(source)==expected[engine],'unexpected archived engine source')
    contents,n=re.subn(r'int main\(int argc,\s*char\s*\*\*\s*argv\)','int one_official_instance(int argc,char** argv)',source.read_text())
    require(n==1,'unexpected native entry point')
    contents+='''
int main(int argc,char** argv) {
    std::ios::sync_with_stdio(false);std::cin.tie(nullptr);
    for(;;) {
        std::cin >> std::ws;
        if(std::cin.peek()==std::char_traits<char>::eof())return 0;
        int result=one_official_instance(argc,argv);
        if(result!=0)return result;
    }
}
'''
    src=tmp/f'batch-{engine}.cpp';src.write_bytes(contents.encode())
    require(sha256(src)=={'star':'40a1f6044cd961f32881a6b6cf6fea8b2ff18e23d8ae444247121ea5ff780caf',
                          'generic':json.loads((HERE/'batch-receipt.json').read_bytes())['generic']['compiled_source']}[engine],
            'generated wrapper differs from archived source')
    binary=tmp/(engine+('.exe' if os.name=='nt' else ''))
    flags=['-O3','-std=c++17']
    if os.name=='nt':flags.append('-static')
    subprocess.run([compiler,*flags,'-I',str(solver),'-I',str(ROOT/'proofs/local'),str(src),'-o',str(binary)],check=True)
    return binary


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--puzzles',required=True,type=Path)
    ap.add_argument('--engine',choices=('star','generic'),default='star');ap.add_argument('--cxx',default='g++')
    ap.add_argument('--jobs',type=int,default=4);ap.add_argument('--shard',type=int,help='optional one of the 256 shards, starting at 0')
    ap.add_argument('--temp-dir',type=Path,help='temporary compilation directory');ap.add_argument('--receipts-only',action='store_true')
    a=ap.parse_args();require(a.jobs>0 and (a.shard is None or 0<=a.shard<256),'invalid selection')
    family=json.loads((HERE/'parents.json').read_bytes());require(sha256(a.puzzles)==family['official_puzzles_sha256'],'wrong official file')
    p=next(p for p in read_puzzles(a.puzzles) if p.id==family['id'])
    union=set()
    for parent in family['parents']:
        require(check(p,parent['program'])==parent['steps'],'invalid witness')
        union.update({s.output for s in replay(p,parent['program'])}-set(p.seeds)-set(p.targets))
    union=sorted(union);require(union==family['union'] and len(union)==20,'bad donor union')
    name='four-new.json' if a.engine=='star' else 'four-new-generic.json'
    doc=json.loads((HERE/name).read_bytes());spec=doc['protocol'];records=doc['shard_results'];shards=256
    require(spec['engine']==a.engine and spec['puzzle']==p.id and spec['donors']==union and spec['required_from_union']==6 and
            spec['arbitrary_helpers']==4 and spec['budget']==10 and spec['shards']==shards and
            spec['official_sha256']==family['official_puzzles_sha256'] and spec['frozen_sha256']==family['frozen_experiment_sha256'],
            'incompatible protocol')
    require(doc['status']=='UNSAT_REGION' and doc['totals']=={'UNSAT':comb(20,6)} and len(records)==shards and
            sorted(r['shard'] for r in records)==list(range(shards)) and doc['nodes']==sum(r['nodes'] for r in records),'incomplete grid')
    require(doc['nodes']=={'star':94901836,'generic':79443526}[a.engine],'unexpected node count')
    groups=[[] for _ in range(shards)]
    for i,g in enumerate(combinations(union,6)):groups[i%shards].append(g)
    for row in records:
        n=len(groups[row['shard']])
        require(row['subsets']==n and row['counts']=={'UNSAT':n} and not row['unknown_indices'] and not row['found'],'incomplete shard')
    if a.receipts_only:
        print(name,'verified receipt coverage',comb(20,6));return
    if a.temp_dir:a.temp_dir.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=a.temp_dir) as tmp:
        binary=build(a.engine,a.cxx,Path(tmp))
        args=['star','0','1','0','1','0','1'] if a.engine=='star' else ['--original','0','1']
        def one(row):
            lines=[]
            for g in groups[row['shard']]:
                goals=sorted(set(p.targets)|set(g))
                lines.append(' '.join(map(str,[p.limit,len(p.seeds),len(goals),4,spec['node_limit'],*p.seeds,*goals])))
            txt=subprocess.run([str(binary),*args],input='\n'.join(lines)+'\n',text=True,capture_output=True,check=True).stdout
            outputs=[line.split() for line in txt.splitlines()]
            require(len(outputs)==len(lines) and all(z[0]=='UNSAT' for z in outputs),'subproblem did not exhaust')
            require(sum(int(z[1]) for z in outputs)==row['nodes'] and sum(int(z[2]) for z in outputs)==row['terminals'] and
                    digest(txt.replace('\r\n','\n').encode()).hexdigest()==row['stdout_sha256'],'native trace differs')
        chosen=records if a.shard is None else [row for row in records if row['shard']==a.shard]
        with ThreadPoolExecutor(a.jobs)as pool:list(pool.map(one,chosen))
    print(a.engine,'replayed',len(chosen),'of',shards,'shards;',sum(row['subsets'] for row in chosen),'subsets')


if __name__=='__main__':main()
