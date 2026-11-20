# Does the order of two searches change the result?

On the 16 preregistered independent programs from 243776e, starting Atakan and Wang separately saved six instructions. Running Atakan first and passing its result to Wang saved seven. Running Wang first and passing its result to Atakan saved six. The best result reduced the independently replayed full table from **140734 to 140727**.

| Row | Frozen parent | Atakan alone | Wang alone | Atakan then Wang | Wang then Atakan |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0535 | 144 | 143 | 143 | 143 | 143 |
| 0604 | 108 | 108 | 106 | 106 | 106 |
| 0627 | 118 | 116 | 118 | **115** | 116 |
| 0807 | 130 | 130 | 129 | 129 | 129 |

Only 0627 shows an advantage over independently starting both methods. The additional gain is one instruction. Atakan’s intermediate 116-step program makes it possible for the same Wang configuration to reach 115. The remaining 12 rows kept their previous lengths.

## Matched comparison

The first group contained the eight winners from the preceding Atakan study. The other eight were previously tested Atakan nonwinners with unchanged parent tapes. Each comparison case was matched on frozen instruction count, then target count and largest-target bit length. Five pairs matched exactly on instruction count. The other three differed by 1, 1 and 2. On the eight prior winners, Atakan then Wang saved five instructions, compared with four for independent starts. On the eight matched cases, every strategy saved two instructions on 0604. These groups measure this selected cohort rather than competition-wide average performance.

Every logical arm received one v30 Atakan frontier search with style 13 and one original Wang incremental search with 360 rounds. Each row used the same Wang seed in every arm. Eight prior unchanged Atakan outputs were reused after matching the input tape and configuration. All other repeated stages in this experiment were reused only when method and exact input were identical. Across the 64 named stage evaluations there were 29 new native calls, eight historical reuses and 27 reuses of this run’s stage outputs.

stages.json.gz preserves all 96 physical tapes, including the 16 frozen parents, 64 individual or sequential stage results, and 16 independent-start winners. rows.json identifies each stage’s input, output, source of computation, SHA-256 and instruction count. verify.py replays all 96, verifies each stage link and independently replays all 1,000 final programs. The four shorter rows and matching provenance are included in shorter.csv and shorter.origins.csv.

## Reproduction

SANTA_PROJECT points to the project code, SANTA_CHECKOUT to a Git clone containing 243776e and aca4989, and SANTA_PUZZLES to the official puzzles.csv. Set SANTA_ATAKAN_EXE to the v30 binary built by the accompanying Atakan frontier package. Set SANTA_WANG_EXE to the executable compiled from generative/wang/incremental.cpp. The fixed binary hashes are in design.json. Passing --rebuilt allows the platform-specific binary hashes to differ. The source and all other inputs or configuration stay fixed. Run from a working copy.

```text
python experiment.py --jobs 4
python verify.py
```

To verify without any native solver binaries, run python verify.py. The public algorithm authors and inherited independent parent implementations are preserved in parent-winner-credits.json and shorter.origins.csv. [Atakan Aldemir v30](https://www.kaggle.com/code/atakanaldemir/santa-2026-joint-recipes-for-large-puzzles?scriptVersionId=371505096) · [Wang Jakie’s original incremental search](https://www.kaggle.com/code/wangjakie/santa-2026-arithmetic-recipe-pool-and-milp?scriptVersionId=371736767)
