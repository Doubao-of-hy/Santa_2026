"""Rebuild the verified K4 and subset lower-bound projection from a fixed parent table."""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
GIT = HERE.parent
BASE = 'd3317babb7d530c031bde7df6f56d00b0247f85d'
FIELDS = ('id', 'local_lower', 'external_lower', 'certified_lower', 'winning_lower_source')
K4 = 'distinct-helper-edges/full-certificates.json'
SUBSET = 'subset-capacity/verified.json'
PARENT = 'evidence/upstream-95780b7.json'
RECEIPT = 'evidence/combined-arithmetic-36882.json'

def sha(blob):
    return hashlib.sha256(blob).hexdigest()

def projection(rows):
    return sha(''.join(','.join(row[k] for k in FIELDS)+'\n' for row in rows).encode())

def rebuild():
    original = subprocess.check_output(['git','show', BASE+':collaboration/puzzle-bounds.csv'], cwd=GIT)
    rows = list(csv.DictReader(io.StringIO(original.decode())))
    prior = json.loads((HERE/PARENT).read_bytes())
    first = json.loads((HERE/K4).read_bytes())
    second = json.loads((HERE/SUBSET).read_bytes())
    if sha(original) != first['base_table_sha256'] or sha(original) != second['published_table_sha256']:
        raise ValueError('A proof was computed from a different table')
    if first['official_sha256'] != second['puzzles_sha256'] or first['official_sha256'] != prior['official_sha256']:
        raise ValueError('Official puzzle inputs differ')
    if len(rows) != 1000 or len({r['id'] for r in rows}) != 1000 or projection(rows) != prior['lower_projection_sha256']:
        raise ValueError('Base projection mismatch')
    by_id = {r['id']:r for r in rows}
    sources = ((K4, first['rows'], 'prior', 'lower'), (SUBSET, second['rows'], 'old', 'new'))
    candidates = {}
    for path, claims, before, after in sources:
        for pid, rec in claims.items():
            previous = int(by_id[pid]['certified_lower'])
            value = rec[after]
            if rec[before] != previous or not previous < value <= int(by_id[pid]['best_verified_upper']):
                raise ValueError(f'Incompatible claim on {pid}')
            candidates.setdefault(pid, []).append((value, path))
    for pid, choices in candidates.items():
        row = by_id[pid]
        best = max(n for n, _ in choices)
        row.update(certified_lower=str(best), winning_lower_source='+'.join(path for n,path in choices if n==best))
    paths = (PARENT,K4,SUBSET,'subset-capacity/witnesses.json')
    receipt = {k:prior[k] for k in ('upstream','official_sha256','external_bounds_sha256','local_manifest_sha256')}
    total = sum(int(r['certified_lower']) for r in rows)
    receipt.update(base_commit=BASE, base_table_sha256=sha(original), parent_lower_projection_sha256=prior['lower_projection_sha256'],
                   previous_certified_lower=prior['certified_lower'], certified_lower=total,
                   count_strict_rows=len(candidates), overlapping_rows=len(first['rows'].keys() & second['rows'].keys()),
                   lower_projection_sha256=projection(rows), dependencies={p:sha((HERE/p).read_bytes()) for p in paths})
    return rows, receipt

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true', help='Update the tracked table and combined receipt.')
    args = parser.parse_args()
    proved, receipt = rebuild()
    target = HERE/'puzzle-bounds.csv'
    with target.open(encoding='utf8', newline='') as f:
        rows = list(csv.DictReader(f))
    if [r['id'] for r in rows] != [r['id'] for r in proved]:
        raise ValueError('Live puzzle IDs changed')
    wanted = receipt['lower_projection_sha256']
    live = projection(rows)
    receipt_path = HERE/RECEIPT
    if args.write:
        if live not in (wanted,receipt['parent_lower_projection_sha256']):
            raise ValueError('Live table contains other proof updates')
        for row, verified in zip(rows,proved):
            for field in FIELDS:
                row[field] = verified[field]
            gap = int(row['best_verified_upper'])-int(row['certified_lower'])
            if gap < 0:
                raise ValueError(row['id'])
            row.update(gap=str(gap), tight=str(int(gap == 0)))
        stream = io.StringIO(newline='')
        writer = csv.DictWriter(stream,fieldnames=list(rows[0]),lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
        target.write_bytes(stream.getvalue().encode())
        receipt_path.write_bytes((json.dumps(receipt,indent=2)+'\n').encode())
    elif live != wanted or json.loads(receipt_path.read_bytes()) != receipt:
        raise ValueError('Published projection or receipt did not match the rebuilt proof')
    print(f"{receipt['count_strict_rows']} unique improvements, {receipt['overlapping_rows']} overlaps, total {receipt['certified_lower']}")

if __name__=='__main__':
    main()
