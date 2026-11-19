"""Create or improve a standalone Santa 2026 submission from the local puzzle CSV."""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from elf import read_puzzles, read_submission, score

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--puzzles", type=Path, default=ROOT / "data/puzzles.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "submission.csv")
    parser.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 1))
    parser.add_argument("--profile", choices=("quick", "standard", "deep"), default="standard")
    parser.add_argument("--resume", action="store_true", help="Improve the existing local submission")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    puzzles = args.puzzles.resolve()
    output = args.output.resolve()
    if output.suffix.lower() != ".csv":
        parser.error("--output must be a CSV filename")
    report = output.with_suffix(".json")
    puzzle_set = read_puzzles(puzzles)
    if output.exists() and not args.resume:
        parser.error("choose a new --output or use --resume to preserve and improve the current file")
    if output.exists():
        print(f"Existing submission: {score(puzzle_set, read_submission(output))} instructions", flush=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    jobs = str(args.jobs)

    with tempfile.TemporaryDirectory(prefix=".santa-run-", dir=ROOT) as temporary:
        path = Path(temporary)
        env = {**os.environ, "TEMP": temporary, "TMP": temporary, "SANTA_BUILD_DIR": temporary}

        def execute(script, *arguments):
            print(f"Running {script}", flush=True)
            subprocess.run([sys.executable, "-B", str(ROOT / script), *map(str, arguments)],
                           cwd=ROOT, env=env, check=True)

        def publish(candidate):
            inputs = [output, candidate] if output.exists() else [candidate]
            execute("portfolio.py", puzzles, output, *inputs, "--report", report)

        if not output.exists():
            first = path / "radix.csv"
            execute("solve.py", "construct", puzzles, first, "--jobs", jobs)
            publish(first)
        if args.profile == "quick":
            return

        rich = path / "dictionary.csv"
        execute("dictionary.py", puzzles, rich, "--fallback", output, "--jobs", jobs,
                "--variants", "0", "6", "--width", "7", "--depth", "2", "--schedule-width", "8")
        publish(rich)

        modular = path / "modular.csv"
        execute("modular_native.py", puzzles, modular, "--baseline", output, "--jobs", jobs,
                "--limit", min(400, len(puzzle_set)), "--direction", "forward", "reverse",
                "--width", "8", "--depth", "4", "--radix-profile", "tuned",
                "--schedule-width", "8")
        publish(modular)

        factors = path / "factors.csv"
        execute("factorization.py", puzzles, output, factors, "--jobs", jobs, "--wide", "--independent")
        publish(factors)

        if args.profile == "deep":
            residues = path / "residue-portfolio.csv"
            execute("modular_search.py", puzzles, residues, "--baseline", output, "--jobs", jobs,
                    "--min-count", "200", "--limit", min(350, len(puzzle_set)),
                    "--width", "6", "--depth", "4", "--span", "1")
            publish(residues)
            live = path / "live-registers.csv"
            execute("dictionary.py", puzzles, live, "--fallback", output, "--jobs", jobs,
                    "--variants", "30", "31", "--depth", "2", "--width", "8",
                    "--pilot", min(300, len(puzzle_set)), "--focus", "expensive")
            publish(live)
            hints = path / "arithmetic-hints.csv"
            execute("dictionary.py", puzzles, hints, "--fallback", output, "--jobs", jobs,
                    "--variants", "18", "--depth", "2", "--width", "7", "--warm",
                    "--factor-hints", "8", "--scale-hints", "8", "--independent",
                    "--pilot", min(128, len(puzzle_set)), "--focus", "expensive")
            publish(hints)
            combined = path / "combined.csv"
            execute("mix.py", puzzles, combined, output, rich, modular, factors, residues, "--jobs", jobs,
                    "--joins", "--global-seconds", "0.6")
            publish(combined)

        allocated = path / "register-allocation.csv"
        scheduling = ("--schedule-width", "16", "--operation-width", "24",
                      "--minimum-gap", "12") if args.profile == "deep" else ()
        execute("reallocate.py", puzzles, output, allocated, "--jobs", jobs, *scheduling)
        publish(allocated)

        repaired = path / "arithmetic-repairs.csv"
        execute("relations.py", puzzles, output, repaired, "--workers", jobs, "--depth", "2",
                "--passes", "4", "--additive", "--product", "--factor")
        publish(repaired)


if __name__ == "__main__":
    main()
