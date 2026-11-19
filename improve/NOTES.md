# Independent improvement pass (2026-11-20)

This directory is a self-contained improvement layer. It does **not** modify any
original solver or submission in the repository root; it only reads them and
writes new candidates under `improve/`.

## What was done

1. Fetched official `santa-2026.zip` into `data/` (gitignored) and replayed both
   existing submissions with `elf.py`:
   - `submission.csv` (independent): **146,435** instructions, verified.
   - `public-assisted/submission.csv`: **137,442** instructions, verified.
2. Downloaded the latest public program datasets (Asterios v23 = 138,169,
   Hanif peephole, ozertuu verified, alexchilton rudolph, konbu17,
   kindasomethin checkpoints 138441/138460/138628, sacuscreed, thisray) plus the
   repo's own `work/gpu/domain-independent.csv` partial candidate.
3. `merge_public.py` independently replays every candidate program per puzzle
   and keeps the shortest valid one. Result: **`improve/merged/submission.csv`
   = 137,275** instructions (167 fewer than the repo public-assisted baseline).
   Per-puzzle provenance in `merged/origins.csv`, hashes in `merged/result.json`.
   Adoption: 877 repo-public-assisted, 103 Asterios-v23, 8 ozertuu, 12 gpu-domain.

## Findings that shape the next algorithm

- `breakdown.py`: of 137,275 instructions, **60,362 (44%)** build small helper
  values (<=1e7: hubs, remainders, radix bases), 26,898 (20%) emit targets,
  50,015 (36%) are large helpers (shared products / scaled products).
- `proto_rewrite.py`: dedup-by-value + dead-code elimination changes program
  length by **zero** on every tested puzzle — the existing programs are already
  tight value-DAGs. A naive 1-op/2-op alternative-derivation rewrite with a
  tree-rank cost model makes them *worse* (double-counts shared values). Local
  peephole rewriting therefore has no headroom; improvements must come from
  better global structure (cheaper shared hub/remainder construction), not from
  post-hoc peephole passes. This prototype is kept only as evidence and is not
  used in the merged submission.
- Public per-puzzle merging saturates near 138k; the leaderboard top (130,600 on
  2026-11-19) is ~7k below the public frontier, so the remaining gap requires a
  stronger constructive search rather than more public sources.

## Reproduce

```powershell
python -B improve/merge_public.py        # rebuild merged/submission.csv
python -B elf.py data/puzzles.csv improve/merged/submission.csv
python -B improve/breakdown.py           # cost breakdown
```

## Environment notes

- Kaggle CLI must be invoked as `python -m kaggle` (the `kaggle` shim exits
  silently). Account `hiyohane`, OAuth.
- No C++ compiler on PATH; `csc.exe` (.NET Framework) is available. The repo's
  strongest searchers (`virtual.cpp` etc.) need g++ to recompile.
- Direct Kaggle submission upload to the GCS endpoint stalls from this network;
  GitHub clone/fetch works.