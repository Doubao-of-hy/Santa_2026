# Sources and provenance

This is original source developed on this account. No third-party solution CSV,
private solution, competition label or external data is included in the release.
The base `recovered/solver.cpp` is our own previously published Apache-2.0 source,
recovered from https://www.kaggle.com/datasets/arsen123/santa-2026-original-dictionary-solver-source .
The recovered source hash is
`5264319457f09b9625e509d9e81d6502af3e92f183b6577fc1be73086428ebcb`.

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
  https://www.kaggle.com/code/kindasomethin/santa-2026-exact-portfolio-frontier-138460
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
