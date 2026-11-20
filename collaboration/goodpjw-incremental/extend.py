"""Run the preregistered remaining 269 independent GoodPJW v10 comparisons."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import csv
import gzip
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

HERE=Path(__file__).resolve().parent
ARMS=("incremental_single","good_incremental_multiple","anneal_multiple")
def digest(blob):return hashlib.sha256(blob).hexdigest()
def dump(path,obj):
    temp=path.with_suffix(".tmp")
    temp.write_bytes((json.dumps(obj,ensure_ascii=False,separators=(",",":"))+"\n").encode());temp.replace(path)
def load_table(blob):return {r["id"]:r for r in csv.DictReader(io.StringIO(blob.decode("utf-8-sig")))}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo",type=Path,default=HERE.parents[1]);ap.add_argument("--puzzles",required=True,type=Path)
    ap.add_argument("--design",type=Path,default=HERE/"extension-design.json")
    ap.add_argument("--pilot-folder",type=Path,default=HERE)
    ap.add_argument("--binary-dir",type=Path);ap.add_argument("--archive",type=Path);ap.add_argument("--cxx",default="g++")
    ap.add_argument("--scratch",type=Path);ap.add_argument("--output",required=True,type=Path)
    ap.add_argument("--jobs",type=int,default=4)
    ap.add_argument("--batch",type=int,action="append",choices=range(1,10),help="optional batch number; otherwise run all")
    a=ap.parse_args()
    if not (a.binary_dir or a.archive):ap.error("Supply --binary-dir or the pinned --archive")
    repo=a.repo.resolve();sys.path.insert(0,str(repo))
    from elf import check,read_puzzles,write_submission
    from checkpoint import independent_score
    spec=importlib.util.spec_from_file_location("independent_registers",repo/"collaboration/polish/replay.py")
    second=importlib.util.module_from_spec(spec);spec.loader.exec_module(second)
    design=json.loads(a.design.read_bytes());design_sha=digest(a.design.read_bytes())
    pilot_paths=(a.pilot_folder/"independent-design.json",a.pilot_folder/"design.json")
    pilot_path=next(p for p in pilot_paths if p.is_file() and digest(p.read_bytes())==design["parent_design_sha256"])
    pilot=json.loads(pilot_path.read_bytes())
    assert digest(pilot_path.read_bytes())==design["parent_design_sha256"]
    assert design["arms"]==list(ARMS) and design["search_count"]==269 and design["rounds"]==180
    assert set(design["excluded_pilot"])=={r["id"] for r in pilot["rows"]}
    assert design["source_tables"]==pilot["sources"]
    assert digest(a.puzzles.read_bytes())==design["official_sha256"]
    puzzles={p.id:p for p in read_puzzles(a.puzzles)}
    tables=[];credits=[]
    for src in design["source_tables"]:
        blob=lambda n:subprocess.check_output(["git","-C",str(repo),"show",src["commit"]+":"+n])
        programs,origins=blob("submission.csv"),blob("origins.csv")
        assert digest(programs)==src["submission_sha256"] and digest(origins)==src["origins_sha256"]
        tables.append(load_table(programs));credits.append(load_table(origins))
    base={k:tuple(tuple(s) for s in json.loads(row["program"])) for k,row in tables[0].items()}
    assert sum(map(len,base.values()))==design["full_parent_score"]
    refs={r["id"]:r for r in design["rows"]}
    assert len(refs)==269 and refs.keys().isdisjoint(set(design["excluded_pilot"])|set(design["excluded_path_relink_cohort"]))
    a.output.mkdir(parents=True,exist_ok=True)
    def write_summary(path,rows):
        path.mkdir(parents=True,exist_ok=True)
        wins={};origin_rows=[]
        aggregate={name:dict(wins=0,saved=0) for name in ARMS}
        for r in sorted(rows,key=lambda t:t["id"]):
            key=r["id"];arms=r["arms"]
            for name in ARMS:
                aggregate[name]["saved"]+=arms[name]["saved"]
                aggregate[name]["wins"]+=bool(arms[name]["saved"])
            name=min(ARMS,key=lambda n:arms[n]["steps"]);w=arms[name]
            if not w["saved"]:continue
            wins[key]=tuple(tuple(step) for step in w["program"])
            sources=refs[key]["parents"][:1] if name==ARMS[0] else refs[key]["parents"]
            roles="wang Jakie, Apache-2.0"
            if name==ARMS[1]:roles+=" | GoodPJW v10 cached multi-parent integration; multiple-parent idea credited to E-Max AI"
            if name==ARMS[2]:roles+=" | project multi-parent Wang annealing"
            provenance=[dict(commit=design["source_tables"][s["index"]]["commit"],program_sha256=s["program_sha256"],
                             credit=s["credit"]) for s in sources]
            origin_rows.append([key,"GoodPJW v10 independent extension / "+name,roles,w["steps"],
                                json.dumps(provenance,separators=(",",":"),ensure_ascii=False),r["seed"],180,w["program_sha256"]])
        table=io.StringIO(newline="")
        writer=csv.writer(table,lineterminator="\n")
        writer.writerow(["id","source","upstream_source","instructions","parent_inputs","seed","rounds","program_sha256"])
        writer.writerows(origin_rows);tmp=path/"origins.tmp";tmp.write_bytes(table.getvalue().encode());tmp.replace(path/"origins.csv")
        write_submission(path/"winners.csv",[p for k,p in puzzles.items() if k in wins],wins)
        combined=base|wins
        full=path/"full-check.csv";n=write_submission(full,list(puzzles.values()),combined)
        assert sorted(check(p,combined[k]) for k,p in puzzles.items())==independent_score(a.puzzles,full)
        full_sha=digest(full.read_bytes());full.unlink()
        docs=sorted(rows,key=lambda q:q["id"])
        zipped=gzip.compress((json.dumps(docs,separators=(",",":"),ensure_ascii=False)+"\n").encode(),mtime=0)
        tmp=path/"rows.tmp";tmp.write_bytes(zipped);tmp.replace(path/"rows.json.gz")
        out=dict(design_sha256=design_sha,cases=len(rows),arms=aggregate,rows_won=len(wins),saved=design["full_parent_score"]-n,
                 parent_total=design["full_parent_score"],overlay_total=n,overlay_sha256=full_sha,
                 winners_sha256=digest((path/"winners.csv").read_bytes()),origins_sha256=digest((path/"origins.csv").read_bytes()),
                 raw_gzip_sha256=digest(zipped))
        dump(path/"summary.json",out);return out

    with tempfile.TemporaryDirectory(dir=a.scratch) as scratch:
        tmp=Path(scratch);exe_root=a.binary_dir.resolve() if a.binary_dir else tmp
        suffix=".exe" if os.name=="nt" else ""
        names=("inc-local","inc-good","anneal-local")
        if not a.binary_dir:
            blob=a.archive.read_bytes();diff=json.loads((a.pilot_folder/"source-diff.json").read_bytes())
            assert digest(blob)==diff["archive_sha256"]
            with zipfile.ZipFile(io.BytesIO(blob)) as z:
                for file,r in diff["rows"].items():
                    if file.endswith((".cpp",".inc")):
                        source=z.read("wangjakie_strategies/"+file);assert digest(source)==r["upstream_sha256"];(tmp/file).write_bytes(source)
            refs_wang=repo/"generative/wang"
            for name,src in zip(names,(refs_wang/"incremental.cpp",tmp/"incremental_seeded.cpp",refs_wang/"anneal_seeded.cpp")):
                flags=["-static"] if os.name=="nt" else []
                subprocess.run([a.cxx,"-std=c++17","-O3",*flags,str(src),"-o",str(tmp/(name+suffix))],check=True,
                               env={**os.environ,"TMP":str(tmp),"TEMP":str(tmp),"TMPDIR":str(tmp)})
        exes=[exe_root/(n+suffix) for n in names]
        fingerprints={n:digest(e.read_bytes()) for n,e in zip(names,exes)}
        def solve(row):
            key=row["id"];p=puzzles[key];record=folder/"state"/(key+".json")
            if record.exists():
                old=json.loads(record.read_bytes());assert old["binary_sha256"]==fingerprints and old["design_sha256"]==design_sha
                return old
            tapes=[];descriptor=[key,list(p.seeds),list(p.targets),p.limit,p.registers]
            def valid(tape):
                n=check(p,tape);assert n==second.run_program(descriptor,tape);return n
            for parent in row["parents"]:
                j=parent["index"];raw=tables[j][key]["program"];t=json.loads(raw);n=valid(t)
                assert n==parent["steps"] and digest(raw.encode())==parent["program_sha256"] and credits[j][key]==parent["credit"]
                tapes.append(t)
            size=len(tapes[0]);seed=710177+int(key[-4:])
            out=dict(id=key,before=size,seed=seed,batch=row["batch"],binary_sha256=fingerprints,design_sha256=design_sha,arms={})
            for ix,(name,exe) in enumerate(zip(ARMS,exes)):
                family=tapes if ix else tapes[:1]
                parts=[[1],[p.limit,p.registers,180,0,seed],[len(p.seeds),*p.seeds],[len(set(p.targets)),*sorted(set(p.targets))],[len(family)]]
                for t in family:parts.extend([[len(t)],*t])
                wire="\n".join(" ".join(map(str,r)) for r in parts)+"\n"
                proc=subprocess.run([str(exe)],input=wire,text=True,capture_output=True,check=True,
                                    creationflags=getattr(subprocess,"BELOW_NORMAL_PRIORITY_CLASS",0))
                fields=proc.stdout.split();n=int(fields[0]);assert len(fields)==1+4*n
                t=[[fields[i],*map(int,fields[i+1:i+4])] for i in range(1,len(fields),4)];assert valid(t)==n<=size
                m=dict(steps=n,saved=size-n,program_sha256=digest(json.dumps(t,separators=(",",":")).encode()))
                if n<size:m["program"]=t
                out["arms"][name]=m
            dump(record,out);return out
        batches=sorted(set(a.batch or range(1,10)))
        for b in batches:
            folder=a.output/f"batch-{b:02d}";(folder/"state").mkdir(parents=True,exist_ok=True)
            group=[r for r in design["rows"] if r["batch"]==b]
            with ThreadPoolExecutor(a.jobs) as pool:completed=list(pool.map(solve,group))
            result=write_summary(folder,completed)
            allrows=[]
            for fin in sorted(a.output.glob("batch-*/summary.json")):
                s=json.loads(fin.read_bytes());raw=(fin.parent/"rows.json.gz").read_bytes()
                assert s["design_sha256"]==design_sha and digest(raw)==s["raw_gzip_sha256"]
                allrows.extend(json.loads(gzip.decompress(raw)))
            assert len({q["id"] for q in allrows})==len(allrows)
            cumulative=write_summary(a.output/"combined",allrows)
            print(b,result["rows_won"],result["saved"],cumulative["cases"],cumulative["rows_won"],cumulative["saved"],flush=True)


if __name__=="__main__":main()
