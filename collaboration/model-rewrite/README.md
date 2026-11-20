# 本机模型改写

`model_rewrite.py` 从当前公开辅助候选抽取 4、6 或 8 条指令的片段，优先选仍有已证上下界差距的短题。它读取协作组的逐题上下界和局部证明档案，跳过已证最短的题、已证无法缩短的片段和已经有更短见证的旧候选。模型只收到片段、初始寄存器值、后续读取的寄存器和片段必须产生的目标。回复按 JSON 数据读取，由本地整数解释器检查片段边界和完整程序，通过后才生成候选。

## 运行

准备官方 `data/puzzles.csv`，在 PowerShell 里读取网关密钥，并启动一次运行。密钥只通过子进程环境提供。

```powershell
$SantaKey = Read-Host '本机网关 API Key' -AsSecureString
$env:SANTA_GATEWAY_API_KEY = [System.Net.NetworkCredential]::new('', $SantaKey).Password
Remove-Variable SantaKey
python -B model_rewrite.py --requests 4
Remove-Item Env:SANTA_GATEWAY_API_KEY
```

持续运行时改用 `python -B -u model_rewrite.py --watch`。进程只经 `127.0.0.1:7863` 调用 `cn:hy4flash-free`，默认每 24 小时至多派 24 次，调用间隔至少 15 秒。每个片段按输入和约束取指纹，派单之前写入 SQLite，同时记录网关实际回报的用量。停机后重启会接着使用台账，中断时已派出的片段也计入上限。使用 `--baseline` 可以选择已经复核的其他完整候选。

## 交接

默认在 `work/model-rewrite/` 保存台账，出现严格缩短后导出 `submission.csv` 和 `changes.json`。交接前核对 `changes.json` 中的官方输入、底稿和候选哈希，再用 `elf.py` 和 `checkpoint.independent_score` 复核全部题目。合并时保留原算式的来源，在改写题的来源中增加模型 ID，并提交对应的证据。

```powershell
python -B -m unittest test_model_rewrite
python -B elf.py data/puzzles.csv work/model-rewrite/submission.csv
```
