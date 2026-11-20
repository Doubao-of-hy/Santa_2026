"""Regenerate the README decision table and certified total from decisions.d.

The table is derived programmatically (never hand-edited) so shard counts and
node totals always match the receipts. Source of truth: decisions.d/*.json plus
any legacy entries still only in decisions.json (decisions.d wins on conflict).
Uppers come from bounds.csv (verified_upper, replayed improve/submission.csv).
"""

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "proofs_ext"


def all_decisions():
    merged = {}
    dj = EXT / "decisions.json"
    if dj.exists():
        for d in json.loads(dj.read_text(encoding="utf8"))["decisions"]:
            merged[(d["id"], d["helpers"])] = d
    for f in sorted((EXT / "decisions.d").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf8"))
        merged[(d["id"], d["helpers"])] = d
    return [merged[k] for k in sorted(merged)]


def main():
    decisions = all_decisions()
    upper = {
        r["id"]: int(r["verified_upper"])
        for r in csv.DictReader(open(EXT / "bounds.csv", newline="", encoding="utf8"))
    }
    certified_total = sum(
        int(r["certified_lower"])
        for r in csv.DictReader(open(EXT / "bounds.csv", newline="", encoding="utf8"))
    )
    rows = ["| 题号 | 辅助数预算 | 分片 | 展开节点合计 | 结论 | 新下界 | 上界 |",
            "|---|---:|---:|---:|---|---:|---:|"]
    for d in decisions:
        nodes = sum(d["shard_nodes"])
        rows.append(
            f"| {d['id']} | {d['helpers']} | {len(d['shard_nodes'])} | {nodes:,} "
            f"| 全部 UNSAT | **{d['lower_bound']}** | {upper[d['id']]} |"
        )
    table = "\n".join(rows)

    readme = EXT / "README.md"
    text = readme.read_text(encoding="utf8")
    # Replace the header + separator + contiguous "| scored_" rows only.
    # No DOTALL: [^\n]* keeps each match on a single line so the greedy row
    # group cannot swallow the prose sections that follow the table.
    pattern = re.compile(
        r"\| 题号 \|[^\n]*\n\|[-| :]+\n(?:\| scored_[^\n]*\n)+"
    )
    text, n = pattern.subn(table + "\n", text, count=1)
    if n != 1:
        raise SystemExit("table header not found")
    # Refresh the certified total line.
    text = re.sub(
        r"全体 1,000 题已证总下界 \*\*[\d,]+\*\*（原 33,586 \+ \d+）。",
        f"全体 1,000 题已证总下界 **{certified_total:,}**"
        f"（原 33,586 + {certified_total - 33586}）。",
        text,
    )
    readme.write_text(text, encoding="utf8")
    print(f"regenerated {len(decisions)} decision rows; certified total {certified_total:,}")


if __name__ == "__main__":
    main()