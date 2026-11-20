"""Recheck each UNSAT certificate added or changed by an upstream Git commit."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from elf import read_puzzles
from proofs_ext.verify import native_input, query


def digest(content):
    return hashlib.sha256(content).hexdigest()


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("commit")
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--puzzles", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--jobs", default=4, type=int)
    parser.add_argument("--audit-pairs", action="store_true", help="also enumerate the entire value range for each target; may be expensive")
    args = parser.parse_args()
    commit = git("rev-parse", "--verify", args.commit + "^{commit}").decode().strip()
    paths = git("diff", "--name-only", "--diff-filter=AM", commit+"^", commit,
                "--", "proofs_ext/decisions.d").decode().splitlines()
    if not paths or args.jobs < 1:
        raise ValueError("Expected changed decision files and a positive worker count")
    data = args.puzzles.read_bytes()
    index = json.loads(git("show", commit+":proofs_ext/decisions.json"))
    if digest(data.replace(b"\r\n", b"\n")) != index["puzzles_lf_sha256"]:
        raise ValueError("Official puzzle data differs")
    puzzles = {p.id:p for p in read_puzzles(args.puzzles)}
    with (ROOT/"collaboration/puzzle-bounds.csv").open(encoding="utf8",newline="") as f:
        by_id = {r["id"]:int(r["local_lower"]) for r in csv.DictReader(f)}
    binary = args.binary.resolve()
    checks = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for path in paths:
            raw = git("show",commit+":"+path)
            row = json.loads(raw)
            p = puzzles[row["id"]]
            if args.audit_pairs and subprocess.run([str(binary),"--audit-pairs"],input=native_input(p,0,0),
                              capture_output=True,text=True,check=True).stdout.strip()!="OK":
                raise ValueError("Incomplete operation coverage for "+p.id)
            count = len(row["shard_nodes"])
            tasks = [pool.submit(query,binary,p,row["helpers"],row["max_nodes_per_shard"],i,count)
                     for i in range(count)]
            runs = [task.result() for task in tasks]
            bound = len(set(p.targets)-set(p.seeds))+row["helpers"]+1
            if (not count or bound!=row["lower_bound"] or any(s!="UNSAT" for s,_,_ in runs)
                    or [n for _,n,_ in runs]!=row["shard_nodes"]
                    or sum(last for _,_,last in runs)!=row["terminal_candidates"]):
                raise ValueError("Trace mismatch for "+p.id)
            checks.append(dict(id=p.id,helpers=row["helpers"],lower=bound,local_lower=by_id[p.id],
                               shards=count,nodes=sum(row["shard_nodes"]),receipt_sha256=digest(raw)))
    report = dict(commit=commit,puzzles_sha256=digest(data),binary_sha256=digest(binary.read_bytes()),
                  native_source_sha256=digest(git("show",commit+":exact_helpers.cpp")),
                  exhaustive_operation_pair_audit=args.audit_pairs,decisions=len(checks),shards=sum(r["shards"] for r in checks),
                  nodes=sum(r["nodes"] for r in checks),stronger=[r["id"] for r in checks if r["lower"]>r["local_lower"]],
                  rows=checks)
    args.output.write_text(json.dumps(report,indent=2)+"\n",encoding="utf8",newline="\n")
    print({k:report[k] for k in ("decisions","shards","nodes","stronger")})


if __name__=="__main__":
    main()
