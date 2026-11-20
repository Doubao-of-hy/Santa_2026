# 三道新公开题的本地再搜索

以提交 34a7042 的两份完整程序为起点。第 64 题从 112 条缩短到 111 条，公开辅助全表从 134,183 降到 134,182。第 362、501 题各保留此前更短的方案。独立全表为 140,722 条。[九次结果和原始署名](results.json) · [第 64 题的程序](public-shorter.csv)

参考 E-Max AI 的两份公开实验。对每题分别使用能在有来源的历史文件中匹配的输入、当前公开辅助解与历史解、当前独立解与独立历史解。第 64 题有一个公开父本无法匹配，实际使用了其余四个，九次运行均从已登记的源码重新编译并再次得到相同的程序。第 362 题有一个父本未能匹配，第 501 题的输入全部匹配。两份全量结果均已用两套解释器回放。[预先登记的比较](../retained-design.json) · [重建所需输入](cases.json.gz) · [E-Max AI 的第 47 版输入](https://www.kaggle.com/datasets/royalacecat/santa-2026-retained-replay-inputs-134190/versions/1)

从仓库根目录运行以下命令，指定官方题库和编译器路径即可重现九次结果。

```text
python -B collaboration/retained-pool/v43/replay.py --repo . --puzzles data/puzzles.csv --book collaboration/frontier-134285/retained/cases.json.gz
```
