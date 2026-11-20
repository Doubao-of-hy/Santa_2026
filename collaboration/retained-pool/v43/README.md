# E-Max AI 第 43 版的来源复现

E-Max AI 的第 43 版笔记本报告了剔除候选时保留初始父程序的图搜索。该版实际发布的 1000 道题解完整复核为 134301。这里在已有 Apache 2.0 引擎上本地实现其搜索规则，用可追溯父程序在作者选择的三道题上运行。第 0716 题完整保留了三个原始输入，以种子 491639、1000 轮得到 116 条指令，与第 43 版逐条相同，比冻结公开父本的 117 条少一条。第 0147 题缺少可归属的原始主程序，替换为本仓库的当前程序，第 0519 题排除了一个无法核实的候选。两题都未在本地重建出更短的程序。[E-Max AI 第 43 版](https://www.kaggle.com/code/royalacecat/santa-2026-public-frontier-score-134-301?scriptVersionId=371837059) · [wang Jakie 搜索引擎](https://www.kaggle.com/code/wangjakie/santa-2026-arithmetic-recipe-pool-and-milp?scriptVersionId=371736767)

`cases.json.gz` 包含第 0716 题三个父程序的代码、实际来源、作者和校验值。第 0716 题也出现在 Asterios 的公开第 123 版。以下命令会重新从固定 Git 记录编译引擎并逐条重放。需要 C++17 编译器及参赛者自行取得的官方题面。

```text
python -B collaboration/retained-pool-v43/replay.py --repo . --puzzles data/puzzles.csv
```
