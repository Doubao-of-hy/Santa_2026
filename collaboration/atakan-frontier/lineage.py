"""Check whether any published v15 profile reproduces the Asterios v120 row exactly."""
import argparse,csv,json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from run import HERE,ROOT,D,OFFICIAL,sha,read_puzzles,trial

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--previous',type=Path,default=ROOT/'work/creative/resume-135077/asterios119/best_programs.csv')
    ap.add_argument('--next',type=Path,default=ROOT/'work/creative/public-refresh-134321/asterios120/best_programs.csv')
    args=ap.parse_args()
    setup=json.loads((HERE/'lineage-design.json').read_bytes());k=setup['puzzle']
    def read(f,version):
        with f.open(encoding='utf-8-sig',newline='') as src:r=next(r for r in csv.DictReader(src) if r['id']==k)
        t=tuple(tuple(op) for op in json.loads(r['program']))
        assert len(t)==setup[version]['length'] and sha(json.dumps(t,separators=(',',':')).encode())==setup[version]['program_sha256']
        return t
    old,new=read(args.previous,'v119'),read(args.next,'v120')
    p=next(p for p in read_puzzles(OFFICIAL) if p.id==k)
    def run(cfg):
        arm='v15-lineage-'+cfg
        D['arms'][arm]=list(map(int,cfg.split()))
        r,t=trial(p,old,arm)
        return {'config':cfg,'steps':len(t),'matches_v120_tape':t==new,'program_sha256':sha(json.dumps(t,separators=(',',':')).encode())}
    with ThreadPoolExecutor(2) as ex:results=list(ex.map(run,setup['v15_configs']))
    (HERE/'lineage-results.json').write_text(json.dumps(results,indent=1)+'\n',encoding='utf8')
    print(results)
if __name__=='__main__':main()
