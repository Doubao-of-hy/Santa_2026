"""Independently reconstruct each registered real puzzle state and compare its five-edge oracle."""
import argparse,csv,hashlib,importlib.util,json,sys,time
from concurrent.futures import ProcessPoolExecutor,as_completed
from pathlib import Path
from ordered import calculate,check_witness
HERE=Path(__file__).resolve().parent

def load(s):
    global helper
    spec=importlib.util.spec_from_file_location('projected_capacity',s/'verify.py')
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
def stamp(vals):
    return hashlib.sha256((','.join(map(str,sorted(vals)))+'\n').encode()).hexdigest()
def worker(arg):
    p,prior,state,reference=arg;begin=time.monotonic()
    i=p['id'];k=state['k'];seeds=set(json.loads(p['starting_values']));goals=set(json.loads(p['targets']));cap=int(p['value_limit'])
    allowed,earlier=helper.envelope(seeds,goals,cap,k)
    assert not k or goals-earlier
    assert ('allowed_count' not in state or len(allowed)==state['allowed_count']) and stamp(allowed)==state['allowed_sha256']
    labels=helper.choose_targets((allowed,allowed|goals),goals,cap)
    assert len(labels)==reference['target_count']
    if 'labels' in state:assert labels==set(state['labels'])
    else:assert stamp(labels)==state['labels_sha256']
    m=len(goals-seeds);h=prior-m-k
    assert h>=4 and h==reference['h']
    _,terms=helper.capacity(allowed,goals,labels,cap,h)
    edges=h*h//4
    cost=edges+min(terms['top_unary']+min(terms['top_pair_bonuses'],terms['top_degrees']//2),terms['top_mixed']//2)
    assert cost==reference['upper_capacity'] and cost<len(labels)
    status,w,stats=calculate(labels,allowed|goals,cap)
    if w:assert check_witness(w,labels,allowed|goals,cap)
    assert {status,reference['status']}!={'ABSENT','PRESENT'},(i,k,status,reference['status'])
    return {'id':i,'k':k,'remaining_helpers':h,'previous':prior,'labels':len(labels),'labels_sha256':stamp(labels),'allowed_sha256':stamp(allowed),'upper_capacity':cost,'primary':reference['status'],'ordered':status,'witness':w,'statistics':stats,'seconds':round(time.monotonic()-begin,3)}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--k4',type=Path,required=True);ap.add_argument('--subset',type=Path,required=True);ap.add_argument('--puzzles',required=True,type=Path);ap.add_argument('--reference',required=True,type=Path);ap.add_argument('--out',type=Path,default=HERE/'panel-results.json');ap.add_argument('--jobs',type=int,default=5)
    args=ap.parse_args();b=args.puzzles.read_bytes();assert hashlib.sha256(b).hexdigest()=='b0c70d849eca078a0e1cf9a4f7b47fd40b7435663f6f84de6725f84724500428'
    with args.puzzles.open(encoding='utf-8-sig',newline='') as f:ps={r['id']:r for r in csv.DictReader(f)}
    ref=json.loads(args.reference.read_bytes());cases=[];ids=set();result=[]
    for name,path in [('development','screen.json'),('holdout','replicate.json')]:
        original={r['id']:r for r in json.loads((args.k4/path).read_bytes())}
        for row in ref[name]:
            i=row['id'];ids.add(i);src={s['k']:s for s in original[i]['states']}
            for s in row['states']:cases.append((ps[i],row['baseline'],src[s['k']],s))
    with ProcessPoolExecutor(args.jobs,initializer=load,initargs=(args.subset,)) as ex:
        futures={ex.submit(worker,c):c for c in cases}
        for f in as_completed(futures):
            v=f.result();result.append(v)
            if len(result)%6==0:print(len(result),'/',len(cases),v['id'],v['ordered'],v['seconds'],flush=True)
    result.sort(key=lambda x:(x['id'],x['k']))
    agree=sum(r['primary']==r['ordered'] for r in result);ids_ok={r['id'] for r in result if r['primary']==r['ordered']=='ABSENT'}
    out={'official_sha256':hashlib.sha256(b).hexdigest(),'reference_sha256':hashlib.sha256(args.reference.read_bytes()).hexdigest(),'panel_rows':len(ids),'eligible_states':len(result),'exact_status_agreements':agree,'dual_absent_rows':len(ids_ok),'results':result}
    args.out.write_text(json.dumps(out,indent=1)+'\n',encoding='utf8');print('completed',len(ids),len(result),agree,len(ids_ok),flush=True)
if __name__=='__main__':main()
