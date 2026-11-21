"""Jointly resynthesize signed affine circuits across several observable outputs."""

import argparse
from bisect import bisect_left
import json
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from fractions import Fraction
from itertools import combinations
from math import gcd, lcm
from pathlib import Path

from solvers.construction.construct import Constructor
from elf import Program, Puzzle, arithmetic, read_puzzles, read_submission, score, sha256, write_submission
from graph import Graph, active_graph, compile_graph, first_recipes


class Infeasible(ValueError):
    """The symbolic identity cannot be realized with positive bounded registers."""


def expanded_forms(graph: Graph, coefficient_limit: int, atom_floor: int, support_limit: int,
                   depth: int = 0):
    forms = {}
    edges = {}
    layers = [{} for _ in range(depth)]

    def fold(terms, previous):
        form = defaultdict(Fraction)
        for operand, ratio in terms:
            for atom, coefficient in previous.get(operand, {operand: 1}).items():
                form[atom] += coefficient * ratio
        form = {atom: coefficient for atom, coefficient in form.items() if coefficient}
        if not form or len(form) > support_limit:
            return None
        if max(max(abs(c.numerator).bit_length(), c.denominator.bit_length()) for c in form.values()) > 34:
            return None
        return form

    for value, (op, left, right) in graph.items():
        if value <= atom_floor:
            continue
        if op in "+-":
            terms = ((left, 1), (right, -1 if op == "-" else 1))
        elif op == "*" and min(left, right) <= coefficient_limit:
            terms = ((max(left, right), min(left, right)),)
        elif op == "/" and right <= coefficient_limit:
            terms = ((left, Fraction(1, right)),)
        else:
            continue
        if depth:
            previous = {}
            for layer in layers:
                if (form := fold(terms, previous)) is not None:
                    layer[value] = form
                previous = layer
        else:
            form = fold(terms, forms)
        if form is None:
            continue
        forms[value] = form
        edges[value] = tuple(operand for operand, _ in terms if operand in forms)
    return forms, edges


def choose_groups(puzzle: Puzzle, graph: Graph, forms, edges, maximum_groups):
    consumers = defaultdict(set)
    for value, (_, left, right) in graph.items():
        for operand in {left, right}:
            consumers[operand].add(value)
    neighbors = {value: set(children) for value, children in edges.items()}
    for owner, children in edges.items():
        for child in children:
            neighbors[child].add(owner)
    targets = set(puzzle.targets)
    visited = set()
    outlets_for = {}
    groups = {}
    for value in forms:
        if value in visited:
            continue
        members = set()
        todo = [value]
        while todo:
            node = todo.pop()
            if node not in members:
                members.add(node)
                todo.extend(neighbors[node] - members)
        visited.update(members)
        outlets = tuple(sorted(node for node in members if node in targets or consumers[node] - members))
        for node in outlets:
            outlets_for[node] = members
        if 2 <= len(outlets) <= 16:
            groups[outlets] = members

    # Separate connected regions may have the same signed dependencies on
    # external atoms, even when the original circuits share no operations.
    participants = defaultdict(set)
    for outlet in outlets_for:
        for first, second in combinations(sorted(forms[outlet]), 2):
            participants[first, second].add(outlet)
    for outputs in participants.values():
        if 2 <= len(outputs) <= 16:
            group = tuple(sorted(outputs))
            groups.setdefault(group, set().union(*(outlets_for[out] for out in group)))
    ranked = sorted(groups.items(), key=lambda item: (
        -(sum(len(forms[out]) - 1 for out in item[0]) + len(item[0])),
        len(item[1]), item[0],
    ))
    yield from ranked[:maximum_groups]


