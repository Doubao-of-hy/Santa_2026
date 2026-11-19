# Santa_2026

Kaggle [Santa 2026 – The Elf Calculator](https://www.kaggle.com/competitions/santa-2026). 每题从给定的整数出发，写一段四则运算程序，让所有目标值在执行期间至少出现一次。评估指标是 1,000 道计分题的总指令数，越少越好。

## 本轮进度

| 全量实验 | 总指令数 |
|---|---:|
| 赛事样例 | 1,490,379 |
| 二进制构造 | 1,242,359 |
| 多进制构造 | 303,217 |
| 提取公因子、目标差及整除关系 | 305,083 |
| 自写构造逐题择优 | 300,044 |
| 六份公开程序逐题择优 | 138,998 |
| 跨程序重组表达式 | 138,952 |
| 再搜索可替换的短算式 | 138,945 |

表中成绩均在本地回放，尚未取得 Kaggle 提交回执。自写构造在独立的 200 道练习题上用了 60,862 条指令。公开程序组合的成绩包含第三方贡献。公开数据集和各版本见 [SOURCES.md](SOURCES.md)。

## 复现

Python 3.11+。原始题目可从赛事 Data 页面获取。下列命令在仓库根目录运行。前三个命令只用 Python 标准库。

```bash
python run.py verify data/puzzles.csv data/sample_submission.csv
python run.py construct data/puzzles.csv out/independent.csv --report out/independent.json
python run.py construct data/practice_puzzles.csv out/practice.csv --report out/practice.json
g++ -O3 -std=c++17 graph_search.cpp -o graph_search
```

公开解逐题择优、搜索及复查的命令见 [SOURCES.md](SOURCES.md)。每次写入 CSV 都先写临时文件，再从磁盘读回并逐条回放，验证成功后才替换输出。求解器不会向 Kaggle 发起提交。

## 方法

- 每个候选程序单独检查寄存器、输入是否已初始化、精确整除、数值上限及全部目标。已经产生过的目标可以从寄存器中覆盖。
- 从零构造时，同时比较二进制、多个带符号或无符号的进制，以及基于目标差和公因子的构造。编译器按需复用中间数，在寄存器紧张时回收并重新计算。
- 重组阶段使用各程序的实际中间值构建有向图，寻找同一个值的不同计算方法。搜索同时考虑一个中间数被多少个目标复用。局部改写允许用新的中间值替换整段算式。每题保留输入程序作为退路。
