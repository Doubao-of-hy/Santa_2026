# 暂时拿掉部分目标再重建整题

从一个已有程序中移除一个目标，或移除共享中间值的两至三个目标。先优化保留下来的程序，再尝试用这份程序中的新数值通过一两步算术补回原目标，最后对整题搜索。对照组用同一对种子和轮数直接优化整题。所有路线在接受改动前都重放每一条寄存器指令。[固定的预算与选择规则](design.json) · [最初选定的 48 个案例](selection.json)

两条路线分别有 8 道开发题、16 道留出题。独立候选在开发组有 2 道共省 3 条，留出组另有 7 道共省 9 条。7 道留出题均严格优于普通搜索。公开辅助候选在同等规模的小组没有直接缩短。固定的后续范围包含 873 道符合条件且未参与这两组的独立题，48 道一批。[开发结果](development.json) · [留出结果](holdout.json) · [扩展名单](extension-selection.json.gz)

复验时，使用设计指定的 Git 历史、官方 puzzles.csv 和本项目根目录。将本目录里的 selection.json、development.json.gz 与 holdout.json.gz 放在临时目录，运行 compare.py，带上 --puzzles、--out、--phase development 或 holdout，并加 --replay-only。从头搜索时使用 collaboration/reactive-tabu/build.py 的 original 引擎。
