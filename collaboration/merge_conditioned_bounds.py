"""Combine a complete first-helper proof with the five independently replayed external decisions."""
import argparse
import csv
import gzip
import io
import json
from pathlib import Path
import subprocess

from merge_arithmetic_bounds import FIELDS, projection, sha

HERE = Path(__file__).resolve().parent
BASE = 'b6f68c1c72b3d3333f07198ece619143201a66b4'
UPSTREAM = '4f841d7d6f69669a6e9c5d3ed180b9e02d08960b'
PARENT = 'evidence/combined-graph-37512.json'
CLAIMS = 'distinct-diamond/conditioned-claims.json.gz'
CHECK = 'distinct-diamond/conditioned-independent.json'
EXTERNAL = 'distinct-diamond/external-replayed.json'
RECEIPT = 'evidence/combined-conditioned-external.json'

def committed(rev, name):
    return subprocess.check_output(['git','show',rev+':'+name],cwd=HERE)

def parse(raw):
    return list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))

def reconstruct(include_external=True):
    prior = json.loads((HERE/PARENT).read_bytes())
    checked = json.loads((HERE/CHECK).read_bytes())
    revision = UPSTREAM if include_external else prior['upstream']
    external = json.loads((HERE/EXTERNAL).read_bytes()) if include_external else {
        'upstream':revision, 'rows':{}, 'official_sha256':prior['official_sha256'],
        'external_bounds_sha256':prior['external_bounds_sha256']}
    raw = committed(BASE,'collaboration/puzzle-bounds.csv')
    rows = parse(raw)
    assert len(rows)==len({r['id'] for r in rows})==1000 and projection(rows)==prior['lower_projection_sha256']
    assert external['official_sha256']==checked['official_sha256']==prior['official_sha256']
    packed = (HERE/CLAIMS).read_bytes()
    assert sha(packed)==checked['certificate_sha256'] and external['upstream']==revision
    doc = json.loads(gzip.decompress(packed))
    assert doc['base']==BASE and doc['base_total']==checked['base_total']==prior['certified_lower']
    claims = doc['rows']
    assert doc['searched']==checked['searched'] and len(claims)==checked['verified_rows']
    old_raw = committed(prior['upstream'],'proofs_ext/bounds.csv')
    new_raw = committed(revision,'proofs_ext/bounds.csv')
    assert sha(old_raw)==prior['external_bounds_sha256'] and sha(new_raw)==external['external_bounds_sha256']
    old_ext = {r['id']:int(r['certified_lower']) for r in parse(old_raw)}
    new_ext = {r['id']:int(r['certified_lower']) for r in parse(new_raw)}
    assert set(old_ext)==set(new_ext)=={r['id'] for r in rows}
    changed = {i:v for i,v in new_ext.items() if v!=old_ext[i]}
    assert changed==external['rows'] and all(changed[i]>old_ext[i] for i in changed)
    strict = 0
    gain = 0
    for row in rows:
        i = row['id']
        old = int(row['certified_lower'])
        assert int(row['external_lower'])==old_ext[i]
        row['external_lower'] = str(new_ext[i])
        alternatives = [('proofs_ext',new_ext[i])]
        if i in claims:
            rec = claims[i]
            assert rec['id']==i and rec['prior']==old<rec['lower']==rec['witness']['result']['closed']
            alternatives.append((CLAIMS,rec['lower']))
            gain += rec['lower']-old
        best = max(old,*(v for name,v in alternatives))
        if best>int(row['best_verified_upper']):
            raise ValueError(f"Incompatible upper bound for {i}")
        if best>old:
            strict += 1
            row['winning_lower_source'] = '+'.join(n for n,v in alternatives if v==best)
            row['certified_lower'] = str(best)
    assert gain==checked['gain']
    receipt = dict(prior)
    for k in ('diamond_claims','conditioned_claims','overlap'):
        receipt.pop(k,None)
    receipt.update(upstream=revision,external_bounds_sha256=sha(new_raw),base_commit=BASE,base_table_sha256=sha(raw),
                   parent_lower_projection_sha256=prior['lower_projection_sha256'],previous_certified_lower=doc['base_total'],
                   certified_lower=sum(int(r['certified_lower']) for r in rows),strict_rows=strict,
                   conditioned_claims=len(claims),external_claims=len(changed),overlap=len(claims.keys() & changed.keys()),
                   lower_projection_sha256=projection(rows))
    dependencies = [PARENT,CLAIMS,CHECK]
    if include_external:
        dependencies.append(EXTERNAL)
    for name in dependencies:
        receipt['dependencies'][name]=sha((HERE/name).read_bytes())
    return rows,receipt

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write',action='store_true')
    parser.add_argument('--table-at',help='Verify the bounds at a historical revision')
    parser.add_argument('--conditioned-only',action='store_true',help='Verify the intermediate layer before the five external additions.')
    args=parser.parse_args()
    if args.table_at and args.write:
        parser.error('Historical tables are read-only')
    proved,receipt=reconstruct(not args.conditioned_only)
    receipt_path=HERE/('evidence/conditioned-37916.json' if args.conditioned_only else RECEIPT)
    target=HERE/'puzzle-bounds.csv'
    source=committed(args.table_at,'collaboration/puzzle-bounds.csv') if args.table_at else target.read_bytes()
    live=parse(source)
    assert [r['id'] for r in live]==[r['id'] for r in proved]
    current=projection(live)
    if args.write:
        accepted={receipt['parent_lower_projection_sha256'],receipt['lower_projection_sha256']}
        if not args.conditioned_only:
            accepted.add(reconstruct(False)[1]['lower_projection_sha256'])
        assert current in accepted
        for row,p in zip(live,proved):
            for field in FIELDS:
                row[field]=p[field]
            gap=int(row['best_verified_upper'])-int(row['certified_lower'])
            assert gap>=0
            row.update(gap=gap,tight=int(gap==0))
        buf=io.StringIO(newline='')
        w=csv.DictWriter(buf,fieldnames=list(live[0]),lineterminator='\n')
        w.writeheader()
        w.writerows(live)
        target.write_bytes(buf.getvalue().encode())
        receipt_path.write_bytes((json.dumps(receipt,indent=2)+'\n').encode())
    else:
        assert current==receipt['lower_projection_sha256'] and json.loads(receipt_path.read_bytes())==receipt
    print(receipt['certified_lower'],receipt['strict_rows'],receipt['overlap'])

if __name__=='__main__':
    main()
