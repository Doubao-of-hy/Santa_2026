"""Represent a straight-line program by arithmetic values and compile it to registers."""

import heapq
import random
from collections import Counter, defaultdict, deque

from elf import Program, Puzzle, check, replay

type Recipe = tuple[str, int, int]
type Graph = dict[int, Recipe]


def recipes_from(puzzle: Puzzle, program: Program) -> dict[int, set[Recipe]]:
    seeds = set(puzzle.seeds)
    recipes = defaultdict(set)
    for value, op, left, right in replay(puzzle, program):
        if value in seeds or value in (left, right):
            continue
        if op in "+*" and left > right:
            left, right = right, left
        recipes[value].add((op, left, right))
    return recipes


def first_recipes(puzzle: Puzzle, program: Program) -> Graph:
    seen = set(puzzle.seeds)
    graph = {}
    for value, op, left, right in replay(puzzle, program):
        if value not in seen:
            seen.add(value)
            graph[value] = op, left, right
    return graph


def active_graph(puzzle: Puzzle, recipes: Graph, targets=None, operand_priority=None) -> Graph:
    # Iterative DFS avoids the recursion limit for long instruction chains.
    seeds = set(puzzle.seeds)
    active = {}
    visiting = set()
    for target in puzzle.targets if targets is None else targets:
        stack = [(target, False)]
        while stack:
            value, ready = stack.pop()
            if value in seeds or value in active:
                continue
            if ready:
                visiting.remove(value)
                active[value] = recipes[value]
                continue
            if value in visiting:
                raise ValueError("arithmetic graph has a cycle")
            visiting.add(value)
            stack.append((value, True))
            _, left, right = recipes[value]
            if operand_priority is not None and operand_priority[right] > operand_priority[left]:
                left, right = right, left
            stack.append((right, False))
            if left != right:
                stack.append((left, False))
    return active


def _target_orders(puzzle: Puzzle, graph: Graph, width: int):
    """Keep target orders whose prefixes expose few values to unfinished work."""
    targets = tuple(dict.fromkeys(t for t in puzzle.targets if t not in puzzle.seeds))
    bits = {value: 1 << index for index, value in
            enumerate(dict.fromkeys((*puzzle.seeds, *graph)))}
    closures = {seed: bits[seed] for seed in puzzle.seeds}
    seed_bits = 0
    for seed in puzzle.seeds:
        seed_bits |= bits[seed]
    for value, (_, left, right) in graph.items():
        closures[value] = bits[value] | closures[left] | closures[right]
    target_specs = [(bits[value], closures[value], 1 << index, value)
                    for index, value in enumerate(targets)]
    groups = defaultdict(int)
    for value, (_, left, right) in graph.items():
        membership = 0
        for _, closure, target_bit, _ in target_specs:
            if closure & bits[value]:
                membership |= target_bit
        groups[membership] |= bits[left] | bits[right]
    max_mask = (1 << len(targets)) - 1
    beam = [(0, 0, seed_bits, ())]
    complete = []
    for _ in targets:
        next_states = {}
        for peak, _, computed, order in beam:
            for bit, closure, _, target in target_specs:
                if computed & bit:
                    continue
                combined = computed | closure
                covered = 0
                for member, _, pattern, _ in target_specs:
                    if combined & member:
                        covered |= pattern
                needed = 0
                for pattern, inputs in groups.items():
                    if not pattern & covered:
                        needed |= inputs
                boundary = (combined & needed).bit_count()
                rank = (max(peak, boundary), boundary, combined, (*order, target))
                if covered == max_mask:
                    complete.append(rank)
                elif combined not in next_states or rank < next_states[combined]:
                    next_states[combined] = rank
        beam = heapq.nsmallest(width, next_states.values())
        if not beam:
            break
    return [rank[3] for rank in heapq.nsmallest(min(width, 4), complete)]


def _operand_pressure(puzzle: Puzzle, graph: Graph) -> dict[int, int]:
    pressure = dict.fromkeys(puzzle.seeds, 1)
    for value, (_, left, right) in graph.items():
        a, b = pressure[left], pressure[right]
        pressure[value] = max(a, b) + int(a == b and left != right)
    return pressure


