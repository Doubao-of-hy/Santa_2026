"""Reselect a circuit from its incumbent and up to three supplied donor CSVs.

Each donor must have been generated independently from the official inputs.
This tool checks file shape, puzzle IDs and arithmetic, not provenance.
It only reads explicit paths. OPTIMAL applies to a screened finite recipe
bank and is not a proof of the puzzle's shortest legal register program.
"""

import argparse
import csv
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from itertools import combinations_with_replacement
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import time

from scc_select import arithmetic, canonical, incumbent_bank, load_solver, optimize
from checkpoint import independent_score
from elf import check, read_puzzles, read_submission, score, sha256, write_submission
from graph import active_graph, first_recipes

CAP_VALUES = 24
CAP_BUILD = 4
CAP_CROSS = 5



def rankbank(p, tape, donors):
    pri,ways=incumbent_bank(p,tape)
    targets=set(p.targets)
    roots=set(p.seeds)
    present=set(pri)|roots
    novelty=set()
    for q in donors:
        check(p,q)
        novelty.update(active_graph(p,first_recipes(p,q)).keys()-present)
    incoming=defaultdict(list)
    observed=tuple(dict.fromkeys((*p.seeds,*pri))); pos={v:i for i,v in enumerate(observed)}
    for a,b in combinations_with_replacement(observed,2):
        for v,r in arithmetic(a,b,p.limit):
            if v in novelty:incoming[v].append(canonical(r))
    use=Counter(x for _,a,b in pri.values() for x in {a,b})+Counter(targets)
    for v,rs in incoming.items():
        rs.sort(key=lambda r:(len(set(r[1:])-roots), sum(pos[x] for x in set(r[1:])),r))
        incoming[v]=list(dict.fromkeys(rs))[:CAP_BUILD]
    results=[]
    for h,build in sorted(incoming.items()):
        links=defaultdict(list)
        for a in observed:
            for v,r in arithmetic(h,a,p.limit):
                if v not in pri or v==a:continue
                r=canonical(r)
                # Price this replacement against the complete incumbent DAG.
                # Using an existing input is not free if the choice keeps it live.
                old=set(pri[v][1:]); need=set(r[1:])-set((h,))
                shallow=sum(use[x]==1 and x not in roots for x in old-need)
                links[v].append((shallow,r))
        distinct=len(links)
        if distinct<2 and not any(s for rs in links.values() for s,r in rs):continue
        # Rank outgoing edges using cheap single-substitution evaluation.
        # Prospective combinations still undergo joint exact node costing.
        def estimate(v,r):
            drops=defaultdict(int)
            for x in set(pri[v][1:]):drops[x]+=1
            for x in set(r[1:])-{h}:drops[x]-=1
            top=-999
            for acquire in build:
                diff=drops.copy()
                for x in set(acquire[1:]):diff[x]-=1
                fringe=[x for x in diff if x in pri and diff[x]==use[x]]
                seen=set()
                while fringe:
                    x=fringe.pop()
                    if x in seen:continue
                    seen.add(x)
                    if x==v:continue
                    for z in set(pri[x][1:]):
                        diff[z]+=1
                        if z in pri and z not in seen and diff[z]==use[z]:
                            fringe.append(z)
                top=max(top,len(seen-{v})-1)
            return top
        ranking=[]
        for v,rs in links.items():
            for s,r in set(rs):ranking.append((estimate(v,r),s,int(v in targets),v,r))
        ranking.sort(reverse=True)
        chosen={}
        for e in ranking:
            chosen.setdefault(e[3],e)
            if len(chosen)>=CAP_CROSS:break
        strongest=max(chosen.values())
        if distinct<2 and strongest[0]<1:continue
        benefit=(strongest[0],sum(x[0]>-1 for x in chosen.values()),min(distinct,9),sum(x[1] for x in chosen.values()),-h.bit_length())
        results.append((benefit,h,build,tuple((v,e[-1]) for v,e in chosen.items())))
    results.sort(reverse=True)
    for _,h,build,links in results[:CAP_VALUES]:
        ways[h]=set(build)
        for v,r in links:ways[v].add(r)
    return pri,ways,{'offered_donor_values':len(novelty),'onehop_donor_values':len(incoming),
                     'screened_donor_values':len(results),'kept_donor_values':min(CAP_VALUES,len(results)),
                     'cap_donor_values':CAP_VALUES,'cap_build_each':CAP_BUILD,'cap_cross_each':CAP_CROSS,
                     'old_active_values':len(pri),'bank_values':len(ways),
                     'bank_recipes':sum(map(len,ways.values())),
                     'max_recipes_per_node_actual':max(map(len,ways.values()),default=0)}

