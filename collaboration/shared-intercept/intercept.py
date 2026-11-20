"""Simultaneous replacement of two private branches by an affine progression."""
from collections import Counter, defaultdict
from itertools import combinations

from elf import check
from gpu_join import cut_many
from gpu_schedule import schedule_like
from graph import active_graph, compile_graph, first_recipes


def choices(a, b, cap):
    a, b = sorted((a, b), reverse=True)
    if a + b <= cap:
        yield a + b, ("+", a, b)
    if a > b:
        yield a - b, ("-", a, b)
    if a * b <= cap:
        yield a * b, ("*", a, b)
    if a % b == 0:
        yield a // b, ("/", a, b)


def private_branches(p, graph, settings):
    goals = sorted(set(p.targets) & graph.keys())
    membership = {v: 1 << i for i, v in enumerate(goals)}
    for v, (_, a, b) in reversed(graph.items()):
        flags = membership.get(v, 0)
        for x in (a, b):
            membership[x] = membership.get(x, 0) | flags
    cost = {}
    cones = defaultdict(list)
    ancestors = {v: 0 for v in p.seeds}
    for i, (v, (_, a, b)) in enumerate(graph.items()):
        ancestors[v] = (1 << i) | ancestors[a] | ancestors[b]
        flags = membership[v]
        if flags.bit_count() == 1:
            keep, _ = cut_many(p, graph, {v})
            cost[v] = len(graph) - len(keep)
            cones[flags].append(v)
    selected = []
    for owner, pool in cones.items():
        ranked = sorted(pool, key=lambda v: (-cost[v], -int(v in goals), v))
        selected.extend((v, owner) for v in ranked[:settings["per_branch"]])
    selected.sort(key=lambda item: (-cost[item[0]], -int(item[0] in goals), item[0]))
    return selected[:settings["max_roots"]], cost, ancestors


