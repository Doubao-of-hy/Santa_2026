"""Merge per-puzzle best across the current candidate and C++ search outputs.

Every program is independently replayed before adoption. Writes
improve/submission.csv (the canonical best) and improve/cpp/merged_result.json.
"""
import json, sys
from pathlib import Path
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
import elf

puzzles = elf.read_puzzles(root / "data/puzzles.csv")
pmap = {p.id: p for p in puzzles}
SOURCES = [
    ("current", root / "improve/submission.csv"),
    ("vsearch", root / "improve/cpp/vsearch.csv"),
    ("vsearch2", root / "improve/cpp/vsearch2.csv"),
    ("matrix", root / "improve/cpp/matrix.csv"),
    ("matrix2", root / "improve/cpp/matrix2.csv"),
    ("matrix3", root / "improve/cpp/matrix3.csv"),
    ("vhard", root / "improve/cpp/vhard.csv"),
]
best = {}
origin = {}
stats = {}
for name, path in SOURCES:
    if not path.exists():
        print(f"skip missing {name}")
        continue
    progs = elf.read_submission(path)
    adopted = improved = 0
    for pid, prog in progs.items():
        p = pmap.get(pid)
        if p is None:
            continue
        try:
            elf.replay(p, prog)
        except Exception:
            continue
        adopted += 1
        if pid not in best or len(prog) < len(best[pid]):
            if pid in best:
                improved += 1
            best[pid] = prog
            origin[pid] = name
    stats[name] = dict(valid=adopted, improved=improved)
    print(f"{name:10s} valid={adopted} improved={improved}")

missing = [p.id for p in puzzles if p.id not in best]
if missing:
    print("MISSING", len(missing)); sys.exit(1)
total = elf.write_submission(root / "improve/submission.csv", puzzles, best)
res = dict(total=total, sha256=elf.sha256(root / "improve/submission.csv"),
           sources=stats,
           adoption={n: sum(1 for v in origin.values() if v == n) for n, _ in SOURCES})
(root / "improve/cpp/merged_result.json").write_text(json.dumps(res, indent=2))
print("TOTAL", total)
print(json.dumps(res["adoption"]))