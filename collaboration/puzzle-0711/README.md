# 第 711 题的独立 21 步程序

从 11 和 14 出发，21 条指令生成了全部六个目标。此前独立程序用 22 步，这次追平了已有公开辅助上界 21。已证明的本题全局下界为 16，最优长度仍在 **16 至 21** 之间。[获胜程序](witness.csv) · [两套解释器的重放回执](verification.json)

搜索使用了官方初值、目标、数值上限 838842、48 个寄存器，以及冻结的两份独立父程序。第一份来自当时的独立提交，长度为 22。第二份来自独立搜索存档，长度为 23。[父程序、辅助值和原始文件 SHA-256](parents.json)

## 算式如何共享

程序先得到 3、9、81、1134 和 10206。从 3 和 9 得到 12，继而得到 132 和 17424。中间数 7218 同时参与两个分支。它与 17424 相加得到 24642，再乘 12 生成目标 295704。它还从 11349 中扣除，生成目标 4131。另两个分支共用 1261。它减 14 得到目标 1247，并参与构造目标 86536。其余目标 158760 和 10338 各由一次乘法或加法完成。[完整数值顺序](verification.json)

候选生成器从独立父程序保留随机选取的目标与部分中间结果。对每个待补目标，先枚举从已保留整数出发的短表达式，再用四种允许的运算反解最后一步。它也把目标与已保留整数合成的余项分解为两侧表达式，尝试整因子，并将新生成的操作数留给后续目标。随机择优和多组候选让短程序可以拥有不同的辅助整数。每轮最后逐个试删辅助数，重新正向检查所有目标是否仍然可达。[生成器源码](balanced.cpp)

## 复核与复现

从仓库根目录运行。重放需要 Python 3.12 以上及从比赛下载的完整官方题表。默认读取 `data/puzzles.csv`，也可以用 `--puzzles PATH` 指定位置。脚本先核对官方完整题表的 SHA-256。

```bash
python -B collaboration/puzzle-0711/verify.py
```

生成器使用 GNU C++17。原实验环境为 Python 3.13.7、GCC 16.2.0、MinGW-W64 x86_64-ucrt-posix-seh（Brecht Sanders r3）。以下两行重跑前 1106 轮，核对第 1105 轮产生的每条指令（轮号从 0 起）。Windows 下编译产物及 `--binary` 参数可写为 `balance-0711.exe`。不同标准库的随机分布实现可能影响搜索顺序。

```bash
g++ -O3 -static -std=c++17 -Wl,--no-insert-timestamp collaboration/puzzle-0711/balanced.cpp -o balance-0711.exe
python -B collaboration/puzzle-0711/verify.py --binary ./balance-0711.exe
```

编译命令中的 `--no-insert-timestamp` 适用于 Windows 的 MinGW 链接器。使用 Linux 的 GNU 链接器时可以省去该选项。原始搜索用种子 1991 跑完 15000 轮，共保留过 3811 个不同的候选数集，最终保留四套 21 步数集。第一份 21 步单题 CSV 的 SHA-256 为 `b278a3e3545cc0e4d32b90846101c1f2d33c41762819d2d50e32cfe1a348b9da`。结构化解释器及独立寄存器解释器分别核验了单题和临时合并的 1000 题文件。回执中的合并总分对应当时冻结的提交版本。[验证回执](verification.json)

## 同一构造方法的三个独立结果

| 题号 | 冻结独立上界 | 新独立上界 | 已知公开辅助上界 | 已证全局下界 | 搜索种子 | 首次得到归档程序的轮号 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| [0818](siblings/0818/witness.csv) | 23 | 21 | 21 | 14 | 1532 | 2142 |
| [0250](siblings/0250/witness.csv) | 23 | 20 | 20 | 14 | 1293 | 919 |
| [0387](siblings/0387/witness.csv) | 24 | 23 | 23 | 18 | 697 | 1591 |

表中每行均有完整父程序、逐条可执行的获胜程序，以及两种解释器对单题和当时整份临时提交的核验回执。每次搜索都从相应的官方种子和独立父程序开始。公开辅助上界只用于比较步数。[0818 回执](siblings/0818/verification.json) · [0250 回执](siblings/0250/verification.json) · [0387 回执](siblings/0387/verification.json)

0818 与 0711 使用同一份生成器。0250 和 0387 使用稀疏整数表，按需存储较大的数，将两份独立候选的辅助值合在一起，再试删仍然多余的值。脚本从本目录的 `balanced.cpp` 生成该版本，并核对源码摘要。0387 还先用原版生成器、种子 1553 跑完 12000 轮，从得到的数集中选取长度至多 25 的程序，每一份均从官方种子执行。复核器重新生成并比对该阶段完整入选名单的摘要，再重跑种子 697 的搜索。[0818 输入](siblings/0818/parents.json) · [0250 输入](siblings/0250/parents.json) · [0387 两阶段输入](siblings/0387/parents.json)

以下命令在仓库根目录执行。`balance-0711.exe` 来自上节的原版编译命令。重放归档程序时只需传入 `--id`。重做搜索则传入对应的生成器。

```bash
python -B collaboration/puzzle-0711/make_sparse.py balance-sparse.cpp
g++ -O3 -static -std=c++17 balance-sparse.cpp -o balance-sparse.exe
python -B collaboration/puzzle-0711/verify.py --id 0818 --binary ./balance-0711.exe
python -B collaboration/puzzle-0711/verify.py --id 0250 --binary ./balance-sparse.exe
python -B collaboration/puzzle-0711/verify.py --id 0387 --binary ./balance-sparse.exe --warmup-binary ./balance-0711.exe
```


同样的方法还在另外 80 道冻结短题上各试了 350 轮，其中 10 道题严格缩短，合计减少 12 步。[80 题首轮快照及全部改进行](wide/README.md)
