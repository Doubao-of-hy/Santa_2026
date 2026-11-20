"""Verify a diverse 25-step program and optionally replay the paired stochastic pilot."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=here.parents[1])
    parser.add_argument("--puzzles", required=True, type=Path)
    parser.add_argument("--parents", type=Path)
    parser.add_argument("--rerun", action="store_true")
    parser.add_argument("--cxx", default="g++")
    parser.add_argument("--scratch", type=Path)
    args = parser.parse_args()
    repo = args.repo.resolve()
    sys.path.insert(0, str(repo))
    from elf import check, read_puzzles, read_submission, replay, sha256
    from tiny import encode

    bank = args.parents or repo / "collaboration/puzzle-0882-diversity/parents.json"
    assert sha256(bank) == "2f01c3719639881aa0ced3749db824abfb80c70c38d83bba4827d1c18e3f3e27"
    records = json.loads(bank.read_bytes())
    assert sha256(args.puzzles) == records["official_puzzles_sha256"]
    puzzle = next(p for p in read_puzzles(args.puzzles) if p.id == records["id"])
    old = set(records["union"])
    seeds = set(puzzle.seeds)
    goals = set(puzzle.targets)
    tapes = [r["program"] for r in records["parents"]]
    union = set()
    assert [check(puzzle, tape) for tape in tapes] == [23, 24, 23, 23, 23]
    for tape in tapes:
        union.update({s.output for s in replay(puzzle, tape)} - seeds - goals)
    assert old == union and len(old) == 20
    witness = here / "novelty-25.csv"
    assert sha256(witness) == "4abb84d1014b4204cb53b3ed062d5dfd60070e62270c9d5957929ef123010a0b"
    physical = replay(puzzle, read_submission(witness)[puzzle.id])
    helpers = {s.output for s in physical} - seeds - goals
    assert len(physical) == 25 and len(helpers) == 13 and len(old & helpers) == 1
    print("25 steps, 13 helpers, 1 shared with the frozen union")
    if not args.rerun:
        return

    blocks = [[puzzle.limit, len(puzzle.seeds), len(puzzle.targets), len(tapes), 23,
               *puzzle.seeds, *puzzle.targets]]
    for tape in tapes:
        steps = replay(puzzle, tape)
        blocks.append([len(steps)])
        blocks.extend([s.output, s.left, s.right] for s in steps)
    blocks.append([len(old), *sorted(old)])
    inp = "\n".join(" ".join(map(str, row)) for row in blocks) + "\n"
    with tempfile.TemporaryDirectory(dir=args.scratch) as scratch:
        exe = Path(scratch) / "search.exe"
        subprocess.run([args.cxx, "-O3", "-std=c++17", "-static", str(here / "novelty_search.cpp"),
                        "-o", str(exe)], check=True)
        for seed, expected in [(112099, [27, 26]), (124017, [27, 25])]:
            for arm, target in zip(["baseline", "guided"], expected):
                run = subprocess.run([str(exe), str(seed), "1800", arm], text=True, input=inp,
                                     capture_output=True, check=True)
                eligible = []
                for line in run.stdout.splitlines():
                    if line.startswith("CELL "):
                        t = list(map(int, line.split()[1:]))
                        length, shared = t[:2]
                        seq = t[5:]
                        assert check(puzzle, encode(puzzle, seq)) == length
                        assert len(old & set(seq)) == shared
                        if shared <= 4:
                            eligible.append(length)
                end = run.stdout.splitlines()[-1].split()
                assert end[:3] == ["END", "1800", "23"]
                assert min(eligible) == target
                print(seed, arm, min(eligible), flush=True)


if __name__ == "__main__":
    main()
