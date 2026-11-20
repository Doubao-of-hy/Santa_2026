"""Rebuild the per-puzzle projection from the verified helper-membership decision trees."""
import argparse
import csv
import gzip
import io
import json
from pathlib import Path
import subprocess
from merge_arithmetic_bounds import FIELDS, projection, sha

HERE=Path(__file__).resolve().parent
BASE='138be6dbe448ef824afe87ba7b17a02e2f21e8a5'
PARENT='evidence/combined-conditioned-external.json'
PACK='conditional-helper-membership'
RESULT='evidence/combined-membership.json'

def blob(rev):
    return subprocess.check_output(['git','show',rev+':collaboration/puzzle-bounds.csv'],cwd=HERE)
def parse(raw):
    return list(csv.DictReader(io.StringIO(raw.decode())))
def material(path):
    raw=(HERE/path).read_bytes()
    return gzip.decompress(raw) if path.endswith('.gz') else raw
def build():
    before=blob(BASE);rows=parse(before);byid={r['id']:r for r in rows}
    prior=json.loads((HERE/PARENT).read_bytes())
    assert len(rows)==len(byid)==1000 and projection(rows)==prior['lower_projection_sha256']
    design=json.loads((HERE/PACK/'design.json').read_bytes())
    baseline={r['id']:int(r['certified_lower']) for r in parse(blob(design['base']))}
    archive=(HERE.parent/design['claims']).read_bytes();assert sha(archive)==design['claims_sha256']
    base_claims=json.loads(gzip.decompress(archive))['claims']
    oldrows={r['id']:r for r in parse(blob(design['base']))}
    order=sorted((x['id'] for x in base_claims if int(oldrows[x['id']]['tight'])==0),
                 key=lambda i:sha((design['salt']+i).encode()))
    dep={**prior['dependencies'],PARENT:sha((HERE/PARENT).read_bytes())};examined=[];claimed=set();strict=0;total_leaves=0
    batches=['pilot','extension']+[f'block-{j:02}' for j in range((len(order)-design['pilot']-64+63)//64)]
    for name in batches:
        prefix=PACK+'/'+name
        path=prefix+('.json.gz' if name.startswith('block-') else '.json')
        verify_path=prefix+'-verified.json';source=material(path)
        group=json.loads(source);verified=json.loads((HERE/verify_path).read_bytes())
        assert group['base']==verified['base']==design['base'] and verified['official_sha256']==prior['official_sha256']
        assert sha(source)==verified['claims_sha256'] and len(group['rows'])==verified['examined']
        members={r['id']:r for r in group['rows'] if r['tree'] is not None}
        assert members.keys()==verified['wins'].keys() and not members.keys()&claimed
        claimed.update(members)
        for key in (path,verify_path):dep[key]=sha((HERE/key).read_bytes())
        examined.extend(r['id'] for r in group['rows'])
        for i,proof in verified['wins'].items():
            r=byid[i];old=int(r['certified_lower']);new=proof['certified_lower']
            assert baseline[i]==proof['previous']==members[i]['old'] and new==baseline[i]+1
            assert new<=int(r['best_verified_upper']) and proof['verified_leaves']==members[i]['closed_leaves']
            total_leaves+=proof['verified_leaves']
            if new>old:
                r['certified_lower']=str(new);r['winning_lower_source']=path;strict+=1
            elif new==old:
                r['winning_lower_source']+='+'+path
    assert examined==order
    for key in (PACK+'/design.json',PACK+'/all-design.json'):dep[key]=sha((HERE/key).read_bytes())
    receipt={k:prior[k] for k in ('upstream','official_sha256','external_bounds_sha256','local_manifest_sha256')}
    receipt.update(base_commit=BASE,base_table_sha256=sha(before),parent_lower_projection_sha256=prior['lower_projection_sha256'],
                   previous_certified_lower=prior['certified_lower'],certified_lower=sum(int(r['certified_lower']) for r in rows),
                   membership_claims=len(claimed),strict_rows=strict,examined=len(examined),closed_leaves=total_leaves,
                   lower_projection_sha256=projection(rows),dependencies=dep)
    return rows,receipt
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--write',action='store_true');ap.add_argument('--table-at');a=ap.parse_args()
    if a.write and a.table_at:ap.error('Historical tables are read-only')
    result,receipt=build()
    table=HERE/'puzzle-bounds.csv';live=parse(blob(a.table_at) if a.table_at else table.read_bytes())
    assert [r['id'] for r in result]==[r['id'] for r in live]
    if a.write:
        assert projection(live) in (receipt['lower_projection_sha256'],receipt['parent_lower_projection_sha256'])
        for row,claim in zip(live,result):
            for k in FIELDS:row[k]=claim[k]
            gap=int(row['best_verified_upper'])-int(row['certified_lower']);assert gap>=0
            row.update(gap=gap,tight=int(gap==0))
        buf=io.StringIO(newline='');w=csv.DictWriter(buf,fieldnames=list(live[0]),lineterminator='\n');w.writeheader();w.writerows(live)
        table.write_bytes(buf.getvalue().encode())
        (HERE/RESULT).write_bytes((json.dumps(receipt,indent=2)+'\n').encode())
    else:assert projection(live)==receipt['lower_projection_sha256'] and json.loads((HERE/RESULT).read_bytes())==receipt
    print(receipt['certified_lower'],receipt['membership_claims'],receipt['strict_rows'],receipt['closed_leaves'])
if __name__=='__main__':main()
