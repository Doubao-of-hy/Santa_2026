# 精确重建程序中的一段计算

将一部分旧操作移出程序，保留这部分必须提供给后续操作的整数，并从真正可用的起始整数重新搜索。这份数据包含两条路线合计 **9,771 个不同的计算接口**。两次搜索若题号、起始整数和必须提供的整数完全相同，只计一个接口。其中 **8,988 个**已确定该接口所需的最短长度。接口的起始整数有时由保留的前半段计算得出。以上结果只适用于这些输入和输出，全题的下界另见逐题证明。[固定接口记录](conditional.jsonl.gz) · [分组、输入与实现哈希](conditional-receipt.json) · [整题下界](../puzzle-bounds.csv)

固定接口使用 sparse-all 搜索生成给定边界数所需的最少额外整数。档案每行含题号、起始整数、必须生成的数、已证下界、已知上界和各预算的决定。FOUND 表示已找到数值构造，UNSAT 表示本预算的分支已完全穷尽，UNKNOWN 表示到达节点上限。写入提交前还需将整题编排到 48 个物理寄存器并重放。第 2 题原先的依赖顺序最多要同时保留 66 个数。调整顺序后得到合法的 246 条程序，比原来的 247 条少一步。[寄存器重排结果](retained-receipt.json) · [第 649 题完整回放](../exact-boundary/README.md)

第 25 题展示另一种搜索方式。选择第 25 题原程序中 35 个供后续步骤使用的边界值，对辅助值 614、4,259、9,824 开放替换，其余旧辅助值仍须从官方初值生成。这 41 条构成的程序段可以缩短，完整独立程序由 124 条减至 123 条。不同批次使用不同的节点和子集预算，逐批的缩短数字不能相加。[冻结父本](parent-0025.csv) · [逐批记录](retained-rows.jsonl.gz)

在仓库根目录运行以下 PowerShell 命令。该案例需要比赛官方的 data/puzzles.csv、Python 和支持 C++17 的 g++。这条路径只使用 CPU。

```powershell
python -B collaboration/window-search/build.py work/conditional
python -B retained_boundary.py collaboration/window-search/parent-0025.csv collaboration/window-search/ids-0025.txt work/conditional/0025.csv --exe work/conditional/retained-batch.exe --per-window 22 --jobs 1
python -B collaboration/exact-boundary/verify.py data/puzzles.csv --solver work/conditional/sparse-all.exe
```

第 25 题命令输出共 20 个决定，19 个 UNSAT、1 个 FOUND，完整程序节省 1 条。第 649 题命令复验 119 条与 118 条两份程序，固定接口的 3 辅助数构造和 2 辅助数无解证明。
