"""Ask a local model for shorter Elf Calculator windows and replay every accepted edit."""

import argparse
from collections import defaultdict
import csv
from dataclasses import dataclass
import gzip
import hashlib
from http.client import HTTPException
import json
import os
from pathlib import Path
import sqlite3
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from checkpoint import atomic_text
from elf import OPERATORS, Program, Puzzle, arithmetic, check, read_puzzles, read_submission, replay, sha256, write_submission


MODEL = "cn:hy4flash-free"
BASE_URL = "http://127.0.0.1:7863/v1"
PROMPT = """Find a strictly shorter Elf Calculator window using the supplied starting values.
Every instruction is [operator, left_register, right_register, destination_register] with zero-based indices. Read both operands before writing. Only + - * and exact / are allowed. Every result must be an integer between 1 and limit. Unlisted starting registers are undefined, but any register below registers can be written. Registers can be overwritten.
Enter with the values in start. At the end, each register in end must hold exactly its listed value. Each value in hit must be produced by at least one instruction, even if later overwritten. The existing window and its output values are given in old and values. Other registers are scratch. Try up to three direct substitutions or common subexpressions. If none works, return null promptly. A proof or exhaustive search is unnecessary.
Reply with exactly {"steps":[...]} or {"steps":null} if you cannot find a shorter window. Use JSON numbers for register indices and don't include comments.
"""


def compact(value):
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


@dataclass(frozen=True)
class Window:
    start: int
    data: dict

    @property
    def end(self):
        return self.start + len(self.data["old"])

    @property
    def key(self):
        return hashlib.sha256((PROMPT + compact(self.data)).encode()).hexdigest()


def windows(puzzle: Puzzle, program: Program, trace):
    """Select windows with room between their length and the distinct-output bound."""
    live = [0] * (len(program) + 1)
    for index in range(len(program) - 1, -1, -1):
        _, left, right, dest = program[index]
        live[index] = (live[index + 1] & ~(1 << dest)) | (1 << left) | (1 << right)

    values = [step.output for step in trace]
    hits = defaultdict(list)
    targets = set(puzzle.targets).difference(puzzle.seeds)
    state = list(puzzle.seeds) + [0] * (puzzle.registers - len(puzzle.seeds))
    states = [state.copy()]
    for index, (instruction, value) in enumerate(zip(program, values)):
        if value in targets:
            hits[value].append(index)
        state[instruction[3]] = value
        states.append(state.copy())

    for start in range(0, len(program) - 3, 2):
        for length in (4, 6, 8):
            end = start + length
            if end > len(program):
                continue
            before, after = states[start], states[end]
            must_hit = sorted(v for v, places in hits.items()
                              if start <= places[0] and places[-1] < end)
            live_out = [(r, v) for r, v in enumerate(after) if live[end] & (1 << r)]
            produced = set(must_hit) | {v for r, v in live_out if before[r] != v}
            if not 0 < len(produced) < length:
                continue
            yield (-len(produced), -length, -len(live_out)), Window(start, {
                "registers": puzzle.registers,
                "limit": puzzle.limit,
                "start": [(r, v) for r, v in enumerate(before) if v],
                "end": live_out,
                "hit": must_hit,
                "old": program[start:end],
                "values": values[start:end],
            })


def verified_edit(puzzle, program, window, content):
    lines = content.strip().splitlines()
    if len(lines) >= 3 and lines[0] in ("```", "```json") and lines[-1] == "```":
        lines = lines[1:-1]
    response = json.loads("\n".join(lines))
    if type(response) is not dict or response.keys() != {"steps"}:
        raise ValueError("expected an object with steps")
    proposal = response["steps"]
    if proposal is None:
        return None
    if type(proposal) is not list or len(proposal) >= window.end - window.start:
        raise ValueError("expected a strictly shorter instruction array")
    state = dict(window.data["start"])
    produced = set()
    replacement = []
    for row in proposal:
        if (type(row) is not list or len(row) != 4 or type(row[0]) is not str
                or row[0] not in OPERATORS or any(type(r) is not int or not 0 <= r < puzzle.registers
                                                 for r in row[1:])):
            raise ValueError("invalid instruction")
        op, left, right, dest = row
        if left not in state or right not in state:
            raise ValueError("undefined input")
        result = arithmetic(op, state[left], state[right])
        if not 1 <= result <= puzzle.limit:
            raise ValueError("value limit violated")
        state[dest] = result
        produced.add(result)
        replacement.append(tuple(row))
    if (not set(window.data["hit"]).issubset(produced)
            or any(state.get(r) != v for r, v in window.data["end"])):
        raise ValueError("window requirements not met")
    candidate = program[:window.start] + tuple(replacement) + program[window.end:]
    check(puzzle, candidate)
    return candidate


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def request_rewrite(window, key):
    body = compact({"model": MODEL, "messages": [
        {"role": "user", "content": PROMPT + compact(window.data)},
    ], "max_tokens": 8000, "stream": False})
    request = Request(BASE_URL + "/chat/completions", data=body.encode(), headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + key,
    })
    http = build_opener(ProxyHandler({}), NoRedirect())
    with http.open(request, timeout=75) as response:
        raw = response.read(262145)
    if len(raw) > 262144:
        raise ValueError("oversized model response")
    answer = json.loads(raw)
    choice = answer["choices"][0]
    usage = answer.get("usage") or {}
    return choice["message"].get("content"), choice.get("finish_reason"), usage


