"""Recompute each candidate prefix envelope and certify a strict gain only after ABSENT."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import perf_counter

from cliques import resolve
from screen import capacities
from sorted_quads import audit


def check_one(entry):
    repo, p, row, independent = entry
    sys.path.insert(0, str(repo))
    from solvers.proofs.domain_bounds import domains, missing_capacity
    from lower_bounds import certificate
    required, _, helper_low, _ = certificate(p)
    maximum = max(row["eligible"])
    domain = {0: set(p.seeds), **dict(domains(p, maximum, 3500))}
    results = []
    for state in row["states"]:
        k = state["k"]
        if k not in row["eligible"]:
            continue
        allowed = domain[k]
        assert required == row["missing"] and k <= helper_low
        assert sha256((",".join(map(str, sorted(allowed)))+"\n").encode()).hexdigest() == state["allowed_sha256"]
        labels, plain, improved = capacities(p, allowed)
        assert state["labels"] == labels and plain == missing_capacity(p, allowed, True) == state["classic"]
        assert improved == state["optimistic"] and required+k+improved == state["total"] > row["prior"]
        start = perf_counter()
        status, stats, witness = resolve(labels, allowed | set(p.targets), p.limit)
        record = dict(k=k, unsupported=len(labels), status=status, statistics=stats,
                      witness=witness, seconds=round(perf_counter()-start, 4),
                      established=required+k+(improved if status=="ABSENT" else plain))
        if independent:
            start=perf_counter()
            other_stats={}
            other,w=audit(labels,allowed|set(p.targets),p.limit,other_stats)
            if {other,status}=={"ABSENT","PRESENT"}:
                raise AssertionError((p.id,status,other))
            if other!="ABSENT":
                record["established"]=required+k+plain
            record.update(independent_status=other,independent_witness=w,independent_statistics=other_stats,
                          independent_seconds=round(perf_counter()-start,4))
        results.append(record)
    return dict(id=p.id, previous=row["prior"], certified=max([row["prior"]]+[x["established"] for x in results]),
                cases=results)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", type=Path, required=True)
    ap.add_argument("--puzzles", type=Path, required=True)
    ap.add_argument("--screen", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--independent", action="store_true")
    a=ap.parse_args()
    sys.path.insert(0, str(a.repo))
    from elf import read_puzzles
    pz={p.id:p for p in read_puzzles(a.puzzles)}
    design=json.loads((Path(__file__).resolve().parent/"design.json").read_bytes())
    assert sha256(a.puzzles.read_bytes()).hexdigest()==design["puzzles_sha256"]
    phase=json.loads(a.screen.read_bytes())
    assert [r["id"] for r in phase] in [design["screen"],design["replicate"]]
    output=[]
    with ProcessPoolExecutor(a.jobs) as pool:
        for r in pool.map(check_one, [(a.repo,pz[r["id"]],r,a.independent) for r in phase if r["eligible"]]):
            output.append(r)
            a.out.write_bytes((json.dumps(output,indent=1)+"\n").encode())
            print(r["id"],r["previous"],r["certified"],[(t["k"],t["status"],t["statistics"]["identities"],t["seconds"]) for t in r["cases"]],flush=True)


if __name__=="__main__":
    main()
