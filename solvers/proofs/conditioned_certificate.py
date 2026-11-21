"""Verify and archive lower bounds obtained by conditioning on the first helper."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import gzip
from hashlib import sha256 as digest
from itertools import combinations_with_replacement
import json
from pathlib import Path
from types import SimpleNamespace

from checkpoint import atomic_text
from solvers.proofs.domain_bounds import domains, missing_capacity
from elf import read_puzzles, sha256

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT/'proofs/conditioned-bounds.json'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def stamp(values):
    return digest((','.join(map(str,sorted(values)))+'\n').encode()).hexdigest()


def frontier(seeds, goals, cap):
    known=set(seeds)
    while True:
        possible=set()
        for a,b in combinations_with_replacement(sorted(known),2):
            possible.update((a+b,b-a,a*b))
            if b%a==0:possible.add(b//a)
        possible={x for x in possible-known if 0<x<=cap}
        direct=possible&goals
        if not direct:return known,possible
        known.update(direct)


def verify_tree(p,lower,tree,cap):
    goals=set(p.targets)
    required=lower-len(goals-set(p.seeds))
    def visit(known,needed,node):
        require(needed>0,'nonpositive auxiliary bound')
        closed,first=frontier(known,goals,p.limit)
        require(goals-closed,'all goals already reached')
        kind=node['kind']
        if kind=='partition':
            require(node['active_sha256']==stamp(closed) and node['active_count']==len(closed),'wrong active domain')
            require(node['next_sha256']==stamp(first) and node['next_count']==len(first),'wrong first candidates')
            seen=set()
            for group in node['groups']:
                choices=set(group['values'])
                require(choices and group['values']==sorted(choices) and choices<=first and not choices&seen,'invalid partition')
                seen.update(choices)
                visit(closed|choices,needed-1,group['proof'])
            require(seen==first,'uncovered first helper')
            return
        if kind=='no_next_value':
            require(not first and node['active_sha256']==stamp(closed),'there is another candidate')
            return
        k=node['k']
        require(type(k) is int and k>=0,'invalid envelope depth')
        spec=SimpleNamespace(seeds=tuple(sorted(closed)),targets=p.targets,limit=p.limit)
        allowed=closed
        if k:
            reached=dict(domains(spec,k,cap))
            require(k in reached,'partial envelope')
            allowed=reached[k]
        require(node['domain_sha256']==stamp(allowed) and node['domain_count']==len(allowed),'wrong envelope')
        if kind=='target_outside':
            require(node['missing_target'] in goals-allowed and k+1>=needed,'insufficient unreachable-target bound')
        else:
            require(kind=='rooted_capacity','unknown leaf type')
            h=missing_capacity(spec,allowed,True)
            require(h==node['h'] and h>0 and k+h>=needed,'insufficient target capacity bound')
    visit(set(p.seeds),required,tree)


def read_index(manifest, official):
    if not manifest.exists():
        return {},{}
    document=json.loads(manifest.read_text(encoding='utf8'))
    require(document['official_sha256']==official,'puzzle data changed')
    packs=document['packs']
    combined={}
    for name,expected in packs.items():
        require(Path(name).name==name and name.startswith('conditioned-'),'invalid archive filename')
        path=manifest.parent/name
        require(sha256(path)==expected,'proof archive hash mismatch')
        rows=json.loads(gzip.decompress(path.read_bytes()))
        for pid, record in rows.items():
            combined[pid]=max(combined.get(pid,0),record['lower'])
    require(combined==document['bounds'],'proof archive and published bounds differ')
    return combined,packs


def records_from(path, official):
    if path.is_file():
        report=json.loads(path.read_text(encoding='utf8'))
        require(report['official_sha256']==official,'source uses different puzzle data')
        for pid,row in report['rows'].items():
            if row['status']=='CERTIFIED':
                yield pid,dict(lower=row['new_lower'],cap=report['settings']['cap'],tree=row['tree'])
        return
    protocol=path/'protocol.json'
    spec=json.loads(protocol.read_text(encoding='utf8'))
    if 'official_sha256' in spec:
        require(spec['official_sha256']==official,'source uses different puzzle data')
    else:
        parent=path.parent/'wave/protocol.json'
        require(sha256(parent)==spec['base_protocol_sha256'],'unrecognized parent protocol')
        require(json.loads(parent.read_text(encoding='utf8'))['official_sha256']==official,'parent uses different puzzle data')
    version=sha256(protocol)
    limits=spec['settings']
    cap=limits['cap'] if 'cap' in limits else max(s['cap'] for s in limits.values())
    for file in sorted((path/'batches').glob('*.json')):
        batch=json.loads(file.read_text(encoding='utf8'))
        require(batch['protocol_sha256']==version,'batch protocol mismatch')
        for pid,lower in batch['positive'].items():
            source=path/'rows'/(pid+'.json')
            require(sha256(source)==batch['row_sha256'][pid],'source record hash mismatch')
            raw=json.loads(source.read_text(encoding='utf8'))
            require(raw['protocol_sha256']==version and raw['id']==pid,'record protocol mismatch')
            row=raw['result']
            require(row['status']=='CERTIFIED' and row['new_lower']==lower,'invalid positive entry')
            yield pid,dict(lower=lower,cap=cap,tree=row['tree'])


def verify_job(job):
    p,record=job
    verify_tree(p,record['lower'],record['tree'],record['cap'])


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('reports',nargs='*',type=Path)
    ap.add_argument('--jobs',type=int,default=4)
    a=ap.parse_args()
    data=ROOT/'data/puzzles.csv';official=sha256(data)
    puzzles={p.id:p for p in read_puzzles(data)}
    bounds,packs=read_index(MANIFEST,official)
    if not a.reports:
        jobs=[]
        for name in packs:
            rows=json.loads(gzip.decompress((MANIFEST.parent/name).read_bytes()))
            jobs.extend((puzzles[pid],record) for pid,record in rows.items())
        with ProcessPoolExecutor(a.jobs) as pool:
            list(pool.map(verify_job,jobs))
        print('replayed',len(bounds),'distinct puzzle bounds')
        return
    pending={}
    for path in a.reports:
        for pid,record in records_from(path,official):
            lower=record['lower']
            if lower<=max(bounds.get(pid,0),pending.get(pid,{}).get('lower',0)):continue
            pending[pid]=record
    with ProcessPoolExecutor(a.jobs) as pool:
        list(pool.map(verify_job,[(puzzles[pid],record) for pid,record in pending.items()]))
    if pending:
        raw=gzip.compress(json.dumps(pending,sort_keys=True,separators=(',',':')).encode(),mtime=0)
        fingerprint=digest(raw).hexdigest()
        archive=MANIFEST.parent/f'conditioned-{fingerprint[:16]}.json.gz'
        archive.write_bytes(raw)
        require(sha256(archive)==fingerprint,'failed to archive certificate')
        packs[archive.name]=fingerprint
        bounds.update({pid:r['lower'] for pid,r in pending.items()})
        atomic_text(MANIFEST,json.dumps(dict(official_sha256=official,packs=packs,bounds=bounds),indent=2)+'\n')
        read_index(MANIFEST,official)
    print('verified',len(pending),'new or stronger proofs;',len(bounds),'distinct puzzles')

if __name__=='__main__':
    main()
