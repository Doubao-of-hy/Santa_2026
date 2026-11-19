"""Apply Atlas cross-trace optimization to locally generated donor programs."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from run_source import HERE, WORK, compile_engine, compiler_path
from elf import check, read_puzzles, read_submission, score, sha256, write_submission


def snapshot(puzzles, paths):
    by_id = {p.id: p for p in puzzles}
    pools = []
    metadata = []
    with tempfile.TemporaryDirectory(dir=WORK, prefix="donors-") as directory:
        snapshot_path = Path(directory) / "snapshot.csv"
        for path in paths:
            data = path.read_bytes()
            snapshot_path.write_bytes(data)
            programs = read_submission(snapshot_path)
            if programs.keys() - by_id.keys():
                raise ValueError(f"{path} contains unknown puzzle IDs")
            subset = [p for p in puzzles if p.id in programs]
            total = score(subset, programs)
            pools.append(programs)
            metadata.append({"path": str(path.resolve()), "rows": len(programs), "instructions": total,
                             "sha256": hashlib.sha256(data).hexdigest()})
    return pools, metadata


def optimize_batch(executable, batch, rows, fieldnames, pools, threads, strategy):
    with tempfile.TemporaryDirectory(dir=WORK, prefix="atlas-cross-") as scratch:
        temporary = Path(scratch)
        source = temporary / "puzzles.csv"
        output = temporary / "optimized.csv"
        with source.open("w", encoding="utf8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows[p.id] for p in batch)
        donor_paths = []
        known = {p.id: set() for p in batch}
        for i, pool in enumerate(pools):
            selected = {}
            covered = []
            for puzzle in batch:
                program = pool.get(puzzle.id)
                if program is not None and program not in known[puzzle.id]:
                    known[puzzle.id].add(program)
                    selected[puzzle.id] = program
                    covered.append(puzzle)
            if not selected:
                continue
            path = temporary / f"donor-{i}.csv"
            write_submission(path, covered, selected)
            donor_paths.append(str(path))
        process = subprocess.run(
            [str(executable), "--"+strategy, str(source), str(output), str(threads), *donor_paths],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf8", cwd=WORK,
        )
        if process.returncode:
            raise RuntimeError(f"Atlas exited {process.returncode}; {process.stderr[-500:].strip()}")
        programs = read_submission(output)
        score(batch, programs)
        return programs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("puzzles", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("sources", type=Path, nargs="+")
    parser.add_argument("--compiler", type=Path)
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--threads", type=int, default=3)
    parser.add_argument("--batch", type=int, default=24)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--priority", choices=("input", "longest", "spread"), default="longest")
    parser.add_argument("--strategy", choices=("optimize","splice","bridge-splice"), default="optimize")
    args = parser.parse_args()
    if min(args.workers, args.threads, args.batch) < 1 or args.limit is not None and args.limit < 1:
        parser.error("positive workers, threads, batch size and limit are required")
    puzzles = read_puzzles(args.puzzles)
    with args.puzzles.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = {r["id"]: r for r in reader}
        fieldnames = reader.fieldnames

    WORK.mkdir(parents=True, exist_ok=True)
    pools, metadata = snapshot(puzzles, args.sources)
    best = {}
    for pool in pools:
        for identifier, candidate in pool.items():
            prior = best.get(identifier)
            if prior is None or len(candidate) < len(prior):
                best[identifier] = candidate
    baseline = score(puzzles, best)
    # An expanding donor bank changes row signatures. Retain any shorter
    # verified result already exported for this local run while trying the
    # new combination, including after an interruption between batches.
    if args.output.exists():
        previous = read_submission(args.output)
        score(puzzles, previous)
        for identifier, candidate in previous.items():
            if len(candidate) < len(best[identifier]):
                best[identifier] = candidate
    if args.priority == "longest":
        selection = sorted(puzzles, key=lambda p: (-len(best[p.id]), p.id))[:args.limit]
    elif args.priority == "spread" and args.limit is not None and args.limit < len(puzzles):
        selection = [puzzles[i * len(puzzles) // args.limit] for i in range(args.limit)]
    else:
        selection = puzzles[:args.limit]
    if args.exe:
        binary = args.exe.resolve()
    else:
        binary, _, _ = compile_engine("atlas", compiler_path(args.compiler))

    # A row can be resumed even when other donors have gained unrelated rows.
    # Commit its raw optimized program before taking the whole-file checkpoint.
    database = sqlite3.connect(args.output.with_suffix(".sqlite"))
    database.execute("CREATE TABLE IF NOT EXISTS solutions "
                     "(signature TEXT PRIMARY KEY, puzzle_id TEXT NOT NULL, program TEXT NOT NULL)")
    input_digest = sha256(args.puzzles)
    binary_digest = sha256(binary)
    # Record the exact donor order and launch settings before dispatching the
    # first batch. This lets an interrupted run resume from its actual inputs.
    launch = {"puzzles":str(args.puzzles.resolve()),"puzzles_sha256":input_digest,
              "binary":str(binary),"binary_sha256":binary_digest,"sources":metadata,
              "strategy":args.strategy,"priority":args.priority,"limit":args.limit,
              "workers":args.workers,"threads":args.threads,"batch":args.batch}
    record_text=json.dumps(launch,sort_keys=True,separators=(",",":"))
    database.execute("CREATE TABLE IF NOT EXISTS launches "
                     "(signature TEXT PRIMARY KEY, settings TEXT NOT NULL)")
    database.execute("INSERT OR IGNORE INTO launches VALUES (?,?)",
                     (hashlib.sha256(record_text.encode("utf8")).hexdigest(),record_text))
    database.commit()
    signatures = {}
    resumed = []
    todo = []
    for puzzle in selection:
        donors = dict.fromkeys(pool[puzzle.id] for pool in pools if puzzle.id in pool)
        record = (input_digest, binary_digest, puzzle.id, list(donors))
        if args.strategy != "optimize":
            record = (*record, args.strategy)
        signature = hashlib.sha256(json.dumps(record, separators=(",", ":")).encode("ascii")).hexdigest()
        signatures[puzzle.id] = signature
        row = database.execute("SELECT program FROM solutions WHERE signature=?", (signature,)).fetchone()
        if row is None:
            todo.append(puzzle)
            continue
        candidate = tuple(tuple(step) for step in json.loads(row[0]))
        check(puzzle, candidate)
        if len(candidate) < len(best[puzzle.id]):
            best[puzzle.id] = candidate
        resumed.append(puzzle.id)
    total = write_submission(args.output, puzzles, best)
    print(f"Replayed all {len(puzzles)} incumbent rows, {total} instructions; "
          f"resumed {len(resumed)}, optimizing {len(todo)}", flush=True)
    start = time.monotonic()
    improvements = {}
    failed = []
    seen = len(resumed)
    batches = [todo[i:i + args.batch] for i in range(0, len(todo), args.batch)]
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        tasks = {executor.submit(optimize_batch, binary, batch, rows, fieldnames, pools, args.threads, args.strategy): batch
                 for batch in batches}
        for task in as_completed(tasks):
            batch = tasks[task]
            try:
                optimized = task.result()
            except (ValueError, RuntimeError) as error:
                labels = [p.id for p in batch]
                failed.append({"ids": labels, "error": str(error)})
                print(f"retained validated donors for {len(batch)} rows: {error}", flush=True)
                continue
            for identifier, candidate in optimized.items():
                database.execute("INSERT OR REPLACE INTO solutions VALUES (?,?,?)",
                                 (signatures[identifier], identifier,
                                  json.dumps(candidate, separators=(",", ":"))))
                prior = best[identifier]
                if len(candidate) < len(prior):
                    improvements[identifier] = len(prior) - len(candidate)
                    best[identifier] = candidate
            database.commit()
            seen += len(optimized)
            total = write_submission(args.output, puzzles, best)
            print(f"{seen}/{len(selection)} optimized, {len(improvements)} improved, {total} steps, "
                  f"{time.monotonic() - start:.1f}s", flush=True)
    database.close()
    report = {
        "programs": len(puzzles), "optimized": seen, "resumed": len(resumed), "baseline": baseline, "instructions": total,
        "output_sha256": sha256(args.output), "input_sha256": sha256(args.puzzles),
        "binary_sha256": sha256(binary), "atlas_source_sha256": sha256(HERE / "atlas.cpp"),
        "strategy": args.strategy,
        "sources": metadata, "improvements": improvements, "failed": failed,
        "seconds": round(time.monotonic() - start, 2),
    }
    args.output.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")
    print(f"Validated {total} steps; saved {baseline-total}; optimized {seen}/{len(selection)}", flush=True)


if __name__ == "__main__":
    main()
