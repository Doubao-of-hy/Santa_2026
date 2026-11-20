# 四条不同温度的局部搜索轨迹

在 134,385 条公开辅助父本上，32 道开发题与 32 道留出题的三种方法均节省 0 条。留出组交换过 203 对结构不同的算式图，其中 111 次两条程序的长度不同。交换确实把搜索带到另一条轨迹，但这次没有得到更短的可运行程序，因此停止扩大这组试验。[冻结分层、题号及逐题署名](design.json) · [分组结果](results.json) · [192 次搜索的逐题记录](rows.json.gz)

| 方法 | 开发组节省 | 留出组节省 | 开发组累计求解秒数 | 留出组累计求解秒数 |
| --- | ---: | ---: | ---: | ---: |
| 原版 Wang 增量搜索 | 0 | 0 | 41.30 | 39.98 |
| 四条独立轨迹 | 0 | 0 | 36.03 | 33.93 |
| 四条轨迹定期交换状态 | 0 | 0 | 35.96 | 34.79 |

每种方法每题各有 240 次迭代。两种四轨迹方法各让四条轨迹走 60 步，沿用 Wang 的算式替换、重建、删点与寄存器编译。温度依次为 0.25、0.65、1.4、2.8，候选程序最多比父本长 2、4、6、9 条。停滞时增加扰动范围，连续 15 次没有刷新该轨迹的最好长度则回退。交换组每三步交替尝试交换相邻温度上的完整状态，按 Metropolis 概率及各轨迹的长度上限接受。独立轨迹组保留其余机制和预算。原版还沿用其自带的交叉操作，表中列出实测时间。两套寄存器解释器检查所有父程序及输出。另有一份由初值 2、3 算出 10 的正对照，三个方法均把 3 条程序缩至可运行的 2 条。

在仓库根目录用 GNU C++17 编译以下两个程序。Windows 可将输出名改为 `original.exe` 和 `replicas.exe`。Python 需要 3.12 或更新版本，并需能读取 Git 历史中的冻结提交。

```sh
g++ -std=c++17 -O3 generative/wang/incremental.cpp -o original
g++ -std=c++17 -O3 -I generative/wang collaboration/parallel-tempering/replicas.cpp -o replicas
python -B collaboration/parallel-tempering/experiment.py --puzzles data/puzzles.csv --original ./original --replicas ./replicas --part development --output development-replay
python -B collaboration/parallel-tempering/experiment.py --puzzles data/puzzles.csv --original ./original --replicas ./replicas --part holdout --output holdout-replay
```

可以用 `--id scored_0957` 对开发组中的一道题复验。固定版本、整表 SHA-256 及逐行程序指纹用于还原父程序，原作者随逐题记录保留。新控制逻辑调用仓库已归档的 wang Jakie 源码，原始发布页标注 Apache-2.0。[Wang 源码和许可](../../generative/wang/NOTICE.md) · [公开程序来源](../../public-assisted/NOTICE.md)