def _operation_order(puzzle: Puzzle, graph: Graph, width: int) -> Graph | None:
    """Search instruction orders while accounting for the exact live-value set."""
    values = list(graph)
    seeds = list(dict.fromkeys(puzzle.seeds))
    indexes = {value: index for index, value in enumerate(values + seeds)}
    operands = [tuple({indexes[left], indexes[right]}) for _, left, right in graph.values()]
    count = len(values)
    dependencies = [sum(1 << i for i in parents if i < count) for parents in operands]
    consumers = [0] * len(indexes)
    successors = [[] for _ in values]
    for index, parents in enumerate(operands):
        for parent in parents:
            consumers[parent] |= 1 << index
            if parent < count:
                successors[parent].append(index)
    initial_ready = sum(1 << i for i, mask in enumerate(dependencies) if not mask)
    initial_live = sum(1 << i for i in range(count, len(indexes)) if consumers[i])
    beam = [(0, initial_ready, initial_live, initial_live.bit_count(), None)]
    for _ in values:
        best = {}
        for done, ready, live, peak, trace in beam:
            choices = ready
            while choices:
                bit = choices & -choices
                choices ^= bit
                node = bit.bit_length() - 1
                completed = done | bit
                kept = live
                for parent in operands[node]:
                    if not consumers[parent] & ~completed:
                        kept &= ~(1 << parent)
                if kept.bit_count() >= puzzle.registers:
                    continue
                if consumers[node]:
                    kept |= bit
                available = ready ^ bit
                for successor in successors[node]:
                    if not dependencies[successor] & ~completed:
                        available |= 1 << successor
                occupancy = kept.bit_count()
                next_peak = max(peak, occupancy)
                before = best.get(completed)
                if before is None or next_peak < before[3]:
                    best[completed] = (completed, available, kept, next_peak, (node, trace))
        if not best:
            return None
        beam = heapq.nsmallest(width, best.values(),
                              key=lambda state: (state[2].bit_count(), state[3],
                                                 -state[1].bit_count(), state[0]))
    trace = beam[0][4]
    order = []
    while trace is not None:
        node, trace = trace
        order.append(values[node])
    return {value: graph[value] for value in reversed(order)}


def _allocate(puzzle: Puzzle, graph: Graph, targets_first: bool, random_seed: int,
              fixed_order: bool = False) -> Program | None:
    if len(graph) > 4096:
        return None
    pending = {}
    successors = defaultdict(list)
    uses = Counter()
    for output, (_, left, right) in graph.items():
        inputs = {left, right}
        pending[output] = sum(value in graph for value in inputs)
        for source in inputs:
            uses[source] += 1
            successors[source].append(output)
    binding = {}
    for index, value in enumerate(puzzle.seeds):
        if uses[value] and value not in binding:
            binding[value] = index
    occupied = set(binding.values())
    free = [i for i in range(puzzle.registers) if i not in occupied]
    heapq.heapify(free)
    ready = {value for value in graph if not pending[value]}
    targets = set(puzzle.targets)
    rng = random.Random(random_seed)
    tie_order = {value: rng.random() if random_seed else -index
                 for index, value in enumerate(graph)}

    def priority(output):
        _, left, right = graph[output]
        freed = (uses[left] == 1) + (right != left and uses[right] == 1)
        retained = uses[output] > 0
        unblocked = sum(pending[next_value] == 1 for next_value in successors[output])
        return (max(0, 1 - freed), retained - freed,
                targets_first and output not in targets, -unblocked, -tie_order[output])

    instructions = []
    ordered = iter(graph)
    while ready:
        value = next(ordered) if fixed_order else min(ready, key=priority)
        ready.remove(value)
        op, left, right = graph[value]
        a, b = binding[left], binding[right]
        for source in {left, right}:
            uses[source] -= 1
            if not uses[source]:
                heapq.heappush(free, binding.pop(source))
        if not free:
            return None
        dest = heapq.heappop(free)
        instructions.append((op, a, b, dest))
        if uses[value]:
            binding[value] = dest
        else:
            heapq.heappush(free, dest)
        for child in successors[value]:
            pending[child] -= 1
            if not pending[child]:
                ready.add(child)
    if len(instructions) != len(graph):
        raise ValueError("failed to schedule complete arithmetic graph")
    return tuple(instructions)


