"""Choose a fresh-construction screen using frozen per-puzzle lengths only."""
import argparse,json,subprocess,tempfile
from pathlib import Path
from measure import BASE,HOLDOUT,PILOT,ROOT,read_submission,read_puzzles,sha256

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('puzzles',type=Path);ap.add_argument('previous_run',type=Path)
    ap.add_argument('output',type=Path);ap.add_argument('--git-root',type=Path,default=ROOT);a=ap.parse_args()
    if sha256(a.previous_run)!='91453abf036867d16293df3467b1e5211df7432153dca3c6a70e9bbe8147fb1b':raise ValueError('prior scratch result differs')
    fresh={i:len(t) for i,t in read_submission(a.previous_run).items()}
    with tempfile.TemporaryDirectory(dir=a.output.parent) as td:
        inputs=[]
        for r in ('submission.csv','public-assisted/submission.csv'):
            f=Path(td)/'lengths.csv'
            f.write_bytes(subprocess.check_output(['git','-C',str(a.git_root),'show',BASE+':'+r]))
            inputs.append({i:len(t) for i,t in read_submission(f).items()})
    own,public=inputs
    rows=[]
    for p in read_puzzles(a.puzzles):
        i=p.id;n=i[-4:]
        if n in PILOT+HOLDOUT:continue
        if len(p.targets)<15 or own[i]<120 or own[i]-public[i]<7:continue
        if fresh[i]-own[i]>7:continue
        rows.append((fresh[i]-own[i],public[i]-own[i],n))
    picked=[r[-1] for r in sorted(rows)]
    j={'commit':BASE,'prior_raw_sha256':sha256(a.previous_run),'criteria':'all with >=15 goals, >=120 independent steps, >=7 gap to assisted and prior raw <=7 above independent. Excludes both earlier splits.','ids':picked}
    a.output.write_text(json.dumps(j,indent=2)+'\n',encoding='utf8')
    print(len(picked),' '.join(picked))

if __name__=='__main__':main()
