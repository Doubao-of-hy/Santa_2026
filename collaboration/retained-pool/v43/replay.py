"""Rebuild and replay an attributed public-assisted retained-pool result."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def digest(tape):
    return hashlib.sha256(json.dumps(tape,separators=(",",":")).encode()).hexdigest()


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo",type=Path,default=Path.cwd())
    ap.add_argument("--puzzles",type=Path,required=True)
    ap.add_argument("--id",action="append",help="repeat to select several cases; default is all recorded cases")
    ap.add_argument("--compiler")
    ap.add_argument("--scratch",type=Path)
    ap.add_argument("--book",type=Path,default=Path(__file__).with_name("cases.json.gz"))
    args=ap.parse_args()
    repo=args.repo.resolve();sys.path.insert(0,str(repo))
    from elf import check,read_puzzles
    book=json.loads(gzip.decompress(args.book.read_bytes()))
    puzzles={p.id:p for p in read_puzzles(args.puzzles)}
    compiler=args.compiler or shutil.which("g++")
    if not compiler:raise SystemExit("Specify a C++17 compiler with --compiler")
    compiler=str(Path(compiler).resolve())
    ids=args.id or sorted(book["cases"])
    headers=("common.inc","compact.inc","cross.inc","recipe_lookup.inc","fast_perturb.inc","cache_lookup.inc","cache_perturb.inc","main.inc")
    source=book["repo_source_commit"]+":generative/wang/"
    def blob(name):return subprocess.check_output(["git","show",source+name],cwd=repo)
    with tempfile.TemporaryDirectory(dir=(args.scratch or repo).resolve()) as td:
        work=Path(td);env=dict(os.environ,TMP=td,TEMP=td)
        for h in headers:(work/h).write_bytes(blob(h))
        built={}
        for i in ids:
            case=book["cases"][i];p=puzzles[case.get("id",i)];mode=case["mode"]
            if mode not in built:
                filename="incremental.cpp" if mode.startswith("incremental") else "anneal.cpp"
                data=blob(filename)
                assert hashlib.sha256(data).hexdigest()==book["source_sha256"][filename]
                original=data.decode();anchor="std::vector<Graph> pool;"
                assert original.count(anchor)==1
                original=original.replace(anchor,anchor+"""
                    for(size_t i=1;i<tapes.size();++i) pool.push_back(graph_from(tapes[i]));
                    const auto retained=pool.size();
                    if(retained) {
                        Graph initial;
                        if(crossover(champion,pool,initial,best)) { champion=initial; trial=initial; }
                    }
                """)
                eviction="if(pool.size()>12)pool.erase(pool.begin()+rng()%5);"
                assert original.count(eviction)==1
                removable="std::min<size_t>(5,pool.size()-retained)" if mode.endswith("oldest") else "pool.size()-retained"
                original=original.replace(eviction,"if(pool.size()>12){const auto count="+removable+";pool.erase(pool.begin()+retained+rng()%count);}")
                cpp=work/(mode+".cpp");cpp.write_text(original,encoding="utf8")
                exe=work/(mode+(".exe" if os.name=="nt" else ""));built[mode]=exe
                subprocess.run([compiler,"-std=c++17","-O3"]+(["-static"] if os.name=="nt" else [])+[str(cpp),"-o",str(exe)],env=env,check=True)
            fields=[[1],[p.limit,p.registers,case["rounds"],0,case["seed"]],[len(p.seeds),*p.seeds],[len(p.targets),*sorted(p.targets)],[len(case["inputs"])]]
            for source_row in case["inputs"]:
                tape=source_row["program"];assert digest(tape)==source_row["sha256"];check(p,tape)
                fields.append([len(tape)]);fields.extend(tape)
            raw=subprocess.check_output([str(built[mode])],input="\n".join(" ".join(map(str,r)) for r in fields)+"\n",text=True,timeout=180).split()
            tape=tuple((raw[k],int(raw[k+1]),int(raw[k+2]),int(raw[k+3])) for k in range(1,len(raw),4))
            assert len(raw)==4*int(raw[0])+1 and check(p,tape)==case["after"] and digest(tape)==case["expected_program_sha256"]
            print(f"{i} {case['before']} -> {len(tape)} {digest(tape)}",flush=True)

if __name__=="__main__":main()
