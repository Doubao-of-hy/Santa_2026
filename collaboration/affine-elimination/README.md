# Reverse recovery of two live-in values

The concurrent linear-equation search saved zero instructions on 24 frozen public rows. Recombining the unchanged parent recipes saved one instruction on scored_0152, from 115 to 114. The runnable row is in control-wins.csv. Its SHA-256 is 55598f425c0f8a6284065abdbb44b7e9ea7a73d45a06643e9da6e323847ffd04.

| Frozen set | Baseline instructions | Parent-only control | With reverse equations | Nonsingular equation pairs | Both anchors reachable independently of the two unknown inputs | New inverse paths |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Development, 8 | 1,239 | 1,239 | 1,239 | 594 | 45 | 51 |
| Held-out, 16 | 2,475 | 2,474 | 2,474 | 1,054 | 140 | 137 |

Three development and five held-out rows produced legal inverse paths with numbers absent from every parent. The 24 pairs of control/treatment selections each reached proven optimality for their finite value/recipe bank. Register replay used the 48-register interpreter. The manufactured positive test recovers 43 and 26 from 69, 17 and 2, creating 86 and 52 in four physical instructions. A proportional pair was rejected.

## What was tested

For anchors z = ax + by + c and w = dx + ey + f, first check that z and w can be reached without using x or y, possibly through different parents. Let D = ae − bd. For nonzero D, construct x = [ez − bw + bf − ec]/D and y = [aw − dz + dc − af]/D. Reduce numerator and denominator by their common factor, enumerate orders of signed terms and check all intermediates for exactness and the official positive value limit. Both expressions enter the same graph. The selector can use either or both. Demand for recovered inputs comes from the original target programs.

Witness discovery uses actual additive and small-scale multiplicative dependencies from the donor graphs. Its implemented bounds are six steps, absolute variable coefficient 24, absolute offset 48 and at most two levels when finding candidate input pairs. Paid scalar constants must already be present in a parent. The 188 new paths did not shorten the selected whole programs. Fixed-bank optimality does not imply that these puzzle programs are globally optimal.

## Source accounting for scored_0152

The original public 115-step row credits Wang Jakie, Kaggle notebook version 371736767, Apache 2.0, applied to the public 134487 project row attributed to E-Max AI, Santa 2026 | Public Frontier | Score 134,561. The other source is Alex Chilton’s 116-step Rudolph v67 portfolio row. Its dataset declares CC0 and documents its aggregate upstream collection. The source export has no per-row upstream column. The inherited public notice remains applicable.

Of all 16 subsets of four possible additional parents, the only one-parent subset that attains 114 adds Rudolph. Among the selected 114 canonical recipes, 23 occur only in the frozen incumbent, 14 only in Rudolph and 77 in both. The two other public sources and the local independent donor were tested and contribute no necessary recipes to the released row. The method that produced the row was the unchanged existing project selector. The reverse-equation search made no attributable scoring gain.

The explicit version pages are [Asterios Panoras v118, Apache 2.0](https://www.kaggle.com/datasets/asteriospanoras/santa-2026-elf-programs-and-experiments/versions/118), [Hanif Noer Rofiq v23, Apache 2.0](https://www.kaggle.com/datasets/hanifnoerrofiq/santa-2026-elf-calculator-peephole-programs/versions/23) and [Alex Chilton v67, CC0](https://www.kaggle.com/datasets/alexchilton/santa-2026-rudolph-programs/versions/67).

## Reproduction

Use Python 3.13, the project dependencies and a Git checkout containing 472b715858b74910ca9b1eafcbea4d64183fa09d. SANTA_CHECKOUT selects that repository, SANTA_PROJECT selects the solver directory, SANTA_PUZZLES selects the official puzzles.csv, and SANTA_DONORS points to the directory containing asterios118/best_programs.csv, hanif23/submission.csv and rudolph67/rudolph_programs.csv. Each input is normalized in memory and checked against DESIGN.md. A pre-normalized programs.csv in each donor directory is also accepted.

Run the following commands from the directory containing this report and experiment.py.

```text
python experiment.py dev
python experiment.py hold
python experiment.py audit
```

The audit repeats all 16 control subsets, writes the released row and runs a second evaluator, checkpoint.independent_score, on the original official scored_0152 inputs. The experiment borrows the fixed-bank selector in collaboration/structure-controls/ruler/selector.py. The public base and local base come directly from the frozen Git commit. The package contains no official puzzle data or downloaded donor tables.
