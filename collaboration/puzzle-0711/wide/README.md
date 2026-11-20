# 80 道邻近短题的独立搜索

80 道题各自从一份冻结独立父程序出发，分别搜索 350 轮，合计 28000 轮。10 道题得到比本轮启动时独立程序更短的可执行行，与两组启动时相同的独立提交快照相比，共少 12 步。全部 80 道题都完成了首轮。[逐题结果及各次比较的提交指纹](results.json)

| 题号与程序 | 冻结父本 | 该配置启动时的独立步数 | 本轮得到的步数 | 首次找到的轮号 |
| --- | ---: | ---: | ---: | ---: |
| [0019](wins/scored_0019.csv) | 25 | 25 | 23 | 149 |
| [0091](wins/scored_0091.csv) | 26 | 26 | 25 | 164 |
| [0130](wins/scored_0130.csv) | 25 | 25 | 24 | 145 |
| [0393](wins/scored_0393.csv) | 24 | 24 | 23 | 65 |
| [0401](wins/scored_0401.csv) | 28 | 28 | 27 | 56 |
| [0455](wins/scored_0455.csv) | 29 | 29 | 27 | 218 |
| [0487](wins/scored_0487.csv) | 29 | 29 | 28 | 265 |
| [0492](wins/scored_0492.csv) | 36 | 36 | 35 | 321 |
| [0863](wins/scored_0863.csv) | 33 | 33 | 32 | 266 |
| [0958](wins/scored_0958.csv) | 28 | 28 | 27 | 295 |

冻结集含 80 道已有独立程序的短题。每题至少有 5 个目标，初值和原程序的计算结果可同时放入 48 个寄存器。80 个记录保留原程序、题号和来源。官方题表由复核者从比赛获取。[冻结父程序](frozen-parents.json)

值域上限在 10 亿以内的 71 道题使用与 0250 相同的稀疏整数搜索。其余 9 道使用 64 位整数并把可选试除提案的质数上限设为 997，余下的因子仍可作为一个操作数。两者均逐步遵守各题的官方整数上限。每道题有独立固定种子，先从被保留的数反解目标和余项，再重建可执行算式并删除冗余中间数。该计算给出可行上界。[共用构造器和算法](../README.md)

比较采用各配置启动时读入的独立提交。两组分别记录该提交的 SHA-256，每题另记归档时主线快照的步数。在此期间已被其他工作追平的结果仍然按启动快照列出。父本改善但在启动时已被追平的行只在完整逐题清单中记录。同一题连续发现多个更短程序时，单行文件夹只保留最短程序。[全部 80 道题的三次比较](results.json)

## 检查与复现

从仓库根目录执行第一条命令，分别用两套解释器核对 80 份原始程序及替换后的整组程序。请先从比赛下载完整官方题表至 `data/puzzles.csv`，或添加 `--puzzles PATH` 指定位置。复核器核对文件指纹后，在临时目录提取本次的 80 条记录。

```bash
python -B collaboration/puzzle-0711/wide/verify.py
```

以下命令重建两种配置，使用 GNU C++17 编译，再重跑所有得到严格改进的行。原构建使用 GCC 16.2.0 MinGW-W64。其他标准库可能产生不同的随机搜索顺序。`--repeat` 也可接一道或多道四位题号；`--repeat all` 会重做完整的 28000 轮。

```bash
python -B collaboration/puzzle-0711/make_sparse.py balance-sparse.cpp
python -B collaboration/puzzle-0711/wide/make_large.py balance-sparse.cpp balance-large.cpp
g++ -O3 -static -std=c++17 balance-sparse.cpp -o balance-sparse.exe
g++ -O3 -static -std=c++17 balance-large.cpp -o balance-large.exe
python -B collaboration/puzzle-0711/wide/verify.py --repeat wins --sparse-binary ./balance-sparse.exe --large-binary ./balance-large.exe
```
