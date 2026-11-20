"""Recheck the five 4f841d7 additions against their published shard counts."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib,importlib.util,json,subprocess,sys
from pathlib import Path
IDS={'scored_0092':8,'scored_0221':8,'scored_0868':7,'scored_0914':7,'scored_0922':8}
def sha(data):return hashlib.sha256(data).hexdigest()
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('repo','puzzles','exe','out'):ap.add_argument('--'+name,type=Path,required=True)
    ap.add_argument('--jobs',type=int,default=8);a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    repo=a.repo.resolve();sys.path.insert(0,str(repo))
    from elf import read_puzzles
    spec=importlib.util.spec_from_file_location('external_search',repo/'proofs_ext/verify.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    rev=subprocess.check_output(['git','rev-parse','4f841d7'],cwd=repo,text=True).strip()
    def get(name):return subprocess.check_output(['git','show',rev+':'+name],cwd=repo)
    aggregate=json.loads(get('proofs_ext/decisions.json'));earlier=json.loads(subprocess.check_output(['git','show','d8af49a:proofs_ext/decisions.json'],cwd=repo))
    keys=lambda rs:{(x['id'],x['helpers']):x for x in rs['decisions']}
    now,before=keys(aggregate),keys(earlier)
    assert now.keys()-before.keys()==set(IDS.items()) and all(now[k]==v for k,v in before.items())
    official=a.puzzles.read_bytes();assert sha(official.replace(b'\r\n',b'\n'))==aggregate['puzzles_lf_sha256']
    ps={p.id:p for p in read_puzzles(a.puzzles)};binhash=sha(a.exe.read_bytes());claims={};tasks=[]
    for i,h in IDS.items():
        decision=json.loads(get(f'proofs_ext/decisions.d/{i}_h{h}.json'))
        assert decision==now[i,h] and not decision.get('subshards')
        assert len(set(ps[i].targets)-set(ps[i].seeds))+h+1==decision['lower_bound']
        claims[i]=decision;tasks.extend((n,i,h,j) for j,n in enumerate(decision['shard_nodes']))
    def run(task):
        n,i,h,j=task;entry=claims[i];total=len(entry['shard_nodes'])
        file=a.out/f'{i}-{j:03}.json';context={'revision':rev,'official_sha256':sha(official),'binary_sha256':binhash,'id':i,'budget':h,'shard':j,'shards':total}
        if file.is_file():
            row=json.loads(file.read_bytes());assert all(row[k]==v for k,v in context.items()) and row['status']=='UNSAT' and row['nodes']==n
            return row
        status,count,last=mod.query(a.exe,ps[i],h,entry['max_nodes_per_shard'],j,total)
        assert status=='UNSAT' and count==n
        row=dict(**context,status=status,nodes=count,terminal_candidates=last)
        temp=file.with_suffix('.tmp');temp.write_bytes((json.dumps(row)+'\n').encode());temp.replace(file)
        return row
    rows=[]
    with ThreadPoolExecutor(a.jobs) as pool:
        for future in as_completed([pool.submit(run,x) for x in sorted(tasks)]):
            rows.append(future.result())
            if len(rows)%20==0:print(len(rows),'/',len(tasks),flush=True)
    assert len(rows)==len(tasks)
    for i,rec in claims.items():assert sum(r['terminal_candidates'] for r in rows if r['id']==i)==rec['terminal_candidates']
    result=dict(upstream=rev,official_sha256=sha(official),external_bounds_sha256=sha(get('proofs_ext/bounds.csv')),binary_sha256=binhash,
                rows={i:v['lower_bound'] for i,v in claims.items()},shards=len(rows),nodes=sum(r['nodes'] for r in rows),
                decisions=sorted(({k:v for k,v in r.items() if k in ('id','budget','shard','shards','nodes','terminal_candidates','status')} for r in rows),key=lambda t:(t['id'],t['shard'])))
    (a.out/'replayed.json').write_bytes((json.dumps(result,indent=1)+'\n').encode());print(result['rows'],result['shards'],result['nodes'],flush=True)
if __name__=='__main__':main()
