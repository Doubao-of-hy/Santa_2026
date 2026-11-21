# 在主库自己的父本上跑退火 · 三题共省 4 条

父本一律是本仓库的 `public-assisted/submission.csv`（**134,063** 条，sha256 `49d1ac9e…`），
引擎是仓库内未改动的 Wang Jakie 实现（`generative/wang/anneal.cpp`、`anneal_diverse.cpp`、
`incremental.cpp`，Apache-2.0，署名见 `generative/wang/NOTICE.md`）。不读、不分发任何外部程序。

## 结果

| 题号 | 父本 | 新 | 省 | 配置 | 程序 sha256 |
| --- | ---: | ---: | ---: | --- | --- |
| scored_0310 | 111 | 109 | 2 | anneal，400 轮，紧上限子集 | `9996632a…571c` |
| scored_0477 | 130 | 129 | 1 | anneal，400 轮，紧上限子集 | `c461935b…b7a6` |
| scored_0512 | 124 | 123 | 1 | anneal，35 轮，全表 | `51e01e6a…8c84` |

套回父本：134,063 → **134,059**（−4）。程序在 `rows.csv`，长度/配置/哈希在 `wins.csv`。

## 差距在哪：先分型，再搜

要判断 4.3% 的差距（榜首 128,330，本表 134,059）落在哪，先按题面分型看"每产出一个新目标要几条指令"：

| 分型 | 题数 | 每目标成本（中位） |
| --- | ---: | ---: |
| `value_limit / max(target)` < 1.5（上限几乎贴着最大目标） | 271 | **6.48** |
| 1.5 – 3 | 352 | 4.10 |
| > 3 | 227 | 3.97 |

紧上限这 271 道就是贵的地方：上限没有余量，每一步都必须压在 1..limit 内，长链只能靠减法和整除拼。
850 道 28–32 目标的题合计 129,276 条，占全表 96.4%，所以差距基本只在这类题里。

三条结构性捷径都先被排除了：

- **跨目标共享不够？** 反向切片统计（按寄存器在每一步的实际归属、先回放求值）显示，中位 **58.4%** 的指令
  被 ≥2 个目标依赖，最高 79.4%——共享已经做得不少，问题不在"没共享"。
- **目标能一步凑出来？** 抽样 200 题，5,380 个需新生产的目标里只有 12 个（0.2%）能由已有值一步得到。
- **目标间有可共享的子乘积？** 两两 gcd>1 占 50.3%，但都来自种子的小素因子（2、3、7），不能省指令；
  另测"锚定最大目标再相减"，差值中位 18 位，也不成立。

所以剩下的是**搜索质量**：同样的结构，骨架挑得够不够省、每条尾巴够不够短。这也是这轮实验的位置。

## 跑过的配置

| 范围 | 轮数 | 模式 | 结果 |
| --- | ---: | --- | ---: |
| 全表 1,000 | 35 | anneal | 134,060 |
| 全表 1,000 | 200 | anneal | 134,060（无新行） |
| 紧上限 271 | 400 | anneal | **49,164**（该子集 −3） |
| 紧上限 271 | 400（种子偏移 1） | anneal | 49,167（无新行） |
| 紧上限 271 | 250 | anneal_diverse | 49,165（−2，与上一轮同两题） |

紧上限子集里只挤出 0310、0477 两题；换种子完全无收益，说明这一批在退火这个邻域内已经饱和。

## 复现

```bash
g++ -O3 -std=c++20 -static generative/wang/anneal.cpp -o /tmp/anneal
g++ -O3 -std=c++20 -static generative/wang/anneal_diverse.cpp -o /tmp/anneal_diverse
g++ -O3 -std=c++20 -static generative/wang/incremental.cpp -o /tmp/incremental

# 0512：全表 35 轮
python -B collaboration/anneal-current-parent/reproduce.py \
    --puzzles data/puzzles.csv --binary-dir /tmp --rounds 35 --jobs 2

# 0310、0477：紧上限子集 400 轮（子集按官方文件顺序生成，种子依赖该顺序）
python -B collaboration/anneal-current-parent/reproduce.py \
    --puzzles data/puzzles.csv --binary-dir /tmp --rounds 400 --select tight --jobs 2
```

脚本自己重跑、逐题回放变短的行，再和 `wins.csv` 比对程序哈希，不一致返回非零。
耗时：全表 35 轮约 2.5 分钟；紧上限 271 题 400 轮约 7 分钟（2 核）。

## 上一版的导入已撤下

`TomYanabe/santa2026` 没有 LICENSE/NOTICE，并且在 2026-11-21 返回 404。它那份 122 道更短的表
既无法授权、也无法让第三方下载复核，所以它的完整表与派生行都不进本仓库（原 PR #1 已关闭）。
本目录三行全部改自仓库自己的程序。
