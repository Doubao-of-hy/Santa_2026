# 用穷举的小电路改写现有程序

独立和公开辅助各检验 32 道开发题、32 道留出题。两种解释器重放两份完整的 1,000 题候选后，仍为原父本 **140,811** 和 **134,385** 条。合成的完全平方能从 6 条缩至 2 条。此次真实题上的所有改写都未减少整题需要的运算数，因此结束本轮搜索。

| 父本与分组 | 检查的子图 | 存在对应短电路的子图 | 实际整数上尝试的不同改写 | 整题节省 |
| --- | ---: | ---: | ---: | ---: |
| 独立开发 | 4,491 | 1,450 | 4,148 | 0 |
| 独立留出 | 3,103 | 1,203 | 3,490 | 0 |
| 公开辅助开发 | 3,214 | 1,169 | 3,399 | 0 |
| 公开辅助留出 | 2,811 | 1,116 | 2,884 | 0 |

每个数保留最近的 96 种至多两输入边界，考察 3 至 16 个节点的子图。C++ 枚举至多 4 条指令，允许重复使用同一中间值。对每个签名、每个长度最多保留 8 个不同特点的候选。两个模取值点只负责筛选；整数整除、数值上限以及整题合法性均以实际程序为准。独立枚举另核对了 1 至 3 条指令的 2,586 个可达「签名、长度」组合。[预登记](design.md) · [枚举器检查](synth-tests.json) · [逐题结果](results.json)

复现时从主分支提交 `472b715` 提取 `submission.csv` 和 `public-assisted/submission.csv`，两个原件的 SHA-256 见逐题结果。调用时提供各自路径及本地官方题库。所有输出进入指定工作目录。

```text
g++ -O3 -std=c++17 collaboration/circuit-cuts/synth.cpp -o synth.exe
python -B collaboration/circuit-cuts/cuts.py --repo . --puzzles data/puzzles.csv --pure FROZEN_PURE.csv --assisted FROZEN_ASSISTED.csv --executable ./synth.exe --output work/circuit-cuts
```
