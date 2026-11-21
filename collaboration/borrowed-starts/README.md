# 暂借中间值，再从正式初值重建

同一道题分别从三种起点搜索。第一种直接改进原程序；第二种暂时把原程序中多处使用的数放进初始寄存器；第三种借用原程序未使用、但可能帮助生成多个旧值的数。搜索结束后，必须从官方初值重新构造用到的每个借值，并在真实寄存器上重放所有目标。三组使用相同种子和轮数，独立与公开辅助程序分别比较。[固定范围、预算与扩展条件](design.json)

按 [构建脚本](../reactive-tabu/build.py) 编译 original 引擎后，在仓库根目录运行以下命令。将 `own` 换为 `public` 可复跑公开辅助组，将 `development` 换为 `holdout` 可复跑留出题。

```shell
python -B collaboration/borrowed-starts/compare.py --phase development --lane own --puzzles data/puzzles.csv --exe work/bin/original --out work/borrowed --jobs 4
```

12 道开发题在两条路线均未缩短。在各 24 道留出题里，独立路线在两道题共省 2 条，第 39 题的借值方案比直接搜索多省 1 条。公开辅助组没有缩短，本轮结束。独立路线的首批 48 道扩展题有 10 道共省 15 条，8 道严格优于直接搜索。预定的独立扩展范围共 804 道。[按组结果和覆盖数](results/summary.json)

归档的每个压缩文件含三种方法的逐题结果、所用初值以及所有缩短的程序。将相应文件放到临时目录并以该目录作为 `--out`，加 `--replay-only` 可以重放整张提交。扩展题用 `--phase expand --block 0` 起按批复核。
