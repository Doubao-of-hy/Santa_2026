"""Restore a scored checkpoint from verified public sources and this project's edits."""

import argparse
import gzip
import hashlib
import json
import os
from difflib import SequenceMatcher
from pathlib import Path
from tempfile import TemporaryDirectory

from fetch_references import fetch_entries
from machine import load_programs, load_puzzles, save_verified, score

HERE = Path(__file__).resolve().parent
DEFAULT_PATCH = HERE / "checkpoints" / "scored-round2.patch.json.gz"


def digest(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()


def manifests():
    out = {}
    for file in ("references.json", "references_round2.json"):
        batch = json.loads((HERE / file).read_text())
        if set(batch) & set(out):
            raise ValueError("Duplicate references")
        out.update(batch)
    return out


def read_sources(puzzles, folder, spec):
    sources = {}
    for name, ref in spec.items():
        src = folder / (name + ".csv")
        if digest(src) != ref["sha256"]:
            raise ValueError(f"Unexpected checksum for {src}")
        programs = load_programs(src, reference=True)
        score(puzzles, programs)
        sources[name] = programs
    return sources


def edits(before, after):
    prev = list(map(tuple, before))
    cur = list(map(tuple, after))
    return [
        [a, b, after[c:d]]
        for tag, a, b, c, d in SequenceMatcher(
            None, prev, cur, autojunk=False
        ).get_opcodes()
        if tag != "equal"
    ]


def apply_edits(original, changes):
    result = []
    last = 0
    for start, end, insert in changes:
        if not last <= start <= end <= len(original):
            raise ValueError("Invalid patch span")
        result.extend(original[last:start])
        result.extend(insert)
        last = end
    return result + original[last:]


def build(args):
    puzzles = load_puzzles(args.puzzles)
    final = load_programs(args.submission)
    total = score(puzzles, final)
    spec = manifests()
    sources = read_sources(puzzles, args.references, spec)
    rows = {}
    used = set()
    for p in puzzles:
        new = final[p.id]
        # Prefer an exact upstream row wherever one is available.
        same = next((k for k, src in sources.items() if src[p.id] == new), None)
        if same is not None:
            rows[p.id] = same
            used.add(same)
            continue
        best = None
        for k, programs in sources.items():
            patch = edits(programs[p.id], new)
            size = len(json.dumps(patch, separators=(",", ":")))
            if best is None or size < best[0]:
                best = (size, k, patch)
        _, source, changes = best
        assert apply_edits(sources[source][p.id], changes) == new
        rows[p.id] = [source, changes]
        used.add(source)
    package = dict(
        format=1,
        puzzles_sha256=digest(args.puzzles),
        submission_sha256=digest(args.submission),
        steps=total,
        sources={k: spec[k]["sha256"] for k in sorted(used)},
        rows=rows,
    )
    content = json.dumps(package, separators=(",", ":")).encode()
    args.patch.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=args.patch.parent) as folder:
        tmp = Path(folder) / "patch.gz"
        tmp.write_bytes(gzip.compress(content, mtime=0))
        tmp.replace(args.patch)


def restore(args):
    package = json.loads(gzip.decompress(args.patch.read_bytes()))
    if package["format"] != 1 or digest(args.puzzles) != package["puzzles_sha256"]:
        raise ValueError("Wrong puzzle file or unsupported patch format")
    puzzles = load_puzzles(args.puzzles)
    spec = manifests()
    required = {k: spec[k] for k in package["sources"]}
    if any(ref["sha256"] != package["sources"][k] for k, ref in required.items()):
        raise ValueError("Patch and source manifest differ")
    if not args.offline:
        fetch_entries(args.references, required)
    sources = read_sources(puzzles, args.references, required)
    codes = {}
    for puzzle, row in package["rows"].items():
        name, changes = (row, []) if isinstance(row, str) else row
        codes[puzzle] = apply_edits(sources[name][puzzle], changes)
    args.submission.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=args.submission.parent) as folder:
        tmp = Path(folder) / "submission.csv"
        steps = save_verified(tmp, puzzles, codes)
        if steps != package["steps"] or digest(tmp) != package["submission_sha256"]:
            raise ValueError(
                "Reconstructed output differs from the published checkpoint"
            )
        os.replace(tmp, args.submission)
    print(
        f"{len(puzzles)} puzzles, {steps} instructions, SHA-256 {package['submission_sha256']}"
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=["restore", "build"])
    ap.add_argument("puzzles", type=Path)
    ap.add_argument("submission", type=Path)
    ap.add_argument("--references", type=Path, default=Path("out/references"))
    ap.add_argument("--patch", type=Path, default=DEFAULT_PATCH)
    ap.add_argument(
        "--offline",
        action="store_true",
        help="Use already downloaded and verified source files",
    )
    args = ap.parse_args()
    if args.action == "build":
        build(args)
    else:
        restore(args)


if __name__ == "__main__":
    main()
