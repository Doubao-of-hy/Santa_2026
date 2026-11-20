# 从官方输入复核 36,731 条总下界

本目录保存了 1,000 道计分题的分析下界、4 份压缩证明树、17 轮辅助数穷举和相关审计。部分轮次有单独的细分记录。19 道题已达到最短。所有穷举都允许永久保留生成的值，因此无解证明也覆盖题目的 48 寄存器限制。用于上界的每份实际程序都按题目的寄存器规则逐条运行。[逐题结果](../../collaboration/puzzle-bounds.csv) · [未决分片](../../collaboration/proof-status.md)

先从比赛下载官方 `puzzles.csv`。原始字节的 SHA-256 为 `b0c70d849eca078a0e1cf9a4f7b47fd40b7435663f6f84de6725f84724500428`。以下命令在仓库根目录执行，示例用 `data/puzzles.csv` 指代本机下载的文件。Python 3.12 或更新版本即可做汇总与分析重算。

```bash
python -B proofs/local/verify.py --puzzles data/puzzles.csv --submission submission.csv --second-submission public-assisted/submission.csv --csv collaboration/puzzle-bounds.csv
python -B proofs/local/verify.py --puzzles data/puzzles.csv --submission submission.csv --second-submission public-assisted/submission.csv --analysis --jobs 4
```

第一条命令核对输入与归档哈希、每个采用的分片网格、子分片完整性及节点合计，合并各类证明，使用两套解释器分别重放两份完整提交，并逐题导出下界、上界和差距。第二条还从官方数字重新计算 1,000 道题的算术包络，并展开四份证明树，从每个节点重新生成候选分组及叶节点下界。完整的原生穷举是下文单独列出的长任务。输入一份其他合法提交也可查询它达到下界的题数。

仓库原有的 `proofs/bounds.csv` 保留原字节。这里的分析包引用另一份有独立来源的历史表，放在本目录的 `proofs/bounds.csv`，对应 SHA-256 为 `f168c8ba41d1ae4653ad87059bd469396ab86bfa863f2a5c930173bf7a556add`。两份历史表中的可行上界在后续有过改进。当前表的上界始终从用户指定的提交重放获得。[分析下界](proofs/domain-bounds.json) · [证明树索引](proofs/conditioned-bounds.json) · [归档文件哈希](files.sha256.json)

### 与其他贡献者的证明合并

复核器读取仓库根目录的 `proofs_ext/bounds.csv`，并从 `proofs/decisions.json`、`proofs_ext/decisions.json` 和 `proofs_ext/decisions.d/` 的预算与官方目标数重建每行下界。若外部某题首次超过本目录的证书，命令会列出该题。使用下列参数重新运行汇总，程序会重放所有带来增益的外部判定，要求逐片穷尽、展开节点数与上游逐片相符，末位候选数合计也须相符。全部通过后才提高该题的合并下界。

```bash
g++ -O3 -std=c++17 exact_helpers.cpp -o external-exact
python -B proofs/local/verify.py --puzzles data/puzzles.csv --submission submission.csv --second-submission public-assisted/submission.csv --external-binary ./external-exact --csv collaboration/puzzle-bounds.csv
```

### 原生全域搜索

使用支持 128 位整数的 GCC 或 Clang。Windows 可将输出名改为 `.exe`。第一行编译增量遍历，第二行编译原始式遍历与独立的三辅助数判定，第三行编译第 882 题正在使用的有界域分组版本。原始编译记录保留在 `work/gpu/closest-36729/*build.json`。其他平台的可执行文件哈希可能不同，启动后会按照本机二进制的哈希单独保存回执。

```bash
g++ -O3 -std=c++17 proofs/local/work/gpu/closest-36729/star.cpp -o proof-star
g++ -O3 -std=c++17 -I proofs/local proofs/local/work/gpu/closest-36729/generic_verifier.cpp -o proof-generic
g++ -O3 -std=c++17 proofs/local/work/gpu/closest-36729/hot.cpp -o proof-hot
python -B proofs/local/native_replay.py --puzzles data/puzzles.csv --binary ./proof-star --save work/replay-star --task 0882:9 --shards 12 --subshards 8 --jobs 4
python -B proofs/local/native_replay.py --puzzles data/puzzles.csv --binary ./proof-generic --engine generic --save work/replay-generic --task 0882:9 --shards 12 --subshards 8 --jobs 4
python -B proofs/local/native_replay.py --puzzles data/puzzles.csv --binary ./proof-star --save work/replay-every-puzzle --jobs 4
```

末条命令对所有有穷举证书的题重算所记录的最强辅助数预算。新建网格与历史网格可以不同，所有分片均须返回无解。用 `--cell 3:2` 可单独检查编号 (3, 2)；输出中会标明整张网格尚未完成。达到限额的格会记为未决，提高 `--nodes` 可重跑它；已完成的格会复用。运行中的第 882 题采用 `--binary ./proof-hot --engine hot --task 0882:10 --shards 24 --subshards 32 --nodes 120000000 --width 16`。同步计算前可先查目前已分配的网格。[分片清单](../../collaboration/proof-status.md)

最后三个辅助数的判定暂时允许未来的目标参与运算。如果每两个不同的新辅助数合计最多产生一个尚缺的目标，三对辅助数合计最多产生三个。因此剩余目标必须分摊给三个辅助数，至少有一个能和旧数、自身或目标组合产生足够多的目标。只靠同一辅助数相互产生的一组目标必须有一个可先生成的入口。另一种情况是某对辅助数产生至少两个目标，此时从算术运算反解即可枚举这样的操作数对，再反推第三个值。两种实现分别使用增量索引和直接的三数可达判定。[增量终局](work/gpu/closest-36729/three.inc) · [独立三数判定](work/gpu/closest-36729/verify3.inc) · [1,082 个对照](work/gpu/closest-36729/alternate-verification.json)
