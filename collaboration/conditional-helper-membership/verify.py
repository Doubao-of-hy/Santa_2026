"""Check every decision leaf afresh and compare small-domain capacities with direct arithmetic."""
import argparse,csv,gzip,hashlib,importlib.util,io,itertools,json,random,subprocess,sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]
sys.path[:0]=[str(REPO),str(HERE.parent/'distinct-diamond')]
from ordered import calculate
spec=importlib.util.spec_from_file_location('integer_checker',HERE.parent/'subset-capacity/verify.py')
mathcheck=importlib.util.module_from_spec(spec);spec.loader.exec_module(mathcheck)

def sha(b):return hashlib.sha256(b).hexdigest()
def stamp(v):return sha((','.join(map(str,sorted(v)))+'\n').encode())
def max_edges(h):return h*(h-1)//2 if h<=3 else h*h//4

def verify_one(task):
    row,receipt,c,base=task
    starts=set(json.loads(row['starting_values']));goals=set(json.loads(row['targets']));cap=int(row['value_limit'])
    k=receipt['k'];h=receipt['h'];missing=len(goals-starts)
    assert base==receipt['old']==missing+k+h and h>=c['excluded_budget'] and k==c['k']
    A,earlier=mathcheck.envelope(starts,goals,cap,k)
    assert not k or goals-earlier
    S=mathcheck.choose_targets((A,A|goals),goals,cap)
    assert stamp(A)==c['evidence']['allowed_sha256'] and stamp(S)==c['evidence']['label_sha256']
    assert calculate(S,A|goals,cap)[0]=='ABSENT'
    todo=[(receipt['tree'],frozenset(),frozenset(),h)];leaves=0
    while todo:
        node,yes,no,budget=todo.pop()
        if 'value' in node:
            x=node['value']
            assert 1<=x<=cap and budget>0 and x not in A|goals|yes|no and set(node)=={'value','included','excluded'}
            todo.append((node['included'],yes|{x},no,budget-1))
            todo.append((node['excluded'],yes,no|{x},budget))
        else:
            assert set(node)=={'needed','ceiling'}
            free=A|yes
            remaining=mathcheck.choose_targets((free,free|goals),goals,cap)
            assert remaining<=S and (A|goals)<=(free|goals|no)
            bound,_=mathcheck.capacity(free,goals,remaining,cap,budget,pair_limit=max_edges(budget),excluded=no)
            assert bound<=node['ceiling']<len(remaining)==node['needed'],(row['id'],bound,node)
            leaves+=1
    assert leaves==receipt['closed_leaves']
    return row['id'],dict(previous=base,certified_lower=base+1,verified_leaves=leaves)

def small():
    from search import Profile
    from diamonds import brute
    from collections import Counter
    rng=random.Random(20261120);counts=Counter()
    for n in range(9,19):
        for _ in range(12):
            vals=list(range(1,n+1));goals=set(rng.sample(vals,rng.randint(3,6)))
            A=set(rng.sample([v for v in vals if v not in goals],1))
            model=Profile(A,goals,n)
            S=set(model.labels);others=set(vals)-A-goals
            diamond=brute(S,A|goals,n)=='PRESENT'
            sample=sorted(others);rng.shuffle(sample);yes=frozenset(sample[:rng.randrange(2)])
            no=frozenset(sample[2:2+rng.randrange(3)])
            for h in range(5):
                if h==4 and diamond:continue
                free=A|set(yes)
                remaining=mathcheck.choose_targets((free,free|goals),goals,n)
                expected,_=mathcheck.capacity(free,goals,remaining,n,h,brute=True,pair_limit=max_edges(h),excluded=no)
                count,fast,_=model.estimate(tuple(sorted(yes)),no,h)
                assert len(remaining)==count and expected<=fast
                for picked in itertools.combinations(sorted(others-yes-no),min(h,len(others-yes-no))):
                    available=free|set(picked)|(goals-remaining)
                    generated=mathcheck.close_once_stable(available,remaining,n)&remaining
                    assert len(generated)<=expected
                    counts['helper_sets']+=1
                counts['capacity_checks']+=1
            counts['domains']+=1
    return dict(counts)

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--puzzles',required=True,type=Path)
    ap.add_argument('--claims',required=True,type=Path);ap.add_argument('--output',required=True,type=Path)
    ap.add_argument('--jobs',type=int,default=4);a=ap.parse_args()
    ds=json.loads((HERE/'design.json').read_bytes());claim= json.loads(a.claims.read_bytes())
    src=(REPO/ds['claims']).read_bytes();assert sha(src)==ds['claims_sha256']
    prior=json.loads(gzip.decompress(src));original=a.puzzles.read_bytes();assert sha(original)==prior['design']['official_sha256']
    raw=subprocess.check_output(['git','show',ds['base']+':collaboration/puzzle-bounds.csv'],cwd=REPO)
    bs={r['id']:r for r in csv.DictReader(io.StringIO(raw.decode()))}
    puzzles={r['id']:r for r in csv.DictReader(io.StringIO(original.decode('utf-8-sig')))}
    poolclaims={r['id']:r for r in prior['claims']}
    eligible=sorted((i for i in poolclaims if not int(bs[i]['tight'])),key=lambda i:sha((ds['salt']+i).encode()))
    group=claim['group']
    if group=='pilot':ids=eligible[:ds['pilot']]
    elif group=='extension':ids=eligible[ds['pilot']:ds['pilot']+64]
    else:
        number=int(group.removeprefix('block-'));assert number>=0 and group==f'block-{number:02}'
        start=ds['pilot']+64+number*64;ids=eligible[start:start+64]
        assert ids
    assert [r['id'] for r in claim['rows']]==ids and claim['base']==ds['base']
    wins=[(puzzles[r['id']],r,poolclaims[r['id']],int(bs[r['id']]['certified_lower'])) for r in claim['rows'] if r['tree']]
    with ProcessPoolExecutor(a.jobs) as ex:result=dict(ex.map(verify_one,wins))
    out=dict(small=small(),base=ds['base'],official_sha256=sha(original),claims_sha256=sha(a.claims.read_bytes()),examined=len(ids),wins=result)
    a.output.write_bytes((json.dumps(out,indent=2)+'\n').encode());print(out['small'],len(result),flush=True)
if __name__=='__main__':main()