def _rematerialize(puzzle: Puzzle, graph: Graph, mode: str) -> Program | None:
    seeds = set(puzzle.seeds)
    binding = {}
    positions = defaultdict(deque)
    for index, (_, left, right) in enumerate(graph.values()):
        for value in {left, right}:
            positions[value].append(index)
    for index, value in enumerate(puzzle.seeds):
        if value in positions and value not in binding:
            binding[value] = index
    free = set(range(puzzle.registers)).difference(binding.values())
    instructions = []
    costs = {seed: 0 for seed in seeds}
    for value, (_, left, right) in graph.items():
        costs[value] = 1 + costs[left] + (costs[right] if right != left else 0)
    position = 0

    def missing_cost(value):
        missing = {value}
        pending = list(graph[value][1:])
        while pending and len(missing) < 12:
            operand = pending.pop()
            if operand not in binding and operand not in missing:
                missing.add(operand)
                pending.extend(graph[operand][1:])
        return len(missing)

    def save(value, op, left, right, pinned):
        a, b = binding[left], binding[right]
        if free:
            destination = free.pop()
        else:
            candidates = binding.keys() - seeds - pinned
            if not candidates:
                raise OverflowError

            def priority(candidate):
                if not positions[candidate]:
                    return (1, 0, 0)
                wait = positions[candidate][0] - position + 1
                if mode == "literal":
                    effort = 1
                elif mode == "dynamic":
                    effort = missing_cost(candidate)
                else:
                    effort = costs[candidate]
                return (0, wait / effort, -effort)

            evicted = max(candidates, key=priority)
            destination = binding.pop(evicted)
        instructions.append((op, a, b, destination))
        if len(instructions) > 4096:
            raise OverflowError
        binding[value] = destination

    def require(value, pinned):
        if value in binding:
            return
        op, left, right = graph[value]
        first, second = sorted((left, right), key=lambda operand: -costs[operand])
        require(first, pinned)
        require(second, pinned | {first})
        save(value, op, left, right, pinned)

    try:
        for position, (value, (_, left, right)) in enumerate(graph.items()):
            for operand in {left, right}:
                if positions[operand].popleft() != position:
                    raise RuntimeError("graph use order is inconsistent")
            require(value, set())
        return tuple(instructions)
    except (OverflowError, RecursionError):
        return None


def compile_graph(puzzle: Puzzle, proposed: Graph, attempts: int = 4,
                  recompute: bool = False, schedule_width: int = 0,
                  operation_width: int = 0) -> Program | None:
    try:
        graph = active_graph(puzzle, proposed)
    except (KeyError, ValueError):
        return None
    chronological = {value: proposed[value] for value in proposed if value in graph}
    available = set(puzzle.seeds)
    for value, (_, left, right) in chronological.items():
        if left not in available or right not in available:
            chronological = graph
            break
        available.add(value)
    for order in (chronological, graph):
        program = _allocate(puzzle, order, False, 0, fixed_order=True)
        if program is not None:
            check(puzzle, program)
            return program
    for attempt in range(attempts):
        program = _allocate(puzzle, graph, bool(attempt % 2), attempt // 2)
        if program is not None:
            check(puzzle, program)
            return program
    alternate = []
    if schedule_width > 0:
        pressure = _operand_pressure(puzzle, graph)
        orders = set()
        for targets in _target_orders(puzzle, graph, schedule_width):
            for priority in (None, pressure):
                order = active_graph(puzzle, graph, targets, priority)
                fingerprint = tuple(order)
                if fingerprint in orders:
                    continue
                orders.add(fingerprint)
                program = _allocate(puzzle, order, False, 0, fixed_order=True)
                if program is not None:
                    check(puzzle, program)
                    return program
                alternate.append(order)
    if operation_width > 0:
        order = _operation_order(puzzle, graph, operation_width)
        if order is not None:
            program = _allocate(puzzle, order, False, 0, fixed_order=True)
            if program is None:
                raise RuntimeError("instruction-order search returned an infeasible schedule")
            check(puzzle, program)
            return program
    if recompute:
        variants = [_rematerialize(puzzle, order, mode)
                    for order in (chronological, graph) for mode in ("literal", "static", "dynamic")]
        variants.extend(_rematerialize(puzzle, order, "dynamic") for order in alternate)
        program = min((candidate for candidate in variants if candidate is not None),
                      key=len, default=None)
        if program is not None:
            check(puzzle, program)
            return program
    return None
