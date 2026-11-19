"""Recombine whole clusters of targets that share different donor helpers."""

import argparse
import json
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from elf import Program, Puzzle, read_puzzles, read_submission, score, sha256, write_submission
from graph import Graph, active_graph, compile_graph, first_recipes


def members(mask):
    while mask:
        bit = mask & -mask
        yield bit.bit_length() - 1
        mask ^= bit


def database(puzzle: Puzzle, graphs: list[Graph]):
    targets = sorted(set(puzzle.targets) - set(puzzle.seeds))
    bit = {value: 1 << index for index, value in enumerate(sorted(set().union(*graphs)))}
    closures = []
    groups = {1 << i for i in range(len(targets))}
    for graph in graphs:
        recipes = {value: active_graph(puzzle, graph, (value,)) for value in targets}
        owner = {}
        masks = []
        for i, value in enumerate(targets):
            closure = recipes[value]
            masks.append(sum(bit[node] for node in closure))
            for node in closure:
                owner[node] = owner.get(node, 0) | (1 << i)
        for shared in owner.values():
            count = shared.bit_count()
            if 2 <= count <= 10:
                groups.add(shared)
            if 4 <= count <= 8:
                for i in members(shared):
                    groups.add(shared ^ (1 << i))
        closures.append(masks)
    return targets, bit, closures, groups


def merge_span(closures, indices):
    union = 0
    for index in indices:
        union |= closures[index]
    return union


def expand_donor(graph, available, roots):
    """Follow donor dependencies only until a value already retained is hit."""
    needed = 0
    pending = list(roots)
    while pending:
        value = pending.pop()
        if (available | needed) & value or value not in graph:
            continue
        needed |= value
        pending.extend(graph[value])
    return needed


def variants(puzzle, base_graph, alternatives, trial_count):
    graphs = [base_graph, *alternatives]
    targets, bit, closures, groups = database(puzzle, graphs)
    all_targets = (1 << len(targets)) - 1
    original = closures[0]
    original_full = merge_span(original, range(len(targets)))
    parents = [{bit[value]: (bit.get(left, 0), bit.get(right, 0))
                for value, (_, left, right) in graph.items()} for graph in graphs]
    target_bits = [bit[value] for value in targets]
    evaluated = []
    for group in groups:
        outside_indices = tuple(members(all_targets ^ group))
        retained = merge_span(original, outside_indices)
        deleted = (original_full & ~retained).bit_count()
        included = tuple(i for i in members(group) if not (retained & target_bits[i]))
        if deleted <= len(included):
            continue
        for donor in range(1, len(graphs)):
            replacement = expand_donor(parents[donor], retained, (target_bits[i] for i in included))
            added = replacement.bit_count()
            if added <= deleted + 1:
                evaluated.append((deleted - added, group, retained, ((donor, replacement),)))
        if len(included) < 2:
            continue
        extended = retained
        partial = []
        for i in sorted(included, key=lambda i: -(original[i] & ~retained).bit_count()):
            if extended & target_bits[i]:
                continue
            donor = min(
                (expand_donor(parents[d], extended, (target_bits[i],)).bit_count(), d)
                for d in range(len(graphs))
            )[1]
            added_values = expand_donor(parents[donor], extended, (target_bits[i],))
            partial.append((donor, added_values))
            extended |= added_values
        added = (extended & ~retained).bit_count()
        if added <= deleted + 1:
            evaluated.append((deleted - added, group, retained, tuple(partial)))
    evaluated.sort(reverse=True)
    seen = set()
    for _, _, retained, replacements in evaluated:
        if (retained, replacements) in seen:
            continue
        seen.add((retained, replacements))
        proposed = {value: recipe for value, recipe in base_graph.items() if bit[value] & retained}
        for donor, values in replacements:
            for value, recipe in graphs[donor].items():
                if bit[value] & values:
                    proposed.setdefault(value, recipe)
        yield proposed
        if len(seen) >= trial_count:
            break


def optimize(puzzle: Puzzle, incumbent: Program, donors: tuple[Program, ...],
             rounds: int, trials: int, schedule: int) -> Program:
    if len(incumbent) <= len(set(puzzle.targets) - set(puzzle.seeds)):
        return incumbent
    alternatives = []
    seen = {incumbent}
    graph_hashes = {frozenset(active_graph(puzzle, first_recipes(puzzle, incumbent)).items())}
    for program in donors:
        if program not in seen:
            seen.add(program)
            graph = active_graph(puzzle, first_recipes(puzzle, program))
            fingerprint = frozenset(graph.items())
            if fingerprint not in graph_hashes:
                graph_hashes.add(fingerprint)
                alternatives.append(graph)
    best = incumbent
    for _ in range(rounds):
        start = best
        graph = active_graph(puzzle, first_recipes(puzzle, start))
        for proposal in variants(puzzle, graph, alternatives, trials):
            try:
                active = active_graph(puzzle, proposal)
            except (KeyError, ValueError):
                continue
            if len(active) >= len(best):
                continue
            candidate = compile_graph(puzzle, active, recompute=True, schedule_width=schedule)
            if candidate is not None and len(candidate) < len(best):
                best = candidate
        if best == start:
            break
    return best


def run_puzzle(task):
    puzzle, incumbent, donors, settings = task
    return puzzle.id, optimize(puzzle, incumbent, donors, *settings)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("puzzles", type=Path)
    parser.add_argument("incumbent", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--donor", nargs="+", type=Path, required=True)
    parser.add_argument("--puzzles-limit", type=int, default=0)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--trials", type=int, default=30)
    parser.add_argument("--schedule", type=int, default=4)
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    puzzles = read_puzzles(args.puzzles)

    def load(path):
        digest = sha256(path)
        programs = read_submission(path)
        if digest != sha256(path):
            raise RuntimeError(f"reference changed while reading: {path}")
        total = score(puzzles, programs)
        return programs, {"path": str(path.resolve()), "sha256": digest, "steps": total}

    incumbent, source = load(args.incumbent)
    donors = [load(path) for path in args.donor]
    selected = puzzles
    if args.puzzles_limit:
        selected = puzzles[::max(1, len(puzzles) // args.puzzles_limit)][:args.puzzles_limit]
    settings = args.rounds, args.trials, args.schedule
    tasks = ((p, incumbent[p.id], tuple(program[p.id] for program, _ in donors), settings)
             for p in selected)
    result = incumbent.copy()
    changes = []
    started = time.monotonic()
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        for i, (identifier, candidate) in enumerate(pool.map(run_puzzle, tasks, chunksize=2), 1):
            if len(candidate) < len(incumbent[identifier]):
                result[identifier] = candidate
                changes.append((identifier, len(incumbent[identifier]), len(candidate)))
            if i % 100 == 0:
                print(i, len(changes), sum(old - new for _, old, new in changes),
                      round(time.monotonic() - started, 1), flush=True)
    final = write_submission(args.output, puzzles, result)
    manifest = {
        "incumbent": source,
        "donors": [metadata for _, metadata in donors],
        "output": {"path": str(args.output.resolve()), "sha256": sha256(args.output), "steps": final},
        "selected": len(selected),
        "changes": changes,
        "seconds": round(time.monotonic() - started, 3),
    }
    args.output.with_suffix(".json").write_text(json.dumps(manifest, indent=2) + "\n",
                                                encoding="utf-8")
    print(f"{source['steps']} -> {final} on {len(selected)} puzzles, {len(changes)} rows improved")


if __name__ == "__main__":
    main()
