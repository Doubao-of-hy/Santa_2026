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
- Sargis Khachatryan, cross-trace recipes and arithmetic cuts (reviewed; MILP not used):
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
not models or external datasets.
