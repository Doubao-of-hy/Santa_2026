"""Prove shortest programs on the bounded small-integer puzzles."""

from functools import lru_cache

from elf import Program, Puzzle, check


def members(mask: int):
    while mask:
        bit = mask & -mask
        yield bit.bit_length() - 1
        mask ^= bit


@lru_cache(maxsize=16)
def operation_table(limit: int) -> tuple[tuple[int, ...], ...]:
    table = [[0] * (limit + 1) for _ in range(limit + 1)]
    for first in range(1, limit + 1):
        for second in range(1, first + 1):
            values = (first + second, first - second, first * second,
                      first // second if first % second == 0 else 0)
            mask = 0
            for value in values:
                if 1 <= value <= limit:
                    mask |= 1 << value
            table[first][second] = table[second][first] = mask
    return tuple(tuple(row) for row in table)


def reachable_from(value, state, table):
    possible = 0
    for other in members(state):
        possible |= table[value][other]
    return possible


def encode(puzzle: Puzzle, values: tuple[int, ...]) -> Program:
    registers = {value: index for index, value in enumerate(puzzle.seeds)}
    program = []
    for destination, value in enumerate(values, start=len(puzzle.seeds)):
        for left, left_register in registers.items():
            for right, right_register in registers.items():
                if left + right == value:
                    instruction = ("+", left_register, right_register, destination)
                elif left - right == value:
                    instruction = ("-", left_register, right_register, destination)
                elif left * right == value:
                    instruction = ("*", left_register, right_register, destination)
                elif left == right * value:
                    instruction = ("/", left_register, right_register, destination)
                else:
                    continue
                break
            else:
                continue
            break
        else:
            raise RuntimeError(f"could not reconstruct instruction for {value}")
        registers[value] = destination
        program.append(instruction)
    result = tuple(program)
    check(puzzle, result)
    return result


def solve_tiny(puzzle: Puzzle, max_steps: int = 32, max_nodes: int = 100_000) -> Program | None:
    """Return a proven optimum or None if the bounded search is inconclusive."""
    if set(puzzle.targets).issubset(puzzle.seeds):
        return ()
    if puzzle.limit > 128:
        return None

    seeds = sum(1 << value for value in set(puzzle.seeds))
    targets = sum(1 << value for value in set(puzzle.targets))
    missing_count = (targets & ~seeds).bit_count()

    # For all tested lengths, even an arbitrary valid program can keep every
    # distinct value it ever generates. Searching permanent sets is complete.
    max_helpers = min(max_steps, puzzle.registers - len(puzzle.seeds)) - missing_count
    if max_helpers < 0:
        return None
    table = operation_table(puzzle.limit)
    initial_options = 0
    for value in members(seeds):
        initial_options |= reachable_from(value, seeds, table)
    failures = {}
    nodes = 0

    def visit(state, options, helpers, path):
        nonlocal nodes
        if nodes >= max_nodes:
            return None
        nodes += 1

        # Each missing target must eventually be generated. Generate all
        # immediately available ones now at no cost to the helper budget.
        while available := options & targets & ~state:
            bit = available & -available
            value = bit.bit_length() - 1
            state |= bit
            path += (value,)
            options |= reachable_from(value, state, table)
        missing = targets & ~state
        if not missing:
            return path
        if helpers == 0 or failures.get(state, -1) >= helpers:
            return None

        candidates = []
        for value in members(options & ~state):
            expanded = state | (1 << value)
            extra = reachable_from(value, expanded, table)
            candidates.append(((extra & missing).bit_count(), value, expanded, options | extra))
        candidates.sort(reverse=True)
        for _, value, expanded, expanded_options in candidates:
            result = visit(expanded, expanded_options, helpers - 1, path + (value,))
            if result is not None:
                return result
            if nodes >= max_nodes:
                return None
        failures[state] = helpers
        return None

    for helpers in range(max_helpers + 1):
        path = visit(seeds, initial_options, helpers, ())
        if path is not None:
            return encode(puzzle, path)
        if nodes >= max_nodes:
            break
    return None
