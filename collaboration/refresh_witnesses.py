"""Refresh both physical witness lengths against an already replayed lower-bound table."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path.insert(0,str(ROOT))
from checkpoint import atomic_text, independent_score
from elf import check, read_puzzles, read_submission, sha256


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--puzzles',required=True,type=Path)
    parser.add_argument('--receipt',required=True,type=Path)
    args=parser.parse_args()
    evidence=json.loads(args.receipt.read_bytes())
    external_sha=sha256(ROOT/'proofs_ext/bounds.csv')
    if external_sha!=evidence['external_bounds_sha256']:
        revision=evidence['upstream']
        if not re.fullmatch(r'[0-9a-f]{40}',revision):
            raise ValueError('Expected a full proof revision')
        frozen=subprocess.check_output(['git','show',revision+':proofs_ext/bounds.csv'],cwd=ROOT)
        external_sha=hashlib.sha256(frozen).hexdigest()
    if (sha256(args.puzzles)!=evidence['official_sha256'] or
            external_sha!=evidence['external_bounds_sha256'] or
            sha256(ROOT/'proofs/local/files.sha256.json')!=evidence['local_manifest_sha256']):
        raise ValueError('Proof inputs changed; rerun proofs/local/verify.py')
    target=HERE/'puzzle-bounds.csv'
    with target.open(encoding='utf8',newline='') as stream:
        rows=list(csv.DictReader(stream))
    cols=('id','local_lower','external_lower','certified_lower','winning_lower_source')
    material=''.join(','.join(r[k] for k in cols)+'\n' for r in rows).encode()
    if hashlib.sha256(material).hexdigest()!=evidence['lower_projection_sha256']:
        raise ValueError('Published lower bounds differ from the verified projection')
    ps={p.id:p for p in read_puzzles(args.puzzles)}
    if len(rows)!=len(ps) or {r['id'] for r in rows}!=ps.keys():raise ValueError('Coverage mismatch')
    lengths=[]
    for destination in ('submission.csv','public-assisted/submission.csv'):
        f=ROOT/destination;tapes=read_submission(f);meta=json.loads(f.with_name('result.json').read_bytes())
        lens={i:check(p,tapes[i]) for i,p in ps.items()}
        if (tapes.keys()!=ps.keys() or sorted(lens.values())!=independent_score(args.puzzles,f) or
                sha256(f)!=meta['sha256'] or sum(lens.values())!=meta['instructions']):
            raise ValueError('Witnesses do not match their score receipt')
        lengths.append(lens)
    from io import StringIO
    out=StringIO(newline='')
    writer=csv.DictWriter(out,fieldnames=list(rows[0]),lineterminator='\n')
    writer.writeheader()
    for row in rows:
        i=row['id'];a,b=(s[i] for s in lengths);best=min(a,b);gap=best-int(row['certified_lower'])
        if gap<0:raise ValueError(i)
        row.update(submission_steps=a,second_submission_steps=b,best_verified_upper=best,gap=gap,tight=int(gap==0))
        writer.writerow(row)
    atomic_text(target,out.getvalue())
    print(sum(int(r['certified_lower']) for r in rows),sum(r['tight'] for r in rows),*[sum(x.values()) for x in lengths])


if __name__=='__main__':main()
