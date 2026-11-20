# 单题复验四种局部改写

从仓库根目录运行以下命令。需要 Git、Python 3.12 或更新版本、GNU C++17 编译器，以及官方的 `puzzles.csv`。Python 依赖可用 `python -m pip install -r requirements.txt numpy ortools==9.15.6755` 安装。本次使用 python-flint 0.9.0。

```sh
python -B collaboration/wang-polish/polish_replay.py --puzzles data/puzzles.csv --lane own --id scored_0180
python -B collaboration/wang-polish/polish_replay.py --puzzles data/puzzles.csv --lane assisted --id scored_0807
```

默认从源码编译四个本地程序，临时目录在复验结束时清理。`--cxx` 可指定编译器，`--scratch` 可指定已有的临时目录。已有编译结果时，分别用 `--group-binary`、`--exchange-binary`、`--factor-binary`、`--order-binary` 指定其中任意一个。最后一项用于中间值替换触发寄存器重排时使用的调度器。用 `--output row.csv --report run.json` 保存优胜程序及其记录。

独立父本取自 Git 提交 `22e78c3` 的 `submission.csv`，公开辅助父本取自 `767761d` 的 `public-assisted/submission.csv`。复验器核对整份父本和官方数据的 SHA-256，确认题号在冻结分组中，再读取同一提交中的逐题来源。Git 克隆需要包含这两个提交。[试验分组和父本指纹](../evidence/wang-polish-design.json)

正序依次尝试下表的四种方法，倒序从同一父程序倒过来执行。每种方法提出的程序都经过 `elf.check` 与独立的寄存器解释器重放。只有严格缩短的程序进入下一步。一轮结束时没有再缩短即停止，两种次序共用相同输入和相同方法的结果缓存。

| 方法 | 冻结参数 |
| --- | --- |
| 成组改写 | 每次 1.15 秒，组宽 8，种子为 1731 加题号乘 73。启用配对及辅助值，kicks 为 1000，kslack 为 2。 |
| 中间值替换 | 192 次测试，96 对候选，两轮，前瞻为 0，重新安排寄存器的时间参数为 0.2。 |
| 带余数的因数分解 | 36 个切点，64 个偏移，关闭联合因数构造，最多保留 32 个候选，启用候选选择。 |
| 有成本的算式组合 | 候选辅助值宽度 24，额外通用辅助值为 0，OR-Tools 确定性时间预算为 0.32。沿用重组器默认种子 20261120 和单搜索线程。 |

独立第 180 题两种次序都由成组改写从 90 缩至 89，所得程序与历史程序相同。公开辅助第 807 题正序由成组改写从 126 缩至 124，倒序先由因数分解缩至 125，再由成组改写缩至 124。成组搜索按墙钟时间停止，因此机器速度和当前负载可能影响重跑结果；记录保留了实测改写与原记录的比较。[180 实测记录](verified-0180.json) · [180 程序](own-pilot.csv) · [807 实测记录及父本作者](verified-0807.json)

运行时加上 `--allocation-control` 可单独验证寄存器压力回退路径。这个与赛题无关的对照从初值 1 和 1000 构造一组同时存活 54 个数的运算，再先后调用原生重排器和 OR-Tools 操作数分配器。两条路径各产生一个可放入 48 个寄存器的程序，两个解释器分别重放。所需的 Python 模块、原生源码和峰值计数函数已随仓库跟踪。[调度器源码及 Python 驱动](../../work/creative/pressure) · [算式组合与原生来源指纹](polish-sources.json)

另用干净 Git 副本编译了原生重排器，并把第 444 题两份历史候选算式图送入实际 `value_exchange.run_row`。首份在重排后由 238 缩至 237；第二份实际进入操作数分配，确认固定顺序无法满足寄存器上限后保留 238 条。候选生成输出在这个回归检查中固定，所有后续调度决策与两次解释器重放都实际执行。[两个条件分支的运行记录](verified-allocation-branch.json)

## 源码和许可

成组引擎 `group_elfopt.cpp` 由 Kaggle 用户 goodpjw2008 发布。文件保留原始内容，SHA-256 为 `16f12d4963acfe795f89f9632e941fb1aea9d8d8de55ac958a45b17a02881db2`。原实验的可执行文件由第 3 版的 `elfopt.cpp` 编译，第 5 版提供相同字节。两版数据集的源码许可记录均为 Apache-2.0。[GoodPJW 第 3 版](https://www.kaggle.com/datasets/goodpjw2008/santa-2026-dag-lns-programs/versions/3) · [第 5 版](https://www.kaggle.com/datasets/goodpjw2008/santa-2026-dag-lns-programs/versions/5) · [Apache-2.0 许可全文](../three-parents/vendor/arsen_v15/Apache-2.0.txt)

算式重组器使用 Arsen Zakaryan 的第 15 版源码。辅助值排序、整数替换和因数分解沿用本仓库实现。父程序保留各自的来源，公开辅助行的作者也会写入复验记录。[Arsen 源码和许可记录](../../generative/arsen_v15/SOURCE.json) · [Arsen 原作者许可声明](../../generative/arsen_v15/LICENSE2026) · [辅助值排序](../release-crossover/paid.py) · [公开父本来源](../../public-assisted/NOTICE.md)
