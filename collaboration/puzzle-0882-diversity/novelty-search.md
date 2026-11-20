# Puzzle 882: searching outside the frozen helper families

The verified 22-step necessary condition in `five-new.md` limits a candidate to four helpers from the 20-value union in `parents.json`. We checked whether that condition can guide construction toward different valid programs. The shortest program overall stays at 23 steps for these runs.

Both policies started from the same five frozen programs. Each seed ran for 1,800 iterations per policy. The control used the selection policy from `collaboration/puzzle-0711/balanced.cpp`. The guided policy recorded programs by length and old-helper count. In most iterations it sampled a near-minimum of length plus a randomized penalty for more than four old helpers. When rebuilding a missing target it also charged 1.2 for each new operand from the old union.

| Seed | Shortest control, ≤4 old helpers | Shortest guided, ≤4 old helpers |
| --- | ---: | ---: |
| 112099 | 27 | 26 |
| 124017 | 27 | 25 |

The stored 25-step program uses 13 helpers. Only one belongs to the frozen union. It can seed further search in the region compatible with a 22-step program. These two seeds measure the sampled trajectories and provide no global lower bound. Every representative program was replayed on the official puzzle. For seed 112099 the control's first 64 iterations also reproduced the original search's 24 output lines after removing instrumentation.

Verify the witness and original parent union from the repository root with Python 3.12+:

```sh
python collaboration/puzzle-0882-diversity/novelty_search.py --puzzles /path/to/puzzles.csv
```

Add `--rerun --cxx /path/to/g++` to compile and reproduce the four runs. The recorded values were obtained using MinGW-w64 GCC with C++17 and libstdc++. Compiler or standard-library changes can affect the sampled programs.
