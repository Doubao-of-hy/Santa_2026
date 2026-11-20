# 近期算式禁忌期的对照

每种方法在每题、每条路线都提出 150 个候选，分成 24 道开发题和 48 道留出题。三选一和带禁忌期两个变体都没有缩短真实程序。原版 Wang 增量搜索在独立留出组缩短 0228 和 0746，各 1 条，在公开辅助开发组缩短 0164 共 1 条。剩余题目不再扩大测试。四份分组候选均重放全部 1,000 题。[开发结果](development.json) · [留出结果](holdout.json)

禁忌规则在独立开发与留出分别阻止 1,539、3,134 个候选，在公开辅助分别阻止 1,630、3,276 个候选。它记录刚弃用的数值与算式，保持一段短禁忌期；遇到更短整题程序可以立即接纳。搜索时间按逐次运行另存，预算用候选次数配平。[开发逐行结果](development.json.gz) · [留出逐行结果](holdout.json.gz)

本地变体复用 Wang Jakie 的增量算式图搜索（Apache-2.0），三选一及禁忌轨迹代码放在本目录。编译器需支持 C++17。以下命令在含冻结提交 aca4989 的仓库根目录运行，提供本地官方题库。

```text
python -B collaboration/reactive-tabu/build.py --repo . --out work/trajectory/bin --cxx g++
python -B collaboration/reactive-tabu/compare.py --repo . --puzzles data/puzzles.csv --bin work/trajectory/bin --out work/trajectory/results --group development
python -B collaboration/reactive-tabu/compare.py --repo . --puzzles data/puzzles.csv --bin work/trajectory/bin --out work/trajectory/results --group holdout
```

[父程序、分组和算法的预登记](design.md) · [原算法说明与许可证](../../generative/wang/NOTICE.md)
