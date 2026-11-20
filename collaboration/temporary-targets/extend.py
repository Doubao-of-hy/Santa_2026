"""Run the disjoint independent extension in restartable batches of 24."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import gzip
import json
from pathlib import Path
import tempfile
from compare import (ARMS, DESIGN, HERE, candidate_rows, check, evaluate, independent_score,
                     inputs, read_puzzles, score, sha256, stable, write_submission)

def write(path,data):
    pending=path.with_suffix('.tmp')
    packet=(json.dumps(data,ensure_ascii=False,separators=(',',':'))+'\n').encode()
    pending.write_bytes(gzip.compress(packet,mtime=0) if path.suffix=='.gz' else packet)
    pending.replace(path)

def load(path):
    blob=path.read_bytes()
    return json.loads(gzip.decompress(blob) if path.suffix=='.gz' else blob)

def validate(records,selection,ps,baseline,out,puzzles):
    pmap={p.id:p for p in ps}
    gains={};saved={arm:0 for arm in ARMS};protected=[];steps=0
    for i,pack in records.items():
        assert i in selection and pack['base_sha256']==stable(baseline[i])==selection[i]['base_sha256']
        lengths={arm:len(baseline[i]) for arm in ARMS}
        for arm,r in pack['arms'].items():
            n=r['stats']['selected']
            assert n<=len(baseline[i]) and len(r['sha256'])==64
            if 'program' in r:
                tape=r['program'];assert check(pmap[i],tape)==n and stable(tape)==r['sha256']
            else:
                assert n==len(baseline[i]) and r['sha256']==stable(baseline[i])
            lengths[arm]=n;saved[arm]+=len(baseline[i])-n
        win=min(ARMS,key=lengths.get)
        if lengths[win]<len(baseline[i]):
            gains[i]=pack['arms'][win]['program']
            steps+=len(baseline[i])-lengths[win]
        if min(lengths['ranked'],lengths['random'])<min(lengths['ordinary'],lengths['graft_only']):protected.append(i)
    with tempfile.TemporaryDirectory(dir=out) as tmp:
        path=Path(tmp)/'full.csv'
        total=write_submission(path,ps,baseline|gains)
        assert total==sum(independent_score(puzzles,path))==sum(map(len,baseline.values()))-steps
    return dict(rows=len(records),strict_rows=len(gains),saved_steps=steps,protected_exclusive=protected,arm_savings=saved,isolated_total=total),gains

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--puzzles',type=Path,required=True);ap.add_argument('--exe',type=Path)
    ap.add_argument('--out',type=Path,required=True);ap.add_argument('--jobs',type=int,default=6)
    ap.add_argument('--phase',choices=('freeze','run','verify'),required=True)
    ap.add_argument('--stop-after',type=int,help='Stop after this many consecutive completed batches')
    a=ap.parse_args();a.out.mkdir(exist_ok=True,parents=True);selection=a.out/'extra-selection.json.gz'
    sources=inputs();base=DESIGN['base'];baseline=sources[base,'own'][0]
    ps=read_puzzles(a.puzzles);pm={p.id:p for p in ps}
    if a.phase=='freeze':
        rows=list(candidate_rows(ps,'own',sources));old=json.loads((HERE/'selection.json').read_bytes())['own']
        assert json.loads(json.dumps(rows[:len(old)]))==old
        write(selection,{'base':base,'official_sha256':sha256(a.puzzles),'batch_size':24,'rows':rows[len(old):]})
        print('additional independent puzzles',len(rows)-len(old),sha256(selection),flush=True);return
    config=load(selection);assert config['base']==base and config['official_sha256']==sha256(a.puzzles)
    extras=config['rows'];sv={r['id']:r for r in extras};bs=config['batch_size'];allwins={};summary=[]
    for start in range(0,len(extras),bs):
        index=start//bs;group=extras[start:start+bs];ident=[r['id'] for r in group]
        file=a.out/f'batch-{index:02}.json.gz'
        if not file.exists():
            if a.phase=='verify':break
            pool=[]
            for row in group:
                i=row['id'];parent=baseline[i]
                donors={k:sources[tuple(row[k]['origin'])][0][i] for k in ('ranked','random')}
                assert all(stable(t)==row[k]['donor_sha256'] for k,t in donors.items())
                pool.append((pm[i],'own',row,parent,donors,a.exe.resolve()))
            records={}
            with ThreadPoolExecutor(a.jobs) as ex:
                for lane,i,result in ex.map(evaluate,pool):
                    opts={}
                    for arm,tape in result['tapes'].items():
                        n=check(pm[i],tape);digest=stable(tape)
                        r=dict(stats=result['stats'][arm],sha256=digest)
                        if n<len(baseline[i]) or digest!=stable(baseline[i]):r['program']=tape
                        opts[arm]=r
                    records[i]=dict(base_sha256=stable(baseline[i]),arms=opts)
            write(file,records)
        data=load(file);assert list(data)==ident and not allwins.keys()&data.keys()
        receipt,gains=validate(data,sv,ps,baseline,a.out,a.puzzles)
        receipt.update(index=index,batch_sha256=sha256(file));summary.append(receipt)
        allwins.update(gains)
        write(a.out/'running.json',dict(base=base,eligible=len(extras),completed=sum(s['rows'] for s in summary),
                                       improvements=len(allwins),saved=sum(s['saved_steps'] for s in summary),batches=summary))
        dst=a.out/'extension-wins.csv'
        temp=dst.with_suffix('.tmp');write_submission(temp,[p for p in ps if p.id in allwins],allwins);temp.replace(dst)
        print(index,len(group),receipt['saved_steps'],sum(s['saved_steps'] for s in summary),flush=True)
        if a.stop_after and index+1>=a.stop_after:break
if __name__=='__main__':
    main()
