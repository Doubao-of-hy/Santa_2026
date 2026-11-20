# 第 334 题的独立因数改写

随附父本从官方起始值生成所有目标，需要 249 条。把目标附近的整数精确分解，找到一个新的中间乘积 47,655,577,306,891,225，可以由 774,575 × 61,524,806,903 得到。原有 8 个辅助数被 5 个新辅助数替换。只还原这一处依赖，程序长度回到 249 条。[替换明细](witness.json) · [独立父本](parent.csv) · [已验证的 246 条程序](shorter.csv)

在仓库根目录运行下面的 PowerShell 命令。需要 Python、NumPy、python-flint、支持 C++17 的 g++，以及比赛官方的 data/puzzles.csv。该例可以在 CPU 上运行。

```powershell
New-Item -ItemType Directory -Force work/factor-example | Out-Null
python -m pip install numpy python-flint
g++ -O3 -std=c++17 factor_resynthesis.cpp -o work/factor-example/factor.exe
python -B factor_resynthesis.py collaboration/factor/parent.csv work/factor-example/shorter.csv --ids collaboration/factor/ids.txt --exe work/factor-example/factor.exe --cuts 36 --offsets 64 --nout 32 --jobs 1
```

命令的最后一行为 `rows 1 saved 3`。写出的 CSV 仅含这道题，可用 checkpoint.py 和现有完整候选按题择短。预附结果由上述搜索实际产生。[运行记录](result.json)
