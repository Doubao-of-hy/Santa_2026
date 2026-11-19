"""Re-download the public program datasets used by merge_public.py.

Run once before merge_public.py on a fresh checkout (the downloads themselves
are not committed, to keep the repository lean). Requires `python -m kaggle`.
"""
import subprocess, sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
DATASETS = [
    "asteriospanoras/santa-2026-elf-programs-and-experiments",
    "hanifnoerrofiq/santa-2026-elf-calculator-peephole-programs",
    "ozertuu/santa-2026-verified-programs",
    "alexchilton/santa-2026-rudolph-programs",
    "konbu17/santa-2026-elf-calculator-programs",
    "kindasomethin/santa-2026-exact-portfolio-checkpoints",
    "sacuscreed/santa-2026",
    "thisray/santa-2026-two-step-dictionary-submission",
]
for d in DATASETS:
    dest = root / "improve/public" / d.split("/")[-1]
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "kaggle", "datasets", "download",
                    "-d", d, "-p", str(dest), "--unzip"], check=False)
print("done; now run: python -B improve/merge_public.py")