"""Rebuild the certified per-puzzle totals, replay the selected submission, and optionally recompute analytic proof trees."""
import argparse
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import csv
import gzip
import hashlib
import json
from pathlib import Path

from checkpoint import certified_bounds, independent_score
from conditioned_certificate import read_index, verify_job
from domain_bounds import bound
from elf import check, read_puzzles, read_submission, sha256
from verify_optimality import query

HERE = Path(__file__).resolve().parent
PROOFS = HERE / "proofs"


def require(ok, message):
    if not ok:
        raise ValueError(message)


def load_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return {row["id"]: row for row in csv.DictReader(stream)}


def results(puzzles):
    historical = load_csv(PROOFS / "bounds.csv")
    domain = load_csv(PROOFS / "domain-bounds.csv")
    current = {pid: int(r["certified_lower"]) for pid, r in domain.items()}
    origin = {pid: "domain-bounds.csv" for pid in current}
    def update(pid, lower, source):
        if lower > current[pid]:
            current[pid] = lower
            origin[pid] = source
    for path in sorted(PROOFS.glob("helper-wave*.json")):
        wave = json.loads(path.read_bytes())
        for pid, row in wave["instances"].items():
            if row["status"] == "UNSAT":
                update(pid, row["certified_lower"], path.name)
    official = json.loads((PROOFS / "domain-bounds.json").read_bytes())["puzzles_sha256"]
    conditioned, packs = read_index(PROOFS / "conditioned-bounds.json", official)
    for pid, lower in conditioned.items():
        update(pid, lower, "conditioned-bounds.json")
    require(set(current) == set(puzzles) == set(historical), "incomplete official coverage")
    return current, origin, domain, historical, packs


def verify_analysis(puzzles, domain, historical, packs, jobs):
    prior = {pid: int(row["prefix_lower"]) for pid, row in historical.items()}
    historical_proof = json.loads((PROOFS / "decisions.json").read_bytes())
    for entry in historical_proof["decisions"]:
        pid = entry["id"]
        p = puzzles[pid]
        require(entry["status"] == "UNSAT", pid)
        lower = len(set(p.targets)-set(p.seeds)) + entry["helpers"] + 1
        prior[pid] = max(prior[pid], lower)
    require(all(lower == int(historical[pid]["certified_lower"]) for pid, lower in prior.items()), "historical table")
    with ProcessPoolExecutor(jobs) as pool:
        for pid, prefix, value, depth in pool.map(bound, ((p, 4, 3500, True) for p in puzzles.values()), chunksize=3):
            r = domain[pid]
            require((prefix, value, depth, max(prior[pid], value)) ==
                    tuple(int(r[k]) for k in ("prefix_lower","domain_lower","first_helpers","certified_lower")), pid)
            require(prefix == int(historical[pid]["prefix_lower"]), pid)
        for name in packs:
            rows = json.loads(gzip.decompress((PROOFS / name).read_bytes()))
            for _ in pool.map(verify_job, ((puzzles[pid], tree) for pid, tree in rows.items()), chunksize=2):
                pass


