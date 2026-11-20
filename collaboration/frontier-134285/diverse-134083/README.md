# 重新生成 E-Max AI 的七道较短程序

E-Max AI 的第 50 版输入包含三个公开程序集。对全部题逐题取短得到 134,091 条。在原作者选中的 7 道题上从固定输入重新搜索后，共省 8 条，完整回放为 134,083 条。三个来源与其他贡献者的署名见原发布和合并清单。七题是原作者在完成比较后选中的成功案例。[计算结果](replayed.json) · [程序](wins.csv) · [输入与程序包版本](sources.json)

Bikram Basnet、Roman Rozen 和 Alex Chilton 新版的另外 6 道题逐条相同，各省 1 条。Bikram 明确将第 269、690、729 题的改进归于同时重建三个目标，其余题保留公开程序集的作者说明。这 6 道与上述 7 道没有重合。相对主线的 134,079 条，合并后为 134,065 条。Pratham Jain 第 25 版逐题核对后没有更短的程序。[逐题参考来源和回放](../../../public-assisted/New-frontier-134065.json) · [合并使用的 13 题](merged-wins.csv)

用 sources.json 中固定版本的输入 ZIP 和源文件目录运行 replay.py，传入 --inputs、--source、--puzzles、--out 与 --compiler。脚本会校验输入文件、重新编译两种搜索程序，并将打印的总数与作者声明的结果核对。
