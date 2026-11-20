# 第 134 题的三父本重组

同一道题有三份独立生成的寄存器程序，长度为 29、30 和 33 条。将三份程序都交给算式重组器后，第 134 题得到 28 条指令的有效程序。相对冻结的 1,000 题独立提交，总数从 141475 降至 141474。[三份输入与输出](programs.csv) · [哈希与来源清单](manifest.json)

| 交给求解器的程序 | 最短输出 |
|---|---:|
| 当前独立解，29 条 | 29 |
| 当前独立解与 Atlas，29、30 条 | 29 |
| 当前独立解与 Rudolph，29、33 条 | 29 |
| 三者同时输入 | **28** |

求解器先收集父本中的数值，再生成它们之间可用的加、减、乘和精确整除算式。它同时为所有目标挑选互相兼容的算式，并排除循环依赖。最后在题面给定的寄存器中执行整段程序。四组优化都在各自的有限候选集合内返回 `OPTIMAL`。全题在任意合法整数与算式下的最短长度仍未知。

28 条程序使用 6 个出现在供体、未出现在当前独立解中的数值。它又形成了三份输入中都没有的 6 条算式。例如，Rudolph 提供了 968，新的 `64 × 968 = 61952` 参与 5 个目标的计算。Atlas 提供了 14654，新的 `879222 − 14654 = 864568` 接着可精确除以 8，生成目标 108071。[六条算式与各自服务的目标](manifest.json)

## 回放与重新搜索

先取得官方比赛 ZIP 或其中的 `puzzles.csv`。在仓库根目录运行第一条命令，即可用 Python 标准库检查四份程序的算术、寄存器、目标覆盖和长度。第二条命令还会重放当前检出的整份提交。[竞赛数据](https://www.kaggle.com/competitions/santa-2026/data)

```console
python -B collaboration/three-parents/reproduce.py path/to/santa-2026.zip
python -B collaboration/three-parents/reproduce.py path/to/puzzles.csv --submission submission.csv
```

要重新进行四组搜索，在当前 Python 环境安装实测的 OR-Tools 版本，再加上 `--search`。程序使用仓库内固定版本的搜索源码，逐组输出求解状态、候选数量、步数和指令是否逐条相同。实测环境为 Python 3.13.7、OR-Tools 9.15.6755。每组使用相同种子 871199、确定性预算 0.48，允许三份输入之间最多 33 条的长度差，额外辅助数为 0。

```console
python -m pip install ortools==9.15.6755
python -B collaboration/three-parents/reproduce.py path/to/santa-2026.zip --search
```

## 来源与样本范围

- 当前独立解来自本项目单父本 GoodPJW 分组搜索。分组优化器由 goodpjw2008 发布，源代码适用 Apache-2.0。[GoodPJW 固定源码](https://www.kaggle.com/datasets/goodpjw2008/santa-2026-dag-lns-programs/versions/3)
- 30 条父本来自本项目独立线的 Atlas 后续搜索，使用 Pablo Diego Pereira 的 Atlas v5 构造器。33 条父本来自 Alex Chilton 的 Rudolph v8 构造器，本次从官方初值生成。两份构造器的原始来源均标注 Apache-2.0。[原始版本和本地变更](../../generative/NOTICE.md) · [Atlas](https://www.kaggle.com/code/pablodiegoo/santa-2026-deterministic-atlas-solver) · [Rudolph](https://www.kaggle.com/code/alexchilton/rudolph-the-red-nosed-register-allocator)
- 三个重组器源码文件原样来自 Arsen Zakaryan 的 v15 发布包。发布清单将这部分代码标为 Apache-2.0。程序启动新搜索前会核对每份文件的 SHA-256。[固定发布包](https://www.kaggle.com/datasets/arsen123/santa-2026-original-dictionary-solver-source/versions/15) · [原作者声明](vendor/arsen_v15/LICENSE2026) · [许可证全文](vendor/arsen_v15/Apache-2.0.txt)

先在分四档选取的 24 道高分差题中比较，8 道开发题、16 道留出题均持平。后续 12 道较短题中，只有第 134 题省了 1 条；其余符合当时条件的 36 道短题全部持平。再用更新后的独立线 141474 和辅助线 135087 选取尚未测试、独立长度 35–85 条且分差 2–8 条的题，共剩 13 道。四个输入组合在这 13 道都没有带来新的缩短。辅助线在这些实验中只提供选题用的长度。[样本与结果](manifest.json)

在 28 条的重组程序上继续运行成组搜索，独立候选又缩至 27 条。这是下一阶段的实物输出。上表的四组对照都从当时固定的父本和可选算式出发。[27 条程序](after-group.csv)
