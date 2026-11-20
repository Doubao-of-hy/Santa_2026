"""Minimize the union of intermediates reachable through a finite set of recorded recipes."""
from collections import defaultdict
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from elf import check, replay
from graph import active_graph, compile_graph, first_recipes


def bits(mask):
    while mask:
        bit = mask & -mask
        yield bit.bit_length()-1
        mask ^= bit


def search(p, parents, budget, extra=None):
    parents = sorted(parents, key=len)
    best_tape = parents[0]
    inputs = set(p.seeds)
    ways = defaultdict(dict)
    for tape in parents:
        for value,op,a,b in replay(p,tape):
            if value in inputs or value in (a,b):
                continue
            key = tuple(sorted(set((a,b)) - inputs))
            ways[value].setdefault(key,(op,a,b))
    for value,op,a,b in extra or ():
        if value not in inputs and value not in (a,b):
            key = tuple(sorted(set((a,b)) - inputs))
            ways[value].setdefault(key,(op,a,b))
    values = sorted(ways)
    index = {v:i for i,v in enumerate(values)}
    edges = [list(ways[v].values()) for v in values]
    pairs = [[sum(1<<index[a] for a in key) for key in ways[v]] for v in values]
    forced = [1<<i for i in range(len(values))]
    # Least fixed point. Every rooted derivation must contain these values, even
    # when the union of different parents also admits cyclic choices.
    while True:
        changed = False
        required = []
        for i,options in enumerate(pairs):
            costs = []
            for pair in options:
                mask = 0
                for j in bits(pair):
                    mask |= forced[j]
                costs.append(mask)
            required.append(costs)
            common = costs[0]
            for cost in costs[1:]:
                common &= cost
            new = forced[i] | common
            if new!=forced[i]:
                forced[i]=new
                changed = True
        if not changed:
            break
    targets = 0
    for v in set(p.targets)-inputs:
        targets |= forced[index[v]]
    choice_nodes = sum(1<<i for i,options in enumerate(pairs) if len(options)>1)
    picks = [0]*len(values)
    best_graph = min(len(active_graph(p,first_recipes(p,t))) for t in parents)
    calls = leaves = bad_cycles = scheduled = 0
    stopped = False
    # Near-identical parents reuse the same deterministic subgraphs. First
    # expose discretionary values required by many other recipes.
    freq = [0]*len(values)
    for options in pairs:
        for pair in options:
            for j in bits(pair):freq[j]+=1

    def visit(need, open_choices):
        nonlocal best_tape,best_graph,calls,leaves,bad_cycles,scheduled,stopped
        if calls>=budget:
            stopped=True
            return
        calls+=1
        count=need.bit_count()
        if count>=len(best_tape):
            return
        pending=need & open_choices
        if not pending:
            leaves+=1
            recipes={values[i]:edges[i][picks[i]] for i in bits(need)}
            try:
                actual=active_graph(p,recipes)
            except (KeyError,ValueError):
                bad_cycles+=1
                return
            best_graph=min(best_graph,len(actual))
            if len(actual)<len(best_tape):
                candidate=compile_graph(p,actual,attempts=5)
                if candidate is not None and len(candidate)<len(best_tape):
                    check(p,candidate)
                    best_tape=candidate
                    scheduled+=1
            return
        decision=None
        for i in bits(pending):
            options=[]
            for j,cost in enumerate(required[i]):
                additional=cost & ~need
                n=additional.bit_count()
                if count+n<len(best_tape):
                    options.append((n,j,additional))
            if not options:
                return
            mi=min(x[0] for x in options)
            key=(len(options)==1,mi,max(x[0] for x in options),freq[i],-len(options))
            if decision is None or key>decision[0]:
                decision=(key,i,options)
                if len(options)==1:
                    break
        _,i,options=decision
        rest=open_choices ^ (1<<i)
        for _,j,add in sorted(options):
            picks[i]=j
            visit(need|add,rest)
            if stopped:
                break
        picks[i]=0

    visit(targets,choice_nodes)
    return best_tape,dict(before=len(parents[0]),after=len(best_tape),graph_upper=best_graph,
                          root_lower=targets.bit_count(),values=len(values),choices=choice_nodes.bit_count(),
                          nodes=calls,leaves=leaves,cycles=bad_cycles,adopted=scheduled,complete=not stopped)
