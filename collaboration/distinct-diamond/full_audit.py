"""Replay full-domain arithmetic diamond certificates and persist independent batch checkpoints."""
import argparse,csv,gzip,hashlib,importlib.util,io,json,os,subprocess,time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from ordered import calculate

HERE=Path(__file__).resolve().parent
CAPACITY_COMMIT='6824dffc90d4d60b80e02516edfcce816a850636'
PRIMARY_COMMIT='2894c28cb72f232d043dba22fe294212b5a38984'
PRIMARY_SHA='38bf08a01551f1d79b5c41d748d1a95398be9ac964854b5441c4a183d05462db'
def sha(blob):return hashlib.sha256(blob).hexdigest()
def stamp(items):return sha((','.join(map(str,sorted(items)))+'\n').encode())
def compressed(obj):return gzip.compress(json.dumps(obj,separators=(',',':'),sort_keys=True).encode(),mtime=0)
def unpack(p):
    b=p.read_bytes()
    return json.loads(gzip.decompress(b) if p.suffix=='.gz' else b)
def put(path,data):
    tmp=path.with_suffix('.tmp');tmp.write_bytes(data);os.replace(tmp,path)
def setup(repo):
    global checks
    f=repo/'collaboration/subset-capacity/verify.py'
    import types
    content=git(repo,CAPACITY_COMMIT,'collaboration/subset-capacity/verify.py')
    checks=types.ModuleType('capacity_checker_for_ordered_diamonds')
    checks.__file__=str(f)
    exec(compile(content,str(f),'exec'),checks.__dict__)
def git(repo,rev,name):
    return subprocess.check_output(['git','-C',str(repo),'show',rev+':'+name])
def context(repo,puzzles,meta):
    data=puzzles.read_bytes();assert sha(data)==meta['official_sha256']
    ps={r['id']:r for r in csv.DictReader(io.StringIO(data.decode('utf-8-sig')))}
    blob=git(repo,meta['base'],'collaboration/puzzle-bounds.csv')
    init={r['id']:r for r in csv.DictReader(io.StringIO(blob.decode()))}
    k4b=git(repo,CAPACITY_COMMIT,'collaboration/distinct-helper-edges/full-certificates.json')
    subb=git(repo,CAPACITY_COMMIT,'collaboration/subset-capacity/verified.json')
    k4=json.loads(k4b)['rows'];subset=json.loads(subb)['rows']
    floors={i:max(int(r['certified_lower']),k4.get(i,{}).get('lower',0),subset.get(i,{}).get('new',0)) for i,r in init.items()}
    assert sum(floors.values())==meta['baseline_total']
    order=sorted((i for i,r in init.items() if floors[i]<int(r['best_verified_upper'])),key=lambda i:hashlib.sha256((meta['order_seed']+i).encode()).digest())
    return ps,floors,order,{i:int(r['best_verified_upper']) for i,r in init.items()},{'published_table':sha(blob),'k4_file':sha(k4b),'subset_file':sha(subb)}
def check(args):
    raw,c,upper=args;i=c['id'];k=c['k'];h=c['excluded_budget']
    seeds=set(json.loads(raw['starting_values']));goals=set(json.loads(raw['targets']));limit=int(raw['value_limit'])
    m=len(goals-seeds)
    assert c['primary']=='ABSENT' and i==raw['id'] and 0<=k<=4 and 4<=c['initial_budget']<=h and c['prior']<c['established']<=upper
    assert m+k+c['initial_budget']>=c['prior'] and m+k+h+1==c['established']
    allowed,earlier=checks.envelope(seeds,goals,limit,k)
    assert len(allowed)<=3500 and (k==0 or bool(goals-earlier))
    base=allowed|goals;S=checks.choose_targets((allowed,base),goals,limit)
    assert len(S)==c['label_count']
    _,terms=checks.capacity(allowed,goals,S,limit,h)
    ceiling=h*h//4+min(terms['top_unary']+min(terms['top_pair_bonuses'],terms['top_degrees']//2),terms['top_mixed']//2)
    assert ceiling==c['capacity'] and ceiling<len(S)
    status,w,stats=calculate(S,base,limit)
    if status!='ABSENT':raise AssertionError((i,k,h,status,w))
    evidence={'ordered':'ABSENT','allowed_count':len(allowed),'allowed_sha256':stamp(allowed),'label_sha256':stamp(S),'remaining_budget':h,'counted':len(S),'cap':ceiling,'terms':terms,'oracle':stats}
    return i,evidence
