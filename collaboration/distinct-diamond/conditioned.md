# 按最先生成的辅助数排除共边三角形

从已有的首个辅助数分支树中选出 680 道上下界仍有间距的题。以提交 b6f68c1 的逐题下界为基准，404 道可再提高 1 条。只计这一层证明，总下界从 37,512 到 37,916。复核共覆盖入选证明的 4,098 个叶子，其中 4,035 个使用了共边三角形的边数上界。[独立复核记录](conditioned-independent.json) · [逐题证书](conditioned-claims.json.gz) · [固定选题](conditioned-design.json)

每个内节点枚举从既有整数出发可得到的下一辅助数，再将所有候选分成互不重叠的组。在同一组里，一次性允许组内所有候选参与后续计算，这会放宽原问题。只有这个放宽后的问题也无法在给定长度内完成，该组才被排除。复核脚本从官方初值重新枚举每个内节点的候选，检查各组无遗漏，并验证每一个叶子都排除了同一个指令预算。[树遍历和算术容量复核](verify_conditioned.py)

对于一个叶子，若两个三角形能共用一条边，则其五条边需分别产生不同的待生成目标。两种整数算法分别检查这种构形能否出现。几个叶子可以共享一次检查，此时把可作边标签的目标取并集，把禁止充当辅助数的值取交集。这个放宽后的范围覆盖各叶子的可能构形。仅在两个算法均已穷尽且判定不存在时，才在对应叶子使用更小的边数上界。各叶子的剩余辅助数预算和整数容量仍分别计算。[数学依据和两个算术算法](README.md) · [按叶搜索实现](conditioned_diamond.py)

在仓库根目录运行以下命令可以用官方题目和仓库中固定版本的原始分支树复核证书。需要有该仓库的 Git 历史。

```powershell
python -B collaboration/distinct-diamond/verify_conditioned.py --repo . --puzzles data/puzzles.csv --claims collaboration/distinct-diamond/conditioned-claims.json.gz --jobs 4
```
