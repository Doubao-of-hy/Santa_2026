"""Verify a pinned Kaggle program dataset and retain its accompanying notices."""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import csv
import json
from pathlib import Path, PurePosixPath
from zipfile import ZipFile, is_zipfile

import requests

from elf import read_puzzles, read_submission, score, write_submission


def read_dataset_table(f):
    with f.open(encoding="utf-8-sig", newline="") as src:
        reader = csv.DictReader(src, strict=True)
        if reader.fieldnames == ["id", "program"]:
            return read_submission(f)
        if not {"id", "program"} <= set(reader.fieldnames or []):
            raise ValueError("missing id or program")
        projection = f.with_suffix(".projection.csv")
        try:
            with projection.open("w", encoding="utf8", newline="") as target:
                writer = csv.writer(target)
                writer.writerow(("id", "program"))
                for row in reader:
                    writer.writerow((row["id"], row["program"]))
            return read_submission(projection)
        finally:
            projection.unlink(missing_ok=True)


def fetch(url, params):
    last = None
    for i in range(5):
        host = ("https://api.kaggle.com/v1", "https://www.kaggle.com/api/v1")[i % 2]
        try:
            response = requests.get(host + url, params=params, timeout=45)
            response.raise_for_status()
            return response
        except requests.RequestException as error:
            last = error
    raise last


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("ref")
    args.add_argument("version", type=int)
    args.add_argument("path", type=Path)
    args = args.parse_args()
    args.path.mkdir(parents=True, exist_ok=True)
    metadata = fetch("/datasets/view/" + args.ref, {"datasetVersionNumber": args.version}).json()
    raw = fetch("/datasets/download/" + args.ref, {"datasetVersionNumber": args.version}).content
    names = []
    candidates = []
    if is_zipfile(BytesIO(raw)):
        with ZipFile(BytesIO(raw)) as archive:
            names = archive.namelist()
            for item in archive.infolist():
                name = PurePosixPath(item.filename).name
                if not name or item.file_size > 8_000_000:
                    continue
                if name.endswith(".csv") and item.file_size > 1_200_000:
                    if "program" in name.lower() or "submission" in name.lower():
                        dest = args.path / name
                        dest.write_bytes(archive.read(item))
                        candidates.append(dest)
                elif name.lower().startswith(("license", "notice", "provenance", "readme", "sources", "attribution", "history")):
                    (args.path / name).write_bytes(archive.read(item))
    else:
        dest = args.path / "raw.csv"
        dest.write_bytes(raw)
        candidates.append(dest)
    puzzles = read_puzzles("data/puzzles.csv")
    programs = []
    for f in candidates:
        if f == args.path / "programs.csv":
            moved = f.with_name("upstream_programs.csv")
            f.replace(moved)
            f = moved
        try:
            rows = read_dataset_table(f)
            programs.append((score(puzzles, rows), f, rows))
        except (ValueError, KeyError) as err:
            print("Skipped", f.name, repr(err))
    count, raw_path, rows = min(programs, key=lambda entry: entry[0])
    dest = args.path / "programs.csv"
    write_submission(dest, puzzles, rows)
    audit = dict(url=f"https://www.kaggle.com/datasets/{args.ref}/versions/{args.version}",
                 metadata_version=metadata.get("currentVersionNumber"), license=metadata.get("licenseName"),
                 description=metadata.get("description"), archive=sha256(raw).hexdigest(),
                 raw_sha256=sha256(raw_path.read_bytes()).hexdigest(), raw=raw_path.name,
                 normalized_sha256=sha256(dest.read_bytes()).hexdigest(), score=count,
                 names=names, utc=datetime.now(timezone.utc).isoformat())
    (args.path / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf8")
    print(count, audit["license"], audit["normalized_sha256"], audit["metadata_version"], flush=True)


if __name__ == "__main__":
    main()
