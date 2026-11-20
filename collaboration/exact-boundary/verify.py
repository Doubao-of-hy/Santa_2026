"""Replay the two scored_0649 programs and their shared arithmetic boundary."""
import argparse
import csv
import hashlib
import json
import subprocess
from pathlib import Path


def read_row(path, identifier):
    with path.open(encoding="utf-8-sig", newline="") as source:
        rows = [row for row in csv.DictReader(source) if row["id"] == identifier]
    assert len(rows) == 1, (identifier, len(rows))
    return rows[0]


def arithmetic(op, a, b):
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    assert op == "/" and a % b == 0, (op, a, b)
    return a // b


def replay(program, seeds, targets, limit, register_count):
    registers = [None] * register_count
    registers[:len(seeds)] = seeds
    seen = set(seeds)
    trace = {}
    outputs = []
    assert len(program) <= 4096
    assert len(json.dumps(program, separators=(",", ":")).encode()) <= 131072
    for op, left, right, destination in program:
        assert all(type(i) is int and 0 <= i < register_count for i in (left, right, destination))
        a, b = registers[left], registers[right]
        assert a is not None and b is not None
        value = arithmetic(op, a, b)
        assert 1 <= value <= limit
        registers[destination] = value
        outputs.append(value)
        if value not in seen:
            trace[value] = (op, min(a, b), max(a, b)) if op in "+*" else (op, a, b)
            seen.add(value)
    assert set(targets) <= seen
    return outputs, trace


def row_hash(program):
    return hashlib.sha256(json.dumps(program, separators=(",", ":")).encode()).hexdigest()


def native(exe, seeds, goals, limit, helper_budget, node_cap):
    request = [limit, len(seeds), len(goals), helper_budget, node_cap, *seeds, *goals]
    process = subprocess.run(
        [str(exe.resolve()), "pair", "0", "1", "0", "1", "0", "1"],
        input=" ".join(map(str, request)) + "\n", text=True, capture_output=True, check=True,
    )
    lines = process.stdout.splitlines()
    status, nodes, _, _ = lines[0].split()
    witness = list(map(int, lines[1].split())) if status == "FOUND" else []
    return status, int(nodes), witness


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("puzzles", type=Path)
    parser.add_argument("--solver", type=Path)
    parser.add_argument("--public-reference", type=Path, help="best_programs.csv from Asterios release 99")
    args = parser.parse_args()
    case = json.loads(Path(__file__).with_name("case.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(args.puzzles.read_bytes()).hexdigest() == case["official_csv_sha256"], "Expected original official puzzles.csv"
    row = read_row(args.puzzles, case["id"])
    seeds = json.loads(row["starting_values"])
    targets = json.loads(row["targets"])
    limit, registers = int(row["value_limit"]), int(row["registers"])
    assert seeds == [6, 29] and len(targets) == 32 and registers == 48 and limit == case["search"]["search_value_limit"]
    results = {}
    for name in ("before", "after"):
        program = case[name]
        assert row_hash(program) == case[name + "_row_sha256"]
        values, graph = replay(program, seeds, targets, limit, registers)
        assert len(graph) == len(values), "This case has one physical instruction per distinct new value"
        results[name] = graph
    before, after = results["before"], results["after"]
    assert (len(before), len(after)) == (119, 118)

    # Recover the old subgraph from the old physical instructions and find every use outside it.
    head = {}
    available = set(seeds)
    for v, recipe in before.items():
        if v <= case["head_ceiling"] and set(recipe[1:]) <= available:
            head[v] = recipe
            available.add(v)
    outside = {v: recipe for v, recipe in before.items() if v not in head}
    boundary = (set(head) & set(targets)) | {x for recipe in outside.values() for x in recipe[1:] if x in head}
    assert sorted(boundary) == case["boundary"]
    assert sorted(set(head) - boundary) == case["original_boundary_helpers"]
    witness, replacement = replay(case["boundary_program"], seeds, boundary, limit, registers)
    assert seeds + witness == case["values_in_witness_order"]
    assert sorted(set(witness) - boundary) == case["replacement_boundary_helpers"]
    assert not (outside.keys() & replacement.keys())
    assert after == outside | replacement
    print(f"{case['id']}: {len(targets)} official targets, {len(before)} -> {len(after)} instructions")
    print(f"{len(boundary)} boundary values: {len(head)} -> {len(replacement)} instructions; {len(outside)} outside recipes match")

    if args.public_reference:
        ref = read_row(args.public_reference, case["id"])
        program = json.loads(ref["program"])
        provenance = case["provenance"]
        assert ref["source"] == provenance["upstream_credit"]
        assert len(program) == int(ref["instructions"]) == provenance["public_reference_steps"]
        assert row_hash(program) == provenance["public_reference_row_sha256"]
        replay(program, seeds, targets, limit, registers)
        print(f"Public reference: {len(program)} instructions, credited to {ref['source']}")
    if args.solver:
        for budget, expected, _ in case["search"]["observed"]:
            status, nodes, sequence = native(args.solver, seeds, sorted(boundary), limit, budget, case["search"]["node_budget"])
            assert status == expected
            if status == "FOUND":
                assert sequence == case["values_in_witness_order"]
            print(f"Fixed boundary and helper budget {budget}: {status}, {nodes} search nodes")


if __name__ == "__main__":
    if not __debug__:
        raise SystemExit("Run without -O to enable replay checks")
    main()
