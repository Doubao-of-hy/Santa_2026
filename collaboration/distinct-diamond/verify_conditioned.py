"""Independently reconstruct each winning helper partition and check every leaf's integer capacity."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import csv
import gzip
import hashlib
import importlib.util
import io
import itertools
import json
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
def sha(b):return hashlib.sha256(b).hexdigest()
def stamp(values):return sha((','.join(map(str,sorted(values)))+'\n').encode())
def packed(path):return json.loads(gzip.decompress(path.read_bytes()))
def encode(obj):return (json.dumps(obj,sort_keys=True,separators=(',',':'))+'\n').encode()
def put(path,obj):
    with path.open('wb') as f:
        with gzip.GzipFile(fileobj=f,mode='wb',filename='',mtime=0) as z:z.write(encode(obj))

def setup(repo):
    global helper
    src=repo/'collaboration/subset-capacity/verify.py'
    spec=importlib.util.spec_from_file_location('capacity_verifier',src)
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)

def check(entry):
    from ordered import calculate
    row,claim,record=entry
    outcome=claim['lower'];cap=int(row['value_limit'])
    seeds=set(json.loads(row['starting_values']));goals=set(json.loads(row['targets']))
    missing=len(goals-seeds)
    if sha(encode(record))!=claim['witness']['tree_sha256']:raise ValueError('Tree digest changed')
    tree=record['tree'];original=claim['witness']['result']
    marks={tuple(leaf['path']):leaf for leaf in original.get('leaf_proofs',[])}
    tests=[];work=[(seeds,(),tree)];seen_paths=set()
    while work:
        start,path,node=work.pop()
        closed=helper.close_once_stable(start,goals,cap)
        assert goals-closed
        if node['kind']=='partition':
            possibilities=set()
            for a,b in itertools.combinations_with_replacement(sorted(closed),2):
                possibilities.update(helper.outcomes(a,b,cap))
            possibilities-=closed
            assert not (possibilities&goals) and len(possibilities)==node['next_count'] and stamp(possibilities)==node['next_sha256']
            assert len(closed)==node['active_count'] and stamp(closed)==node['active_sha256']
            seen=set()
            for j,group in enumerate(node['groups']):
                choices=set(group['values'])
                assert choices and choices<=possibilities and not (choices&seen)
                seen.update(choices);work.append((closed|choices,(*path,j),group['proof']))
            assert seen==possibilities
            continue
        assert node['kind']=='rooted_capacity'
        k=node['k'];A,earlier=helper.envelope(closed,goals,cap,k)
        assert len(A)==node['domain_count'] and stamp(A)==node['domain_sha256'] and (k==0 or goals-earlier)
        seen_paths.add(path)
        banned=A|goals;labels=helper.choose_targets((A,banned),goals,cap)
        h=outcome-1-missing-len(path)-k
        if marks:
            leaf=marks[path]
            assert stamp(labels)==leaf['labels_sha256'] and stamp(banned)==leaf['forbidden_sha256']
        else:
            assert original.get('ordinary_only')
            leaf={'uses':'ordinary'}
        if h<0:continue
        edge_limit=None if leaf['uses']=='ordinary' or h<4 else h*h//4
        hits,_=helper.capacity(A,goals,labels,cap,h,pair_limit=edge_limit)
        assert hits<len(labels),(row['id'],path,h,hits,len(labels))
        if leaf['uses']!='ordinary':
            assert leaf['uses'] in ('leaf-negative','shared-negative')
            tests.append((labels,banned,leaf))
    assert len(seen_paths)==original['leaves'] and (not marks or seen_paths==set(marks))
    shared=[(s,f) for s,f,r in tests if r['uses']=='shared-negative']
    if shared:
        s=set.union(*(a for a,b in shared));f=set.intersection(*(b for a,b in shared))
        old=original['common']
        assert old['mobius']==old['ordered']=='ABSENT' and stamp(s)==old['labels_sha256'] and stamp(f)==old['forbidden_sha256']
        assert calculate(s,f,cap)[0]=='ABSENT'
    for labels,banned,leaf in tests:
        if leaf['uses']=='leaf-negative':
            assert leaf['proof']['mobius']==leaf['proof']['ordered']=='ABSENT' and calculate(labels,banned,cap)[0]=='ABSENT'
    return row['id'],len(seen_paths),len(tests)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo',type=Path,required=True);ap.add_argument('--puzzles',type=Path,required=True)
    ap.add_argument('--claims',type=Path,required=True);ap.add_argument('--from-batches',type=Path)
    ap.add_argument('--jobs',type=int,default=5);ap.add_argument('--summary',type=Path)
    a=ap.parse_args();repo=a.repo.resolve()
    ds=json.loads((HERE/'conditioned-design.json').read_bytes())
    def at(rev,key):return subprocess.check_output(['git','show',rev+':'+key],cwd=repo)
    cfg=json.loads((repo/'collaboration/distinct-helper-edges/conditioned-design.json').read_bytes())
    baseline={r['id']:r for r in csv.DictReader(io.StringIO(at(ds['base'],'collaboration/puzzle-bounds.csv').decode()))}
    blobs=a.puzzles.read_bytes();assert sha(blobs)==cfg['puzzles_sha256']==ds['official_sha256']
    ps={r['id']:r for r in csv.DictReader(io.StringIO(blobs.decode('utf-8-sig')))}
    trees={}
    for name,digest in cfg['packs'].items():
        raw=at(cfg['snapshot'],'proofs/local/proofs/'+name)
        assert sha(raw)==digest;trees[name]=json.loads(gzip.decompress(raw))
    if a.from_batches:
        files=[*sorted(a.from_batches.glob('pilot-*.json.gz')),*sorted(a.from_batches.glob('extension-*.json.gz'))]
        all_rows=[r for f in files for r in packed(f)]
        eligible={i for tree in trees.values() for i in tree if not int(baseline[i]['tight'])}
        assert len(all_rows)==len(eligible) and {r['id'] for r in all_rows}==eligible
        claims={r['id']:r for r in all_rows if r['lower']>r['prior']}
        doc={'base':ds['base'],'base_total':ds['baseline'],'searched':len(eligible),'rows':claims}
        put(a.claims,doc)
    doc=packed(a.claims);claims=doc['rows']
    assert doc['base']==ds['base'] and sum(int(r['certified_lower']) for r in baseline.values())==doc['base_total']==ds['baseline']
    selected=[]
    for i,r in claims.items():
        assert i==r['id'] and int(baseline[i]['certified_lower'])==r['prior']<r['lower']<=int(baseline[i]['best_verified_upper'])
        assert r['lower']==r['witness']['result']['closed']
        selected.append((ps[i],r,trees[r['witness']['pack']][i]))
    with ProcessPoolExecutor(a.jobs,initializer=setup,initargs=(repo,)) as ex:
        verified=list(ex.map(check,selected))
    delta=sum(r['lower']-r['prior'] for r in claims.values())
    summary=dict(official_sha256=sha(blobs),base_total=ds['baseline'],searched=doc['searched'],verified_rows=len(verified),
                 covered_leaves=sum(n for _,n,_ in verified),diamond_leaves=sum(n for _,_,n in verified),
                 gain=delta,combined_lower=ds['baseline']+delta,certificate_sha256=sha(a.claims.read_bytes()))
    if a.summary:a.summary.write_bytes((json.dumps(summary,indent=2)+'\n').encode())
    print(summary,flush=True)
if __name__=='__main__':main()
