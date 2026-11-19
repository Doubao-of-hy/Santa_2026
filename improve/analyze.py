"""Per-puzzle gap analysis: current lengths vs certified lower bounds."""
import csv, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import elf

root = Path(__file__).resolve().parent.parent
puzzles = elf.read_puzzles(root / "data/puzzles.csv")
pa = elf.read_submission(root / "public-assisted/submission.csv")
ind = elf.read_submission(root / "submission.csv")

bounds = {}
with (root / "work/virtual/certificates.csv").open(encoding="utf-8") as f:
    for row in csv.DictReader(f):
        bounds[row["id"]] = int(row["certified_lower_bound"])

rows = []
for p in puzzles:
    a, b = len(pa[p.id]), len(ind[p.id])
    lb = bounds.get(p.id, 0)
    rows.append((p.id, a, b, lb, a - lb, len(p.targets), len(p.seeds), p.limit))

rows.sort(key=lambda r: -r[4])
total_a = sum(r[1] for r in rows)
total_b = sum(r[2] for r in rows)
total_lb = sum(r[3] for r in rows)
print(f"public-assisted={total_a} independent={total_b} lower_bound={total_lb}")
print(f"{'id':14s} {'pa':>5s} {'ind':>5s} {'lb':>4s} {'gap':>5s} {'ntgt':>4s} {'nseed':>5s} limit")
for r in rows[:40]:
    print(f"{r[0]:14s} {r[1]:5d} {r[2]:5d} {r[3]:4d} {r[4]:5d} {r[5]:4d} {r[6]:5d} {r[7]}")

# distribution of gaps
import collections
hist = collections.Counter()
for r in rows:
    hist[r[4] // 25 * 25] += 1
print("gap histogram (bucket: count):", dict(sorted(hist.items())))

with (Path(__file__).parent / "gaps.json").open("w") as f:
    json.dump([dict(id=r[0], pa=r[1], ind=r[2], lb=r[3], gap=r[4],
                    ntargets=r[5], nseeds=r[6], limit=r[7]) for r in rows], f)