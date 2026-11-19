"""Prototype: value-DAG dedup + DCE + cheap alternative-derivation rewriting.

Goal: measure how much headroom exists in current programs before investing
in a fast native implementation. Operates on distinct integer values.
"""
import json, sys, collections
from pathlib import Path
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
import elf

OPS = ("+", "-", "*", "/")

def apply(op, a, b):
    if op == "+": return a + b
    if op == "-": return a - b
    if op == "*": return a * b
    if b == 0 or a % b: return None
    return a // b


class DAG:
    def __init__(self, puzzle, prog):
        self.p = puzzle
        self.limit = puzzle.limit
        self.seeds = set(puzzle.seeds)
        self.targets = set(puzzle.targets)
        # value -> (op, a, b) definition; seeds -> None
        self.defn = {s: None for s in self.seeds}
        regs = list(puzzle.seeds) + [0] * (48 - len(puzzle.seeds))
        for op, l, r, d in prog:
            a, b = regs[l], regs[r]
            v = apply(op, a, b)
            regs[d] = v
            if v not in self.defn:
                self.defn[v] = (op, a, b)
        self.required = set(self.targets)

    def live(self):
        """Values needed to produce all targets (ancestors via definitions)."""
        seen = set()
        stack = list(self.required)
        while stack:
            v = stack.pop()
            if v in seen: continue
            seen.add(v)
            d = self.defn.get(v)
            if d:
                stack.append(d[1]); stack.append(d[2])
        return seen

    def length(self):
        return len(self.live() - self.seeds)

    def ranks(self):
        """min ops from seeds assuming current definitions (tree cost lower bd)."""
        live = self.live()
        rank = {s: 0 for s in self.seeds}
        # topo by dependency
        order = []
        visited = set()
        def visit(v):
            if v in visited: return
            visited.add(v)
            d = self.defn.get(v)
            if d:
                visit(d[1]); visit(d[2])
            order.append(v)
        for v in live: visit(v)
        for v in order:
            d = self.defn.get(v)
            if d:
                rank[v] = 1 + rank.get(d[1], 99) + rank.get(d[2], 99)
        return rank, live


def rewrite(dag, rounds=6):
    improved_total = 0
    for it in range(rounds):
        rank, live = dag.ranks()
        V = sorted(live)
        vset = set(V)
        # pair result -> (a,b,op)  (only pairs of live values)
        pair = {}
        for a in V:
            for b in V:
                for op in OPS:
                    v = apply(op, a, b)
                    if v is None or v < 1 or v > dag.limit: continue
                    if v not in pair:
                        pair[v] = (a, b, op)
        # try to find cheaper definition for each live non-seed value
        best_gain = 0
        best_move = None
        for v in V:
            if v in dag.seeds: continue
            cur = dag.defn[v]
            cur_cost = 1 + rank.get(cur[1], 99) + rank.get(cur[2], 99)
            # 1-op alternative using cheaper parents
            for op in OPS:
                pass
            # 2-op: v = X op c or c op X, X a pair result
            for c in V:
                cands = []
                # X + c = v -> X = v-c
                cands.append((v - c, "+", c, False))
                # X - c = v -> X = v+c
                cands.append((v + c, "-", c, False))
                # c - X = v -> X = c-v
                cands.append((c - v, "-", c, True))
                # X * c = v -> X = v/c
                if c and v % c == 0: cands.append((v // c, "*", c, False))
                # X / c = v -> X = v*c
                cands.append((v * c, "/", c, False))
                # c / X = v -> X = c/v
                if v and c % v == 0: cands.append((c // v, "/", c, True))
                for X, op, cc, rev in cands:
                    if X not in pair: continue
                    a, b, op2 = pair[X]
                    if X in dag.seeds:  # actually 1-op
                        cost = 1 + rank.get(a, 99) + rank.get(cc, 99)
                    else:
                        cost = 2 + rank.get(a, 99) + rank.get(b, 99) + rank.get(cc, 99)
                    # only count if intermediate X is new or already live
                    gain = cur_cost - cost
                    if gain > best_gain:
                        best_gain = gain
                        best_move = (v, a, b, op2, cc, op, rev, X)
        if best_move is None or best_gain <= 0:
            break
        v, a, b, op2, c, op, rev, X = best_move
        # install: ensure X defined (if not seed/live), then v = X op c (or c op X)
        if X not in dag.defn:
            dag.defn[X] = (op2, a, b)
        if rev:
            dag.defn[v] = (op, c, X)
        else:
            dag.defn[v] = (op, X, c)
        improved_total += best_gain
    return improved_total


def main():
    puzzles = {p.id: p for p in elf.read_puzzles(root / "data/puzzles.csv")}
    progs = elf.read_submission(root / "improve/merged/submission.csv")
    ids = sys.argv[1:] or list(puzzles)[:15]
    tot_orig = tot_dedup = tot_rw = 0
    for pid in ids:
        p = puzzles[pid]
        prog = progs[pid]
        dag = DAG(p, prog)
        orig = len(prog)
        dedup = dag.length()
        g = rewrite(dag)
        rw = dag.length()
        tot_orig += orig; tot_dedup += dedup; tot_rw += rw
        print(f"{pid}: orig={orig} dedup+DCE={dedup} rewrite={rw} (gain {orig-rw})")
    print(f"TOTAL orig={tot_orig} dedup={tot_dedup} rewrite={tot_rw}")

if __name__ == "__main__":
    main()