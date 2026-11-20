# 分开求解两组目标再合并

每题从官方初值出发。先把目标平分，让两个子程序分别优化，再合并算式并重排到 48 个寄存器，最后优化一次整题。随机分组和从 160 种分组里选择共享中间值最少的分组，各给两个子题和合并后的整题 100 轮。对照组将同样的 300 轮分作三次整题优化。每题使用同一组三个固定种子，底层搜索来自 Wang Jakie 的增量算式优化器。[算法来源](../../generative/wang/NOTICE.md) · [冻结方案](design.json)

独立解与公开辅助解各 12 道开发、24 道留出，开发组均无缩短。独立留出组中，整题对照省 5 条，两种分组各省 4 条，两种分组均未独自赢得一道题。公开辅助组均无缩短。四个完整候选各用两个解释器重放全部 1,000 题，独立结果由 140,727 降至 140,722。[开发结果](development.json) · [留出结果](holdout.json) · [四份采用的程序](holdout-independent.csv)

复核时先使用 collaboration/reactive-tabu/build.py 构建 original，再运行 compare.py，指定 --repo、--puzzles、--exe、--design、--group 和 --out。把 development.json.gz 和 holdout.json.gz 复制到输出目录并加 --replay-only，可以仅用官方题目、冻结 Git 版本和两套解释器检查已保存的结果。
