"""Recover a shared multiplier from a retained target and rebuild neighboring targets."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import random

from elf import check, read_puzzles, read_submission, write_submission
from graph import active_graph, compile_graph, first_recipes
from solvers.gpu.gpu_schedule import schedule_like
from solvers.matrix.matrix_construct import Route, choose
from solvers.matrix.matrix_graft import pool, trim


def path(target, center, factor, offset, limit, reverse):
    shifted = center + offset
    product = shifted * factor
    error = target - product
    if not (0 < shifted <= limit and 0 < product <= limit and 0 < factor <= limit):
        return None
    edges = {}

    def shift(value, delta):
        if delta:
            edges[value + delta] = ("+" if delta > 0 else "-", value, abs(delta))

    if reverse:
        shift(target, -error)
        if factor != 1:
            edges[shifted] = ("/", product, factor)
        shift(shifted, -offset)
    else:
        shift(center, offset)
        if factor != 1:
            edges[product] = ("*", shifted, factor)
        shift(product, error)
    if any(v in edge[1:] for v, edge in edges.items()):
        return None
    return edges


def offsets(row, center):
    k, t = row["k"], row["t"]
    d = (2 * (t - k * center) + k) // (2 * k)
    return {0, d, d - 1, d + 1}


def construct(p, old, group, anchor, center):
    graph = active_graph(p, first_recipes(p, old))
    selected = {row["t"] for row in group} - {anchor["t"]}
    fixed = active_graph(p, graph, set(p.targets) - selected)
    free = set(fixed) | set(p.seeds)
    wanted = selected - free
    if not wanted:
        return old
    reverse = [path(anchor["t"], center, anchor["k"], s, p.limit, True)
               for s in offsets(anchor, center)]
    if center in free:
        reverse = [{}]
    menus = {}
    for row in group:
        t = row["t"]
        if t not in wanted:
            continue
        original = trim(t, graph, free, set())
        options = {tuple(sorted(original.graph.items())): original}
        for adjustment in offsets(row, center):
            forward = path(t, center, row["k"], adjustment, p.limit, False)
            if forward is None:
                continue
            for backward in reverse:
                if backward is None or (set(backward) & set(forward)):
                    continue
                route = trim(t, backward | forward, free, set())
                if route.leaves & wanted:
                    continue
                options.setdefault(tuple(sorted(route.graph.items())), route)
        menus[t] = list(options.values())
    literals = {v for options in menus.values() for r in options for v in r.leaves}
    hints, materials = pool(p, free, literals)
    for t, options in menus.items():
        menus[t] = [r for r in options if r.leaves <= free | materials.keys()]
        if not menus[t]:
            raise ValueError(f"Missing incumbent route for {p.id}/{t}")
    seed = int(p.id.rsplit("_", 1)[-1]) if p.id.rsplit("_", 1)[-1].isdigit() else 1
    # The forced trial pays the fixed cost of discovering the center even
    # when a single local change would prefer to stay with the original.
    proposals = []
    for forced in (True, False):
        menu = {t: options[1:] if forced and len(options) > 1 else options for t, options in menus.items()}
        proposed, needed = choose(menu, p, free, seed, hints)
        recipes = graph | materials | proposed | fixed
        try:
            rebuilt = active_graph(p, recipes)
        except (KeyError, ValueError):
            continue
        if len(rebuilt) < len(old):
            proposals.append(rebuilt)
    best = old
    for rebuilt in sorted(proposals, key=len):
        scheduled = schedule_like(p, old, rebuilt)
        if scheduled is None or len(scheduled) > len(rebuilt):
            alternate = compile_graph(p, rebuilt, attempts=2, recompute=True, schedule_width=5)
            if alternate and (scheduled is None or len(alternate) < len(scheduled)):
                scheduled = alternate
        if scheduled and len(scheduled) < len(best):
            check(p, scheduled)
            best = scheduled
    return best


def solve(args):
    puzzle, old, model, anchor_limit = args
    groups = defaultdict(dict)
    for row in (*model["targets"], *model.get("alternatives", ())):
        h = row["a"] * row["b"]
        if row["t"] != row["k"] * h + row["r"] or row["t"] not in puzzle.targets:
            raise ValueError((puzzle.id, row))
        groups[h][row["t"]] = row
    best = old
    for h, mapping in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len(mapping) < 3:
            continue
        group = list(mapping.values())
        graph = active_graph(puzzle, first_recipes(puzzle, best))
        free = set(graph) | set(puzzle.seeds)
        # Try an existing offset of the fitted center as a hub when possible.
        nearby = [v for v in free if abs(h - v) <= 192]
        centers = list(dict.fromkeys((h, *sorted(nearby, key=lambda v: abs(h-v))[:2])))
        for center in centers:
            anchors = sorted(group, key=lambda r: (r["k"] not in free,
                             min(abs(r["t"]-r["k"]*center), abs(r["e"])),
                             r["k"], r["t"]))
            for anchor in anchors[:1 if center in free else anchor_limit]:
                best = construct(puzzle, best, group, anchor, center)
    return puzzle.id, best


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("models", "incumbent", "output"):
        parser.add_argument(arg, type=Path)
    parser.add_argument("--rows", type=int, default=0)
    parser.add_argument("--anchors", type=int, default=3)
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--seed", type=int, default=1951)
    args = parser.parse_args()
    puzzles = read_puzzles("data/puzzles.csv")
    indexed = {p.id: p for p in puzzles}
    incumbent = read_submission(args.incumbent)
    models = [json.loads(s) for s in args.models.read_text(encoding="utf8").splitlines()]
    random.Random(args.seed).shuffle(models)
    tasks = [(indexed[m["id"]], incumbent[m["id"]], m, args.anchors)
             for m in (models[:args.rows] if args.rows else models)]
    done = {}
    with ProcessPoolExecutor(args.jobs) as workers:
        for pid, result in workers.map(solve, tasks):
            check(indexed[pid], result)
            done[pid] = result
            if len(done) % 30 == 0:
                write_submission(args.output, [p for p in puzzles if p.id in done], done)
    write_submission(args.output, [p for p in puzzles if p.id in done], done)
    print(len(done), "puzzles,", sum(len(incumbent[k]) - len(v) for k, v in done.items()), "saved")


if __name__ == "__main__":
    main()
