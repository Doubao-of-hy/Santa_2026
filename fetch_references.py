"""Fetch versioned public program files and verify their exact bytes."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import tempfile
from urllib.request import urlopen
from zipfile import ZipFile


def fetch(folder, manifest=None):
    spec = json.loads(
        (manifest or Path(__file__).with_name("references.json")).read_text()
    )
    fetch_entries(folder, spec)


def fetch_entries(folder, spec):
    folder.mkdir(parents=True, exist_ok=True)
    for name, ref in spec.items():
        dest = folder / (name + ".csv")
        if dest.exists():
            if hashlib.sha256(dest.read_bytes()).hexdigest() != ref["sha256"]:
                raise ValueError(f"{dest} already exists with different contents")
            continue
        url = f"https://www.kaggle.com/api/v1/datasets/download/{ref['dataset']}?datasetVersionNumber={ref['version']}"
        with (
            urlopen(url, timeout=90) as response,
            ZipFile(io.BytesIO(response.read())) as archive,
        ):
            content = archive.read(ref["file"])
        if hashlib.sha256(content).hexdigest() != ref["sha256"]:
            raise ValueError(f"Unexpected checksum for {name}")
        with tempfile.NamedTemporaryFile(dir=folder, delete=False) as out:
            out.write(content)
            tmp = Path(out.name)
        try:
            tmp.replace(dest)
        finally:
            tmp.unlink(missing_ok=True)
        print(f"{name}: verified", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("directory", type=Path, nargs="?", default=Path("data"))
    ap.add_argument(
        "--manifest", type=Path, help="Alternate version and checksum manifest"
    )
    args = ap.parse_args()
    fetch(args.directory, args.manifest)
