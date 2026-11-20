"""Compare the GoodPJW v10 seeded engines with their Wang controls on frozen independent inputs."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
NAMES = ("incremental_single", "good_incremental_single", "good_incremental_multiple", "anneal_multiple", "good_anneal_multiple")
def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo",type=Path,default=HERE.parents[1])
    ap.add_argument("--puzzles",required=True,type=Path)
    ap.add_argument("--archive",type=Path,help="pinned GoodPJW v10 dataset ZIP, used to build the four engines")
    ap.add_argument("--binary-dir",type=Path,help="existing executables inc-local, inc-good, anneal-local, anneal-good")
    ap.add_argument("--cxx",default="g++")
    ap.add_argument("--scratch",type=Path)
    ap.add_argument("--jobs",type=int,default=3)
    ap.add_argument("--id",help="optionally replay one of the 16 registered puzzles")
    ap.add_argument("--out",required=True,type=Path)
    args=ap.parse_args()
    if not (args.archive or args.binary_dir): ap.error("set --archive or --binary-dir")
    repo=args.repo.resolve();sys.path.insert(0,str(repo))
    from elf import check,read_puzzles,write_submission
    spec=importlib.util.spec_from_file_location("second_check",repo/"collaboration/polish/replay.py")
    other=importlib.util.module_from_spec(spec);spec.loader.exec_module(other)
    design=json.loads((HERE/"design.json").read_bytes());diff=json.loads((HERE/"source-diff.json").read_bytes())
    datasets=[];credits=[]
    def table(blob):return {r["id"]:r for r in csv.DictReader(io.StringIO(blob.decode("utf-8-sig")))}
    for source in design["sources"]:
        fetch=lambda f:subprocess.check_output(["git","-C",str(repo),"show",source["commit"]+":"+f])
        b=fetch("submission.csv");c=fetch("origins.csv")
        assert sha(b)==source["submission_sha256"] and sha(c)==source["origins_sha256"]
        datasets.append(table(b));credits.append(table(c))
    puzzles={p.id:p for p in read_puzzles(args.puzzles)}
    assert sha(args.puzzles.read_bytes())=="b0c70d849eca078a0e1cf9a4f7b47fd40b7435663f6f84de6725f84724500428"
    args.out.mkdir(parents=True,exist_ok=True)
    results=[]
    with tempfile.TemporaryDirectory(dir=args.scratch) as scratch:
        temp=Path(scratch)
        if args.binary_dir:
            exe_root=args.binary_dir.resolve()
        else:
            exe_root=temp
            archive=args.archive.read_bytes();assert sha(archive)==diff["archive_sha256"]
            with zipfile.ZipFile(io.BytesIO(archive)) as z:
                for n,r in diff["rows"].items():
                    if n.endswith((".cpp",".inc")):
                        content=z.read("wangjakie_strategies/"+n)
                        assert sha(content)==r["upstream_sha256"]
                        (temp/n).write_bytes(content)
            origin=repo/"generative/wang"
            cpp={"inc-local":origin/"incremental.cpp","anneal-local":origin/"anneal_seeded.cpp",
                 "inc-good":temp/"incremental_seeded.cpp","anneal-good":temp/"anneal_seeded.cpp"}
            for k,source in cpp.items():
                flags=["-static"] if os.name=="nt" else []
                name=k+(".exe" if os.name=="nt" else "")
                subprocess.run([args.cxx,"-O3","-std=c++17",*flags,str(source),"-o",str(temp/name)],check=True,
                               env={**os.environ,"TMP":str(temp),"TEMP":str(temp),"TMPDIR":str(temp)})
        titles=["inc-local","inc-good","inc-good","anneal-local","anneal-good"]
        binaries=[exe_root/(n+(".exe" if os.name=="nt" else "")) for n in titles]
        def run(row):
            key=row["id"];p=puzzles[key];tapes=[]
            descriptor=[p.id,list(p.seeds),list(p.targets),p.limit,p.registers]
            def verify(tape):
                size=check(p,tape);assert other.run_program(descriptor,tape)==size;return size
            for ref in row["parents"]:
                j=ref["index"];raw=datasets[j][key]["program"];tape=json.loads(raw)
                assert sha(raw.encode())==ref["program_sha256"] and credits[j][key]==ref["credit"]
                assert verify(tape)==ref["steps"]
                tapes.append(tape)
            original=tapes[0];score=len(original);record=dict(id=key,before=score,arms={})
            for ix,(name,exe) in enumerate(zip(NAMES,binaries)):
                family=tapes[:1] if ix<2 else tapes
                seed=710177+int(key[-4:])
                data=[[1],[p.limit,p.registers,design["rounds"],0,seed],[len(p.seeds),*p.seeds],
                      [len(set(p.targets)),*sorted(set(p.targets))],[len(family)]]
                for tape in family:data.extend([[len(tape)],*tape])
                wire="\n".join(" ".join(map(str,r)) for r in data)+"\n"
                proc=subprocess.run([str(exe)],input=wire,text=True,capture_output=True,check=True,
                                    creationflags=getattr(subprocess,"BELOW_NORMAL_PRIORITY_CLASS",0))
                fields=proc.stdout.split();size=int(fields[0]);assert len(fields)==1+size*4
                returned=[[fields[i],*map(int,fields[i+1:i+4])] for i in range(1,len(fields),4)]
                assert verify(returned)==size<=score
                checkrow=dict(steps=size,saved=score-size,program_sha256=sha(json.dumps(returned,separators=(",",":")).encode()))
                if size<score:checkrow["program"]=returned
                record["arms"][name]=checkrow
            return record
        selected=design["rows"] if not args.id else [r for r in design["rows"] if r["id"]==args.id]
        if not selected:ap.error("puzzle outside the frozen comparison")
        with ThreadPoolExecutor(args.jobs) as pool:results=list(pool.map(run,selected))
        receipt=dict(design_sha256=sha((HERE/"design.json").read_bytes()),
                     binary_sha256={k:sha(p.read_bytes()) for k,p in zip(titles,binaries)},rows=results)
    receipt["aggregate"]={k:{"saved":sum(r["arms"][k]["saved"] for r in results),
                              "wins":sum(bool(r["arms"][k]["saved"]) for r in results)} for k in NAMES}
    receipt["same_single_incremental_outputs"]=sum(r["arms"][NAMES[0]]["program_sha256"]==r["arms"][NAMES[1]]["program_sha256"] for r in results)
    receipt["same_seeded_anneal_outputs"]=sum(r["arms"][NAMES[3]]["program_sha256"]==r["arms"][NAMES[4]]["program_sha256"] for r in results)
    best={}
    for r in results:
        arm=min(NAMES,key=lambda a:r["arms"][a]["steps"])
        if r["arms"][arm]["saved"]:best[r["id"]]=tuple(tuple(s) for s in r["arms"][arm]["program"])
    if best:write_submission(args.out/"winners.csv",[p for k,p in puzzles.items() if k in best],best)
    (args.out/"independent-results.json").write_bytes((json.dumps(receipt,ensure_ascii=False,separators=(",",":"))+"\n").encode())
    print(receipt["aggregate"],receipt["same_single_incremental_outputs"],receipt["same_seeded_anneal_outputs"],len(best),flush=True)


if __name__=="__main__":main()
