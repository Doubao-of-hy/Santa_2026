"""Screen all frozen puzzles and every available depth 0..4, independently of the clique bounds."""
import argparse,csv,gzip,hashlib,io,itertools,json,math,os,subprocess
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from search import Capacity,HERE,GIT,OFFICIAL,read_puzzles,domains,maximum_deleted,supported,certificate

def one(entry):
    p,floor,recorded=entry
    missing=set(p.targets)-set(p.seeds);m=len(missing)
    answer={'id':p.id,'floor':floor,'missing':m,'stages':{}}
    if recorded['tight']:answer['skip']='certified upper equals lower';return answer
    hopeful={k for k in range(5) if (h:=floor-m-k)>=0 and maximum_deleted(m,sum(t<=min(p.seeds) for t in missing),h)>0}
    if not hopeful:answer['skip']='seed-injection ceiling';return answer
    available={0:(set(p.seeds),None)}
    if max(hopeful)>0:
        from solvers.proofs.domain_bounds import close
        last=close(set(p.seeds),set(p.targets),p.limit)
        for k,E in domains(p,max(hopeful),3500):
            available[k]=E,last;last=E
    for k in sorted(hopeful):
        h=floor-m-k
        if k not in available:
            answer['stages'][k]={'skip':'envelope cap'};continue
        E,prev=available[k]
        if k>0 and not set(p.targets)-prev:
            answer['stages'][k]={'skip':'prefix necessity unavailable'};continue
        # Cases with exactly the same depth and exclusion budget used by the first pass
        # can reuse the archived deterministic search, including zero results.
        rr=recorded.get('prior')
        if rr and (rr['k'],rr['h'])==(k,h):
            answer['stages'][k]={'reuse':True,'maxdrop':rr['maxdrop_after_envelope'],'trials':sum(v['subsets'] for v in rr['trial_counts'].values()),'witnesses':rr['verified']};continue
        base,incid=supported(p,E);u=len(incid);maxdrop=maximum_deleted(u,sum(t<=min(p.seeds) for t in incid),h)
        stats={'maxdrop':maxdrop,'unsupported':u,'size':len(E),'budget':h,'trials':0,'witnesses':[]};answer['stages'][k]=stats
        if not maxdrop:continue
        cap=Capacity(p,base,incid);allmask=(1<<u)-1;values=list(incid)
        for j in range(1,min(3,maxdrop)+1):
            for deletion in itertools.combinations(values,j):
                s=allmask^sum(cap.bits[t] for t in deletion);c=cap.ceiling(s,h);stats['trials']+=1
                if c<s.bit_count():
                    stats['witnesses'].append({'deleted':deletion,'counted':s.bit_count(),'capacity':c,'new_lower':floor+1,'h':h});break
            if stats['witnesses']:break
        if stats['witnesses']:break
    return answer

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--jobs',type=int,default=5);ap.add_argument('--register',action='store_true');args=ap.parse_args()
    initial=json.loads((HERE/'design.json').read_bytes())
    blob=subprocess.check_output(['git','-C',str(GIT),'show',initial['frozen']+':collaboration/puzzle-bounds.csv'])
    assert hashlib.sha256(blob).hexdigest()==initial['current_sha256']
    bounds={r['id']:r for r in csv.DictReader(io.StringIO(blob.decode('utf8')))}
    ps=read_puzzles(OFFICIAL);earlier=json.loads((HERE/'results.json').read_bytes());lookup={r['id']:r for r in earlier}
    prior_receipt=HERE/'first-four.json'
    primary=json.loads((prior_receipt if prior_receipt.exists() else HERE/'verified.json').read_bytes())
    base={i:max(int(r['certified_lower']),primary['rows'].get(i,{}).get('new',0)) for i,r in bounds.items()}
    desc={'frozen':initial['frozen'],'published_sum':sum(int(r['certified_lower']) for r in bounds.values()),'after_four_initial_claims':sum(base.values()),'input_sha256':initial['puzzles_sha256'],'published_table_sha256':initial['current_sha256'],'rows':len(ps),'earlier_results_sha256':hashlib.sha256((HERE/'results.json').read_bytes()).hexdigest(),'selection':'All 1000 frozen puzzles; skip previously tight rows, screen every depth 0..4 with max domain 3500 and with at least one real target outside the preceding prefix. Retain all official targets as operands. Search all surviving one-to-three deletions in each original unsupported set; stop a winning row on its first strict gain over its previously published floor or the initial four row updates. Reuse the prior search only with exactly the same row, prefix and remaining-helper budget. No change to the pair-count formula and no Turan/K4 refinement. Record any sizes beyond three the count screen does not rule out.'}
    config=HERE/'full-design.json'
    if args.register:
        assert not config.exists();config.write_text(json.dumps(desc,indent=1)+'\n',encoding='utf8');print('registered',hashlib.sha256(config.read_bytes()).hexdigest());return
    assert json.loads(config.read_bytes())==desc
    jobs=[(p,base[p.id],{'tight':int(bounds[p.id]['best_verified_upper'])==base[p.id],'prior':lookup.get(p.id)}) for p in ps]
    rows=[]
    with ProcessPoolExecutor(args.jobs) as pool:
        for row in pool.map(one,jobs,chunksize=1):
            rows.append(row)
            for k,stage in row['stages'].items():
                if stage.get('witnesses'):print(row['id'],k,stage['witnesses'],flush=True)
            if len(rows)%100==0:
                print('progress',len(rows),flush=True)
                (HERE/'full-results.json.gz').write_bytes(gzip.compress(json.dumps(rows,separators=(',',':')).encode(),mtime=0))
    assert len(rows)==1000
if __name__=='__main__':main()
