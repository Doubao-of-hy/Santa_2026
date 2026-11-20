"""Verify the published union using both project interpreters and a pinned Git parent."""
import argparse,csv,hashlib,io,json,subprocess,sys,tempfile
from pathlib import Path

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--repo",type=Path,required=True)
    ap.add_argument("--data",type=Path,required=True);ap.add_argument("--result-dir",type=Path,default=Path(__file__).resolve().parent)
    args=ap.parse_args();repo=args.repo.resolve();out=args.result_dir.resolve();sys.path.insert(0,str(repo))
    from checkpoint import independent_score
    from elf import read_puzzles,read_submission,write_submission,sha256
    design=json.loads((Path(__file__).with_name("design.json")).read_bytes())
    result=json.loads((out/"result.json").read_bytes())["score"]["union"]
    parent=subprocess.check_output(["git","-C",str(repo),"show",design["commit"]+":public-assisted/submission.csv"])
    assert hashlib.sha256(parent).hexdigest()==design["baseline_sha256"]
    base={r["id"]:tuple(map(tuple,json.loads(r["program"]))) for r in csv.DictReader(io.StringIO(parent.decode("utf-8-sig")))}
    patch=read_submission(out/"shorter.csv")
    assert {i:[len(base[i]),len(t)] for i,t in patch.items()}==result["winners"]
    with tempfile.TemporaryDirectory(dir=out) as scratch:
        file=Path(scratch)/"verified.csv"
        score=write_submission(file,read_puzzles(args.data),base|patch)
        counts=independent_score(args.data,file)
        assert len(counts)==1000 and sum(counts)==score==result["score"] and sha256(file)==result["sha256"]
    print(len(patch),"improvements,",score,"instructions,",result["sha256"])

if __name__=="__main__":main()
