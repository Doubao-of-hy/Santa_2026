"""Verify the 80 frozen parents and all archived improved rows; optionally repeat searches."""
import argparse
import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT))
from checkpoint import independent_score
from elf import check,read_puzzles,read_submission,replay,sha256,write_submission
from tiny import encode


def repeat(p,parents,record,binary):
    traces=[replay(p,r["program"]) for r in parents]
    fields=[p.limit,len(p.seeds),len(p.targets),len(traces),min(map(len,traces)),*p.seeds,*p.targets]
    data=[" ".join(map(str,fields))]
    for trace in traces:
        data.append(str(len(trace)))
        data.extend(f"{s.output} {s.left} {s.right}" for s in trace)
    count=record["rounds"]
    run=subprocess.run([str(binary.resolve()),str(record["seed"]),str(count)],
                       input="\n".join(data)+"\n",text=True,capture_output=True,check=True)
    lines=iter(run.stdout.splitlines())
    best=None
    end=None
    for line in lines:
        fields=line.split()
        if fields[0]=="WIN":
            n=int(fields[2])
            seq=[int(next(lines).split()[0]) for _ in range(n)]
            best=encode(p,tuple(seq))
            assert check(p,best)==n
        elif fields[0]=="END":
            end=int(fields[2])
    assert end==record["search_best"]
    if "file" in record:
        assert best==read_submission(HERE/record["file"])[p.id]
    return end


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--puzzles",type=Path,help="Optional full official puzzles.csv")
    parser.add_argument("--temp-dir",type=Path,help="Parent of temporary verification files")
    parser.add_argument("--repeat",nargs="+",help="Puzzle numbers or the words wins or all")
    parser.add_argument("--sparse-binary",type=Path)
    parser.add_argument("--large-binary",type=Path)
    args=parser.parse_args()
    manifest=json.loads((HERE/"results.json").read_bytes())
    source=HERE/"frozen-parents.json"
    assert sha256(source)==manifest["frozen_file_sha256"]
    frozen=json.loads(source.read_bytes())
    official=args.puzzles or ROOT/"data"/"puzzles.csv"
    assert sha256(official)==frozen["official"]==manifest["official_sha256"]
    ps={p.id:p for p in read_puzzles(official) if p.id in frozen["jobs"]}
    records=manifest["puzzles"]
    assert len(ps)==len(records)==len(frozen["jobs"])==80
    baseline={}
    combined={}
    for r in records:
        i=r["id"];p=ps[i];j=frozen["jobs"][i]
        assert r["frozen_length"]==j["own_length"]
        for v in j["parents"]:check(p,v["program"])
        baseline[i]=tuple(tuple(step) for step in j["parents"][0]["program"]);combined[i]=baseline[i]
        assert check(p,baseline[i])==j["own_length"]
        assert ("file" in r)==(r["search_best"]<r["launch_length"])
        if "file" in r:
            f=HERE/r["file"]
            assert sha256(f)==r["witness_sha256"]
            row=read_submission(f)
            assert set(row)=={i} and check(p,row[i])==r["search_best"]
            combined[i]=row[i]
    assert {r["file"] for r in records if "file" in r}=={p.relative_to(HERE).as_posix() for p in (HERE/"wins").glob("*.csv")}
    with tempfile.TemporaryDirectory(dir=args.temp_dir) as tmp:
        local=Path(tmp)/"puzzles.csv"
        with official.open(encoding="utf-8-sig",newline="") as src, local.open("w",encoding="utf-8",newline="") as out:
            reader=csv.DictReader(src);writer=csv.DictWriter(out,fieldnames=reader.fieldnames)
            writer.writeheader()
            writer.writerows(r for r in reader if r["id"] in ps)
        for name,pg in (("parents",baseline),("winners",combined)):
            out=Path(tmp)/f"{name}.csv";write_submission(out,ps.values(),pg)
            assert independent_score(local,out)==sorted(map(len,pg.values()))
    winners=[r for r in records if "file" in r]
    print(f"Replayed all 80 parents and {len(winners)} strict launch-time winners with two interpreters.")
    if not args.repeat:return
    requested=set(args.repeat)
    targets={p["id"] for p in records} if "all" in requested else set()
    if "wins" in requested:targets.update(r["id"] for r in winners)
    targets.update(t if t.startswith("scored_") else "scored_"+t for t in requested-{"all","wins"})
    assert targets<=set(ps),targets-set(ps)
    for r in records:
        if r["id"] not in targets:continue
        binary=args.large_binary if r["profile"]=="large" else args.sparse_binary
        if not binary:parser.error(f"{r['id']} needs --{r['profile']}-binary")
        length=repeat(ps[r["id"]],frozen["jobs"][r["id"]]["parents"],r,binary)
        print(f"{r['id']} reproduced the archived length {length}.",flush=True)


if __name__=="__main__":
    main()
