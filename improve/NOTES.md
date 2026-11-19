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

## Best independent candidate

**`improve/submission.csv` = 137,038 instructions** (sha256
`8744ad59963070ec2e38aa060b8a1e5f2f1dd5376ecd1177d6d0b3d49bfe64bc`), fully
replayed on all 1,000 scored puzzles — **404 below** the repo's
`public-assisted/submission.csv` (137,442), shorter on 186+ puzzles, and does not
modify any original file. Pipeline: public merge (137,275) -> pure-Python
`algebra_rewrite` (137,254) -> cross-donor `mix.py` (137,223) -> C++
`virtual_search` x2 (137,108) -> `matrix_construct --anchored` hub reconstruction
x2 (137,038, still accumulating marginally). `crossover_graft.py` added 0.

Pipeline to reproduce the best candidate:

```powershell
python -B improve/fetch_public.py                 # download public donors (once)
python -B improve/merge_public.py                 # -> improve/merged/submission.csv (137,275)
python -B improve/algebra_pass.py                 # -> improve/algebra/submission.csv (137,254)
python -B mix.py data/puzzles.csv improve/mix/submission.csv submission.csv public-assisted/submission.csv improve/merged/submission.csv improve/algebra/submission.csv --joins --trials 4 --passes 6 --jobs 4
python -B mix.py data/puzzles.csv improve/submission.csv submission.csv public-assisted/submission.csv improve/merged/submission.csv improve/mix/submission.csv --joins --trials 6 --passes 10 --jobs 4
# C++ stage (requires work/toolchain g++; see run_cpp_search.ps1):
python -B virtual_search.py data/puzzles.csv improve/submission.csv improve/cpp/vsearch.csv --exe work/virtual/improve_planner.exe --leaves 120 --width 8 --scan 2 --joins 15949 --style 4 --tail 8 --jobs 8
python -B matrix_construct.py work/virtual/confident-models.jsonl improve/cpp/matrix.csv --incumbent improve/submission.csv --exe work/virtual/improve_planner.exe --variants 6 --workers 8 --anchored
python -B improve/merge_cpp.py                    # per-puzzle best of all sources
python -B elf.py data/puzzles.csv improve/submission.csv
```

## C++ constructive search (g++ now available)

The user supplied a portable WinLibs zip; it is extracted to `work/toolchain/`
(gitignored) and `virtual.cpp` compiles to `work/virtual/improve_planner.exe`
with `work/toolchain/mingw64/bin/g++.exe -O3 -march=x86-64 -static -std=c++17`.
The machine has 16 cores / ~32 GB RAM; run searches with `--jobs 8`+ (the earlier
"crashes" at jobs 4 were a 115 s timeout killing the process, exit 143, not OOM).

Results against the mixed incumbent:
- `virtual_search.py` warm (leaves 120 / width 8 / scan 2 / joins 15949 / style 4
  / tail 8): seed 17 saved 20 on 17 puzzles; seed 7 saved 15 on 15. A different
  config (style 6 / tail 12 / seed 99) saved 0 on 60 — single-config warm search
  saturates near the mixed incumbent.
- `matrix_construct.py --anchored` hub reconstruction is the most productive C++
  route: anchored to the 137,223 incumbent it saved ~91 instructions over the
  first 170 of 530 confident models. Re-anchoring to the improved 137,108 best
  drops the gain rate to ~1 per 30 models (diminishing returns — the candidate is
  near the ceiling of these methods).

`improve/run_cpp_search.ps1` automates compile + extended search + matrix.
`improve/merge_cpp.py` merges current best + vsearch + vsearch2 + matrix + matrix2
per puzzle with full replay. Larger gains toward the 130,600 leaderboard top
require substantially more compute (many variants/seeds, GPU search) than these
single passes; the remaining gap is structural, not a missing local trick.

## Experiments and negative results (so we do not repeat them)

- `proto_rewrite.py`: dedup-by-value + dead-code elimination changes program
  length by **zero** on every tested puzzle — the existing programs are already
  tight value-DAGs. A naive 1-op/2-op alternative-derivation rewrite with a
  tree-rank cost model makes them *worse* (double-counts shared values). Local
  peephole rewriting has no headroom.
- `reallocate.py` (register reallocation + instruction-order search,
  schedule-width 10 / operation-width 6): **0** puzzles improved — consistent
  with the programs already being tightly scheduled.
- `csplanner.cs`: an independent C# 5 port of the core LiveBank dictionary +
  TargetSearch beam planner, matching the native stdin/stdout interface so it
  plugs into `virtual_search.py`. Compiled with the .NET Framework `csc`
  (C# 5 only). **Fresh** runs average ~185 instructions/puzzle vs the incumbent
  ~137 — clearly inferior (it lacks `custom_palette`, `branching_products`,
  joint `meetings`, and the full move set of `virtual.cpp`), and large
  concurrent dictionaries exhaust memory. Per the project guidance ("do not
  grind on a bad algorithm"), this port is **abandoned** as a competitive solver;
  it is kept only as a documented experiment. The proven algorithm is
  `virtual.cpp`, which needs g++ to compile.

## Conclusion on the remaining gap

Public per-puzzle merging saturates near 138k and the repo's programs are
locally optimal under peephole/algebraic/reallocation passes. The leaderboard top
(130,600 on 2026-11-19) is ~6,650 below our 137,254; closing it requires running
the proven C++ constructive search (`virtual.cpp` / `matrix_construct.py`) with
extended compute, not more public sources or local post-processing.

## Turnkey C++ search (requires g++)

`improve/run_cpp_search.ps1` compiles `virtual.cpp` and runs an extended
`virtual_search.py` (leaves 96, width 7, scan 2, joins 13) warm-started from the
merged incumbent, then `matrix_construct.py --anchored --variants 8` on the
confident hub models. Outputs land in `improve/cpp/`; merge per-puzzle best
before submitting. g++ was not present on this machine and auto-mode blocked
automatic toolchain download; install it manually:

```powershell
winget install -e --id BrechtSanders.WinLibs.POSIX.UCRT --accept-source-agreements --accept-package-agreements
powershell -ExecutionPolicy Bypass -File improve\run_cpp_search.ps1
```

## Environment / handoff notes

- Kaggle CLI must be invoked as `python -m kaggle` (the `kaggle` shim exits
  silently). Account `hiyohane`, OAuth.
- No C++ compiler on PATH or anywhere on the machine; `csc.exe` (.NET Framework,
  C# 5) is available. The repo's strongest searchers need g++ to recompile.
- Direct Kaggle submission upload to the GCS endpoint stalls from this network
  (China uplink). The verified candidate `improve/submission.csv` is ready to
  submit when the network allows.
- GitHub `git push` requires interactive authentication (Git Credential Manager);
  read/clone works anonymously but write needs the user to authenticate. The
  improvement commits are prepared locally.