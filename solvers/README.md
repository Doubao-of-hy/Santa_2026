# 求解器

从仓库根目录运行 `python -B run.py --output candidate.csv --profile quick` 可以生成一份候选。若要改进某一类方法，可从下表找到对应实现。实验的输入、比较结果与复跑记录见[协作实验索引](../collaboration/README.md)。

| 目录 | 内容 |
| --- | --- |
| [construction](construction/) | 从题目初值构造程序，包括混合进制、算式库和同余搜索 |
| [arithmetic](arithmetic/) | 寻找多个目标可共享的因数、余数和中间值 |
| [graphs](graphs/) | 改写算式依赖图、交换候选的局部结构、合并不同来源的解 |
| [registers](registers/) | 在 48 个寄存器内重新排布程序，搜索可替换的指令段 |
| [matrix](matrix/) | 识别目标之间的乘积结构，并构造对应算式 |
| [proofs](proofs/) | 精确搜索、证明边界、复验最短性 |
| [gpu](gpu/) | GPU 并行搜索及其计算内核 |
| [native](native/) | C++ 与 C# 搜索程序，包括[共享中间值搜索](native/virtual.cpp) |

单独运行某个 Python 求解器时，在仓库根目录使用模块名。例如，`python -B -m solvers.graphs.virtual_search --help` 查看依赖图搜索参数，`python -B -m solvers.matrix.matrix_scan --help` 查看乘积结构识别参数。完整候选用[评分器](../elf.py)逐题复验。
