"""Apply only the archived improvements to the exact Git baseline; two interpreters replay all rows."""
from pathlib import Path
import argparse,json,subprocess,tempfile,sys
HERE=Path(__file__).resolve().parent
ROOT=next(p for p in HERE.parents if (p/'elf.py').is_file())
sys.path.insert(0,str(ROOT))
from checkpoint import independent_score
from elf import check,read_puzzles,read_submission,sha256,write_submission

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--puzzles',type=Path,default=ROOT/'data/puzzles.csv')
    ap.add_argument('--git-root',type=Path,default=ROOT)
    ap.add_argument('--work',type=Path,default=ROOT/'work/fresh-check')
    a=ap.parse_args();a.work.mkdir(parents=True,exist_ok=True)
    r=json.loads((HERE/'results.json').read_bytes())
    assert sha256(a.puzzles)==r['official_sha256']
    assert sha256(HERE/'wins.csv')==r['wins_sha256']
    ps=read_puzzles(a.puzzles);by={p.id:p for p in ps}
    patch=read_submission(HERE/'wins.csv')
    with tempfile.TemporaryDirectory(dir=a.work) as td:
        f=Path(td)/'parent.csv'
        f.write_bytes(subprocess.check_output(['git','-C',str(a.git_root),'show',r['commit']+':submission.csv']))
        assert sha256(f)==r['baseline_hashes']['own']
        parent=read_submission(f)
        assert set(patch)==set(r['wins'])
        for i,t in patch.items():assert check(by[i],t)==r['wins'][i]['after']<len(parent[i])==r['wins'][i]['before']
        out=Path(td)/'full.csv'
        score=write_submission(out,ps,parent|patch)
        assert sha256(out)==r['candidate_sha256']
        assert score==r['independent_after']==sum(independent_score(a.puzzles,out))
        print(len(ps),'puzzles,',len(patch),'strict improvements,',score,'instructions')

if __name__=='__main__':main()
