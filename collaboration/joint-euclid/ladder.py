"""Two-output Euclidean reductions with exact arithmetic and paid terminal operands."""
from collections import Counter
from itertools import combinations, product

from elf import check
from solvers.gpu.gpu_join import cut_many
from solvers.gpu.gpu_schedule import schedule_like
from graph import active_graph, compile_graph, first_recipes


def operations(a, b, bound):
    big, small = max(a, b), min(a, b)
    if big + small <= bound:
        yield big + small, ("+", big, small)
    if big > small:
        yield big - small, ("-", big, small)
    if big * small <= bound:
        yield big * small, ("*", big, small)
    if big % small == 0:
        yield big // small, ("/", big, small)


def paired_cuts(p, graph, settings):
    singles = {}
    for t in sorted(set(p.targets) & graph.keys()):
        kept, _ = cut_many(p, graph, {t})
        singles[t] = len(graph) - len(kept)
    roots = sorted(singles, key=lambda t: (-singles[t], t))[:settings["highest_private_targets"]]
    candidates = []
    for a, b in combinations(roots, 2):
        kept, free = cut_many(p, graph, {a, b})
        cost = len(graph) - len(kept)
        difference = abs(a.bit_length() - b.bit_length())
        rank = (-min(cost, 18), -min(singles[a], singles[b]), difference, -cost, a, b)
        candidates.append((rank, (a, b), cost, set(p.seeds) | free.keys()))
    return sorted(candidates, key=lambda item: item[0])[:settings["max_pairs"]]


def combine(*patches):
    result = {}
    for patch in patches:
        for v, expression in patch.items():
            if v in result and result[v] != expression:
                return None
            result[v] = expression
    return result


def search_pair(p, graph, roots, paid, cost, settings, counters, receive):
    blocked = set(roots)
    independent = set(p.seeds)
    for v, (_, a, b) in graph.items():
        if v not in blocked and a in independent and b in independent:
            independent.add(v)
    old_private = independent - paid
    paid_list = sorted(paid)
    one = {}
    for i, a in enumerate(paid_list):
        for b in paid_list[:i + 1]:
            for v, edge in operations(a, b, p.limit):
                if v not in paid:
                    one.setdefault(v, edge)

    def terminal(v):
        if v in paid:
            return [{}]
        result = [{}] if v in old_private else []
        if v in one:
            result.append({v: one[v]})
        return result

    def linked(t, s):
        for side, edge in ((t - s, ("+", s, t - s)), (s - t, ("-", s, s - t)),
                           (s + t, ("-", s + t, s)), (t // s, ("*", s, t // s)),
                           (s // t, ("/", s, s // t)), (s * t, ("/", s * t, s))):
            if edge[0] == "*" and t % s:
                continue
            if edge[0] == "/" and edge[1] == s and s % t:
                continue
            if side in paid and t not in (s, side):
                yield {t: edge}

    def leaves(x, y):
        left, right = terminal(x), terminal(y)
        if x == y:
            yield from left
            return
        for u, v in product(left, right):
            yield combine(u, v)
        for a, b, direct in ((x, y, left), (y, x, right)):
            if direct and b not in paid:
                for u, v in product(direct, linked(b, a)):
                    yield combine(u, v)

    def reduce_pair(pair, history, trail):
        for a, b in (pair, pair[::-1]):
            if a in paid or a == b:
                continue
            for k in sorted({1, a // b, (a + b - 1) // b}):
                if k < 1 or (k > 1 and k not in paid and k not in one):
                    continue
                v = k * b
                r = abs(a - v)
                if v > p.limit or r >= a:
                    continue
                step = {}
                if k > 1 and k not in paid:
                    step[k] = one[k]
                if k > 1 and v not in paid:
                    step[v] = ("*", k, b)
                if r:
                    step[a] = ("+", v, r) if a > v else ("-", v, r)
                elif a in paid:
                    continue
                patch = combine(history, step)
                if patch is None:
                    continue
                new_pair = tuple(sorted((b, r or b), reverse=True))
                yield new_pair, patch, (*trail, (a, b, k, r))

    states = [(tuple(sorted(roots, reverse=True)), {}, ())]
    for level in range(settings["depth"] + 1):
        candidates = {}
        for (x, y), steps, trail in states:
            counters["states"] += 1
            seen = set()
            for end in leaves(x, y):
                if end is None:
                    continue
                patch = combine(steps, end)
                if patch is None:
                    continue
                stamp = tuple(sorted(patch.items()))
                if stamp in seen:
                    continue
                seen.add(stamp)
                counters["grounded_shallow" if level <= 1 else "grounded_deep"] += 1
                receive(roots, cost, patch, trail)
            if level == settings["depth"]:
                continue
            for pair, patch, new_trail in reduce_pair((x, y), steps, trail):
                x2, y2 = pair
                def price(v):
                    if v in paid:
                        return 0
                    if v in one or v in old_private:
                        return 1
                    return 2 + v.bit_length() / 10
                rank = (len(patch) + price(x2) + price(y2), x2.bit_length() + y2.bit_length(),
                        len(patch), new_trail)
                if pair not in candidates or rank < candidates[pair][0]:
                    candidates[pair] = (rank, patch, new_trail)
        states = [(pair, patch, trail) for pair, (_, patch, trail) in
                  sorted(candidates.items(), key=lambda item: item[1][0])[:settings["beam"]]]
        if not states:
            break


def run(p, tape, settings, replay):
    assert check(p, tape) == replay(p, tape)
    graph = active_graph(p, first_recipes(p, tape))
    counters = Counter()
    best = {"one": tape, "ladder": tape}
    info = {"one": None, "ladder": None}
    smallest = {"one": None, "deep": None}
    cache = {}

    def consider(roots, cost, patch, trail):
        category = "one" if len(trail) <= 1 else "deep"
        key = tuple(sorted(patch.items()))
        if key not in cache:
            try:
                rebuilt = active_graph(p, graph | patch)
            except (KeyError, ValueError):
                cache[key] = (None, None)
                return
            counters["distinct_complete_graphs"] += 1
            sequence = None
            if len(rebuilt) < len(tape):
                counters["graphs_below_parent"] += 1
                sequence = schedule_like(p, tape, rebuilt)
                if sequence is None or len(sequence) > len(rebuilt):
                    other = compile_graph(p, rebuilt, attempts=3, schedule_width=3, recompute=True)
                    sequence = min((t for t in (other, sequence) if t is not None), key=len, default=None)
                if sequence is not None:
                    assert check(p, sequence) == replay(p, sequence)
            cache[key] = (len(rebuilt), sequence)
        size, sequence = cache[key]
        if size is None:
            return
        if smallest[category] is None or size < smallest[category]:
            smallest[category] = size
        affected = ("one", "ladder") if len(trail) <= 1 else ("ladder",)
        for arm in affected:
            if sequence is not None and len(sequence) < len(best[arm]):
                best[arm] = sequence
                info[arm] = dict(roots=roots, cut_cost=cost, trace=trail,
                                 changes={v: e for v, e in patch.items() if graph.get(v) != e})

    for _, roots, cost, paid in paired_cuts(p, graph, settings):
        counters["cuts"] += 1
        search_pair(p, graph, roots, paid, cost, settings, counters, consider)
    return best, dict(baseline=len(tape), graph=len(graph), stats=dict(counters),
                      minimum_graph=smallest, lengths={k: len(v) for k, v in best.items()},
                      witness=info)