def run(p, tape, settings, replay):
    assert check(p, tape) == replay(p, tape)
    graph = active_graph(p, first_recipes(p, tape))
    roots, costs, ancestors = private_branches(p, graph, settings)
    bits = {v: 1 << i for i, v in enumerate(graph)}
    known = set(p.seeds) | graph.keys()
    seeds = set(p.seeds)
    multipliers = Counter()
    for _, (op, a, b) in graph.items():
        if op == "*":
            multipliers.update({a, b})
    coeff = sorted((v for v in known if v <= 65536),
                   key=lambda v: (v not in seeds and v > 32, -multipliers[v], v))
    coeff = sorted(set([1] + coeff[:settings["max_coefficients"] - 1]))
    diffs = defaultdict(list)
    for k, l in combinations(coeff, 2):
        diffs[l - k].append((k, l))

    # This dictionary screens impossible values before any per-cut reachability claim.
    ordered = sorted(known)
    one = set()
    for i, a in enumerate(ordered):
        for b in ordered[:i + 1]:
            one.update(v for v, _ in choices(a, b, p.limit))
    reachable = known | one
    candidates = []
    stats = Counter(private_roots=len(roots))
    for (a, owner), (b, other) in combinations(roots, 2):
        if owner == other:
            continue
        stats["cross_branch_pairs"] += 1
        u, v = sorted((a, b))
        difference = v - u
        pairs = []
        for d, slopes in diffs.items():
            if difference % d:
                continue
            h = difference // d
            if h not in reachable or h in (u, v):
                continue
            for k, l in slopes:
                intercept = u - k * h
                e = abs(intercept)
                if not e or e not in reachable or max(l * h, e) > p.limit:
                    continue
                forbidden = bits[u] | bits[v]
                if any(ancestors.get(s, 0) & forbidden for s in (k, l)):
                    continue
                if {u, v} & {e, k, l}:
                    continue
                stats["global_affine_witnesses"] += 1
                rank = (-(costs[u] + costs[v]), int(h not in known) + int(e not in known),
                        -(int(k * h in known) + int(l * h in known)),
                        -min(costs[u], costs[v]), k + l, h, intercept)
                pairs.append((rank, (k, l, h, intercept)))
        if pairs:
            pairs.sort()
            candidates.append((pairs[0][0], u, v, pairs[:settings["max_witnesses_per_pair"]]))
    candidates.sort()
    stats["screened_pairs"] = len(candidates)
    single, joint = {}, {}
    def offer(bank, patch, info):
        stamp = tuple(sorted(patch.items()))
        if stamp not in bank:
            bank[stamp] = (patch, info)
    for _, u, v, items in candidates[:settings["max_pairs_to_build"]]:
        _, free = cut_many(p, graph, {u, v})
        paid = set(p.seeds) | free.keys()
        pair_mask = bits[u] | bits[v]
        wanted = set()
        for _, (k, l, h, signed) in items:
            wanted.update((h, abs(signed)))
        make = {}
        paid_order = sorted(paid)
        for i, a in enumerate(paid_order):
            for b in paid_order[:i + 1]:
                for target, edge in choices(a, b, p.limit):
                    if target in wanted and target not in paid:
                        make.setdefault(target, edge)
        def buy(x):
            options = []
            if x in paid or x in graph and not ancestors[x] & pair_mask:
                options.append({})
            if x in make:
                options.append({x: make[x]})
            return options
        for _, (k, l, h, signed) in items:
            if any(x != 1 and x not in paid for x in (k, l)):
                continue
            for left in buy(h):
                for right in buy(abs(signed)):
                    stats["grounded_witnesses"] += 1
                    base = left | right
                    roots_patches = []
                    for x, m in ((u, k), (v, l)):
                        q = m * h
                        patch = dict(base)
                        if m != 1 and q not in paid:
                            patch[q] = ("*", m, h)
                        patch[x] = ("+" if signed > 0 else "-", q, abs(signed))
                        roots_patches.append(patch)
                    info = dict(pair=[u, v], slopes=[k, l], scale=h, intercept=signed)
                    for patch in roots_patches:
                        offer(single, patch, info)
                    offer(joint, roots_patches[0] | roots_patches[1], info)
    stats["single_offers"], stats["joint_offers"] = len(single), len(joint)
    def apply(bank, group):
        best = tape
        chosen = graph
        used = []
        # Parent-based graph sizes rank proposals once. Both arms use this strict-decrease rule.
        initial = []
        for patch, witness in bank:
            try:
                item = active_graph(p, chosen | patch)
            except (ValueError, KeyError):
                continue
            initial.append((len(item), len(patch), patch, witness))
        stats[group + "_acyclic_offers"] = len(initial)
        if initial:
            stats[group + "_minimum_graph"] = min(x[0] for x in initial)
        for _, _, patch, witness in sorted(initial, key=lambda x: x[:2]):
            try:
                rebuilt = active_graph(p, chosen | patch)
            except (ValueError, KeyError):
                continue
            if len(rebuilt) >= len(best):
                continue
            new = schedule_like(p, best, rebuilt)
            if new is None or len(new) > len(rebuilt):
                alt = compile_graph(p, rebuilt, attempts=3, schedule_width=3, recompute=True)
                new = min((s for s in (new, alt) if s is not None), key=len, default=None)
            if new is not None and len(new) < len(best):
                assert check(p, new) == replay(p, new)
                used.append(dict(before=len(best), after=len(new), **witness))
                chosen, best = rebuilt, new
        return best, used
    control, cpath = apply(single.values(), "single")
    treatment, tpath = apply([*joint.values(), *single.values()], "union")
    if len(control) <= len(treatment):
        treatment, tpath = control, cpath
    return {"single": control, "joint": treatment}, dict(baseline=len(tape), graph=len(graph),
           lengths={"single": len(control), "joint": len(treatment)}, stats=dict(stats),
           witness={"single": cpath, "joint": tpath})
