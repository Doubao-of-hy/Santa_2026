# 单父本串行压缩的两个可回放案例

第 710 题和第 789 题的独立父本合计 249 条指令。四法各自从相同父本搜索，逐题取最短合计 247 条。把一种方法接受的程序交给下一种方法，两题合计 243 条。每个中间程序都包含完整的物理寄存器指令。[程序表](programs.csv) · [父本、输出和官方输入哈希](manifest.json)

| 题号 | 父本 | 分组搜索 group | 常量替换 exchange | 因式重构 factor | 辅助数筛选 paid | 串行接受的步骤 |
|---|---:|---:|---:|---:|---:|---|
| scored_0710 | 121 | 120 | 121 | 121 | 121 | group 120 → exchange 119 → paid 118 |
| scored_0789 | 128 | 127 | 128 | 128 | 128 | group 127 → exchange 126 → group 125 |

## 用自己的官方题面重放

在仓库根目录用 Python 3.9 或更高版本执行下面的命令。参数可以是 Kaggle 下载的竞赛 ZIP，或从中解出的计分文件 `puzzles.csv`。命令输出两题的单法长度、每次串行缩短、两题合计。加上 `--submission submission.csv` 会额外回放当前检出的整份提交，并计算采用这两条候选后能达到的总数。[官方竞赛数据](https://www.kaggle.com/competitions/santa-2026/data)

```console
python -I -B collaboration/polish/replay.py path/to/santa-2026.zip
python -I -B collaboration/polish/replay.py path/to/puzzles.csv --submission submission.csv
```

脚本只依赖 Python 标准库。它校验输入与程序哈希，按顺序执行每条寄存器指令，检查未初始化读取、寄存器范围、精确整除、值域和所有目标。报告中的长度和变化均从实物程序计算。[验证程序](replay.py)

## 重新搜索分组步骤

从 GoodPJW 的固定版数据集中取出 `elfopt.cpp`。发布者标注源代码适用 Apache 2.0。源码文件的 SHA-256 为 `16f12d4963acfe795f89f9632e941fb1aea9d8d8de55ac958a45b17a02881db2`。以下命令以 MinGW g++ 为例。已有同版可执行文件时可以直接传给 `--group-engine`。[GoodPJW 固定源码](https://www.kaggle.com/datasets/goodpjw2008/santa-2026-dag-lns-programs/versions/3)

```console
g++ -std=c++17 -O3 -static -march=x86-64 path/to/elfopt.cpp -o elfopt.exe
python -I -B collaboration/polish/replay.py path/to/santa-2026.zip --group-engine ./elfopt.exe
```

此选项对三次接受的 group 转换分别执行搜索，验证新生成的程序是否有效，并报告它是否逐条吻合。分组宽度为 8，单次用时 1.15 秒，辅助数、成对搜索、扰动次数和余量参数分别为 1、1、1000、2。每题的种子收录于清单。时间预算会使不同机器探索的候选数量发生变化。

## 搜索来源与复现范围

两个起点均取自合计 141494 条的独立父本，只使用了对应题面和本题的一份程序。第 710 题的父本来自本地 `own-composition-gpu.csv`，第 789 题的父本来自 `own-composition-factor.csv`。两份来源文件、两个起点及当时整套独立父本的哈希保存在清单中。读者重放所需的起始程序已包含在表内。[来源清单](manifest.json)

原实验按 group、exchange、factor、paid 的顺序运行，只接受严格缩短，一个完整循环没有缩短即停止。exchange 和 factor 使用本项目的整数常量替换和因式重构实现。paid 使用本地可移除依赖数量挑选 24 个候选，再调用 Arsen Zakaryan 的 `recombine2026.solve`，确定性预算为 0.32。Arsen v15 原创代码的发布清单标注 Apache-2.0，`recombine2026.py` 的 SHA-256 为 `43c0fc702350b367bdb15048167c6a63f4b26db900d5790f9f0790f0e10ba204`。[Arsen v15 固定源码](https://www.kaggle.com/datasets/arsen123/santa-2026-original-dictionary-solver-source/versions/15)

本目录支持四种单法和全部接受步骤的物理回放，也支持重新运行分组搜索。exchange、factor、paid 的搜索用本地原环境再次运行时，两题都重现了原先记录的事件序列和最终程序哈希。此入口只回放这三种方法留下的结果。

这两题选自已有改善的实验组。另以固定哈希从此前程序未变的题中分层抽样，独立线与公开辅助线各取 48 题，两批中有 44 个相同题号。独立线仅第 730 题由 group 从 111 降至 110，公开辅助线全部持平。两批留出题中串行均未超过逐题最佳单法。
