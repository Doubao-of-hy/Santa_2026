# Solver experiments and prior searches

These are historical runs on fixed, hashed parents. Compare scores within a row. The current independent and assisted programs have separate per-puzzle origin ledgers. The tables below report local instruction counts from full 1,000-puzzle replays. [Current project status](../README.md) · [Independent origins](../origins.csv) · [Assisted origins](../public-assisted/origins.csv) · [Experiment hashes and gains](evidence/solver-experiments.json)

## Refining a single existing program

| Method | Parent | Result | Steps saved | Puzzles improved |
|---|---:|---:|---:|---:|
| GoodPJW v5 on independent programs | 142219 | 141890 | 329 | 218 |
| GoodPJW v5 on publicly attributed programs | 135222 | 135167 | 55 | 42 |
| Arsen v15 and local helper ranking on independent programs | 141613 | 141555 | 58 | 51 |
| Arsen v15 and local helper ranking on publicly attributed programs | 135161 | 135138 | 23 | 20 |

**GoodPJW.** The native engine searches alternative computations around a group of existing values. The independent pilot compared groups of 3 and 8 on 50 stratified puzzles with matched seeds and 1.8 seconds per group. The full pass chose the group by stratum. Each puzzle search received only its own parent program. Exact scores of archived programs can be replayed. A new time-limited search can explore a different number of candidates. [Pinned GoodPJW release](https://www.kaggle.com/datasets/goodpjw2008/santa-2026-dag-lns-programs/versions/5)

**Arsen and shared helpers.** Arsen's optimizer rebuilds arithmetic recipes over the parent's values, selects an acyclic graph with CP-SAT, and schedules it into physical registers. The published helper ranking favors new values that can serve several existing outputs. Our ranking counts old instructions that can be removed, excludes any still needed to construct the replacement, and counts each removable instruction once across all uses. On the assisted parent, using zero helpers saved 2 steps. Giving the original ranking 24 helpers saved 9, and the local ranking with 24 helpers saved 17. Taking the shortest per puzzle and repeating on the 20 changed programs saved 23 steps in total. On the independent parent, the corresponding single-pass savings were 7, 20 and 51. Their per-puzzle union saved 55, and a repeat on the winners saved another 3. Runs used one CP-SAT search worker, seed 20261120 and a deterministic-time budget of 0.22 per call. An optimal CP-SAT status applies to the enumerated recipes. [Pinned Arsen release](https://www.kaggle.com/datasets/arsen123/santa-2026-original-dictionary-solver-source/versions/15) · [Per-puzzle gains](evidence/solver-experiments.json)

## Small programs rebuilt from official starting values

We selected 34 puzzles with independent parents of 16–52 instructions and tested the same puzzle IDs on the assisted line. The independent line selected and searched its candidates using independent programs. Each search added selected old intermediate values to the required outputs. The machine had to construct those values from the official starts. We then omitted a subset of the old values and allowed up to three freely chosen intermediate integers. Each witness was scheduled and physically replayed. The native search agreed with an independent exhaustive implementation on 140 small integer cases. All 120 positive cases produced valid programs.

| Conditional search | Independent parent 141669 | Assisted parent 135161 |
|---|---:|---:|
| Distinct subsets with a valid witness | 2 | 0 |
| Distinct subsets exhaustively ruled out | 27025 | 26046 |
| Distinct subsets stopped at the node limit | 700 | 574 |
| Puzzles with all three-old-values-omitted subsets ruled out, allowing two free values | 19 | 20 |
| Puzzles with all four-old-values-omitted subsets ruled out, allowing three free values | 7 | 7 |

The two independent witnesses shortened 0021 from 43 to 42 and 0221 from 38 to 37, matching the later incumbent. Both pairs then went through single-parent and two-parent Arsen selection and matched GoodPJW searches. The equal-length parents used identical sets of intermediate numbers. After normalizing commutative operand order, each 0021 parent had two recipes absent from its counterpart. The 0221 recipes were identical. Neither puzzle shortened further. The search established conditional exclusions and produced no new global optimality certificate. The evidence lists every puzzle covered by the complete three- and four-omission searches. [Coverage, parent hashes and crossover comparison](evidence/solver-experiments.json)

## Comparisons with no gain on the tested inputs

| Comparison | Observed result |
|---|---|
| Asterios v96 and Rudolph v51 | Each release scored 135806 locally. Rudolph v51 had zero rows shorter than the 135161 assisted parent across all 1,000 puzzles. |
| Wider helper pool | The published ranking with 96 helpers and the local ranking with 8 helpers each produced zero improvements on the same 160 stratified assisted puzzles at the same 0.22 budget. |
| Signed-digit Horner construction and retained anchors | Rob Sartin's code completed all 32 stratified puzzles in 9829 steps. The assisted and independent reference totals were 4322 and 4524. |
| One- and two-step greedy construction | Maroofiums' solver completed none of those 32 puzzles. |
| Priyanshu RAJ v6 recipe recombination | The current assisted parent alone and the same parent plus Asterios v96 each ended at 4322 steps on the 32 puzzles. |

The source-count table preserves the original 67 distinct credits in the 1,000-row Asterios v96 release. The current assisted origins identify the credited source for each selected row. [Asterios attribution](../public-assisted/NOTICE.md) · [Release 96 source counts](evidence/asterios-v96-sources.csv) · [Rudolph v51](https://www.kaggle.com/datasets/alexchilton/santa-2026-rudolph-programs/versions/51) · [Rob Sartin revision](https://github.com/robsartin/elf-abacus/tree/8843ff7566e8fe4d001bc3464cfb06fbf4b49d54) · [Maroofiums revision](https://github.com/maroofiums/santa-elf-calculator/tree/9ff0a44bb15d08fef0859d8df8c966a3a214f755) · [Priyanshu RAJ v6](https://www.kaggle.com/datasets/priyanshurajpgiit/santa-2026-v6-py/versions/1)

The paid-helper ranking can also be run on any single parent. [Code and CLI](../generative/arsen_v15/README.md)
