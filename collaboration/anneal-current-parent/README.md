# 在主库自己的父本上跑 Wang 退火 · 两题共省 3 条

仓库里的退火实验此前都从更旧的表起跑（134,430、134,500、141,435）。这里把
`public-assisted/submission.csv`（**134,063** 条，sha256 `49d1ac9e…`）当作父本，
用仓库内原封不动的 Wang Jakie 引擎（`generative/wang/anneal.cpp`、`anneal_diverse.cpp`、
`incremental.cpp`，Apache-2.0，署名见 `generative/wang/NOTICE.md`）逐题扰动，
再把每轮胜出的程序逐题取短。

## 结果

| 题号 | 父本 | 新 | 省 | 配置 | 程序 sha256 |
| --- | ---: | ---: | ---: | --- | --- |
| scored_0310 | 111 | 109 | 2 | anneal，35 轮（200 轮同结果），种子 737049+题索引 | `9996632a…f1b` |
| scored_0512 | 124 | 123 | 1 | 同上 | `51e01e6a…8c84` |

两行套回公开辅助父本：134,063 → **134,060**（−3）。两行程序在 `rows.csv`，
父本与长度、哈希在 `wins.csv`。两题都在仓库自己的程序上改出来，不涉及任何外部来源。

## 跑过的配置（各 1,000 题，2 核）

| 轮数 | 模式 | 全表结果 |
| ---: | --- | ---: |
| 35 | anneal | 134,060 |
| 200 | anneal | 134,060（无新行） |

上表是在 **134,063** 这份仓库自带父本上跑出来的：35 轮与 200 轮都只缩短了 0310、0512 两题，
200 轮没有新行。此前在一份混入外部候选行的父本上，同一套网格还缩短过另外 4 道
（0016、0524、0747、0803），但那些行是外部程序的派生结果，随本仓库的分发许可尚未解决，
因此本目录不收录它们的程序，也不把它们的节省计入这里的数字。

## 复现

```bash
g++ -O3 -std=c++20 -static generative/wang/anneal.cpp -o /tmp/anneal
g++ -O3 -std=c++20 -static generative/wang/anneal_diverse.cpp -o /tmp/anneal_diverse
g++ -O3 -std=c++20 -static generative/wang/incremental.cpp -o /tmp/incremental

python -B collaboration/anneal-current-parent/reproduce.py \
    --puzzles data/puzzles.csv --binary-dir /tmp --rounds 35 --jobs 2
# 200 轮同样只得到这两行：python -B ... --rounds 200
```

脚本打印该配置下所有变短的题、逐题长度与程序哈希，并与 `wins.csv` 比对；哈希不一致时返回非零。
父本是仓库内文件，读取时用官方 `puzzles.csv` 逐条回放，任何非法程序都会在比较阶段抛出异常。

耗时参考：1,000 题 × 35 轮约 2.5 分钟，× 200 轮约 10 分钟（2 核）。

## 关于上一版 PR 里的外部导入

上一版从这个目录之外导入了 `TomYanabe/santa2026` 的 `submissions/best.csv`（当时 1,000 题里
有 122 道更短，整表 134,063 → 133,890）。该仓库没有 LICENSE 也没有 NOTICE，并且在
2026-11-21 已经返回 404（仓库被删除或转为私有），既拿不到授权、也无法让第三方复核。
所以这条路线已撤下：不保留它的完整表，也不保留由它派生的行，PR 一并关闭。
