# 两个共边三角形对辅助数的限制

把每个尚未覆盖的目标分配给第一次生成它的那条指令。若两个不同的额外辅助数共同生成了至少一个分配目标，在它们之间画一条边，并用其中一个目标标记。每条边选一个代表，因此整张图的标记两两不同。一个辅助数配合已知值产生的目标、同一辅助数使用两次产生的目标，以及同一对辅助数多生成的目标，沿用独立容量证明另行计数。[全部运算及容量定义](../subset-capacity/README.md)

四个不同辅助数之间，若两组三角形共用一条边，就有五条边。两套整数验证器分别检查五个不同目标能否给这些边作标记。当所有可能均穷尽且没有解，含有这样的五条边的图就被排除。

设额外辅助数个数为 h。当 h 至少为 4 时，这种图最多有 ⌊h²/4⌋ 条边。若没有三角形，由 Mantel 定理直接得到。若存在三角形，每个外部顶点最多与其中一个顶点相邻。删除这三个顶点，删去的边至多为 h 条。在 h 等于 4、5、6 时，余下 1、2、3 个顶点，最多分别有 0、1、3 条边。对更大的 h 使用归纳，并有 h + ⌊(h−3)²/4⌋ ≤ ⌊h²/4⌋。这个上限适用于分配了不同代表目标的辅助数对。

第一套程序枚举带标记三角形的整数闭合条件，再检验两个顶点能否共用一个新的邻点。第二套按三角形中最小的辅助数排列操作数，独立求解整数多项式，允许第四点处于任意数值位置。两者都在没有穷尽的恒等分支返回 UNKNOWN。[第一套程序](diamonds.py) · [第二套程序](ordered.py)

首批选定 32 道题。两套算法对 39 个能改变容量的前缀域给出相同判定，28 道题的下界各提高一条。小整数对照中，第一套与 384 次直接穷举一致。第二套还检验了 130 个全标签小域、第四点的各个数值位置和未决情形。[首批对照](pilot-results.json) · [独立复验](panel-results.json) · [小域检验](tiny.json)

扩展以 36,882 条的逐题下界为起点。20 道题已证最短，其余 980 道已用第一套算法逐题筛完，622 道产生严格候选。独立整数算法对这 622 道题全部重建各自最强的前缀并确认容量不足，共核验 692,296,416 个整数多项式。[逐题双重证书](claims.json.gz) · [复验统计](final-summary.json)。全部批次的记录包含判断、前缀和预算。[固定范围](extension-design.json) · [全量筛查记录](full-scan.json.gz)

从本仓库根目录运行下面的命令可复验开发与留出组。官方数据文件应放于 data/puzzles.csv。

```powershell
python -B collaboration/distinct-diamond/compare.py --k4 collaboration/distinct-helper-edges --subset collaboration/subset-capacity --repo proofs/local --puzzles data/puzzles.csv --design collaboration/distinct-diamond/design.json --out pilot-replay.json
python -B collaboration/distinct-diamond/tiny_tests.py
python -B collaboration/distinct-diamond/full_audit.py --repo . --puzzles data/puzzles.csv --claims collaboration/distinct-diamond/claims.json.gz --jobs 4
```
