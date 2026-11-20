# Reworking the 50 latest public-merge rows

The 50 rows improved by the four-source public release were frozen at 62378d6 and searched again. The registered single-parent method saved two instructions and the registered crossover method saved three. Taking the shortest row from either arm reduced the frozen full submission from 134,324 to **134,321**. Two separate interpreters checked the accepted rows. The second interpreter replayed all 1,000 merged programs. These are local public-assisted results.

| Row | Frozen | Single-parent Wang search | External-parent crossover | Selected source |
| --- | ---: | ---: | ---: | --- |
| 0147 | 96 | 94 | 94 | Single parent, GoodPJW v10 |
| 0557 | 109 | 109 | 108 | Public releases Asterios v119 and Asterios v113 |

The remaining 48 rows retained their original lengths. The cohort began with 5,640 instructions. Every row had a distinct alternate arithmetic graph. Both arms received 360 rounds and the same random seed per row. Cumulative task wall times across the 50 cases were 100.223 seconds for the single-parent arm and 100.279 seconds for crossover. The 0147 tie was assigned to the single-parent arm as registered. The one extra instruction saved specifically by the crossover arm occurred on 0557. This comparison covers one seed on the 50 freshly merged cases.

## Credits and outputs

Wang Jakie supplied the original incremental search. GoodPJW v10 includes the one-line external-parent admission change credited by GoodPJW to E-Max AI (RoyalAceCat). Row 0147 builds on GoodPJW’s v10 public-assisted our_programs.csv. Row 0557 combines the Asterios v119 entry credited to Ertuğrul Özer and the Asterios v113 entry credited to Wang Jakie. The paired output preserves the contributing source chain in shorter.origins.csv. design.json records all considered source archives, licenses and actual parents for each trial. Source details also appear in the repository public-assisted/NOTICE.md, GoodPJW-v10-NOTICE.md and Hanif-v24-NOTICE.md.

- [Wang Jakie’s original algorithm](https://www.kaggle.com/code/wangjakie/santa-2026-arithmetic-recipe-pool-and-milp?scriptVersionId=371736767)
- [GoodPJW v10](https://www.kaggle.com/datasets/goodpjw2008/santa-2026-dag-lns-programs/versions/10)
- [Asterios v119](https://www.kaggle.com/datasets/asteriospanoras/santa-2026-elf-programs-and-experiments/versions/119)
- [Asterios v113](https://www.kaggle.com/datasets/asteriospanoras/santa-2026-elf-programs-and-experiments/versions/113)

## Replay

Use Python 3.13 and a clone containing commits 62378d6 and 472b715. Set SANTA_CHECKOUT to the clone, SANTA_PROJECT to the solver tree containing the official data/puzzles.csv, and SANTA_DONORS to the parent of the four donor folders. The exact raw input paths are good10/our_programs.csv, good10/public_frontier.csv, hanif24/submission.csv, asterios119/best_programs.csv and rudolph68/rudolph_programs.csv. The driver can normalize them in memory. The independent verification requires only the two result CSVs, row records, repository and official puzzle file.

Set SANTA_BIN to the directory containing the two native solver programs. Build inc-local from generative/wang/incremental.cpp in the repository and inc-good from wangjakie_strategies/incremental_seeded.cpp in GoodPJW v10 using g++ -O3 -std=c++17, adding -static on Windows. Use the .exe suffix on Windows. Both solvers use their distributed include files. The original compiler output hashes are recorded in design.json. A rebuilt toolchain may produce a different executable hash, so the replay flag accepts that change and still verifies all data, cohort and parameter hashes.

Run in a working copy if retaining the original timings is important. The search writes run-specific elapsed times, programs, and source credits. Verification recomputes the full-table total and SHA-256, then removes the temporary full submission.

```text
python experiment.py run --rebuilt --jobs 4
python verify.py --puzzles PATH/TO/puzzles.csv
```

The experiment-specific search used the same authorized public binaries already built for the comparison on independently constructed inputs. All working files were stored on E. The final folder holds only this report, the registered design, the two scripts, row-level outcomes, verified winning programs with matching attribution, and the replay receipt.
