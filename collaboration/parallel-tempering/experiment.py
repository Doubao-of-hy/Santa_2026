"""Replay the preregistered three-arm comparison on one row or a complete split."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ARMS = ("original", "isolated", "exchange")


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def store(path, content):
    temp = path.with_suffix(".tmp")
    temp.write_bytes((json.dumps(content, separators=(",", ":"), ensure_ascii=False) + "\n").encode())
    temp.replace(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", type=Path, default=HERE.parents[1])
    ap.add_argument("--puzzles", type=Path, required=True)
    ap.add_argument("--original", type=Path, required=True)
    ap.add_argument("--replicas", type=Path, required=True)
    ap.add_argument("--part", choices=("development", "holdout"), required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--id")
    ap.add_argument("--jobs", type=int, default=3)
    a = ap.parse_args()
    repo = a.repo.resolve()
    sys.path.insert(0, str(repo))
    from elf import check, read_puzzles, write_submission
    spec = importlib.util.spec_from_file_location("independent_registers", repo / "collaboration/polish/replay.py")
    independent = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(independent)
    design = json.loads((HERE / "design.json").read_bytes())
    parent = subprocess.check_output(["git", "-C", str(repo), "show", design["commit"] + ":" + design["parent_file"]])
    origins = subprocess.check_output(["git", "-C", str(repo), "show", design["commit"] + ":" + design["attribution_file"]])
    assert sha(parent) == design["parent_sha256"] and sha(origins) == design["attribution_sha256"]
    assert sha(a.puzzles.read_bytes()) == design["puzzles_sha256"]
    refs = {r["id"]: r for r in design["inputs"]}
    readers = lambda blob: {r["id"]: r for r in csv.DictReader(io.StringIO(blob.decode("utf-8-sig")))}
    parents, authors = readers(parent), readers(origins)
    puzzles = {p.id: p for p in read_puzzles(a.puzzles)}
    selected = [key for st in design["strata"] for key in st[a.part]]
    if a.id:
        if a.id not in selected:
            ap.error("puzzle outside selected split")
        selected = [a.id]
    a.output.mkdir(parents=True, exist_ok=True)
    origin_exe, replica_exe = a.original.resolve(strict=True), a.replicas.resolve(strict=True)
    executables = dict(original=sha(origin_exe.read_bytes()), replicas=sha(replica_exe.read_bytes()))
    context = dict(design=sha((HERE / "design.json").read_bytes()), binary_sha256=executables,
                   source_sha256=sha((HERE / "replicas.cpp").read_bytes()), part=a.part)
    def run(key):
        dest = a.output / (key + ".json")
        if dest.exists():
            prior = json.loads(dest.read_bytes())
            assert prior["context"] == context
            return prior
        p = puzzles[key]
        program = json.loads(parents[key]["program"])
        assert sha(parents[key]["program"].encode()) == refs[key]["row_program_sha256"]
        assert refs[key]["credit"] == authors[key]
        descriptor = [key, list(p.seeds), list(p.targets), p.limit, p.registers]
        def validated(tape):
            size = check(p, tape)
            assert independent.run_program(descriptor, [list(s) for s in tape]) == size
            return size
        initial = validated(program)
        assert initial == refs[key]["size"] == int(authors[key]["instructions"])
        seed = 310117 + 4099 * int(key[-4:])
        lines = [[1], [p.limit, p.registers, design["rounds_per_arm"], 0, seed],
                 [len(p.seeds), *p.seeds], [len(p.targets), *sorted(p.targets)], [1], [len(program)], *program]
        wire = "\n".join(" ".join(map(str, r)) for r in lines) + "\n"
        result = dict(id=key, before=initial, credit=authors[key], context=context, seed=seed, arms={})
        # Rotate execution order deterministically across rows to reduce timing-order effects.
        offset = int(key[-4:]) % len(ARMS)
        for arm in ARMS[offset:] + ARMS[:offset]:
            t = time.perf_counter()
            exe = origin_exe if arm == "original" else replica_exe
            proc = subprocess.run([str(exe)], text=True, input=wire, capture_output=True, check=True,
                                  env={**os.environ, "SANTA_REPLICA_EXCHANGES": str(int(arm == "exchange"))},
                                  creationflags=getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0))
            elapsed = round(time.perf_counter() - t, 4)
            fields = proc.stdout.split()
            n = int(fields[0])
            assert len(fields) == 4 * n + 1
            tape = [[fields[i], *map(int, fields[i+1:i+4])] for i in range(1, len(fields), 4)]
            assert validated(tape) == n <= initial
            stats = {}
            if arm != "original":
                label, *metrics = proc.stderr.split()
                keys = ["proposals","accepted","uphill","resets","swap_tests","swap_accepts","different_graph_swaps","unequal_length_swaps"]
                assert label == "replicas" and len(metrics) == len(keys)
                stats = dict(zip(keys, map(int, metrics)))
                assert stats["proposals"] == design["rounds_per_arm"]
                assert stats["swap_tests"] == (30 if arm == "exchange" else 0)
            row = dict(steps=n, saved=initial-n, seconds=elapsed, counters=stats,
                       program_sha256=sha(json.dumps(tape, separators=(",", ":")).encode()))
            if n < initial:
                row["program"] = tape
            result["arms"][arm] = row
        store(dest, result)
        return result

    whole = {}
    with ThreadPoolExecutor(a.jobs) as pool:
        for f in as_completed([pool.submit(run, key) for key in selected]):
            row = f.result()
            whole[row["id"]] = row
            print(row["id"], row["before"], [row["arms"][arm]["steps"] for arm in ARMS], flush=True)
    counts = {}
    for arm in ARMS:
        rows = [r["arms"][arm] for r in whole.values()]
        counts[arm] = dict(saved=sum(x["saved"] for x in rows), wins=sum(x["saved"] > 0 for x in rows),
                           seconds=round(sum(x["seconds"] for x in rows),2),
                           counters=dict(sum((Counter(x["counters"]) for x in rows),Counter())))
    winners = {}
    for key in selected:
        r = whole[key]
        best_arm = min(ARMS, key=lambda arm: r["arms"][arm]["steps"])
        best = r["arms"][best_arm]
        if best["saved"]:
            winners[key] = (best_arm, best)
    if winners:
        write_submission(a.output / "wins.csv", [p for k,p in puzzles.items() if k in winners],
                         {key:tuple(tuple(s) for s in r["program"]) for key,(_,r) in winners.items()})
    paired = Counter()
    for r in whole.values():
        diff = r["arms"]["isolated"]["steps"] - r["arms"]["exchange"]["steps"]
        paired["net"] += diff
        paired["exchange_shorter" if diff>0 else "isolated_shorter" if diff<0 else "tied"] += 1
    summary = dict(context=context, cases=len(whole), ids=selected, arms=counts, comparison=dict(paired),
                   winners={key:dict(arm=arm,saved=r["saved"]) for key,(arm,r) in winners.items()},
                   combined_saved=sum(r["saved"] for _,r in winners.values()))
    store(a.output / "summary.json", summary)
    print(a.part, counts, dict(paired), summary["combined_saved"], flush=True)


if __name__ == "__main__":
    main()
