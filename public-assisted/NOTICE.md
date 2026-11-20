# Attribution

## Public-assisted checkpoint

Asterios Panoras publishes the verified program collection and preserves each selected program's contributor in its `source` column. Release 96 contains 1,000 programs totaling 135,806 instructions. Its Kaggle metadata specifies Apache 2.0. The local candidate combines selected public programs with further arithmetic rewrites. Its `origins.csv` records the selected local source and the upstream credit for each puzzle. [Pinned Asterios release 96](https://www.kaggle.com/datasets/asteriospanoras/santa-2026-elf-programs-and-experiments/versions/96) · [Per-puzzle origins](origins.csv) · [License text](LICENSE.txt)

The release has 67 distinct original source descriptions. The accompanying count table preserves each description verbatim, including intermediate portfolio authors and prior optimizers. Pratham Jain documents the licenses and attribution of inputs to his portfolio. The Hanif contribution has its own notice. [Release 96 source counts](../collaboration/evidence/asterios-v96-sources.csv) · [Pratham Jain release 23](https://www.kaggle.com/datasets/kindasomethin/santa-2026-exact-portfolio-checkpoints/versions/23) · [Hanif v15 notice](Hanif-v15-NOTICE.md)

Local refinements include the original recipe recombiner published by Arsen Zakaryan, the large-neighborhood optimizer published by goodpjw2008, and this project's shared-helper ranking. A row can carry both the original program author's credit and the name of a later optimizer. [Optimizer credits](../generative/NOTICE.md) · [Frozen inputs and verification](../collaboration/methods.md)

## Historical credits

Asterios v13 is a collection verified and published by Asterios Panoras. The original dataset identifies the contributors to each program in its source column. The same credits are retained in origins.csv for selected Asterios v13 rows.

The programs are public work released under the Apache License 2.0, re-verified here; `source` names the origin of each one:
Tony Li (Elf Calculator With Register Reuse), konbu17 (Wider Dictionary + Portfolio and its dataset), Elias T.-H. Shieh (Verified Best Programs and dataset), Mizero Lucky Gall and thisray (credited in those datasets), Nilanjan_Saha123 (Best-of-Public Elf Optimizer), Atakan Aldemir (Joint Recipes for Large Puzzles), Angel Jacinto Sanchez Ruiz (Public Merge) and Sargis Khachatryan (Cross-Trace MILP). `elf_tools/elf_suffix_ext.cpp` is based on Nilanjan_Saha123's suffix rebuilder. This dataset is released under the Apache License 2.0.

[Original publication](https://www.kaggle.com/datasets/asteriospanoras/santa-2026-elf-programs-and-experiments/versions/13)

Earlier local rewrites also used Asterios v8 and v10. Contributors are listed in Asterios-history.csv and origins.csv. [Version 8](https://www.kaggle.com/datasets/asteriospanoras/santa-2026-elf-programs-and-experiments/versions/8) [Version 10](https://www.kaggle.com/datasets/asteriospanoras/santa-2026-elf-programs-and-experiments/versions/10)

Local changes include selecting shorter complete programs and resynthesizing arithmetic. The contributed Hanif v15 program lineage and local solver source credits are documented separately. [Hanif v15](Hanif-v15-NOTICE.md) · [Generative solver credits](../generative/NOTICE.md)
