"""Apply the repo's pure-Python algebraic rewrite pass to every puzzle.

Uses algebra_rewrite.repair_algebra (reassociate / distribute / squared-difference
/ exchange-carry), which only keeps programs that are shorter and pass replay.
Reads improve/merged/submission.csv, writes improve/algebra/submission.csv.
Never touches original files.
"""
import json, sys, time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
import elf
from algebra_rewrite import repair_algebra

puzzles = elf.read_puzzles(root / "data/puzzles.csv")
inc = elf.read_submission(root / "improve/merged/submission.csv")


def work(p):
    prog = inc[p.id]
    try:
        better = repair_algebra(p, prog)
    except Exception:
        better = prog
    if len(better) < len(prog):
        elf.check(p, better)
        return p.id, better, len(prog) - len(better)
    return p.id, prog, 0


def main():
    outdir = root / "improve/algebra"
    outdir.mkdir(exist_ok=True)
    programs = dict(inc)
    gain = improved = 0
    start = time.monotonic()
    rows = []
    with ProcessPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(work, p): p.id for p in puzzles}
        done = 0
        for fut in as_completed(futs):
            pid, prog, g = fut.result()
            programs[pid] = prog
            gain += g
            if g:
                improved += 1
                rows.append((pid, g))
            done += 1
            if done % 100 == 0:
                print(f"{done}/1000 gain {gain} on {improved}, {time.monotonic()-start:.1f}s", flush=True)
    total = elf.write_submission(outdir / "submission.csv", puzzles, programs)
    rows.sort(key=lambda r: -r[1])
    (outdir / "gains.json").write_text(json.dumps(
        dict(total=total, gain=gain, improved=improved,
             sha256=elf.sha256(outdir / "submission.csv"),
             top=rows[:40]), indent=2))
    print(f"TOTAL {total} (gain {gain} on {improved} puzzles)")
    print("top gains:", rows[:15])


if __name__ == "__main__":
    main()