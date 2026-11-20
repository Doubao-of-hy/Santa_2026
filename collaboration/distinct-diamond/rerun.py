"""Replay just the compact manifest, given official puzzle CSV and standard-library capacity checker."""
import argparse,csv,gzip,hashlib,json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from panel import load,worker

HERE=Path(__file__).resolve().parent
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--puzzles',type=Path,required=True);ap.add_argument('--subset',type=Path,required=True);ap.add_argument('--jobs',type=int,default=5)
    args=ap.parse_args();manifest=json.loads(gzip.decompress((HERE/'inputs.json.gz').read_bytes()))
    assert hashlib.sha256(args.puzzles.read_bytes()).hexdigest()==manifest['official_sha256']
    with args.puzzles.open(encoding='utf-8-sig',newline='') as f:p={r['id']:r for r in csv.DictReader(f)}
    cases=[(p[r['id']],r['prior'],s,s) for r in manifest['rows'] for s in r['states']]
    with ProcessPoolExecutor(args.jobs,initializer=load,initargs=(args.subset,)) as pool:result=list(pool.map(worker,cases))
    saved={(r['id'],r['k']):r for r in json.loads((HERE/'panel-results.json').read_bytes())['results']}
    for r in result:
        original=saved[r['id'],r['k']]
        assert all(r[k]==v for k,v in original.items() if k!='seconds')
    print(len(result),'real states reproduced,',len({r['id'] for r in result if r['ordered']=='ABSENT'}),'rows with a dual absence')
if __name__=='__main__':main()
