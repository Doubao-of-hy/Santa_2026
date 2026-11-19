"""Merge per-puzzle best programs from public sources + repo candidates.

Every candidate is independently replayed with elf.replay before adoption.
Outputs: improve/merged/submission.csv, origins.csv, result.json
"""
import csv, json, sys, hashlib
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
import elf

puzzles = elf.read_puzzles(root / "data/puzzles.csv")
pmap = {p.id: p for p in puzzles}

SOURCES = [
    ("repo-public-assisted", root / "public-assisted/submission.csv", "std"),
    ("repo-independent", root / "submission.csv", "std"),
    ("asterios-v23", root / "improve/public/santa-2026-elf-programs-and-experiments/best_programs.csv", "asterios"),
    ("hanif-peephole", root / "improve/public/santa-2026-elf-calculator-peephole-programs/submission.csv", "std"),
    ("ozertuu-verified", root / "improve/public/santa-2026-verified-programs/best_programs.csv", "std"),
    ("alexchilton-rudolph", root / "improve/public/santa-2026-rudolph-programs/rudolph_programs.csv", "std"),
    ("konbu17", root / "improve/public/santa-2026-elf-calculator-programs/submission.csv", "std"),
    ("kindasomethin-138441", root / "improve/public/santa-2026-exact-portfolio-checkpoints/submission_138441.csv", "std"),
    ("kindasomethin-138460", root / "improve/public/santa-2026-exact-portfolio-checkpoints/submission_138460.csv", "std"),
    ("kindasomethin-138628", root / "improve/public/santa-2026-exact-portfolio-checkpoints/submission_138628.csv", "std"),
    ("sacuscreed", root / "improve/public/santa-2026/submission.csv", "std"),
    ("thisray", root / "improve/public/santa-2026-two-step-dictionary-submission/submission.csv", "std"),
    ("repo-gpu-domain", root / "work/gpu/domain-independent.csv", "std"),
]


def load(path: Path, kind: str):
    out = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = row["id"]
            try:
                instr = json.loads(row["program"])
                prog = tuple((r[0], r[1], r[2], r[3]) for r in instr)
            except Exception:
                continue
            out[pid] = prog
    return out


best = {}
origin = {}
stats = {}
for name, path, kind in SOURCES:
    if not path.exists():
        print(f"skip missing {name}")
        continue
    progs = load(path, kind)
    adopted = improved = invalid = 0
    for pid, prog in progs.items():
        p = pmap.get(pid)
        if p is None:
            continue
        if len(prog) > elf.MAX_STEPS:
            invalid += 1
            continue
        try:
            elf.replay(p, prog)
        except Exception:
            invalid += 1
            continue
        adopted += 1
        if pid not in best or len(prog) < len(best[pid]):
            if pid in best:
                improved += 1
            best[pid] = prog
            origin[pid] = name
    stats[name] = dict(valid=adopted, improved=improved, invalid=invalid,
                       total=sum(len(v) for v in progs.values() if v))
    print(f"{name:26s} valid={adopted:4d} improved={improved:4d} invalid={invalid:3d}")

missing = [p.id for p in puzzles if p.id not in best]
if missing:
    print("MISSING:", missing[:10], "count", len(missing))
    sys.exit(1)

outdir = root / "improve/merged"
outdir.mkdir(exist_ok=True)
total = elf.write_submission(outdir / "submission.csv", puzzles, best)
with (outdir / "origins.csv").open("w", encoding="utf-8", newline="") as f:
    w = csv.writer(f, lineterminator="\n")
    w.writerow(("id", "source", "instructions"))
    for p in puzzles:
        w.writerow((p.id, origin[p.id], len(best[p.id])))
result = dict(total_instructions=total,
              sha256=elf.sha256(outdir / "submission.csv"),
              sources=stats,
              adoption={name: sum(1 for v in origin.values() if v == name)
                        for name, _, _ in SOURCES})
(outdir / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print("TOTAL:", total)
print(json.dumps(result["adoption"], indent=1))