def load_donors(paths, puzzles):
    """Reject malformed rows and unknown IDs instead of silently skipping them."""
    donors = []
    for path in paths:
        rows = read_submission(path)
        if not rows:
            raise ValueError(f"{path}: empty donor CSV")
        if unknown := sorted(rows.keys() - puzzles.keys()):
            raise ValueError(f"{path}: unknown donor puzzle ID {unknown[0]!r}")
        for pid, tape in rows.items():
            try:
                check(puzzles[pid], tape)
            except ValueError as e:
                raise ValueError(f"{path}: illegal donor row: {e}") from e
        donors.append(rows)
    return donors


def optimize_one(task):
    puzzle, incumbent, donors, seconds = task
    start = time.process_time()
    if not donors:
        return puzzle.id, incumbent, {"status": "NO_DONOR", "before": len(incumbent),
                                     "after": len(incumbent), "cpu_seconds": 0}
    primary, ways, limits = rankbank(puzzle, incumbent, donors)
    if not ways:
        tape, result = incumbent, {"status": "TRIVIAL", "finite_bank_node_lower_bound": 0}
    else:
        tape, result = optimize(puzzle, incumbent, primary, ways, seconds)
    check(puzzle, tape)
    if len(tape) > len(incumbent):
        raise ValueError(f"{puzzle.id}: candidate regressed")
    used = active_graph(puzzle, first_recipes(puzzle, tape))
    result.update(limits, before=len(incumbent), after=len(tape), donors=len(donors),
                  used_bank_values=len(used), selected_new_values=len(used.keys() - primary.keys()),
                  cpu_seconds=round(time.process_time() - start, 6))
    return puzzle.id, tape, result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("puzzles", type=Path, help="Official puzzle CSV")
    parser.add_argument("incumbent", type=Path, help="Complete independently generated submission")
    parser.add_argument("output", type=Path, help="New complete CSV; must not exist")
    parser.add_argument("--donor", type=Path, action="append", required=True,
                        help="Explicit independent donor CSV, complete or partial (repeat up to 3 times)")
    parser.add_argument("--ids-file", type=Path, help="Optional file containing case IDs")
    parser.add_argument("--seconds", type=float, default=1.5, help="Maximum CP-SAT wall seconds per case")
    parser.add_argument("--jobs", type=int, default=1, help="Concurrent cases using one SAT worker each")
    a = parser.parse_args(argv)
    if not 1 <= len(a.donor) <= 3 or len({p.resolve() for p in a.donor}) != len(a.donor):
        parser.error("supply one to three distinct donor CSV paths")
    if a.jobs < 1 or not math.isfinite(a.seconds) or a.seconds <= 0:
        parser.error("positive --jobs and finite positive --seconds are required")
    inputs = {path.resolve() for path in (a.puzzles, a.incumbent, a.ids_file, *a.donor)
              if path is not None}
    if a.output.resolve() in inputs or a.output.exists() or a.output.is_symlink():
        parser.error("output must be a different, unused path")
    if not a.output.parent.is_dir():
        parser.error("output parent directory does not exist")
    try:
        puzzles = read_puzzles(a.puzzles)
        by_id = {p.id: p for p in puzzles}
        prior = read_submission(a.incumbent)
        prior_score = score(puzzles, prior)
        selected = a.ids_file.read_text(encoding="utf-8").split() if a.ids_file else list(prior)
        ids = set(selected)
        if not ids or ids - prior.keys() or len(ids) != len(selected):
            raise ValueError("IDs must be a nonempty subset of known puzzle IDs with no duplicates")
        explicit = load_donors(a.donor, by_id)
    except (ValueError, OSError, csv.Error, RecursionError) as e:
        parser.error(str(e))
    try:
        load_solver()
    except ImportError:
        parser.error("requires OR-Tools, tested with 9.15.6755")

    work = [(p, prior[p.id], tuple(d[p.id] for d in explicit if p.id in d), a.seconds)
            for p in puzzles if p.id in ids]
    best = dict(prior)
    with ProcessPoolExecutor(a.jobs) as pool:
        for identifier, tape, report in pool.map(optimize_one, work, chunksize=1):
            print(json.dumps({"id": identifier, **report}), flush=True)
            if len(tape) < len(best[identifier]):
                best[identifier] = tape

    with TemporaryDirectory(dir=a.output.parent, prefix=".donor-select-") as d:
        candidate = Path(d) / "candidate.csv"
        result = write_submission(candidate, puzzles, best)
        secondary = independent_score(a.puzzles, candidate)
        if secondary != sorted(map(len, best.values())) or sum(secondary) != result or result > prior_score:
            raise ValueError("complete candidate failed independent replay")
        # Exclusive open prevents accidentally overwriting a file created by
        # another process since argument validation. Bytes have been replayed.
        with a.output.open("xb") as out:
            out.write(candidate.read_bytes())
    print(json.dumps(dict(prior=prior_score, score=result, saved=prior_score-result,
                          improved=sum(len(best[k]) < len(prior[k]) for k in ids),
                          replayed=len(puzzles), sha256=sha256(a.output), scope="finite_recipe_bank")),
          flush=True)


if __name__ == "__main__":
    main()

