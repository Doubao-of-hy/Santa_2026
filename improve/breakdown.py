"""Cost breakdown: how many instructions build small helpers vs targets."""
import json, sys, collections
from pathlib import Path
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
import elf

puzzles = elf.read_puzzles(root / "data/puzzles.csv")
progs = elf.read_submission(root / "improve/merged/submission.csv")

cat = collections.Counter()
per = []
for p in puzzles:
    trace = elf.replay(p, progs[p.id])
    targets = set(p.targets)
    n_small = n_target = n_big_helper = 0
    small_vals = set()
    for s in trace:
        if s.output in targets:
            n_target += 1
        elif s.output <= 10**7:
            n_small += 1
            small_vals.add(s.output)
        else:
            n_big_helper += 1
    cat["small"] += n_small
    cat["target"] += n_target
    cat["big_helper"] += n_big_helper
    per.append((p.id, len(trace), n_small, n_target, n_big_helper, len(p.seeds)))

print("totals:", dict(cat), "sum", sum(cat.values()))
per.sort(key=lambda r: -r[2])
print(f"{'id':14s} {'len':>4s} {'small':>5s} {'tgt':>4s} {'bigh':>4s} seeds")
for r in per[:25]:
    print(f"{r[0]:14s} {r[1]:4d} {r[2]:5d} {r[3]:4d} {r[4]:4d} {r[5]}")
import statistics
print("small median", statistics.median(r[2] for r in per),
      "mean", round(statistics.mean(r[2] for r in per), 1))
json.dump(per, open(Path(__file__).parent / "breakdown.json", "w"))