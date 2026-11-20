"""Exact interpreter and file handling for the Elf Calculator."""

import argparse
import csv
import hashlib
import json
import math
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

MAX_STEPS = 4096
MAX_BYTES = 131072
OPERATORS = frozenset("+-*/")
type Instruction = tuple[str, int, int, int]
type Program = tuple[Instruction, ...]


@dataclass(frozen=True)
class Puzzle:
    id: str
    seeds: tuple[int, ...]
    targets: tuple[int, ...]
    limit: int
    registers: int = 48

    def __post_init__(self):
        if not self.id or not 1 <= self.registers <= 48:
            raise ValueError("invalid puzzle identifier or register count")
        if not 1 <= self.limit <= 10**18 or not 1 <= len(self.seeds) <= self.registers:
            raise ValueError(f"{self.id}: invalid value limit or starting values")
        if any(type(value) is not int or not 1 <= value <= self.limit
               for values in (self.seeds, self.targets) for value in values):
            raise ValueError(f"{self.id}: invalid starting or target value")


class Step(NamedTuple):
    output: int
    operator: str
    left: int
    right: int


def arithmetic(op: str, left: int, right: int) -> int:
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if op == "/":
        answer, remainder = divmod(left, right)
        if not remainder:
            return answer
        raise ValueError(f"inexact division {left}/{right}")
    raise ValueError(f"unknown operator: {op!r}")


def replay(puzzle: Puzzle, program: Program) -> list[Step]:
    if len(program) > MAX_STEPS:
        raise ValueError(f"{puzzle.id}: too many instructions")
    registers = [0] * puzzle.registers
    registers[:len(puzzle.seeds)] = puzzle.seeds
    missing = set(puzzle.targets).difference(puzzle.seeds)
    trace = []
    for index, (op, left, right, destination) in enumerate(program, 1):
        if any(type(r) is not int or not 0 <= r < puzzle.registers
               for r in (left, right, destination)):
            raise ValueError(f"{puzzle.id}: invalid register at instruction {index}")
        first, second = registers[left], registers[right]
        if not first or not second:
            raise ValueError(f"{puzzle.id}: undefined operand at instruction {index}")
        try:
            result = arithmetic(op, first, second)
        except ValueError as error:
            raise ValueError(f"{puzzle.id}: instruction {index} has {error}") from error
        if not 1 <= result <= puzzle.limit:
            raise ValueError(f"{puzzle.id}: value limit violated at instruction {index}")
        registers[destination] = result
        missing.discard(result)
        trace.append(Step(result, op, first, second))
    if missing:
        raise ValueError(f"{puzzle.id}: missing {len(missing)} targets; first is {min(missing)}")
    return trace


def check(puzzle: Puzzle, program: Program) -> int:
    return len(replay(puzzle, program))


def read_puzzles(path: str | Path) -> list[Puzzle]:
    with Path(path).open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source, strict=True)
        required = {"id", "starting_values", "targets", "value_limit", "registers"}
        if (not reader.fieldnames or not required.issubset(reader.fieldnames)
                or len(set(reader.fieldnames)) != len(reader.fieldnames)):
            raise ValueError(f"{path}: missing puzzle columns")
        seen = set()
        puzzles = []
        for row in reader:
            if None in row or any(row[key] is None for key in required):
                raise ValueError(f"{path}: malformed puzzle row {reader.line_num}")
            seeds, targets = json.loads(row["starting_values"]), json.loads(row["targets"])
            if type(seeds) is not list or type(targets) is not list:
                raise ValueError(f"{path}: starting_values and targets must be arrays")
            puzzle = Puzzle(row["id"], tuple(seeds), tuple(targets), int(row["value_limit"]),
                            int(row["registers"]))
            if puzzle.id in seen:
                raise ValueError(f"{path}: duplicate puzzle {puzzle.id}")
            seen.add(puzzle.id)
            puzzles.append(puzzle)
    if not puzzles:
        raise ValueError(f"{path}: no puzzles")
    return puzzles


def read_submission(path: str | Path) -> dict[str, Program]:
    programs = {}
    with Path(path).open(encoding="utf-8-sig", newline="") as source:
        reader = csv.reader(source, strict=True)
        if next(reader, None) != ["id", "program"]:
            raise ValueError(f"{path}: expected id,program header")
        for identifier, raw in reader:
            if not identifier or identifier in programs:
                raise ValueError(f"{path}: empty or duplicate puzzle ID {identifier!r}")
            if len(raw.encode("utf-8")) > MAX_BYTES:
                raise ValueError(f"{path}: program for {identifier} exceeds byte limit")
            instructions = json.loads(raw)
            if type(instructions) is not list or len(instructions) > MAX_STEPS:
                raise ValueError(f"{path}: invalid program array for {identifier}")
            program = []
            for row in instructions:
                if (type(row) is not list or len(row) != 4 or type(row[0]) is not str
                        or row[0] not in OPERATORS or any(type(r) is not int for r in row[1:])):
                    raise ValueError(f"{path}: malformed instruction for {identifier}")
                program.append(tuple(row))
            programs[identifier] = tuple(program)
    return programs


def score(puzzles: list[Puzzle], programs: dict[str, Program]) -> int:
    required = {puzzle.id for puzzle in puzzles}
    if required != programs.keys():
        raise ValueError(f"ID mismatch: {len(required - programs.keys())} missing, "
                         f"{len(programs.keys() - required)} unexpected")
    return sum(check(puzzle, programs[puzzle.id]) for puzzle in puzzles)


def write_submission(path: str | Path, puzzles: list[Puzzle], programs: dict[str, Program]) -> int:
    total = score(puzzles, programs)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="",
                                         dir=path.parent, delete=False) as target:
            scratch = Path(target.name)
            writer = csv.writer(target, lineterminator="\n")
            writer.writerow(("id", "program"))
            for puzzle in puzzles:
                writer.writerow((puzzle.id, json.dumps(programs[puzzle.id], separators=(",", ":"))))
        if read_submission(scratch) != programs:
            raise RuntimeError("programs changed during serialization")
        for retry in range(10):
            try:
                os.replace(scratch, path)
                break
            except PermissionError as exc:
                if getattr(exc, "winerror", None) not in (5, 32) or retry == 9:
                    raise
                time.sleep(min(.8, .04 * 2**retry))
    finally:
        if scratch is not None and scratch.exists():
            scratch.unlink()
    return total


def sha256(path: str | Path) -> str:
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("puzzles", type=Path)
    parser.add_argument("submission", type=Path)
    args = parser.parse_args()
    puzzles = read_puzzles(args.puzzles)
    programs = read_submission(args.submission)
    total = score(puzzles, programs)
    counts = sorted(map(len, programs.values()))
    print(json.dumps({
        "puzzles": len(puzzles), "instructions": total,
        "median": (counts[(len(counts) - 1) // 2] + counts[len(counts) // 2]) / 2,
        "p90": counts[math.ceil(len(counts) * 0.9) - 1],
        "longest": counts[-1], "sha256": sha256(args.submission),
    }, indent=2))


if __name__ == "__main__":
    main()