def select(rows,floors,order,number,sz):
    assert [r['id'] for r in rows]==order[(number-1)*sz:number*sz]
    claims=[];n=0
    for r in rows:
        i=r['id'];assert floors[i]==r['prior']<=r['best']
        if r['best']==r['prior']:continue
        viable=[s for s in r['states'] if s['status']=='ABSENT' and s['established']==r['best']]
        s=min(viable,key=lambda s:(s['k'],s['excluded_budget']))
        claims.append({'id':i,'prior':r['prior'],'established':r['best'],'k':s['k'],'initial_budget':s['h'],'excluded_budget':s['excluded_budget'],'capacity':s['final_cap'],'label_count':s['unsupported'],'primary':s['status']})
        n+=r['best']-r['prior']
    return claims,n
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--repo',type=Path,required=True);ap.add_argument('--puzzles',type=Path,required=True)
    ap.add_argument('--claims',type=Path,help='Replay a portable manifest; the first primary scan files are not required.')
    ap.add_argument('--source',type=Path);ap.add_argument('--design',type=Path);ap.add_argument('--out',type=Path,default=HERE/'claims.json.gz')
    ap.add_argument('--checkpoints',type=Path,default=HERE/'batches');ap.add_argument('--first',type=int,default=1);ap.add_argument('--last',type=int,default=31);ap.add_argument('--jobs',type=int,default=6)
    args=ap.parse_args()
    if args.claims:
        package=unpack(args.claims);meta=package['design']
    else:
        if not args.source or not args.design:ap.error('provide --claims or --source and --design')
        meta=unpack(args.design)
    ps,floors,order,uppers,hashes=context(args.repo,args.puzzles,meta)
    if args.claims:
        assert hashes==package['baseline_files'] and package['official_rows']==len(order)
        rows=package['claims'];assert len(rows)==len({c['id'] for c in rows})
        for c in rows:assert c['prior']==floors[c['id']]
        primary_bytes=git(args.repo,PRIMARY_COMMIT,'collaboration/distinct-diamond/full-scan.json.gz')
        assert sha(primary_bytes)==PRIMARY_SHA
        raw_source=json.loads(gzip.decompress(primary_bytes));expected=[]
        bnums=[b['number'] for b in package['batches']]
        assert len(set(bnums))==len(bnums) and bnums==sorted(bnums)
        for b in package['batches']:
            n=b['number'];raw=raw_source[f'batch-{n:02}.json']
            assert sha((json.dumps(raw,separators=(',',':'))+'\n').encode())==b['primary_sha256']
            expected_claims,gain=select(raw,floors,order,n,meta['batch_size'])
            assert len(raw)==b['source_rows'] and gain==b['strict_gain']
            expected.extend(expected_claims)
        assert expected==[{k:v for k,v in c.items() if k!='evidence'} for c in rows]
        assert sum(c['established']-c['prior'] for c in rows)==sum(b['strict_gain'] for b in package['batches'])
        with ProcessPoolExecutor(args.jobs,initializer=setup,initargs=(args.repo,)) as pool:
            for (i,ev),c in zip(pool.map(check,[(ps[c['id']],c,uppers[c['id']]) for c in rows],chunksize=1),rows):
                assert i==c['id'] and ev==c['evidence']
        print('validated',len(rows),'dual certificates; gains',sum(c['established']-c['prior'] for c in rows));return
    args.checkpoints.mkdir(exist_ok=True,parents=True)
    done=[]
    with ProcessPoolExecutor(args.jobs,initializer=setup,initargs=(args.repo,)) as pool:
        for n in range(args.first,args.last+1):
            primary=args.source/f'batch-{n:02}.json'
            if not primary.exists():break
            blob=primary.read_bytes();orig=json.loads(blob);claims,gain=select(orig,floors,order,n,meta['batch_size'])
            key={'number':n,'primary_sha256':sha(blob),'source_rows':len(orig),'strict_gain':gain}
            dest=args.checkpoints/f'batch-{n:02}.json.gz'
            if dest.exists():
                previous=unpack(dest);assert all(previous[k]==v for k,v in key.items());assert [{k:v for k,v in c.items() if k!='evidence'} for c in previous['claims']]==claims
                done.append(previous);continue
            for (i,ev),c in zip(pool.map(check,[(ps[c['id']],c,uppers[c['id']]) for c in claims],chunksize=1),claims):
                assert i==c['id'];c['evidence']=ev
            batch={**key,'claims':claims};put(dest,compressed(batch));done.append(batch)
            print('dual',n,len(claims),gain,flush=True)
            package={'design':meta,'official_rows':len(order),'baseline_files':hashes,'batches':[{k:v for k,v in r.items() if k!='claims'} for r in done],'claims':[c for r in done for c in r['claims']]}
            put(args.out,compressed(package))
    if done:
        package={'design':meta,'official_rows':len(order),'baseline_files':hashes,'batches':[{k:v for k,v in r.items() if k!='claims'} for r in done],'claims':[c for r in done for c in r['claims']]}
        put(args.out,compressed(package))
if __name__=='__main__':main()
