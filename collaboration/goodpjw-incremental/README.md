# GoodPJW 第 10 版的 Wang 搜索

在 16 道独立题上，逐题择优把已重放的 1,000 题独立候选从 **140,811 缩到 140,805**。第 180 题省 2 条，第 225 题省 2 条，第 429 题和第 927 题各省 1 条。当时公开辅助候选已有更短的这四题程序。每份冻结父程序、全部 80 份搜索输出以及合并后的整表都经两套寄存器解释器重放。[四份可运行程序](winners.csv) · [每份程序的引擎、父本和作者](winner-origins.csv)

第 10 版的 18 个 C++ 及包含文件中，16 个与本仓库或本地保留的 Wang 原始源码逐字节相同，另一个 `anneal_seeded.cpp` 与本仓库版本执行相同的父本加载循环。新增的 `incremental_seeded.cpp` 相对 `incremental.cpp` 仅新增一行，在进入迭代前把其他父程序的算式图加入交叉池。所有底层图改写操作沿用原实现。GoodPJW 的驱动最多选 4 份不同的历史程序，每份最多比父本长 3 条；其运行脚本循环切换策略和随机种子。原搜寻逻辑署名 wang Jakie，GoodPJW 的说明把预装父本的想法归于 E-Max AI。[固定 v10 发布页](https://www.kaggle.com/datasets/goodpjw2008/santa-2026-dag-lns-programs/versions/10) · [逐文件哈希、原作者声明和许可证](source-diff.json)

在当前独立候选中排除已登记的 64 道路径重连题，另有 285 题符合独立历史父本相差不超过 3 条且程序不同的条件。按长度分八层，各取两题。这 16 题共有 20 份额外独立父程序。每臂每题计算 180 轮，相同题号使用相同随机种子。单父本增量搜索的两个版本在全部 16 题给出逐条相同的程序，两种多父本退火版本也是如此。[冻结题号和全部父本来源](design.json) · [分臂结果和程序指纹](independent-results.json)

| 引擎 | 父本 | 缩短题数 | 共省 |
| --- | --- | ---: | ---: |
| 本地 Wang 增量版 | 单父本 | 2 | 3 |
| GoodPJW 增量版 | 单父本 | 2 | 3 |
| GoodPJW 增量版 | 多父本 | 3 | 3 |
| 本地多父本退火 | 多父本 | 3 | 4 |
| GoodPJW 多父本退火 | 多父本 | 3 | 4 |

额外父本让增量版在第 927 题从 124 缩至 123，同时在第 180 题只到 88，单父本能到 87。多父本相对单父本在这个样本上的总节省相同，逐题结果互补。该对照只覆盖这 16 道题及这组种子。

使用包含冻结提交的 Git 克隆、Python 3.12 或更新版本及 GNU C++17 编译器，从仓库根目录运行以下命令。脚本先核对发布包 SHA-256 及原生文件指纹，从临时目录编译，直接执行需要的搜索引擎。输入程序均来自登记的独立 Git 提交。

```sh
python -B collaboration/goodpjw-incremental/compare.py --puzzles data/puzzles.csv --archive /path/to/goodpjw-v10.zip --out recovered
```

已有编译结果时可用 `--binary-dir` 替代 `--archive`。目录内应包含 `inc-local`、`inc-good`、`anneal-local` 和 `anneal-good`，Windows 使用对应的 `.exe` 文件名。
