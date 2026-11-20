"""Replay one registered pair from the frozen Git baseline and locally available official input."""
import argparse
import csv
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    args=argparse.ArgumentParser(description=__doc__)
    args.add_argument("--repo",type=Path,default=Path.cwd())
    args.add_argument("--puzzles",type=Path,required=True)
    args.add_argument("--id",default="scored_0680")
    args.add_argument("--compiler",type=Path)
    args.add_argument("--scratch",type=Path)
    a=args.parse_args()
    repo=a.repo.resolve()
    here=Path(__file__).resolve().parent
    sys.path.insert(0,str(repo))
    from elf import read_puzzles
    import method
    receipt=json.loads((here/"result.json").read_bytes())
    for name,digest in receipt["artifact_sha256"].items():
        assert hashlib.sha256((here/name).read_bytes()).hexdigest()==digest,name
    assert hashlib.sha256(a.puzzles.read_bytes()).hexdigest()==receipt["fresh_rudolph_generation"]["official_input_sha256"]
    expected=json.loads(gzip.decompress((here/"rows.json.gz").read_bytes()))[a.id]
    baseline=subprocess.check_output(["git","show",receipt["base_commit"]+":submission.csv"],cwd=repo)
    assert hashlib.sha256(baseline).hexdigest()==receipt["base_sha256"]
    def extract(bs):
        for record in csv.DictReader(io.StringIO(bs.decode("utf-8-sig"))):
            if record["id"]==a.id:return tuple(tuple(i) for i in json.loads(record["program"]))
        raise KeyError(a.id)
    first=extract(baseline)
    second=extract(gzip.decompress((here/"guides.csv.gz").read_bytes()))
    p=next(p for p in read_puzzles(a.puzzles) if p.id==a.id)
    compiler=str(a.compiler.resolve()) if a.compiler else shutil.which("g++")
    if not compiler:raise RuntimeError("Specify a C++17 compiler with --compiler")
    with tempfile.TemporaryDirectory(dir=(a.scratch or repo).resolve()) as scratch:
        directory=Path(scratch)
        for name in ("common.inc","compact.inc","cross.inc","recipe_lookup.inc","fast_perturb.inc","main.inc"):
            source=subprocess.check_output(["git","show",receipt["base_commit"]+":generative/wang/"+name],cwd=repo)
            (directory/name).write_bytes(source)
        src=(directory/"cross.inc").read_bytes()
        line=b"for(int attempt=0;attempt<7;attempt++){"
        assert src.count(line)==1
        (directory/"cross_counted.inc").write_bytes(src.replace(line,b"for(int attempt=0;attempt<7 && charged_attempts<rounds;attempt++){++charged_attempts;"))
        method.WANG_BINARY=directory/("wang.exe" if os.name=="nt" else "wang")
        cmd=[compiler,"-O3","-std=c++17"]+(["-static"] if os.name=="nt" else [])
        env=dict(os.environ,TMP=scratch,TEMP=scratch)
        subprocess.run(cmd+["-I",scratch,str(here/"wang_control.cpp"),"-o",str(method.WANG_BINARY)],check=True,env=env)
        actual,_=method.one((p,first,second,expected["guide_source"]))
    for arm in ("greedy","random","wang"):
        for k in list(actual[arm]):
            if k in ("cpu_sec","native_wall_s"):continue
            assert actual[arm][k]==expected[arm][k],(arm,k)
    print(json.dumps({"id":a.id,"partition":expected["partition"],"parent":len(first),"guide":len(second),
          "matched_physical_state_hashes":sum(actual[arm]["physical"] for arm in ("greedy","random")),
          "replayed_scores":{arm:actual[arm]["best"] for arm in ("greedy","random","wang")}},indent=2))


if __name__=="__main__":
    main()
