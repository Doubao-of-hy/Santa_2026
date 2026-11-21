# 协作实验索引

准备接手一道题时，先查[当前分工](STATUS.md)和[逐题上下界](puzzle-bounds.csv)。[方法比较](methods.md)记录哪些实验带来了改进，具体实验目录保存复跑说明和结果。

| 研究方向 | 实验记录 |
| --- | --- |
| 围绕已有程序重建、交换片段 | [暂时拿掉目标再补回](withheld-targets/) · [Wang 退火的两题复现实验](anneal-current-parent/) · [禁忌搜索](reactive-tabu/) · [并行回火](parallel-tempering/) · [多父代交换](three-parents/) |
| 寻找可共享的算式 | [共用商](shared-quotients/) · [联合辗转相除](joint-euclid/) · [共同截距](shared-intercept/) · [因数分解](factor/) |
| 把多个来源的程序组合起来 | [公开版本交叉](release-crossover/) · [公开程序重组](fresh-public-recombination/) · [跨题模板](cross-puzzle-templates/) |
| 缩短指令与寄存器安排 | [局部改写](polish/) · [窗口搜索](window-search/) · [寄存器搜索](register-search/) |
| 抬高下界、证明最短 | [证明进展](proof-status.md) · [精确边界](exact-boundary/) · [第 711 题](puzzle-0711/) · [第 882 题](puzzle-0882-diversity/) |
| 查证分数和证明 | [榜单快照](leaderboard.json) · [证明复核记录](evidence/) · [全部项目进展](../PROGRESS.md) |
