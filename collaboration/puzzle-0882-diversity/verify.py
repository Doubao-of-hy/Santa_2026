"""Replay the five donors, their unrestricted complement searches and optional independent controls."""
import argparse
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations, combinations_with_replacement
import json
from math import comb
from pathlib import Path
import random
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'proofs/local'))
from elf import Puzzle,check,read_puzzles,replay,sha256


def require(condition,what):
    if not condition:raise ValueError(what)


def run(binary,p,donors,r,k,i,n,limit,old=(),oldcap=100):
    nums=[p.limit,k,r,i,n,oldcap,limit,len(p.seeds),len(p.targets),len(donors),len(old),*p.seeds,*p.targets,*donors,*old]
    raw=subprocess.run([str(binary.resolve())],input=' '.join(map(str,nums))+'\n',
                       text=True,check=True,capture_output=True).stdout.splitlines()
    result,*counts=raw[0].split()
    seen,tested,excluded,unknown,nodes=map(int,counts)
    return result,seen,tested,excluded,unknown,nodes


def bfs(p,h):
    required=set(p.targets);seeds=set(p.seeds);todo=deque([frozenset(seeds)]);seen=set(todo)
    while todo:
        present=todo.popleft()
        if required<=present:return True
        for a,b in combinations_with_replacement(sorted(present),2):
            for v in (a+b,b-a,a*b,b//a if b%a==0 else 0):
                if not 1<=v<=p.limit or v in present:continue
                after=present|{v}
                if len(after-required-seeds)<=h and after not in seen:
                    todo.append(after);seen.add(after)
    return False


def small_controls(binary):
    rng=random.Random(360882);n=positive=0
    for i in range(120):
        cap=rng.randint(12,52)
        starts=tuple(sorted(rng.sample(range(1,min(cap,12)),rng.randint(1,3))))
        goals=tuple(rng.sample([x for x in range(1,cap+1) if x not in starts],rng.randint(1,3)))
        available=sorted(set(range(1,cap+1))-set(starts)-set(goals))
        donors=sorted(rng.sample(available,min(len(available),rng.randint(2,6))))
        r=rng.randint(0,min(3,len(donors)));k=rng.randrange(4)
        old=rng.sample(donors,rng.randint(0,len(donors)));oldcap=rng.randint(0,len(old))
        p=Puzzle('case',starts,goals,cap,48)
        for part in range(2):
            possible=any(bfs(Puzzle('expanded',starts,goals+group,cap,48),k)
                         for j,group in enumerate(combinations(donors,r)) if j%2==part and len(set(group)&set(old))<=oldcap)
            result,*_=run(binary,p,donors,r,k,part,2,1000000,old,oldcap)
            require(result==('FOUND' if possible else 'UNSAT_REGION'),'small-domain disagreement')
            n+=1;positive+=possible
    record=json.loads((HERE/'small-audit.json').read_bytes())
    require((n,positive,n-positive)==(record['decisions'],record['found'],record['unsat']),'small audit counters')
    return n


def official_controls(binary,p,reference,jobs):
    doc=json.loads((HERE/'official-sample-audit.json').read_bytes())
    rows=list(doc['rows'])
    held=json.loads((HERE/'independent-audit.json').read_bytes())['additional_native_generic_comparisons']
    rows.extend({'selected':r['selected'],'k':3,'result':r['reference'],'our_nodes':r['native_nodes']} for r in held)
    def one(row):
        g,k=row['selected'],row['k']
        result,*_,nodes=run(binary,p,g,len(g),k,0,1,3000000)
        require(result==('FOUND' if row['result']=='FOUND' else 'UNSAT_REGION') and nodes==row['our_nodes'],'official subset')
        if reference:
            goals=tuple(sorted(set(p.targets)|set(g)))
            stream=[p.limit,len(p.seeds),len(goals),k,15000000,*p.seeds,*goals]
            raw=subprocess.run([str(reference.resolve()),'--original','0','1'],input=' '.join(map(str,stream))+'\n',
                               capture_output=True,text=True,check=True).stdout.splitlines()
            require(raw[0].split()[0]==row['result'],'independent traversal disagreement')
    with ThreadPoolExecutor(jobs)as pool:list(pool.map(one,rows))
    return len(rows)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--puzzles',type=Path,required=True);ap.add_argument('--binary',type=Path,required=True)
    ap.add_argument('--jobs',type=int,default=4);ap.add_argument('--audit',action='store_true')
    ap.add_argument('--max-new',type=int,choices=(1,2,3),default=3,help='replay all exclusions up to this many new values')
    ap.add_argument('--reference-binary',type=Path,help='also independently search the official positive/negative controls')
    ap.add_argument('--operations-binary',type=Path,help='run all-domain direct-arithmetic controls from operations.cpp')
    a=ap.parse_args();require(a.jobs>=1,'positive jobs required')
    donors=json.loads((HERE/'parents.json').read_bytes())
    require(sha256(a.puzzles)==donors['official_puzzles_sha256'],'wrong official inputs')
    p=next(x for x in read_puzzles(a.puzzles) if x.id==donors['id'])
    union=set()
    for r in donors['parents']:
        helpers={op.output for op in replay(p,r['program'])}-set(p.seeds)-set(p.targets)
        require(sorted(helpers)==r['helpers'] and check(p,r['program'])==r['steps'],'parent did not replay')
        union.update(helpers)
    require(len(donors['parents'])==5 and sorted(union)==donors['union'] and len(union)==20,'wrong donor union')
    if a.operations_binary:
        payload=[p.limit,len(p.seeds),len(p.targets),len(union),*p.seeds,*p.targets,*sorted(union)]
        counts=subprocess.run([str(a.operations_binary.resolve())],input=' '.join(map(str,payload))+'\n',
                              text=True,capture_output=True,check=True).stdout.strip()
        require(counts=='3366864 1496384 120','direct forward operation audit')
        print('complete operation, one-step and closure controls:',counts,flush=True)
    fixed=ROOT/'proofs/local/proofs/helper-wave17.json'
    require(sha256(fixed)=='bfd7930400c7aaba76a7e2b9df1101df55e1da83e4d9fe336bb68e0de5f0eb4a','independent 22-step lower bound')
    source=json.loads((HERE/'small-audit.json').read_bytes())
    require(sha256(HERE/'bundle_exact.cpp')==source['cpp_sha256'],'changed native source')
    stages=[('one-new.json',1,16,171754),('two-new.json',2,32,9645718),('three-new.json',3,256,557154081)]
    for name,expected_k,expected_shards,expected_nodes in stages[:a.max_new]:
        doc=json.loads((HERE/name).read_bytes());s=doc['protocol'];n=s['shards'];r=s['exact_donor_requirement'];k=s['unrestricted_new_budget']
        expect=comb(len(union),r);cells=doc['records']
        require(s['official_sha256']==donors['official_puzzles_sha256'] and
                s['sources_sha256']==donors['frozen_experiment_sha256'] and s['binary_sha256']==source['binary_sha256'] and
                k==expected_k and r==10-expected_k and n==expected_shards and sum(c['nodes'] for c in cells)==expected_nodes and
                s['donors']==sorted(union) and s['helper_limit']==r+k==10 and s['selected_old_limit']>=r and
                s['existing_upper']==23 and doc['status']=='UNSAT_REGION' and len(cells)==n and
                sorted(c['shard'] for c in cells)==list(range(n)),'receipt metadata')
        def cell(c):
            i=c['shard'];count=(expect+n-1-i)//n
            actual=run(a.binary,p,s['donors'],r,k,i,n,s['node_budget_per_subset'],s['old'],s['selected_old_limit'])
            require(actual==('UNSAT_REGION',expect,count,count,0,c['nodes']) and c['shards']==n and
                    c['tested']==c['excluded']==count and c['unknown']==0 and c['status']=='UNSAT_REGION','native replay mismatch')
        with ThreadPoolExecutor(a.jobs)as pool:list(pool.map(cell,cells))
        require(doc['excluded']==doc['tested']==expect and doc['unknown']==0,'region is incomplete')
        print(f'{name}: {expect} subsets, {n} shards, all exhausted',flush=True)
    if a.audit or a.reference_binary:
        print('small-domain controls',small_controls(a.binary))
        print('official controls',official_controls(a.binary,p,a.reference_binary,a.jobs))


if __name__=='__main__':main()
