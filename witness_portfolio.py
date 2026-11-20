"""Select a whole puzzle graph from the individual arithmetic edges of GPU witnesses."""
import argparse
from collections import Counter
from pathlib import Path
import json
import sys
from time import monotonic

from checkpoint import atomic_text
from elf import check, read_puzzles, read_submission, sha256, write_submission
from graph import active_graph, first_recipes
from pooled_joins import PooledEngine, optimize

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'generative'))
sys.path.insert(0, str(ROOT / 'work/creative/native-bank'))
from component_select import canonical, solve
from parallel_solve import arithmetic
from reachability_select import solve_free

if (ROOT/'work/creative/native-bank/native_table.dll').is_file():
    from native_table import native_table as table_builder
else:
    from gpu_join import make_table as table_builder


def candidates(p, tape, witnesses, closure):
    primary = active_graph(p, first_recipes(p, tape))
    ways = {v: {canonical(r)} for v, r in primary.items()}
    seeds = set(p.seeds)
    inputs = list(dict.fromkeys((*p.seeds, *primary)))
    for v, edges in witnesses.items():
        if v not in seeds:
            ways.setdefault(v, set())
    def close_input(i, x):
        for y in inputs[:i+1]:
            for out,edge in arithmetic(x,y,p.limit):
                if out in ways and out not in (x,y) and len(ways[out])<60:
                    ways[out].add(canonical(edge))
    if closure:
        for i,x in enumerate(inputs):
            close_input(i,x)
    for v,edges in witnesses.items():
        if v not in seeds:ways[v].update(edges)
    if closure:
        demand = Counter(x for edges in ways.values() for _, a, b in edges for x in {a, b})
        extra = sorted(ways.keys() - primary.keys(), key=lambda v: (-demand[v], v))
        first_extra=len(inputs)
        inputs.extend(extra[:closure])
        for i in range(first_extra,len(inputs)):
            close_input(i,inputs[i])
    return primary, ways


def extract(p, tape, menu, trials, seconds, free):
    _, best, _ = solve(p, [tape], trials, seconds, candidate_bank=menu)
    if free:
        _, other, _ = solve_free(p, [tape], trials, seconds, candidate_bank=menu)
        if len(other) < len(best):
            best = other
    check(p, best)
    return best


def save(output, selected, wins, rows, config, start):
    write_submission(output, [p for p in selected if p.id in wins], wins)
    totals=dict(sum((Counter(row) for row in rows.values()),Counter()))
    report=dict(**config, seconds=monotonic()-start, complete=len(selected)==len(rows),
                totals=totals,rows=rows)
    atomic_text(output.with_suffix('.json'),json.dumps(report,indent=2)+'\n')
    return totals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--ids', type=Path, required=True)
    parser.add_argument('--width', type=int, default=104)
    parser.add_argument('--cuts', type=int, default=16)
    parser.add_argument('--retire', type=int, default=0)
    parser.add_argument('--tails', type=int, default=6)
    parser.add_argument('--capacity', type=int, default=12)
    parser.add_argument('--hubs', type=int, default=0)
    parser.add_argument('--repeated',type=int,default=0,
                        help='Additional reverse queries for repeated-operand suffixes per cut')
    parser.add_argument('--quadratic',type=int,default=0,
                        help='Additional exact quadratic suffix queries per cut')
    parser.add_argument('--quadratic-offsets',type=int,default=0,
                        help='Also invert quadratic suffixes of this many nearby residuals')
    parser.add_argument('--shallow-first',action='store_true',
                        help='Check one-step against two-step values for a much larger set of inverse targets')
    parser.add_argument('--closure', type=int, default=160)
    parser.add_argument('--trials', type=int, default=2)
    parser.add_argument('--seconds', type=float, default=.2)
    parser.add_argument('--free', action='store_true')
    parser.add_argument('--controls', action='store_true')
    a = parser.parse_args()
    ids = set(a.ids.read_text().split())
    selected = [p for p in read_puzzles(ROOT/'data/puzzles.csv') if p.id in ids]
    if len(selected) != len(ids):
        raise ValueError('unknown puzzle ID')
    base = read_submission(a.base)
    if min(a.hubs,a.repeated,a.quadratic,a.quadratic_offsets)<0: parser.error('search sizes must be nonnegative')
    if min(a.retire,a.cuts)<0 or not 1<=a.cuts+a.retire<=32:
        parser.error('The total number of cuts must be between 1 and 32')
    engine = PooledEngine(a.output.parent,a.hubs)
    rows = {}
    wins = {}
    start = monotonic()
    settings = {k:v for k,v in vars(a).items() if k not in ('ids','output','base')}
    config=dict(parent=sha256(a.base),ids=sha256(a.ids),settings=settings,table_builder=table_builder.__name__,
                sources={k:sha256(ROOT/k) for k in ('witness_portfolio.py','pooled_joins.py',
                         'pooled_joins.cl','generative/component_select.py','generative/reachability_select.py')})
    if a.quadratic:config['sources']['quadratic_suffix.py']=sha256(ROOT/'quadratic_suffix.py')
    for p in selected:
        parent = base[p.id]
        witnesses = {}
        paired, scan = optimize(p, parent, engine, a.width, a.cuts, a.tails, a.capacity,
                                alternate=True, table_builder=table_builder, share=True,
                                reprice=True, witnesses=witnesses,retire=a.retire,shallow_first=a.shallow_first,
                                repeated=a.repeated,quadratic=a.quadratic,quadratic_offsets=a.quadratic_offsets)
        menu = candidates(p, paired, witnesses, a.closure)
        picked = extract(p, paired, menu, a.trials, a.seconds, a.free)
        row = dict(parent=len(parent), paired=len(paired), selected=len(picked),
                   values=len(menu[1]), edges=sum(map(len,menu[1].values())),
                   probes=scan.get('probes',0))
        if a.quadratic:row['quadratic_queries']=scan.get('quadratic_queries',0)
        if a.hubs:
            row.update(shared_values=scan.get('shared_values',0),extra_matches=scan.get('extra_matches',0))
        if a.controls:
            base_menu = candidates(p, paired, {}, a.closure)
            control = extract(p, paired, base_menu, a.trials, a.seconds, a.free)
            row['without_witnesses'] = len(control)
            if len(control) < len(picked):
                picked = control
        row['best'] = len(picked)
        rows[p.id] = row
        if len(picked) < len(parent):
            wins[p.id] = picked
            print(p.id, len(parent), len(paired), len(picked), flush=True)
        if len(rows)%64==0 and len(rows)<len(selected):
            save(a.output,selected,wins,rows,config,start)
    totals=save(a.output,selected,wins,rows,config,start)
    print(len(rows),totals,flush=True)

if __name__ == '__main__':
    main()
