"""Share the pair-coverage audit across runs instead of paying it every time.

`exact_helpers --audit-pairs` costs whatever the puzzle's value space costs, not
what the helper budget costs: scored_0630, scored_0583 and scored_0777 each need
more than 15 minutes on one core, while their entire shard grids take minutes
(0.9-1.2 million nodes per shard).  The audit input depends only on the puzzle,
so one `OK` per puzzle is enough.  Receipts land in `audit.d/<id>.json`, keyed by
the hash of the exact audit input, so a stale or edited puzzle is re-audited.
"""

import json
import subprocess
import time
from hashlib import sha256
from pathlib import Path

EXT = Path(__file__).resolve().parent
AUDIT_DIR = EXT / "audit.d"


def native_input(puzzle, helpers=0, node_limit=0):
    return (
        f"{puzzle.limit} {len(puzzle.seeds)} {len(puzzle.targets)} {helpers} {node_limit}\n"
        + " ".join(map(str, puzzle.seeds + puzzle.targets))
        + "\n"
    )


def ensure_audit(binary, puzzle, refresh=False, quiet=False):
    """Return the cached `OK` audit receipt, running the audit once if needed."""
    payload = native_input(puzzle)
    digest = sha256(payload.encode()).hexdigest()
    path = AUDIT_DIR / f"{puzzle.id}.json"
    if not refresh and path.exists():
        record = json.loads(path.read_text(encoding="utf8"))
        if record.get("input_sha256") == digest and record.get("status") == "OK":
            if not quiet:
                print(f"audit {puzzle.id}: cached ({record['seconds']} s when first run)",
                      flush=True)
            return record
    start = time.time()
    audit = subprocess.run([str(binary), "--audit-pairs"], input=payload, text=True,
                           capture_output=True, check=True)
    if audit.stdout.strip() != "OK":
        raise ValueError(f"{puzzle.id}: pair coverage audit failed: {audit.stdout.strip()[:80]}")
    AUDIT_DIR.mkdir(exist_ok=True)
    record = {
        "id": puzzle.id,
        "status": "OK",
        "input_sha256": digest,
        "seconds": round(time.time() - start, 1),
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf8")
    temporary.replace(path)
    if not quiet:
        print(f"audit {puzzle.id}: ran {record['seconds']} s, cached", flush=True)
    return record
