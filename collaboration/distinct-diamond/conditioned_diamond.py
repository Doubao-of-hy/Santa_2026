"""Price and certify diamond-free bounds inside every branch of a previously verified tree."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys

def paths(repo):
    sys.path[:0]=[str(repo/'collaboration/distinct-helper-edges'),str(repo/'collaboration/distinct-diamond'),str(repo)]

def edge_limit(h):
    return h*(h-1)//2 if h<4 else h*h//4

def priced(p,allowed):
    from screen import capacities
    return capacities(p,allowed,edge_limit)

def evidence(labels,forbidden,limit):
    from conditioned import stamp
    from diamonds import find_diamond
    from ordered import calculate
    a,w=find_diamond(labels,forbidden,limit)
    b,w2,stats=calculate(labels,forbidden,limit)
    if {a,b}=={'PRESENT','ABSENT'}:raise ValueError('Arithmetic oracles disagree')
    return dict(mobius=a,ordered=b,labels=len(labels),labels_sha256=stamp(labels),forbidden=len(forbidden),
                forbidden_sha256=stamp(forbidden),ordered_counts=stats,mobius_witness=w,ordered_witness=w2)

def test(task):
    repo,p,records,prior,upper=task
    paths(repo)
    from conditioned import canonical,check_tree,sha
    best=prior
    winning=None
    for pack,tree in records:
        checked=check_tree(p,tree,best,priced,evidence)
        if checked['closed']>best:
            best=checked['closed']
            winning={'pack':pack,'tree_sha256':sha(canonical(tree)),'result':checked}
    if best>upper:raise ValueError(p.id)
    return dict(id=p.id,prior=prior,lower=best,witness=winning)

def load_inputs(repo,puzzles,design):
    paths(repo)
    from elf import read_puzzles
    from conditioned import load
    cfg,trees,_,_=load(repo,puzzles,repo/'collaboration/distinct-helper-edges')
    raw=subprocess.check_output(['git','show',design['base']+':collaboration/puzzle-bounds.csv'],cwd=repo)
    original={r['id']:r for r in csv.DictReader(io.StringIO(raw.decode()))}
    assert len(original)==1000 and sum(int(r['certified_lower']) for r in original.values())==design['baseline']
    assert hashlib.sha256(puzzles.read_bytes()).hexdigest()==design['official_sha256']==cfg['puzzles_sha256']
    pilot=[r['id'] for r in cfg['pilot'] if not int(original[r['id']]['tight'])]
    other=[k for k in sorted(trees) if k not in pilot and not int(original[k]['tight'])]
    return {p.id:p for p in read_puzzles(puzzles)},trees,original,pilot,other

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('repo','puzzles','out'):ap.add_argument('--'+name,type=Path,required=True)
    ap.add_argument('--jobs',type=int,default=4)
    ap.add_argument('--phase',choices=('pilot','extension'),required=True)
    a=ap.parse_args()
    repo=a.repo.resolve();a.out.mkdir(exist_ok=True,parents=True)
    design=json.loads((repo/'collaboration/distinct-diamond/conditioned-design.json').read_bytes())
    ps,trees,original,pilot,other=load_inputs(repo,a.puzzles,design)
    ids=pilot if a.phase=='pilot' else other
    if a.phase=='extension':
        proof=json.loads(gzip.decompress((a.out/'pilot-00.json.gz').read_bytes()))
        if not any(row['lower']>row['prior'] for row in proof):raise ValueError('No pilot gain')
    with ProcessPoolExecutor(a.jobs) as pool:
        for start in range(0,len(ids),32):
            file=a.out/f'{a.phase}-{start//32:02}.json.gz'
            chosen=ids[start:start+32]
            if file.is_file():
                rows=json.loads(gzip.decompress(file.read_bytes()))
                assert [r['id'] for r in rows]==chosen
            else:
                rows=list(pool.map(test,[(repo,ps[k],trees[k],int(original[k]['certified_lower']),int(original[k]['best_verified_upper'])) for k in chosen]))
                blob=(json.dumps(rows,separators=(',',':'))+'\n').encode()
                with file.with_suffix('.tmp').open('wb') as f:
                    with gzip.GzipFile(fileobj=f,mode='wb',filename='',mtime=0) as z:z.write(blob)
                file.with_suffix('.tmp').replace(file)
            print(a.phase,start,len(rows),sum(r['lower']-r['prior'] for r in rows),flush=True)
if __name__=='__main__':main()
