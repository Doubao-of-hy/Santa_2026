"""Find reusable partial expressions across arithmetic dependency cones."""

from collections import Counter, defaultdict
from functools import cache
from itertools import combinations, product
from typing import NamedTuple

from elf import Program, Puzzle
from graph import Graph, Recipe, active_graph, compile_graph, first_recipes


class Rewrite(NamedTuple):
    output: int
    recipe: Recipe
    helpers: tuple[tuple[int, Recipe], ...]


def sum_recipe(first: tuple[int, int], second: tuple[int, int]) -> tuple[int, int, Recipe] | None:
    left, sign_left = first
    right, sign_right = second
    signed = left * sign_left + right * sign_right
    if not signed:
        return None
    if sign_left == sign_right:
        recipe = "+", min(left, right), max(left, right)
    else:
        recipe = "-", max(left, right), min(left, right)
    return abs(signed), 1 if signed > 0 else -1, recipe


def product_recipe(first: tuple[int, int], second: tuple[int, int]) -> tuple[int, int, Recipe] | None:
    left, sign_left = first
    right, sign_right = second
    if sign_left == sign_right:
        return left * right, sign_left, ("*", min(left, right), max(left, right))
    big, small = max(left, right), min(left, right)
    quotient, remainder = divmod(big, small)
    if remainder:
        return None
    return quotient, sign_left if left >= right else sign_right, ("/", big, small)


def reassociate(output: int, graph: Graph, known: set[int], limit: int):
    outer, left, right = graph[output]
    add = outer in "+-"
    group = "+-" if add else "*/"
    operation = sum_recipe if add else product_recipe
    signs = (1, -1 if outer in "-/" else 1)
    for nested, outside in ((0, 1), (1, 0)):
        inner = graph.get((left, right)[nested])
        if inner is None or inner[0] not in group:
            continue
        terms = (
            ((left, right)[outside], signs[outside]),
            (inner[1], signs[nested]),
            (inner[2], -signs[nested] if inner[0] in "-/" else signs[nested]),
        )
        for i, j, remaining in ((0, 1, 2), (0, 2, 1)):
            partial = operation(terms[i], terms[j])
            if partial is None or not 1 <= partial[0] <= limit or partial[0] == output:
                continue
            root = operation((partial[0], partial[1]), terms[remaining])
            if root is None or root[:2] != (output, 1) or root[2] == graph[output]:
                continue
            helpers = () if partial[0] in known else ((partial[0], partial[2]),)
            yield Rewrite(output, root[2], helpers)


def distribute(output: int, graph: Graph, known: set[int], limit: int):
    operator, left, right = graph[output]
    if operator in "+-":
        products = graph.get(left), graph.get(right)
        if all(recipe is not None and recipe[0] == "*" for recipe in products):
            (_, a, b), (_, c, d) = products
            for (first, common), (second, matching) in product(((a, b), (b, a)), ((c, d), (d, c))):
                if common != matching:
                    continue
                partial = sum_recipe((first, 1), (second, -1 if operator == "-" else 1))
                if partial is None or partial[1] < 0 or partial[0] in (output, common):
                    continue
                value, _, recipe = partial
                operands = min(value, common), max(value, common)
                helpers = () if value in known else ((value, recipe),)
                yield Rewrite(output, ("*", *operands), helpers)
    if operator == "*":
        for nested, common in ((left, right), (right, left)):
            inner = graph.get(nested)
            if inner is None or inner[0] not in "+-":
                continue
            _, first, second = inner
            children = first * common, second * common
            if max(children) > limit or output in children:
                continue
            if not any(value in known for value in children):
                continue
            helpers = tuple((value, ("*", min(leaf, common), max(leaf, common)))
                            for value, leaf in zip(children, inner[1:]) if value not in known)
            yield Rewrite(output, (inner[0], *children), helpers)


def deep_reassociate(output: int, graph: Graph, known: set[int], limit: int):
    outer, left, right = graph[output]
    group = "+-" if outer in "+-" else "*/"
    operation = sum_recipe if outer in "+-" else product_recipe
    initial = ((left, 1), (right, -1 if outer in "-/" else 1))
    levels = {initial}
    for _ in range(2):
        expanded = set()
        for leaves in levels:
            for index, (value, sign) in enumerate(leaves):
                inner = graph.get(value)
                if inner is not None and inner[0] in group:
                    factors = ((inner[1], sign), (inner[2], -sign if inner[0] in "-/" else sign))
                    expanded.add(leaves[:index] + factors + leaves[index + 1:])
        levels = expanded
    for leaves in sorted(levels):
        full = (1 << len(leaves)) - 1

        @cache
        def parts(mask):
            if mask.bit_count() == 1:
                value, sign = leaves[mask.bit_length() - 1]
                return [(value, sign, None, ())]
            completed = set()
            left_mask = (mask - 1) & mask
            while left_mask:
                right_mask = mask ^ left_mask
                if right_mask < left_mask:
                    for first, second in product(parts(left_mask), parts(right_mask)):
                        combined = operation(first[:2], second[:2])
                        if combined is None or combined[0] > limit:
                            continue
                        value, sign, recipe = combined
                        helpers = ()
                        if mask == full or value not in known:
                            helpers = tuple(sorted(set(first[3] + second[3])))
                        if mask != full and value not in known:
                            helpers = (*helpers, (value, recipe))
                        completed.add((value, sign, recipe, helpers))
                left_mask = (left_mask - 1) & mask
            return sorted(completed, key=lambda item: (len(item[3]), item))[:9]

        for value, sign, recipe, helpers in parts(full):
            if value == output and sign == 1 and recipe != graph[output]:
                if not any(value == output for value, _ in helpers):
                    yield Rewrite(output, recipe, helpers)


