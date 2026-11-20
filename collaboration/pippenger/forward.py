"""Construct a whole puzzle from signed digits and transposed equal-column buckets."""
from collections import defaultdict
from itertools import zip_longest


def digits(value, base, limit):
    original = value
    row = []
    while value:
        q, r = divmod(value, base)
        if (base == 2 and r and q % 2) or (base > 2 and 2 * r > base):
            r -= base
            q += 1
        row.append(r)
        value = q
    if sum(max(0, digit) * base ** j for j, digit in enumerate(row)) <= limit:
        return row
    row = []
    while original:
        original, r = divmod(original, base)
        row.append(r)
    return row


class Builder:
    def __init__(self, puzzle):
        self.p = puzzle
        self.known = set(puzzle.seeds)
        self.graph = {}
        self.saved_columns = 0

    def emit(self, value, op, left, right):
        assert 1 <= value <= self.p.limit
        if value not in self.known:
            assert left in self.known and right in self.known
            self.graph[value] = op, left, right
            self.known.add(value)
        return value

    def add(self, x, y):
        return self.emit(x + y, "+", x, y)

    def total(self, values):
        values = list(values)
        if not values:
            return None
        out = values[0]
        for value in values[1:]:
            out = self.add(out, value)
        return out

    def constant(self, value):
        if value not in self.known:
            if value == 1:
                seed = self.p.seeds[0]
                self.emit(1, "/", seed, seed)
            else:
                half = self.constant(value // 2)
                even = self.add(half, half)
                if value % 2:
                    self.add(even, self.constant(1))
        return value

    def weighted(self, groups, control):
        if not groups:
            return None
        if control:
            terms = []
            for digit, subtotal in groups:
                if digit > 1:
                    subtotal = self.emit(digit * subtotal, "*", subtotal, self.constant(digit))
                terms.append(subtotal)
            return self.total(terms)
        bins = defaultdict(list)
        for digit, subtotal in groups:
            bins[digit].append(subtotal)
        running = None
        contributions = []
        for digit in range(max(bins), 0, -1):
            layer = self.total(bins[digit])
            if layer is not None:
                running = layer if running is None else self.add(running, layer)
            contributions.append(running)
        return self.total(contributions)

    def build(self, base, block_size, control):
        targets = sorted(set(self.p.targets) - set(self.p.seeds))
        rows = [digits(t, base, self.p.limit) for t in targets]
        count = max(map(len, rows), default=0)
        weights = [self.constant(1)] if count else []
        for _ in range(1, count):
            old = weights[-1]
            weights.append(self.emit(base * old, "*", old, self.constant(base)))
        for low in range(0, len(rows), block_size):
            chunk = rows[low:low + block_size]
            buckets = defaultdict(list)
            for j, column in enumerate(zip_longest(*chunk, fillvalue=0)):
                if any(column):
                    buckets[(column, j if control else None)].append(weights[j])
            vectors = []
            for (column, _), values in buckets.items():
                self.saved_columns += len(values) - 1
                vectors.append((column, self.total(values)))
            for k in range(len(chunk)):
                pos = self.weighted([(col[k], s) for col, s in vectors if col[k] > 0], control)
                neg = self.weighted([(-col[k], s) for col, s in vectors if col[k] < 0], control)
                out = pos if neg is None else self.emit(pos - neg, "-", pos, neg)
                assert out == targets[low + k]
        return self.graph
