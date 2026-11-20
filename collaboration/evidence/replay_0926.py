"""Replay the single incremental #926 certificate committed inside the v121 snapshot."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile

SNAPSHOT = "95780b7841ab78e02b724b11aa286f4dedd8581d"
PRIOR = "35c63e842c1df9d19fcfae116014f50ff5df421b"
ID = "scored_0926"


def source_metadata(repo):
    def oid(path):
        return subprocess.check_output(["git", "-C", str(repo), "rev-parse", SNAPSHOT + ":" + path],
                                       text=True).strip()
    return dict(source_aggregate_git_blob=oid("proofs_ext/decisions.json"),
                external_bounds_git_blob=oid("proofs_ext/bounds.csv"),
                prior_puzzle_bounds_git_blob=oid("collaboration/puzzle-bounds.csv"),
                source_record={"path": "proofs_ext/decisions.json", "id": ID, "helpers": 7},
                missing_targets=7, max_nodes_per_shard=50000000,
                lower_source="proofs_ext/decisions.json, scored_0926, helpers=7")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def rows(data):
    return list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("repo", "puzzles", "binary", "out"):
        parser.add_argument("--" + option, type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=8)
    args = parser.parse_args()
    repo = args.repo.resolve()
    sys.path.insert(0, str(repo / "proofs/local"))
    import verify as v
    def get(ref, name):
        return subprocess.check_output(["git", "-C", str(repo), "show", ref + ":" + name])
    def emit(file, obj):
        file.write_bytes((json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode())
    args.out.mkdir(parents=True, exist_ok=True)
    previous_blob = get(SNAPSHOT, "collaboration/evidence/upstream-35c63e8.json")
    previous = json.loads(previous_blob)
    manifest = sha(get(SNAPSHOT, "proofs/local/files.sha256.json"))
    assert manifest == previous["local_manifest_sha256"]
    assert manifest == sha((repo / "proofs/local/files.sha256.json").read_bytes())
    assert sha(args.puzzles.read_bytes()) == previous["official_sha256"]
    engine_sha = sha(args.binary.read_bytes())
    puzzles = {p.id: p for p in v.read_puzzles(args.puzzles)}
    new_blob = get(SNAPSHOT, "proofs_ext/decisions.json")
    agg = json.loads(new_blob)
    old = json.loads(get(PRIOR, "proofs_ext/decisions.json"))
    assert sha(args.puzzles.read_bytes().replace(b"\r\n", b"\n")) == agg["puzzles_lf_sha256"]
    key = lambda x: (x["id"], x["helpers"])
    prior = {key(x): x for x in old["decisions"]}
    assert all(x == prior[key(x)] for x in agg["decisions"] if key(x) in prior)
    new = [x for x in agg["decisions"] if key(x) not in prior]
    assert [key(x) for x in new] == [(ID, 7)]
    decision = new[0]
    ns = len(decision["shard_nodes"])
    assert ns == 32 and not decision.get("subshards", 0)
    p = puzzles[ID]
    lower = len(set(p.targets) - set(p.seeds)) + decision["helpers"] + 1
    assert lower == decision["lower_bound"] == 15
    def run(i):
        status, nodes, last = v.query(args.binary, p, 7, decision["max_nodes_per_shard"], i, ns)
        assert status == "UNSAT" and nodes == decision["shard_nodes"][i]
        return dict(shard=i, status=status, nodes=nodes, terminal_candidates=last)
    with ThreadPoolExecutor(args.jobs) as pool:
        shard_rows = list(pool.map(run, range(ns)))
    assert sum(x["terminal_candidates"] for x in shard_rows) == decision["terminal_candidates"] == 0
    print("native replays", len(shard_rows), sum(x["nodes"] for x in shard_rows), flush=True)
    old_table = rows(get(SNAPSHOT, "collaboration/puzzle-bounds.csv"))
    cols = ("id", "local_lower", "external_lower", "certified_lower", "winning_lower_source")
    def projection(table):
        return sha("".join(",".join(str(r[x]) for x in cols) + "\n" for r in table).encode())
    assert projection(old_table) == previous["lower_projection_sha256"]
    ext_raw = get(SNAPSHOT, "proofs_ext/bounds.csv")
    ext = {r["id"]: int(r["certified_lower"]) for r in rows(ext_raw)}
    assert {r["id"] for r in old_table if ext[r["id"]] != int(r["external_lower"])} == {ID}
    witnesses = []
    lengths = []
    with tempfile.TemporaryDirectory(dir=args.out) as scratch:
        fp = Path(scratch) / "submission.csv"
        for name in ("submission.csv", "public-assisted/submission.csv"):
            blob = get(SNAPSHOT, name)
            fp.write_bytes(blob)
            tapes = v.read_submission(fp)
            assert set(tapes) == set(puzzles)
            lens = {k: v.check(q, tapes[k]) for k, q in puzzles.items()}
            assert sorted(lens.values()) == v.independent_score(args.puzzles, fp)
            lengths.append(lens)
            witnesses.append(dict(source=name, sha256=sha(blob), replayed_total=sum(lens.values())))
    new_table = []
    for r in old_table:
        t = dict(r)
        pid = r["id"]
        if pid == ID:
            assert int(r["certified_lower"]) == 14 and ext[pid] == 15
            t.update(external_lower=15, certified_lower=15, winning_lower_source="proofs_ext")
        a, b = (x[pid] for x in lengths)
        lb = int(t["certified_lower"])
        ub = min(a, b)
        assert lb <= ub
        t.update(submission_steps=a, second_submission_steps=b, best_verified_upper=ub, gap=ub - lb, tight=int(lb == ub))
        new_table.append(t)
    with (args.out / "puzzle-bounds.csv").open("w", newline="", encoding="utf-8") as dest:
        writer = csv.DictWriter(dest, fieldnames=old_table[0], lineterminator="\n")
        writer.writeheader()
        writer.writerows(new_table)
    report = dict(upstream=SNAPSHOT, previous_receipt="upstream-35c63e8.json",
                  previous_receipt_sha256=sha(previous_blob), previous_certified_lower=36767,
                  certified_lower=sum(int(r["certified_lower"]) for r in new_table),
                  proved_optimal=sum(r["tight"] for r in new_table), incremental_gain=1, scored_0926=[15, min(x[ID] for x in lengths)],
                  official_sha256=previous["official_sha256"], binary_sha256=engine_sha,
                  local_manifest_sha256=manifest,
                  source_aggregate="proofs_ext/decisions.json", aggregate_sha256=sha(new_blob),
                  external_bounds_sha256=sha(ext_raw), lower_projection_sha256=projection(new_table),
                  bounds_csv_sha256=sha((args.out / "puzzle-bounds.csv").read_bytes()),
                  helpers=7, shards=ns, nodes=sum(x["nodes"] for x in shard_rows), terminal_candidates=0,
                  witnesses=witnesses, shard_results=shard_rows, **source_metadata(repo))
    assert report["certified_lower"] == 36768 and report["proved_optimal"] == 20
    emit(args.out / "upstream-95780b7.json", report)
    print(report["certified_lower"], report["proved_optimal"], report["scored_0926"], witnesses, flush=True)


if __name__ == "__main__":
    main()