def normalize(terms):
    common = lcm(*(coefficient.denominator for _, coefficient in terms))
    ints = [int(coefficient * common) for _, coefficient in terms]
    divisor = gcd(*ints)
    if ints[0] < 0:
        divisor = -divisor
    return tuple((atom, n // divisor) for (atom, _), n in zip(terms, ints))


def row_cost(row):
    return max(0, len(row) - 1) + sum(abs(coefficient) != 1 for coefficient in row.values())


def shared_patterns(rows):
    patterns = Counter()
    for row in rows.values():
        for first, second in combinations(sorted(row), 2):
            terms = ((first, row[first]), (second, row[second]))
            exact = normalize(terms)
            patterns[exact] += 1
            pattern = (terms[0][0], 1), (terms[1][0], 1 if terms[0][1] * terms[1][1] > 0 else -1)
            if pattern != exact:
                patterns[pattern] += 1
    for first, second in combinations(rows.values(), 2):
        proportional = defaultdict(list)
        for atom in sorted(first.keys() & second.keys()):
            proportional[first[atom] / second[atom]].append((atom, first[atom]))
        for terms in proportional.values():
            if len(terms) >= 3:
                patterns[normalize(terms)] += 2
    for pattern, occurrences in patterns.items():
        if occurrences >= 2:
            yield pattern


def substitute(rows, pattern, helper):
    updated = rows.copy()
    count = 0
    for output, row in rows.items():
        if not all(atom in row for atom, _ in pattern):
            continue
        ratios = [row[atom] / coefficient for atom, coefficient in pattern]
        if min(ratios) > 0:
            scale = min(ratios)
        elif max(ratios) < 0:
            scale = max(ratios)
        else:
            continue
        updated_row = row.copy()
        for atom, coefficient in pattern:
            updated_row[atom] -= coefficient * scale
        updated_row[helper] = updated_row.get(helper, 0) + scale
        updated[output] = {atom: coefficient for atom, coefficient in updated_row.items() if coefficient}
        count += 1
    return updated, count


def basis_shifts(rows, available):
    """Look for exact base changes a = k*b ± r among available opaque atoms."""
    result = rows
    replaced = set()
    for _ in range(3):
        atoms = sorted(set().union(*result.values()) - replaced)
        possibilities = []
        prior_cost = sum(map(row_cost, result.values()))
        before = Counter(atom for row in result.values() for atom in row)
        old_reuse = sum(count * (count - 1) for count in before.values())
        for atom in atoms:
            for scale in (1, 2, 3, 4, 8):
                center = bisect_left(atoms, atom // scale)
                for basis in atoms[max(0, center - 3):center + 4]:
                    residue = atom - scale * basis
                    if basis >= atom or (residue and abs(residue) not in available):
                        continue
                    if abs(residue) >= atom:
                        continue
                    adjusted = {}
                    for output, row in result.items():
                        if atom not in row:
                            adjusted[output] = row
                            continue
                        candidate = row.copy()
                        factor = candidate.pop(atom)
                        candidate[basis] = candidate.get(basis, 0) + factor * scale
                        if residue:
                            magnitude = abs(residue)
                            candidate[magnitude] = candidate.get(magnitude, 0) + (
                                factor if residue > 0 else -factor)
                        adjusted[output] = {a: c for a, c in candidate.items() if c}
                    cost = prior_cost - sum(map(row_cost, adjusted.values()))
                    frequencies = Counter(a for row in adjusted.values() for a in row)
                    reuse = sum(count * (count - 1) for count in frequencies.values()) - old_reuse
                    if cost > 0 or (cost == 0 and reuse > 0):
                        possibilities.append((cost, reuse, -abs(residue), atom, adjusted))
        if not possibilities:
            break
        _, _, _, atom, result = max(possibilities, key=lambda option: option[:4])
        replaced.add(atom)
    return result


class Builder:
    def __init__(self, puzzle: Puzzle, available: set[int]):
        self.puzzle = puzzle
        self.solver = Constructor(puzzle, 64, balanced=True, indirect=True)
        self.solver.known.update(available)

    def clone(self):
        duplicate = Builder(self.puzzle, self.solver.known)
        duplicate.solver.graph = self.solver.graph.copy()
        return duplicate

    def emit(self, op, left, right):
        if left not in self.solver.known or right not in self.solver.known:
            raise Infeasible("operand unavailable")
        out = arithmetic(op, left, right)
        if not 1 <= out <= self.puzzle.limit:
            raise Infeasible("intermediate outside legal register range")
        self.solver.add(out, (op, left, right))
        return out

    def scale(self, value, coefficient):
        coefficient = abs(Fraction(coefficient))
        result = value * coefficient
        if result.denominator != 1 or not 1 <= result <= self.puzzle.limit:
            raise Infeasible("nonintegral or oversized scaled term")
        if result in self.solver.known:
            return int(result)
        if coefficient.denominator > 1:
            self.solver.constant(coefficient.denominator)
            value = self.emit("/", value, coefficient.denominator)
        if coefficient.numerator == 2:
            return self.emit("+", value, value)
        if coefficient.numerator > 1:
            self.solver.constant(coefficient.numerator)
            value = self.emit("*", value, coefficient.numerator)
        return value

    def combine(self, terms, preference):
        terms = list(terms)
        known = self.solver.known
        while len(terms) > 1:
            options = []
            for i, j in combinations(range(len(terms)), 2):
                left, right = terms[i], terms[j]
                value = left + right
                if abs(value) <= self.puzzle.limit:
                    options.append((abs(value) not in known and value != 0,
                                    left * right > 0 if preference else False, abs(value), i, j))
            if not options:
                raise Infeasible("no signed grouping fits the value limit")
            _, _, _, i, j = min(options)
            right, left = terms.pop(j), terms.pop(i)
            out = left + right
            if out:
                if left * right > 0:
                    self.emit("+", abs(left), abs(right))
                else:
                    self.emit("-", max(abs(left), abs(right)), min(abs(left), abs(right)))
                terms.append(out)
        return terms[0] if terms else 0

    def realize(self, form, denominator_late, group_coefficients, preference):
        denominator = lcm(*(coefficient.denominator for coefficient in form.values())) if denominator_late else 1
        buckets = defaultdict(list)
        for atom, coefficient in form.items():
            positive = atom if coefficient > 0 else -atom
            buckets[abs(coefficient * denominator)].append(positive)
        terms = []
        for coefficient, values in sorted(buckets.items()):
            grouped = [self.combine(values, preference)] if group_coefficients else values
            for value in grouped:
                if value:
                    result = self.scale(abs(value), coefficient)
                    terms.append(result if value > 0 else -result)
        numerator = self.combine(terms, preference)
        if numerator <= 0:
            raise Infeasible("nonpositive output")
        if denominator == 1:
            return numerator
        self.solver.constant(denominator)
        return self.emit("/", numerator, denominator)

    def shortest_realization(self, output, form, preference):
        best = None
        common = lcm(*(coefficient.denominator for coefficient in form.values()))
        integer_factor = gcd(*(int(coefficient * common) for coefficient in form.values()))
        scale = Fraction(integer_factor, common)
        options = [(form, Fraction(1), late, grouping)
                   for late, grouping in ((False, True), (False, False), (True, True), (True, False))]
        if scale != 1 and scale > 0:
            primitive = {atom: coefficient / scale for atom, coefficient in form.items()}
            options.append((primitive, scale, False, True))
        for chosen, factor, denominator_late, group_coefficients in options:
            candidate = self.clone()
            try:
                result = candidate.realize(chosen, denominator_late, group_coefficients, preference)
                if candidate.scale(result, factor) != output:
                    continue
            except ValueError:
                continue
            if best is None or len(candidate.solver.graph) < len(best.solver.graph):
                best = candidate
        return best


def one_proposal(puzzle, graph, forms, outlets, members, use_sharing, preference, shift):
    # The old DAG remains available as a fallback. Expressions are built
    # from opaque boundary atoms without treating replaced outputs as free.
    rows = {output: forms[output] for output in outlets}
    boundary = set().union(*rows.values())
    blocked = set(outlets)
    for value, (_, left, right) in graph.items():
        if left in blocked or right in blocked:
            blocked.add(value)
    if boundary & (blocked - set(outlets)):
        return None
    available = set(puzzle.seeds) | (graph.keys() - members - blocked) | (boundary - blocked)
    if shift:
        rows = basis_shifts(rows, available)
    builder = Builder(puzzle, available)
    if use_sharing:
        for _ in range(8):
            alternatives = []
            initial = sum(map(row_cost, rows.values()))
            for motif in shared_patterns(rows):
                summation = sum(atom * coefficient for atom, coefficient in motif)
                helper = abs(summation)
                if not 1 <= helper <= puzzle.limit or helper in outlets or helper in dict(motif):
                    continue
                form = tuple((atom, coefficient if summation > 0 else -coefficient)
                             for atom, coefficient in motif)
                reduced, support = substitute(rows, form, helper)
                if support < 2:
                    continue
                estimated = initial - sum(map(row_cost, reduced.values()))
                if helper not in builder.solver.known:
                    estimated -= len(form) - 1 + sum(abs(c) != 1 for _, c in form)
                if estimated >= 0:
                    alternatives.append((estimated, support, helper, form, reduced))
            alternatives.sort(key=lambda choice: choice[:4], reverse=True)
            used = False
            for _, _, helper, form, reduced in alternatives[:5]:
                if reduced == rows:
                    continue
                if helper in builder.solver.known:
                    rows = reduced
                    used = True
                    break
                draft = builder.shortest_realization(helper, {atom: Fraction(c) for atom, c in form}, preference)
                if draft is not None:
                    rows, builder = reduced, draft
                    used = True
                    break
            if not used:
                break

    for output in (value for value in graph if value in rows):
        form = rows[output]
        if any(atom not in builder.solver.known for atom in form):
            return None
        realized = builder.shortest_realization(output, form, preference)
        if realized is None:
            return None
        builder = realized
    return graph | builder.solver.graph


def repair(puzzle: Puzzle, incumbent: Program, group_count: int, schedule: int) -> Program:
    best = incumbent
    for coefficient_limit, atom_floor, depth in ((128, 12, 0), (32768, 128, 0),
                                                 (1048576, 256, 0), (1048576, 32, 3)):
        graph = active_graph(puzzle, first_recipes(puzzle, best))
        forms, edges = expanded_forms(graph, coefficient_limit, atom_floor, support_limit=8,
                                      depth=depth)
        for outlets, members in choose_groups(puzzle, graph, forms, edges, group_count):
            if len(members) <= len(outlets):
                continue
            for share, preference, shift in ((True, 0, False), (True, 1, False), (False, 1, False),
                                              (True, 1, True)):
                candidate = one_proposal(puzzle, graph, forms, outlets, members, share, preference,
                                         shift)
                if candidate is None:
                    continue
                try:
                    active = active_graph(puzzle, candidate)
                except (KeyError, ValueError):
                    continue
                if len(active) >= len(best):
                    continue
                compiled = compile_graph(puzzle, candidate, recompute=True, schedule_width=schedule)
                if compiled is not None and len(compiled) < len(best):
                    best = compiled
    return best


def worker(task):
    puzzle, incumbent, groups, schedule = task
    return puzzle.id, repair(puzzle, incumbent, groups, schedule)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("puzzles", type=Path)
    parser.add_argument("incumbent", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--groups", type=int, default=6)
    parser.add_argument("--schedule", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    puzzles = read_puzzles(args.puzzles)
    before = sha256(args.incumbent)
    old = read_submission(args.incumbent)
    if sha256(args.incumbent) != before:
        raise RuntimeError("incumbent changed while loading")
    initial = score(puzzles, old)
    selection = puzzles[::max(1, len(puzzles) // args.limit)][:args.limit] if args.limit else puzzles
    result = old.copy()
    changes = []
    start = time.monotonic()
    tasks = ((p, old[p.id], args.groups, args.schedule) for p in selection)
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        for i, (key, option) in enumerate(pool.map(worker, tasks, chunksize=2), 1):
            if len(option) < len(old[key]):
                result[key] = option
                changes.append((key, len(old[key]), len(option)))
            if i % 25 == 0:
                print(i, len(changes), sum(old - new for _, old, new in changes),
                      round(time.monotonic() - start, 1), flush=True)
    final = write_submission(args.output, puzzles, result)
    record = {"incumbent": str(args.incumbent.resolve()), "incumbent_sha256": before,
              "output": str(args.output.resolve()), "output_sha256": sha256(args.output),
              "initial": initial, "final": final, "changes": changes, "puzzles": len(selection),
              "seconds": round(time.monotonic() - start, 3)}
    args.output.with_suffix(".json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"{initial} -> {final}, {len(changes)} improved over {len(selection)} puzzles", flush=True)


if __name__ == "__main__":
    main()
