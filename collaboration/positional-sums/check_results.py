"""Validate scores from the official four puzzles without using parent programs in synthesis."""
from pathlib import Path
import argparse
import csv
import json
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p/'elf.py').is_file())
sys.path.insert(0, str(ROOT))
from checkpoint import independent_score
from elf import check, read_puzzles, read_submission, sha256, write_submission

IDS = ['0493','0269','0163','0255']
HOLDOUT = ['0780','0612','0610','0470']
COMMIT = '595401bd916c41dcbf060f9f5681057694d4f6ec'
OFFICIAL = 'b0c70d849eca078a0e1cf9a4f7b47fd40b7435663f6f84de6725f84724500428'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('puzzles', type=Path)
    ap.add_argument('run_dir', type=Path)
    ap.add_argument('--git-root', type=Path, default=ROOT)
    ap.add_argument('--output', type=Path)
    args = ap.parse_args()
    if sha256(args.puzzles)!=OFFICIAL:raise ValueError('official input differs')
    ps={p.id:p for p in read_puzzles(args.puzzles)}
    with tempfile.TemporaryDirectory(dir=args.run_dir) as temp:
        tmp=Path(temp)
        with args.puzzles.open(encoding='utf-8-sig',newline='') as src, (tmp/'pilot.csv').open('w',encoding='utf8',newline='') as dst:
            rows=csv.DictReader(src)
            writer=csv.DictWriter(dst,fieldnames=rows.fieldnames)
            writer.writeheader()
            writer.writerows(row for row in rows if row['id'] in {'scored_'+i for i in IDS})
        parents={}
        for lane,rel in [('independent','submission.csv'),('assisted','public-assisted/submission.csv')]:
            path=tmp/(lane+'.csv')
            path.write_bytes(subprocess.check_output(['git','-C',str(args.git_root),'show',COMMIT+':'+rel]))
            parents[lane]=read_submission(path)
        results={}
        for i in IDS:
            meta=json.loads((args.run_dir/(i+'.json')).read_bytes())
            pid='scored_'+i
            results[i]={**meta,**{k:check(ps[pid],pg[pid]) for k,pg in parents.items()}}
        for arm in ['ordinary','shared']:
            programs={}
            for i in IDS:programs.update(read_submission(args.run_dir/(i+'-'+arm+'.csv')))
            out=tmp/(arm+'.csv')
            write_submission(out,[ps[k] for k in sorted(programs)],programs)
            scores=independent_score(tmp/'pilot.csv',out)
            assert scores==sorted(results[i][arm]['physical'] for i in IDS)
        report={'official':OFFICIAL,'comparison_commit':COMMIT,'pilot':IDS,'unused_holdout':HOLDOUT,'rows':results}
        text=json.dumps(report,indent=2)+'\n'
        if args.output:args.output.write_text(text,encoding='utf8',newline='\n')
        else:print(text)

if __name__=='__main__':main()
