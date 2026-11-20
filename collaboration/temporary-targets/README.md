# 临时增加一个目标再移除

独立候选在 12 道开发题中省 5 条，在另外 24 道题省 14 条。公开辅助候选在开发题省 1 条，在后 24 道没有新增收益。每题四种程序都经官方初值、寄存器和输出规则重放。[开发组](development.json) · [留出组](holdout.json)

从同一道题的旧程序中选一个当前方案未使用的中间值，把它的算法接到当前程序上，暂时将这个数也设为必须生成的目标。完成第一轮搜索后移除这个要求，只保留生成官方目标所需的算式，再做第二轮搜索。比较原程序直接搜索、接入相同算式但从未强制生成、强制生成优先选择的值、强制生成随机选择的值。各组两轮各 160 次，以最终物理程序长度评分。[选题与预算](design.json) · [逐题指定的数及来源](selection.json)

在独立组，受保护的方案在五道题上同时击败了两种对照。公开辅助组没有这样的题。其余符合预登记条件的独立题共 26 道，全部已完成。8 道再省 9 条。三组总计 19 道独立题省 28 条，独立候选降到 140,694。与原有公开辅助程序逐题取短后，第 492、809、919 题共省 4 条，公开辅助候选为 134,178。[扩展运行与各组结果](extension/running.json) · [扩展的 8 份程序](extension/extension-wins.csv) [搜索与全量回放](compare.py)

在仓库根目录使用 collaboration/reactive-tabu/build.py 编译其 original 引擎。把 selection.json 及相应的 .json.gz 实测文件放进输出目录后，可以重放每个策略的整个 1,000 题候选。

```text
python -B collaboration/temporary-targets/compare.py --puzzles data/puzzles.csv --out work/temporary-targets --phase development --replay-only
python -B collaboration/temporary-targets/compare.py --puzzles data/puzzles.csv --out work/temporary-targets --phase holdout --replay-only
```
