"""Dissect one puzzle's program: values, ops, and structure vs hub model."""
import json, sys
from pathlib import Path
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
import elf

pid = sys.argv[1] if len(sys.argv) > 1 else "scored_0421"
puzzles = {p.id: p for p in elf.read_puzzles(root / "data/puzzles.csv")}
progs = elf.read_submission(root / "improve/merged/submission.csv")
p = puzzles[pid]
prog = progs[pid]
trace = elf.replay(p, prog)
targets = set(p.targets)
print(f"{pid}: seeds={p.seeds} limit={p.limit} ntargets={len(p.targets)} len={len(prog)}")
regs = list(p.seeds) + [0] * (48 - len(p.seeds))
for i, ((op, l, r, d), step) in enumerate(zip(prog, trace)):
    tag = "TARGET" if step.output in targets else ""
    print(f"{i:3d} r{d:02d} = r{l:02d} {op} r{r:02d}   {regs[l]} {op} {regs[r]} = {step.output} {tag}")
    regs[d] = step.output