def open_ledger(path):
    db = sqlite3.connect(path, isolation_level="IMMEDIATE")
    db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS attempts (
            fingerprint TEXT PRIMARY KEY,
            reserved_at INTEGER NOT NULL,
            dataset TEXT NOT NULL,
            puzzle_id TEXT NOT NULL,
            status TEXT NOT NULL,
            steps INTEGER,
            candidate TEXT
        );
        CREATE INDEX IF NOT EXISTS attempts_recent ON attempts (reserved_at);
        CREATE TABLE IF NOT EXISTS usage (
            fingerprint TEXT PRIMARY KEY REFERENCES attempts(fingerprint),
            credit REAL,
            total_tokens INTEGER
        );
    """)
    return db


def reserve(db, task, dataset, identifier, daily_limit):
    """Reserve a single attempt before HTTP, including ambiguous interrupted calls."""
    now = int(time.time())
    with db:
        db.execute("BEGIN IMMEDIATE")
        recent = db.execute("SELECT count(*) FROM attempts WHERE reserved_at > ?",
                            (now - 86400,)).fetchone()[0]
        if recent >= daily_limit:
            return "budget"
        update = db.execute("INSERT OR IGNORE INTO attempts VALUES (?, ?, ?, ?, 'started', NULL, NULL)",
                            (task, now, dataset, identifier))
        return "reserved" if update.rowcount else "duplicate"


def save_attempt(db, task, status, candidate=None, usage=None):
    with db:
        db.execute("UPDATE attempts SET status=?, steps=?, candidate=? WHERE fingerprint=?",
                   (status, len(candidate) if candidate is not None else None,
                    compact(candidate) if candidate is not None else None, task))
        if type(usage) is dict:
            credit, tokens = usage.get("credit"), usage.get("total_tokens")
            db.execute("INSERT INTO usage VALUES (?, ?, ?)",
                       (task, credit if type(credit) in (int, float) else None,
                        tokens if type(tokens) is int else None))


def certified_bounds(data_hash):
    root = Path(__file__).resolve().parent / "collaboration"
    header = json.loads((root / "evidence/combined-graph-37512.json").read_bytes())
    if header["official_sha256"] != data_hash:
        return {}, {}
    with (root / "puzzle-bounds.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    lower = {row["id"]: int(row["certified_lower"]) for row in rows}
    upper = {row["id"]: int(row["best_verified_upper"]) for row in rows}
    return lower, upper


def certified_windows(data_hash):
    root = Path(__file__).resolve().parent / "collaboration/window-search"
    header = json.loads((root / "conditional-receipt.json").read_bytes())
    if header["official"] != data_hash:
        return {}
    archive = root / "conditional.jsonl.gz"
    if sha256(archive) != header["conditional_file_sha256"]:
        raise ValueError("window certificate hash mismatch")
    result = defaultdict(list)
    with gzip.open(archive, "rt", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            result[row["id"]].append((row["lower"], set(row["starts"]), set(row["goals"])))
    return result


def already_certified(window, certificates):
    start = dict(window.data["start"])
    available = set(start.values())
    goals = set(window.data["hit"]) | {v for r, v in window.data["end"] if start.get(r) != v}
    return any(lower >= len(window.data["old"]) and available <= starts and targets <= goals
               for lower, starts, targets in certificates)


def apply_saved(db, dataset, puzzles, baseline):
    programs = baseline.copy()
    by_id = {puzzle.id: puzzle for puzzle in puzzles}
    origins = {}
    for identifier, task, steps, raw in db.execute(
            "SELECT puzzle_id, fingerprint, steps, candidate FROM attempts "
            "WHERE dataset=? AND status='accepted' ORDER BY steps, fingerprint", (dataset,)):
        if identifier not in programs or steps >= len(programs[identifier]):
            continue
        candidate = tuple(tuple(row) for row in json.loads(raw))
        if check(by_id[identifier], candidate) != steps:
            raise ValueError("candidate length disagrees with ledger")
        programs[identifier] = candidate
        origins[identifier] = {"model": MODEL, "window_sha256": task, "steps": steps,
                               "previous_steps": len(baseline[identifier])}
    return programs, origins


def export(state, puzzles, programs, dataset, baseline_hash, origins):
    if not origins:
        return
    output = state / "submission.csv"
    steps = write_submission(output, puzzles, programs)
    atomic_text(state / "changes.json", json.dumps({
        "puzzles_sha256": dataset, "baseline_sha256": baseline_hash,
        "submission_sha256": sha256(output), "instructions": steps, "rows": origins,
    }, ensure_ascii=False, indent=2) + "\n")


def pending(db, puzzles, programs, bounds, known_upper, certificates=None):
    attempted = {row[0] for row in db.execute("SELECT fingerprint FROM attempts")}
    certificates = certificates or {}
    ordered = sorted(puzzles, key=lambda p: (len(programs[p.id]) - bounds.get(p.id, 0),
                                              len(programs[p.id]), p.id))
    for puzzle in ordered:
        program = programs[puzzle.id]
        if (len(program) <= bounds.get(puzzle.id, 0)
                or len(program) > known_upper.get(puzzle.id, len(program))):
            continue
        choices = sorted(windows(puzzle, program, replay(puzzle, program)),
                         key=lambda pair: pair[0], reverse=True)
        for _, window in choices:
            if window.key not in attempted and not already_certified(window, certificates.get(puzzle.id, ())):
                yield puzzle, window
                break


def run(args, db, key):
    dataset = sha256(args.puzzles)
    puzzles = read_puzzles(args.puzzles)
    bounds, known_upper = certified_bounds(dataset)
    certificates = certified_windows(dataset)
    baseline_path = args.baseline.resolve()
    if baseline_path == (args.state / "submission.csv").resolve():
        raise ValueError("baseline must be separate from the worker output")
    requests = 0
    previous = None
    while args.watch or requests < args.requests:
        baseline_hash = sha256(baseline_path)
        if baseline_hash != previous:
            baseline = read_submission(baseline_path)
            if sha256(baseline_path) != baseline_hash:
                continue
            if baseline.keys() != {puzzle.id for puzzle in puzzles}:
                raise ValueError("baseline puzzle IDs differ from the input")
            programs, origins = apply_saved(db, dataset, puzzles, baseline)
            export(args.state, puzzles, programs, dataset, baseline_hash, origins)
            previous = baseline_hash
        pause = 60
        for puzzle, window in pending(db, puzzles, programs, bounds, known_upper, certificates):
            if not args.watch and requests >= args.requests:
                return
            if sha256(baseline_path) != baseline_hash:
                pause = 0
                break
            task = window.key
            reservation = reserve(db, task, dataset, puzzle.id, args.daily_limit)
            if reservation == "budget":
                break
            if reservation == "duplicate":
                continue
            requests += 1
            program = programs[puzzle.id]
            usage = None
            try:
                answer, finish, usage = request_rewrite(window, key)
                if finish == "length":
                    candidate, status = None, "truncated"
                elif type(answer) is not str or not answer.strip():
                    candidate, status = None, "empty_reply"
                else:
                    candidate = verified_edit(puzzle, program, window, answer)
                    status = "accepted" if candidate is not None else "no_edit"
            except HTTPError as exc:
                save_attempt(db, task, f"http_{exc.code}")
                print(f"{puzzle.id}: gateway HTTP {exc.code}", flush=True)
                if exc.code in (401, 403, 404):
                    return
                pause = 120
                break
            except (URLError, OSError, HTTPException):
                save_attempt(db, task, "transport_unknown")
                print(f"{puzzle.id}: transport failure", flush=True)
                break
            except (ValueError, TypeError, KeyError, IndexError):
                save_attempt(db, task, "invalid", usage=usage)
                print(f"{puzzle.id}: invalid proposal", flush=True)
            else:
                save_attempt(db, task, status, candidate, usage)
                if candidate is not None:
                    programs, origins = apply_saved(db, dataset, puzzles, baseline)
                    export(args.state, puzzles, programs, dataset, baseline_hash, origins)
                    print(f"{puzzle.id}: {len(program)} -> {len(candidate)} ({MODEL})", flush=True)
                else:
                    print(f"{puzzle.id}: {status}", flush=True)
            if args.watch or requests < args.requests:
                time.sleep(args.delay)
        if not args.watch:
            return
        time.sleep(pause)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--puzzles", type=Path, default=Path("data/puzzles.csv"))
    parser.add_argument("--baseline", type=Path, default=Path("public-assisted/submission.csv"))
    parser.add_argument("--state", type=Path, default=Path("work/model-rewrite"))
    parser.add_argument("--watch", action="store_true", help="keep working under the daily cap")
    parser.add_argument("--requests", type=int, default=4, help="request cap for a single run")
    parser.add_argument("--daily-limit", type=int, default=24, help="global rolling 24-hour cap for this ledger")
    parser.add_argument("--delay", type=float, default=15, help="seconds between model calls")
    args = parser.parse_args()
    if args.requests < 1 or args.daily_limit < 1 or args.delay < 1:
        parser.error("requests, daily limit and delay must be at least one")
    key = os.environ.get("SANTA_GATEWAY_API_KEY")
    if not key:
        parser.error("set SANTA_GATEWAY_API_KEY before launching the worker")
    args.state.mkdir(parents=True, exist_ok=True)
    lock = sqlite3.connect(args.state / "worker.sqlite3", timeout=0)
    try:
        try:
            lock.execute("BEGIN EXCLUSIVE")
        except sqlite3.OperationalError:
            parser.error("cannot lock the state directory; check for another worker")
        db = open_ledger(args.state / "attempts.sqlite3")
        try:
            run(args, db, key)
        finally:
            db.close()
    except KeyboardInterrupt:
        pass
    finally:
        lock.close()


if __name__ == "__main__":
    main()
