# Sources and provenance

This is original source developed on this account. No third-party solution CSV,
private solution, competition label or external data is included in the release.
The base `recovered/solver.cpp` is our own previously published Apache-2.0 source,
recovered from https://www.kaggle.com/datasets/arsen123/santa-2026-original-dictionary-solver-source .
The initial historical source hash was
`5264319457f09b9625e509d9e81d6502af3e92f183b6577fc1be73086428ebcb`.
The current own-source base, including macro-gated historical extensions, is
`72a5afc34541d8af2e7822ddb7a254d3823ba6364cf51584ce45f2da5ffebb8b`.

Conceptual attribution (not copied code):

- Tony Li, dictionary beam search and register reuse:
  https://www.kaggle.com/code/tonylica/elf-calculator-with-register-reuse
- konbu17, wider dictionaries, per-puzzle portfolios, cheapest-target ordering,
  virtual-register plans and exact graph rewrites:
  https://www.kaggle.com/code/konbu17/santa-2026-wider-dictionary-portfolio-163k
- Mizero Lucky Gall, rebuilding-cost-aware register eviction:
  https://www.kaggle.com/code/mizeroluckygall/elf-calc-cost-aware-registers-peephole-pass
- Sargis Khachatryan, cross-trace recipes and arithmetic cuts (MILP implemented independently):
  https://www.kaggle.com/code/avazaku/elf-calc-cross-trace-milp-arithmetic-cuts
- yuki16, heterogeneous per-puzzle portfolios:
  https://www.kaggle.com/code/yuki16/santa2026-boscoster-gapdescent-portfolio
- Michael McLoughlin, addition-chain algorithms, shared dictionary and dead-node ideas:
  https://github.com/mmcloughlin/addchain (BSD-3-Clause; no source copied).
- Ding et al., *Some New Methods to Generate Short Addition Chains*, shared window
  precomputation: https://arxiv.org/html/2207.13276v2 (conceptual reference only).

Public-source score claims are not our measurements. The release README reports
only our own replayed programs and original Kaggle evaluation observations.

Official input identifier: `santa-2026`.
https://www.kaggle.com/competitions/santa-2026
Inputs remain subject to competition rules; accept those rules and obtain inputs
through Kaggle. The input files and generated target-bearing artifacts are not
redistributed. The solver uses Python's standard library and C++17 standard library,
not models. The current optimizer additionally uses SciPy/NumPy and optional OR-Tools.

## Current public-program provenance and conceptual sources

The current result is a public-program portfolio with incremental original optimization,
NOT a claimed from-scratch 138k solver. Program inputs are referenced, never bundled.
See `reproduce_current.py` for exact pinned identifiers and required SHA-256 hashes.

- Pratham Jain, Exact Portfolio Frontier, version 3 (the same notebook was renamed
  from the 138628 slug to the 138460 slug):
  https://www.kaggle.com/code/kindasomethin/santa-2026-exact-portfolio-frontier-138441
- Angel Jacinto Sanchez Ruiz, Public Merge:
  https://www.kaggle.com/code/sacuscreed/public-merge
- Roman Rozen, IceFire Strong Start, version 16:
  https://www.kaggle.com/code/romanrozen/santa-2026-icefire-strong-start
- Bikram Basnet, Arithmetic Graph Rewrites:
  https://www.kaggle.com/code/bikrambasnet1/santa-2026-arithmetic-graph-rewrites
- Atakan Aldemir, joint recipe frontier:
  https://www.kaggle.com/code/atakanaldemir/santa-2026-joint-recipes-for-large-puzzles
- Sargis Khachatryan, shared helper joins and chain resynthesis:
  https://www.kaggle.com/code/avazaku/elf-calc-shared-helpers-chain-resynthesis
- Pablo Diego Pereira, Deterministic Atlas Solver, version 5:
  https://www.kaggle.com/code/pablodiegoo/santa-2026-deterministic-atlas-solver
  Inspected/executed as an external tool in a separate ablation (138601 -> 138592).
  Its code is not copied into this source-only release. Square peeling and backward
  arithmetic joins informed our independent short-cut search.
- Alex Chilton, Rudolph register allocation and ruin/recreate:
  https://www.kaggle.com/code/alexchilton/rudolph-the-red-nosed-register-allocator
- Juan Severiano, exact validator and reproducible arithmetic repair:
  https://github.com/Juan-Severiano/santa-2026

Foundational public portfolio lineage includes Tony Li, konbu17, thisray, Mizero
Lucky Gall, Hanif Noer Rofiq, Suka, Elias T.-H. Shieh, and the authors listed above.
Upstream dataset `konbu17/santa-2026-elf-calculator-programs` has explicit
Apache-2.0 metadata. We do not infer a redistribution right for every nested input;
all third-party program files remain excluded from this release.

The source here is original Apache-2.0 code. The base solver was recovered from our
own prior release; current additions are macro-gated square/quotient search, cut
resynthesis, shared-helper MILP, exact validation, and reproducibility tooling.

## Continuation sources

- The same Frontier publication, **version 4**, is now titled 138441. Pinned file
  hashes and versions are in `reproduce_latest.py`; v3 remains pinned by the
  preceding pipeline. No upstream programs are embedded or redistributed.
- Roman Rozen, IceFire Strong Start **version 18**, for donor diversity and
  constructive scheduling/CP-SAT concepts; no source code copied.
- Mizero Lucky Gall, Merge + Polish **versions 7 and 8**, for window/suffix-repair ideas
  and public donor programs:
  https://www.kaggle.com/code/mizeroluckygall/elf-calculator-best-of-public-merge-polish
- Georgy Mamarin, shared setup-cost analysis:
  https://www.kaggle.com/code/georgymamarin/santa-2026-why-the-first-target-costs-3x-more
- Public discussion of neighbouring fields and cumulative-benefit heuristics:
  https://www.kaggle.com/competitions/santa-2026/discussion/760300
- Schkufza, Sharma and Aiken, *Stochastic Superoptimization*, ASPLOS 2013:
  https://arxiv.org/abs/1211.0557 . Conceptual motivation for neutral search;
  our selected pipeline uses only strictly shorter final programs.

The new closure-deletion and coordinated-cut implementations are original work
on this account. Only our own source, documentation, license and tests are eligible
for the separate public dataset. Upstream public program inputs stay referenced
by identifier/hash because nested redistribution licenses are not all established
and competition data security rules still apply.

Version audit: the first unversioned Merge+Polish output was v7 even though
metadata subsequently reported current v8. Explicit version-qualified downloads
resolved this: v7 hash starts `d2be3223`, v8 starts `52c5bd13`. The reproduction
script pins each separately and never silently uses a mismatched download.
