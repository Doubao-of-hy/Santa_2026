"""Select and recompile paths through nearby alternative accumulator values."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import random
import subprocess
from time import monotonic

from checkpoint import atomic_text
from elf import arithmetic, check, read_puzzles, read_submission, sha256, write_submission
from solvers.gpu.gpu_join import cut_many
from solvers.gpu.gpu_schedule import schedule_like
from graph import active_graph, compile_graph, first_recipes


def cases(p, graph, count, radius, interiors=False):
    counts = Counter(x for _, a, b in graph.values() for x in {a, b})
    goals = set(p.targets)
    # An original value is paid only if all of its former prerequisites are
    # still needed outside the cut and do not depend on the removed root.
    choices = []
    for root in graph:
        is_interior = root not in goals and counts[root] == 1
        if is_interior != interiors:
            continue
        kept, external = cut_many(p, graph, {root})
        n = len(graph) - len(kept)
        if n < 4:
            continue
        private = [v for v in graph if v not in kept]
        multiplications = sum(graph[v][0] == '*' for v in private)
        choices.append((min(n, 14) + min(5, multiplications), root, private, external))
    choices.sort(key=lambda c: (-c[0], c[1]))
    for _, root, private, external in choices[:count]:
        paid = set(p.seeds) | set(external)
        cones = {}
        for i, v in enumerate(private):
            _, a, b = graph[v]
            cones[v] = (1 << i) | cones.get(a, 0) | cones.get(b, 0)
        values = {v: cones[v].bit_count() for v in private}
        small = sorted(x for x in paid if x <= 1024)
        side = {x for v in private for x in graph[v][1:] if x in paid}
        for v in private:
            if v == root or v < 2 or not radius:
                continue
            # Shift intermediate carries and snap them to nearby multiples of
            # actual arithmetic bases in the incumbent and outer program.
            offsets = set(range(1, radius + 1)) | set(small[:radius]) | side
            for d in offsets:
                for w in (v-d, v+d):
                    if 0 < w <= p.limit:
                        values.setdefault(w, -1)
            for m in small[:radius * 2]:
                if m < 2:
                    continue
                q, r = divmod(v, m)
                for w in (v-r, v-r+m, q, q+1):
                    if 0 < w <= p.limit:
                        values.setdefault(w, -1)
        # Restrict the accumulator vocabulary; side constants can use the
        # whole external dictionary regardless of this bound.
        yield root, private, sorted(paid), values


def solve(p, old, exe, count, radius, split=False, interiors=False, deep=0, share=False):
    graph = active_graph(p, first_recipes(p, old))
    regions = list(cases(p, graph, count, radius, interiors))
    data = []
    for root, private, paid, states in regions:
        header = (p.limit, root, len(private)-1+int(share), len(paid), len(states))
        data.append(' '.join(map(str, (*header, *paid))))
        data.extend(f'{v} {c}' for v, c in states.items())
    cmd = [exe]
    if split:
        cmd.append('--split')
    if deep or share:
        if not split:
            raise ValueError('Four-operation joins and shared rewrites require split entries')
        cmd.append(str(deep))
    if share:
        cmd.append('--ties')
    raw = subprocess.run(cmd, input='\n'.join(data)+'\n', text=True,
                         capture_output=True, check=True)
    stream = iter(raw.stdout.splitlines())
    stats = Counter(cuts=len(regions))
    proposals = []
    groups = defaultdict(list)
    visited = set()
    old_uses = Counter(x for _,a,b in graph.values() for x in {a,b})
    for root, _, _, states in regions:
        expanded, alternatives = map(int, next(stream).split())
        stats['state_pairs'] += expanded
        stats['states'] += len(states)
        for _ in range(alternatives):
            changes = {}
            for _ in range(int(next(stream))):
                value, op, a, b = next(stream).split()
                value, a, b = int(value), int(a), int(b)
                if arithmetic(op,a,b) != value or not 1 <= value <= p.limit:
                    raise ValueError('incorrect path edge')
                changes[value] = op, a, b
            if root not in changes:
                continue
            try:
                merged = active_graph(p, graph | changes)
            except (KeyError, ValueError):
                continue
            if len(merged) < len(graph):
                proposals.append((len(merged), changes))
            if share and len(merged) <= len(graph):
                edits = {v:r for v,r in merged.items() if graph.get(v)!=r}
                fingerprint = tuple(sorted(edits.items()))
                if not edits or fingerprint in visited:
                    continue
                visited.add(fingerprint)
                # Two neutral paths can pay for one shared new constant or
                # jointly remove the last two uses of an old constant.
                keys = {(1,v) for v in edits if v not in graph}
                new_uses = Counter(x for _,a,b in merged.values() for x in {a,b})
                keys.update((2,h) for h in new_uses if 0<new_uses[h]<old_uses[h])
                for key in keys:
                    groups[key].append((root,edits))
    if next(stream,None) is not None:
        raise ValueError('extra native output')
    if share:
        tried_pairs = set()
        for choices in groups.values():
            for i,(root,left) in enumerate(choices):
                for other,right in choices[:i]:
                    if root==other:
                        continue
                    pair=tuple(sorted((id(left),id(right))))
                    if pair in tried_pairs:
                        continue
                    tried_pairs.add(pair)
                    patches = [left | right]
                    if any(k in right and right[k]!=r for k,r in left.items()):
                        patches.append(right | left)
                    for patch in patches:
                        try:
                            merged = active_graph(p,graph | patch)
                        except (KeyError,ValueError):
                            continue
                        if len(merged)<len(graph):
                            proposals.append((len(merged),patch))
                            stats['joint_candidates']+=1
        stats['joint_pairs'] = len(tried_pairs)
        stats['alternative_plans'] = len(visited)
    best, working = old, graph
    stats['logical_candidates'] = len(proposals)
    tried = set()
    for _, patch in sorted(proposals, key=lambda z:z[0]):
        signature = tuple(sorted(patch.items()))
        if signature in tried:
            continue
        tried.add(signature)
        try:
            g = active_graph(p, working | patch)
        except (KeyError, ValueError):
            continue
        if len(g) >= len(best):
            continue
        tape = schedule_like(p, best, g)
        if tape is None or len(tape) > len(g):
            other = compile_graph(p, g, attempts=4, recompute=True, schedule_width=4)
            if other is not None and (tape is None or len(other) < len(tape)):
                tape = other
        if tape is not None and len(tape) < len(best):
            check(p,tape)
            best, working = tape, g
    return p, best, dict(stats)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('base','exe','output'):
        parser.add_argument(name,type=Path)
    for name,default in [('rows',64),('cuts',12),('radius',6),('jobs',3),('seed',363533)]:
        parser.add_argument('--'+name,type=int,default=default)
    parser.add_argument('--ids', type=Path)
    parser.add_argument('--split',action='store_true')
    parser.add_argument('--interiors',action='store_true')
    parser.add_argument('--share',action='store_true',
                        help="Combine equal-cost changes at different roots when they can share work")
    parser.add_argument('--deep',type=int,default=0,
                        help="Probe this many side expressions in each size range for four-operation joins")
    a = parser.parse_args()
    puzzles = read_puzzles('data/puzzles.csv')
    base = read_submission(a.base)
    if a.ids:
        selection = set(a.ids.read_text().split())
        rows = [p for p in puzzles if p.id in selection]
    else:
        rows = [p for p in puzzles if max(p.targets).bit_length()>=33 and len(p.targets)>=15]
        random.Random(a.seed).shuffle(rows)
    if a.rows:
        rows = rows[:a.rows]
    started = monotonic()
    wins, stats = {}, {}
    with ThreadPoolExecutor(a.jobs) as pool:
        jobs = [pool.submit(solve,p,base[p.id],a.exe.resolve(),a.cuts,a.radius,a.split,a.interiors,a.deep,a.share) for p in rows]
        for job in jobs:
            p,tape,record = job.result()
            record['saved'] = len(base[p.id])-len(tape)
            stats[p.id] = record
            if record['saved']:
                wins[p.id] = tape
                print(p.id, record['saved'], flush=True)
    write_submission(a.output,[p for p in puzzles if p.id in wins],wins)
    totals = dict(sum(map(Counter,stats.values()),Counter()))
    report = dict(parent=sha256(a.base),executable=sha256(a.exe),seed=a.seed,radius=a.radius,split=a.split,interiors=a.interiors,deep=a.deep,share=a.share,
                  totals=totals,seconds=monotonic()-started,results=stats)
    atomic_text(a.output.with_suffix('.json'),json.dumps(report,indent=2)+'\n')
    print(len(rows),totals,flush=True)


if __name__=='__main__':
    main()
