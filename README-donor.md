# 使用独立备用解压缩配方库

```bash
python -B scc_donor_select.py data/puzzles.csv submission.csv trial.csv \
  --donor other-independent.csv --donor optional-partial.csv \
  --ids-file ids.txt --seconds 1.5 --jobs 4
```

在项目根目录运行（Python 3.12+，已用 OR-Tools 9.15.6755 实测）。
显式提供 1～3 份从官方题目独立求出的 `id,program` CSV，允许不同文件包含同一题、允许部分题；不提供 `--ids-file` 时处理所有题。
脚本不读取预设候选路径，不访问网络。算法验证程序合法性，不能从 CSV 判断算式是否独立生成，因此来源由调用者保证。

只考虑备用 DAG 中尚不在当前 DAG、但能用当前值一步生成的值，优先保留有多个潜在下游或能替换低复用链条的候选。
每题最多增加 24 个值，每个最多 4 个生成配方、5 条连向原 DAG 的交叉配方。
联合选择时每个选中新值均计一条指令，最终还必须通过 48 寄存器合法编译。
`OPTIMAL` 只表示在构造出的有限配方库中算术 DAG 节点数最优，不是题目最短性证明。
保留原结果，只有严格更短的合法候选才替换相应行；完整结果经双重重放后写入新文件。
