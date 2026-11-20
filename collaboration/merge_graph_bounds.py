"""Reconstruct two additional certificate layers against the 36,882-step snapshot."""
import argparse
import csv
import gzip
import io
import json
from pathlib import Path
import subprocess

from merge_arithmetic_bounds import FIELDS, projection, sha

HERE = Path(__file__).resolve().parent
BASE = '6824dffc90d4d60b80e02516edfcce816a850636'
PARENT = 'evidence/combined-arithmetic-36882.json'
CONDITIONED = 'distinct-helper-edges/conditioned-full-certificates.json'
DIAMOND = 'distinct-diamond/claims.json.gz'
RECEIPT = 'evidence/combined-graph-37512.json'

def rebuild():
    parent = json.loads((HERE/PARENT).read_bytes())
    original = subprocess.check_output(['git','show',BASE+':collaboration/puzzle-bounds.csv'],cwd=HERE)
    rows = list(csv.DictReader(io.StringIO(original.decode())))
    by_id = {r['id']:r for r in rows}
    if len(rows)!=len(by_id) or len(rows)!=1000 or projection(rows)!=parent['lower_projection_sha256']:
        raise ValueError('The fixed parent table differs from its proof')
    old = {i:int(row['certified_lower']) for i,row in by_id.items()}
    cond = json.loads((HERE/CONDITIONED).read_bytes())
    dia = json.loads(gzip.decompress((HERE/DIAMOND).read_bytes()))
    if len(dia['batches'])!=31 or len({b['number'] for b in dia['batches']})!=31 or sum(b['source_rows'] for b in dia['batches'])!=980:
        raise ValueError('Expected the 31 completed batches')
    if dia['design']['official_sha256']!=parent['official_sha256'] or dia['design']['baseline_total']!=sum(old.values()):
        raise ValueError('Input baseline mismatch')
    layers=({}, {})
    for c in dia['claims']:
        i=c['id']
        if i in layers[0] or old[i]!=c['prior'] or c['primary']!='ABSENT' or c['evidence']['ordered']!='ABSENT' or c['evidence']['cap']!=c['capacity'] or c['capacity']>=c['label_count']:
            raise ValueError(f'Invalid diamond claim on {i}')
        layers[0][i]=c['established']
    plain=json.loads((HERE/'distinct-helper-edges/full-certificates.json').read_bytes())
    if cond['plain_certificates_sha256']!=sha((HERE/'distinct-helper-edges/full-certificates.json').read_bytes()):
        raise ValueError('The conditioned proof starts from a different set of claims')
    for i,c in cond['rows'].items():
        if c['prior']>old[i] or i in plain['rows'] and c['prior']!=plain['rows'][i]['lower']:
            raise ValueError(f'Invalid conditioned baseline on {i}')
        layers[1][i]=c['lower']
    count=0
    for i,row in by_id.items():
        best=max(old[i],layers[0].get(i,0),layers[1].get(i,0))
        if best>int(row['best_verified_upper']):
            raise ValueError(f'Lower bound exceeds verified physical upper on {i}')
        if best>old[i]:
            count+=1
            row['certified_lower']=str(best)
            row['winning_lower_source']='+'.join(p for layer,p in zip(layers,(DIAMOND,CONDITIONED)) if layer.get(i)==best)
    total=sum(int(r['certified_lower']) for r in rows)
    receipt={k:parent[k] for k in ('upstream','official_sha256','external_bounds_sha256','local_manifest_sha256')}
    receipt.update(base_commit=BASE,base_table_sha256=sha(original),parent_lower_projection_sha256=parent['lower_projection_sha256'],
                   previous_certified_lower=sum(old.values()),certified_lower=total,strict_rows=count,
                   diamond_claims=len(layers[0]),conditioned_claims=len(layers[1]),overlap=len(layers[0].keys()&layers[1].keys()),
                   lower_projection_sha256=projection(rows),dependencies=dict(parent['dependencies']))
    for path in (PARENT,DIAMOND,CONDITIONED):
        receipt['dependencies'][path]=sha((HERE/path).read_bytes())
    return rows,receipt

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--write',action='store_true')
    args=ap.parse_args()
    proved,receipt=rebuild()
    table=HERE/'puzzle-bounds.csv'
    with table.open(encoding='utf8',newline='') as f:
        live=list(csv.DictReader(f))
    if [r['id'] for r in proved]!=[r['id'] for r in live]:raise ValueError('Live puzzle IDs changed')
    wanted=receipt['lower_projection_sha256']
    if args.write:
        if projection(live) not in (wanted,receipt['parent_lower_projection_sha256']):
            raise ValueError('Concurrent proof update')
        for r,p in zip(live,proved):
            for k in FIELDS:r[k]=p[k]
            gap=int(r['best_verified_upper'])-int(r['certified_lower'])
            if gap<0:raise ValueError(r['id'])
            r.update(gap=str(gap),tight=str(int(gap==0)))
        buf=io.StringIO(newline='');writer=csv.DictWriter(buf,fieldnames=list(live[0]),lineterminator='\n')
        writer.writeheader();writer.writerows(live)
        table.write_bytes(buf.getvalue().encode())
        (HERE/RECEIPT).write_bytes((json.dumps(receipt,indent=2)+'\n').encode())
    elif projection(live)!=wanted or json.loads((HERE/RECEIPT).read_bytes())!=receipt:
        raise ValueError('Published bounds differ from the reconstruction')
    print(receipt['strict_rows'],receipt['certified_lower'])

if __name__=='__main__':
    main()
