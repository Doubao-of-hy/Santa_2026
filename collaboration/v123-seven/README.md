# 七道新公开程序上的等时搜索

选取 Asterios 第 123 版刚刚使本仓库缩短的七道题。固定父本是 Git 提交 `86b3f5c` 的公开辅助解，合计 134285 条指令。每题最多包含四个有逐题署名的来源，即当前仓库、上一版仓库、Asterios 第 121 版与第 123 版。完全相同的程序去重后，每题有两至三个输入。`design.json` 记录每次原始署名和指纹，`inputs.json.gz` 保存程序。

| 组 | 每次如何启动 |
| --- | --- |
| A | Wang 从当前解开始，历史父程序保留在交叉池。 |
| B | Atakan 先处理当前解，再将所得程序与同样的历史父程序交给 Wang。 |
| C | Wang 只使用当前解，使用不同种子独立重启。 |

每组每题有 24 秒墙钟预算。B 的 Atakan 最多占 12 秒。Wang 每次运行 240 轮，同题三组的第 `k` 次重启共用种子。到时终止尚未完成的启动；实际完成的轮数随机器速度而变。`observations.json.gz` 保存已完成与超时启动、种子、用时和返回的程序指纹。

七题均未得到更短的程序。A、B、C 分别完成 118、111、125 次 Wang 搜索，B 完成 7 次 Atakan 搜索。三组和逐题合并结果分别完成两套解释器的全库重放，均为 134285，指纹也与父本相同。未达到登记的扩展门槛，邻近题保持未测试。

从本目录运行下列命令可以不重复搜索，直接用两套解释器核验最终结果。参赛者需自行取得官方题面。

```text
python -B verify.py --repo <仓库路径> --data <puzzles.csv路径>
```

重新搜索需使用 Atakan 第 30 版可执行文件和 Wang 的历史父程序保留策略。Atakan 的固定源码构建程序在仓库的 `collaboration/atakan-frontier/build.py`。执行 `build_wang.py --repo <仓库路径> --out <编译目录>` 可从已固定的 Git 对象重建 Wang。运行 `run.py --repo <仓库路径> --data <题面> --atakan <frontier程序> --wang <incremental程序> --rebuilt --output <结果目录>` 即可按登记预算重新比较。[Atakan Aldemir 第 30 版](https://www.kaggle.com/code/atakanaldemir/santa-2026-joint-recipes-for-large-puzzles?scriptVersionId=371505096) · [wang Jakie 第五版](https://www.kaggle.com/code/wangjakie/santa-2026-arithmetic-recipe-pool-and-milp?scriptVersionId=371736767) · [E-Max AI 的历史父程序保留策略](https://www.kaggle.com/code/royalacecat/santa-2026-public-frontier-score-134-305?scriptVersionId=371833506)