def squared_difference(output: int, graph: Graph, known: set[int], limit: int):
    operator, left, right = graph[output]
    if operator == "-":
        first, second = graph.get(left), graph.get(right)
        if (first is not None and second is not None and first[0] == second[0] == "*"
                and first[1] == first[2] and second[1] == second[2]):
            a, b = first[1], second[1]
            plus, minus = a + b, a - b
            if 0 < minus and plus <= limit and output not in (plus, minus):
                helpers = tuple((value, (op, a, b)) for value, op in ((plus, "+"), (minus, "-"))
                                if value not in known)
                yield Rewrite(output, ("*", minus, plus), helpers)


def exchange_carry(output: int, graph: Graph, known: set[int], limit: int):
    outer, left, right = graph[output]
    if outer not in "+-":
        return
    children = ((left, 1), (right, 1 if outer == "+" else -1))
    for node, sign in children:
        inner = graph.get(node)
        if inner is None or inner[0] != "*":
            continue
        for divisor in set(inner[1:]):
            if divisor == 1:
                continue
            for residual in known:
                for value in (output - residual, output + residual) if sign > 0 else (residual - output,):
                    multiplier, remainder = divmod(value, divisor)
                    if (remainder or multiplier not in known or value in (node, output)
                            or not 1 <= value <= limit):
                        continue
                    if sign < 0:
                        recipe = "-", residual, value
                    elif value > output:
                        recipe = "-", value, residual
                    else:
                        recipe = "+", min(value, residual), max(value, residual)
                    multiplication = "*", min(divisor, multiplier), max(divisor, multiplier)
                    helpers = () if value in known else ((value, multiplication),)
                    yield Rewrite(output, recipe, helpers)


def candidates(graph: Graph, puzzle: Puzzle):
    known = graph.keys() | set(puzzle.seeds)
    targets = set(puzzle.targets)
    shared = defaultdict(set)
    singleton = set()
    users = defaultdict(set)
    replacements = defaultdict(lambda: defaultdict(set))
    for output in graph:
        old_inputs = {value for value in graph[output][1:] if value in graph and value not in targets}
        for value in old_inputs:
            users[value].add(output)
        rewrites = (*reassociate(output, graph, known, puzzle.limit),
                    *distribute(output, graph, known, puzzle.limit),
                    *deep_reassociate(output, graph, known, puzzle.limit),
                    *squared_difference(output, graph, known, puzzle.limit),
                    *exchange_carry(output, graph, known, puzzle.limit))
        for rewrite in rewrites:
            if rewrite.helpers:
                helper_values = tuple(sorted({value for value, _ in rewrite.helpers}))
                shared[helper_values].add(rewrite)
            singleton.add(rewrite)
            dependencies = set(rewrite.recipe[1:]) | {
                child for _, helper in rewrite.helpers for child in helper[1:]
            }
            for removed in old_inputs - dependencies:
                replacements[removed][output].add(rewrite)
    yield from ((rewrite,) for rewrite in sorted(singleton))
    for rewrites in shared.values():
        if len(rewrites) < 2:
            continue
        ordered = sorted(rewrites)
        if len(ordered) > 2:
            yield tuple({rewrite.output: rewrite for rewrite in ordered}.values())
        yield from combinations(ordered, 2)
    for helper, options in replacements.items():
        users_of_helper = users[helper]
        if not 2 <= len(users_of_helper) <= 4 or options.keys() != users_of_helper:
            continue
        choices = [sorted(options[value], key=lambda rewrite: (len(rewrite.helpers), rewrite))[:4]
                   for value in sorted(users_of_helper)]
        yield from product(*choices)


def edge_counts(puzzle: Puzzle, graph: Graph) -> Counter:
    return Counter(puzzle.targets) + Counter(
        child
        for _, first, second in graph.values()
        for child in {first, second}
        if child in graph
    )


def could_shorten(graph: Graph, counts: Counter, changes: Graph) -> bool:
    delta = Counter()
    for value, (_, first, second) in changes.items():
        for child in {first, second}:
            delta[child] += 1
        if value in graph:
            _, old_first, old_second = graph[value]
            for child in {old_first, old_second}:
                delta[child] -= 1
    missing = len(changes.keys() - graph.keys())
    exhausted = [value for value, net in delta.items() if value in graph and counts[value] + net == 0]
    deleted = set()
    while exhausted:
        value = exhausted.pop()
        if value in deleted:
            continue
        deleted.add(value)
        if len(deleted) > missing:
            return True
        _, first, second = changes.get(value, graph[value])
        for child in {first, second}:
            delta[child] -= 1
            if child in graph and counts[child] + delta[child] == 0:
                exhausted.append(child)
    return False


def rewrite_graph(puzzle: Puzzle, graph: Graph) -> Graph | None:
    result = None
    best_length = len(graph)
    counts = edge_counts(puzzle, graph)
    for options in candidates(graph, puzzle):
        if len({option.output for option in options}) != len(options):
            continue
        changes = {}
        for option in options:
            changes[option.output] = option.recipe
            changes.update(option.helpers)
        if not could_shorten(graph, counts, changes):
            continue
        try:
            active = active_graph(puzzle, graph | changes)
        except (KeyError, ValueError):
            continue
        if len(active) < best_length:
            result = active
            best_length = len(active)
    return result


def repair_algebra(puzzle: Puzzle, original: Program) -> Program:
    graph = active_graph(puzzle, first_recipes(puzzle, original))
    for _ in range(4):
        candidate = rewrite_graph(puzzle, graph)
        if candidate is None:
            break
        program = compile_graph(puzzle, candidate)
        if program is None:
            break
        if len(program) < len(original):
            original = program
        graph = candidate
    return original
