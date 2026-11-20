"""Verify that every accepted physical row replays in both project interpreters."""
import argparse
import gzip
import json
import tempfile
from collections import Counter
from pathlib import Path
from run import D,HERE,OFFICIAL,frozen,sha,read_puzzles,check,write_submission,independent_score
from elf import read_submission

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--puzzles',type=Path,default=OFFICIAL)
    args=ap.parse_args()
    data=args.puzzles;assert sha(data.read_bytes())==D['puzzles_sha256']
    puzzles=read_puzzles(data);idx={p.id:p for p in puzzles}
    raw=HERE/'details.json'
    detail_bytes=raw.read_bytes() if raw.exists() else gzip.decompress((HERE/'details.json.gz').read_bytes())
    details=json.loads(detail_bytes)
    combined={}
    for lane,prefix in [('independent',''),('public','public-assisted/')]:
        base=frozen(prefix,'submission.csv',D['parents'][prefix]['sha256'])
        tables={k:tuple(tuple(i) for i in json.loads(r['program'])) for k,r in base.items()}
        before=sum(map(len,tables.values()))
        wins=read_submission(HERE/(lane+'-shorter.csv'))
        for k,t in wins.items():assert check(idx[k],t)==len(t)<len(tables[k])
        with tempfile.TemporaryDirectory(dir=HERE) as tmp:
            file=Path(tmp)/'merged.csv';total=write_submission(file,puzzles,tables|wins)
            ret=independent_score(data,file)
            assert sum(ret)==total and len(ret)==1000
            digest=sha(file.read_bytes())
        trials=[r for r in details.values() if r['lane']==lane];summary={}
        for phase in sorted({r['phase'] for r in trials}):
            part={arm:[r for r in trials if r['phase']==phase and r['arm']==arm] for arm in D['arms']}
            summary[phase]={arm:{'trials':len(rows),'wins':sum(r['before']>r['after'] for r in rows),'saved':sum(r['before']-r['after'] for r in rows),'seconds':round(sum(r['seconds'] for r in rows),3)} for arm,rows in part.items() if rows}
        combined[lane]={'frozen':before,'verified':total,'programs_sha256':digest,'replayed_rows':1000,'trial_count':len(trials),'by_split_and_arm':summary,
                        'wins':{k:[len(tables[k]),len(t)] for k,t in wins.items()},'winners_csv_sha256':sha((HERE/(lane+'-shorter.csv')).read_bytes())}
    (HERE/'verification.json').write_text(json.dumps(combined,indent=1)+'\n',encoding='utf8')
    print({k:(v['frozen'],v['verified'],v['trial_count']) for k,v in combined.items()})
if __name__=='__main__':main()