def external_bounds(puzzles, official_file, historical, local, binary, jobs):
    repo = HERE.parents[1]
    ext = repo / "proofs_ext"
    ext_table = load_csv(ext / "bounds.csv")
    require(set(ext_table) == set(puzzles), "missing external table rows")
    normalized = hashlib.sha256(official_file.read_bytes().replace(b"\r\n",b"\n")).hexdigest()
    documents = [repo / "proofs/decisions.json", ext / "decisions.json"]
    receipts = {}
    for path in documents:
        document = json.loads(path.read_bytes())
        require(document["puzzles_lf_sha256"] == normalized, "external puzzle data differs")
        for r in document["decisions"]:
            receipts[r["id"],r["helpers"]] = r
    for path in sorted((ext / "decisions.d").glob("*.json")):
        r = json.loads(path.read_bytes())
        receipts[r["id"],r["helpers"]] = r
    external = {pid:int(r["prefix_lower"]) for pid,r in historical.items()}
    sources = {}
    for (pid,h),r in receipts.items():
        require(r.get("status","UNSAT")=="UNSAT" and r["shard_nodes"] and
                all(isinstance(n,int) and n>=0 for n in r["shard_nodes"]), f"invalid external decision {pid}")
        p = puzzles[pid]
        value = len(set(p.targets)-set(p.seeds))+h+1
        require(r.get("lower_bound",value)==value,pid)
        if value>external[pid]:
            external[pid]=value
            sources[pid]=r
    for pid,v in external.items():
        require(v==int(ext_table[pid]["certified_lower"]) and int(ext_table[pid]["prefix_lower"])==
                int(historical[pid]["prefix_lower"]), f"external table/receipts disagree at {pid}")
    better = [pid for pid in external if external[pid]>local[pid]]
    if better and binary is None:
        raise ValueError(f"external gains need a native replay with --external-binary: {', '.join(better)}")
    with ThreadPoolExecutor(jobs) as pool:
        for pid in better:
            p=puzzles[pid];r=sources[pid];m=r.get("subshards",1);n=r.get("root_shards",len(r["shard_nodes"]))
            require(n*m==len(r["shard_nodes"]),f"wrong external grid at {pid}")
            futures=[pool.submit(query,binary.resolve(),p,r["helpers"],r["max_nodes_per_shard"],i,n,
                                 j if m>1 else None,m) for j in range(m) for i in range(n)]
            replay=[f.result() for f in futures]
            require(all(s=="UNSAT" for s,_,_ in replay) and [x for _,x,_ in replay]==r["shard_nodes"] and
                    sum(x for _,_,x in replay)==r["terminal_candidates"],f"external trace mismatch at {pid}")
    return external, better


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--puzzles", type=Path, required=True)
    parser.add_argument("--submission", type=Path, required=True)
    parser.add_argument("--second-submission", type=Path, help="optional second physically replayed upper bound")
    parser.add_argument("--external-binary", type=Path, help="original unpruned-branch engine for future stronger external rows")
    parser.add_argument("--analysis", action="store_true", help="also rerun every analytic bound and conditioned proof tree")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--csv", type=Path, help="write the rebuilt per-puzzle bounds and witness lengths")
    args = parser.parse_args()
    require(args.jobs >= 1, "invalid worker count")
    for relative, digest in json.loads((HERE / "files.sha256.json").read_bytes()).items():
        require(sha256(HERE / relative) == digest, f"changed proof source or receipt: {relative}")
    ps = {p.id:p for p in read_puzzles(args.puzzles)}
    rows = read_submission(args.submission)
    require(len(ps) == len(rows) == 1000 and set(rows) == set(ps), "invalid official submission coverage")
    lengths = {pid:check(p,rows[pid]) for pid,p in ps.items()}
    require(sorted(lengths.values()) == independent_score(args.puzzles,args.submission), "interpreter disagreement")
    receipt = certified_bounds(HERE, args.puzzles, rows, ps)
    lower, origin, domain, historical, packs = results(ps)
    other={}
    if args.second_submission:
        alt=read_submission(args.second_submission)
        require(set(alt)==set(ps),"second submission coverage")
        other={pid:check(p,alt[pid]) for pid,p in ps.items()}
        require(sorted(other.values())==independent_score(args.puzzles,args.second_submission),"second interpreter disagreement")
    feasible={pid:min(n,other.get(pid,n)) for pid,n in lengths.items()}
    if args.analysis:
        verify_analysis(ps, domain, historical, packs, args.jobs)
    require(sum(lower.values()) == receipt["arithmetic_lower_bound"] == 36731, "unexpected local lower bound")
    external,better=external_bounds(ps,args.puzzles,historical,lower,args.external_binary,args.jobs)
    combined={pid:max(v,external[pid]) for pid,v in lower.items()}
    require(all(combined[pid] <= n for pid,n in feasible.items()), "witness below its lower bound")
    exact = sorted(pid for pid,n in feasible.items() if combined[pid]==n)
    if args.csv:
        with args.csv.open("w",encoding="utf-8",newline="") as f:
            w=csv.writer(f,lineterminator="\n")
            w.writerow(("id","local_lower","external_lower","certified_lower","winning_lower_source","submission_steps",
                        "second_submission_steps","best_verified_upper","gap","tight"))
            w.writerows((pid,lower[pid],external[pid],combined[pid],"proofs_ext" if pid in better else origin[pid],
                         lengths[pid],other.get(pid,""),feasible[pid],feasible[pid]-combined[pid],int(pid in exact)) for pid in sorted(ps))
    print(json.dumps({"puzzles":len(ps),"certified_lower":sum(combined.values()),"replayed_upper":sum(lengths.values()),
                      "second_replayed_upper":sum(other.values()) if other else None,"external_stronger_replayed":better,
                      "proved_optimal":len(exact),"proved_optimal_ids":exact,"scored_0882":[combined["scored_0882"],feasible["scored_0882"]],
                      "analytic_recalculation":args.analysis},ensure_ascii=False))


if __name__ == "__main__":
    main()
