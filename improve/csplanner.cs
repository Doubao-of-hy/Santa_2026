// Independent C# port of the core LiveBank dictionary + TargetSearch beam planner.
// Matches the native stdin/stdout interface used by virtual_search.py / matrix_construct.py.
// C# 5 compatible (compiles with .NET Framework csc).
// Build: csc -nologo -optimize -platform:x64 -out:work\virtual\csplanner.exe improve\csplanner.cs
// SPDX-License-Identifier: Apache-2.0
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;

static class P {
    public const char NONE = '\0';
    public static long Apply(char op, long a, long b) {
        if (op == '+') return a + b;
        if (op == '-') return a - b;
        if (op == '*') return a * b;
        if (op == '/') return a / b;
        throw new Exception("bad op");
    }
}

class Node { public long v; public int a, b; public char op; public int cost; }
class Edge { public long outv, a, b; public char op; }

class LiveBank {
    public long limit; public int maxEntries;
    public Dictionary<long, int> index = new Dictionary<long, int>();
    public List<Node> nodes = new List<Node>();
    public List<int> zero = new List<int>(), one = new List<int>();
    public List<KeyValuePair<long, int>>[] near = new List<KeyValuePair<long, int>>[3];
    public List<KeyValuePair<long, int>>[] fresh = new List<KeyValuePair<long, int>>[3];
    public List<int> moduli = new List<int> { 16, 81, 125, 256, 1024, 4096 };
    public List<List<List<int>>> columns = new List<List<List<int>>>();
    public Dictionary<long, List<long>> divisorCache = new Dictionary<long, List<long>>();
    HashSet<long> missingThree = new HashSet<long>();
    public bool joinMode2 = true, joinMode1 = true;
    int tLeft, tRight; char tOp;

    public LiveBank(long cap, int maxE) {
        limit = cap; maxEntries = maxE;
        for (int i = 0; i < 3; i++) { near[i] = new List<KeyValuePair<long, int>>(); fresh[i] = new List<KeyValuePair<long, int>>(); }
    }
    public int Get(long v) { int id; return index.TryGetValue(v, out id) ? id : -1; }
    public void Remember(long v, int a, int b, char op, int price) {
        if (v < 1 || v > limit) return;
        int id = Get(v);
        if (id < 0) {
            if (price == 2 && nodes.Count >= maxEntries) return;
            id = nodes.Count; index[v] = id;
            nodes.Add(new Node { v = v, a = a, b = b, op = op, cost = price });
        } else {
            if (nodes[id].cost <= price) return;
            nodes[id] = new Node { v = v, a = a, b = b, op = op, cost = price };
        }
        if (price == 0) zero.Add(id);
        if (price == 1) one.Add(id);
        fresh[price].Add(new KeyValuePair<long, int>(v, id));
    }
    public void Join(int i, int j, int price) {
        long a = nodes[i].v, b = nodes[j].v;
        Remember(a + b, i, j, '+', price);
        if (a > b) { Remember(a - b, i, j, '-', price); if (a % b == 0) Remember(a / b, i, j, '/', price); }
        if (b > a) { Remember(b - a, j, i, '-', price); if (b % a == 0) Remember(b / a, j, i, '/', price); }
        if (a <= limit / b) Remember(a * b, i, j, '*', price);
    }
    public void Extend(List<long> values) {
        missingThree.Clear();
        int first = zero.Count, old1 = one.Count;
        foreach (long v in values) Remember(v, -1, -1, P.NONE, 0);
        for (int i = first; i < zero.Count; i++)
            for (int j = 0; j <= i; j++) Join(zero[i], zero[j], 1);
        for (int i = 0; i < one.Count; i++) {
            if (nodes[one[i]].cost != 1) continue;
            int start = i < old1 ? first : 0;
            for (int j = start; j < zero.Count; j++) Join(one[i], zero[j], 2);
        }
        for (int price = 0; price < 3; price++) {
            var added = fresh[price]; var old = near[price];
            if (added.Count == 0) continue;
            added.Sort(delegate(KeyValuePair<long, int> x, KeyValuePair<long, int> y) { return x.Key.CompareTo(y.Key); });
            if (old.Count == 0) { near[price] = added; fresh[price] = new List<KeyValuePair<long, int>>(); continue; }
            old.AddRange(added);
            old.Sort(delegate(KeyValuePair<long, int> x, KeyValuePair<long, int> y) { return x.Key.CompareTo(y.Key); });
            added.Clear();
        }
        if (joinMode2) {
            columns.Clear();
            for (int j = 0; j < moduli.Count; j++) {
                int m = moduli[j];
                if (Get(m) < 0) { columns.Add(new List<List<int>>()); continue; }
                var col = new List<List<int>>(m);
                for (int k = 0; k < m; k++) col.Add(new List<int>());
                foreach (var e in near[2]) col[(int)(e.Key % m)].Add(e.Value);
                columns.Add(col);
            }
        }
    }
    void TryJoin(long y, int id, char operation, bool reverse) {
        if (tOp != P.NONE || y < 1 || y > limit) return;
        int j = Get(y);
        if (j >= 0 && nodes[j].cost + nodes[id].cost <= 2) {
            tLeft = reverse ? j : id; tRight = reverse ? id : j; tOp = operation;
        }
    }
    public int Third(long x) {
        if (x < 1 || x > limit) return -1;
        int known = Get(x);
        if (known >= 0 || missingThree.Contains(x)) return known;
        tLeft = -1; tRight = -1; tOp = P.NONE;
        foreach (int i in zero) {
            long a = nodes[i].v;
            TryJoin(x - a, i, '+', false); if (tOp != P.NONE) break;
            TryJoin(a - x, i, '-', false); if (tOp != P.NONE) break;
            if (x <= limit - a) { TryJoin(x + a, i, '-', true); if (tOp != P.NONE) break; }
            if (a > 1 && x % a == 0) { TryJoin(x / a, i, '*', false); if (tOp != P.NONE) break; }
            if (a > x && a % x == 0) { TryJoin(a / x, i, '/', false); if (tOp != P.NONE) break; }
            if (a > 1 && x <= limit / a) { TryJoin(x * a, i, '/', true); if (tOp != P.NONE) break; }
        }
        if (tOp == P.NONE) { if (missingThree.Count < 250000) missingThree.Add(x); return -1; }
        int nid = nodes.Count; index[x] = nid;
        nodes.Add(new Node { v = x, a = tLeft, b = tRight, op = tOp, cost = 1 + nodes[tLeft].cost + nodes[tRight].cost });
        return nid;
    }
    public void Materialize(int i, List<Edge> outp, HashSet<long> seen) {
        var x = nodes[i];
        if (x.cost == 0 || !seen.Add(x.v)) return;
        Materialize(x.a, outp, seen); Materialize(x.b, outp, seen);
        outp.Add(new Edge { outv = x.v, a = nodes[x.a].v, b = nodes[x.b].v, op = x.op });
    }
    public List<long> Divisors(long n) {
        List<long> res;
        if (divisorCache.TryGetValue(n, out res)) return res;
        res = new List<long>();
        for (long d = 1; d * d <= n && d <= 200000; d++) {
            if (n % d == 0) { res.Add(d); if (d != n / d) res.Add(n / d); }
            if (res.Count > 400) break;
        }
        res.Sort(); divisorCache[n] = res; return res;
    }
}

class Path {
    public long rem; public int cost, parent, scale, bias; public char sign; public double rank;
    public int compound = -1, exponent = 1, shift = -1, denominator = -1;
}

class TargetSearch {
    public LiveBank bank; public int width, upper, bestNode = -1, terminal = -1; public double alpha;
    public List<Path> paths = new List<Path>(), next = new List<Path>();
    public Dictionary<long, int> visited = new Dictionary<long, int>();
    public TargetSearch(LiveBank d, int w, int ceiling, double a) { bank = d; width = w; upper = ceiling; alpha = a; }
    public void Offer(int parent, long rem, int scale, int bias, char sign, int compound, int exponent, int shift, int denominator) {
        if (rem < 1 || rem > bank.limit) return;
        int cost = paths[parent].cost;
        if (scale >= 0) cost += 1 + bank.nodes[scale].cost;
        if (bias >= 0) cost += 1 + bank.nodes[bias].cost;
        if (compound >= 0) cost += 1 + (compound == bias ? 0 : bank.nodes[compound].cost);
        if (exponent > 1) cost += exponent == 2 ? 1 : 2;
        if (shift >= 0) cost += 2 + bank.nodes[shift].cost;
        if (denominator >= 0) cost += 1 + (denominator == bias || denominator == scale ? 0 : bank.nodes[denominator].cost);
        if (cost >= upper) return;
        int final = bank.Get(rem);
        if (final >= 0) {
            cost += bank.nodes[final].cost;
            if (cost >= upper) return;
            if (cost < upper) { upper = cost; terminal = final; bestNode = paths.Count; }
            paths.Add(new Path { rem = rem, cost = cost, parent = parent, scale = scale, bias = bias, sign = sign, compound = compound, exponent = exponent, shift = shift, denominator = denominator });
            return;
        }
        if (rem >= paths[parent].rem || cost + 3 >= upper) return;
        double rank = cost + alpha * Math.Log(rem, 2);
        if (next.Count == width && rank >= next[next.Count - 1].rank) return;
        int vc;
        if (visited.TryGetValue(rem, out vc) && vc <= cost) return;
        for (int k = 0; k < next.Count; k++) if (next[k].rem == rem) { if (next[k].cost <= cost) return; next.RemoveAt(k); break; }
        int pos = next.FindIndex(delegate(Path pp) { return pp.rank > rank; });
        if (pos < 0) pos = next.Count;
        next.Insert(pos, new Path { rem = rem, cost = cost, parent = parent, scale = scale, bias = bias, sign = sign, rank = rank, compound = compound, exponent = exponent, shift = shift, denominator = denominator });
        if (next.Count > width) next.RemoveAt(next.Count - 1);
    }
    void Offer(int parent, long rem, int scale, int bias, char sign) { Offer(parent, rem, scale, bias, sign, -1, 1, -1, -1); }
    void Offset(int p, long rem, int id, char sign) {
        if (rem == 0) return;
        if (bank.Get(rem) >= 0) Offer(p, rem, -1, id, sign);
        if ((rem & 15) == 0) {
            int shift = 0; long t = rem; while ((t & 1) == 0) { t >>= 1; shift++; }
            while (shift >= 4) { int factor = bank.Get(1L << shift); if (factor >= 0) { Offer(p, rem >> shift, factor, id, sign); break; } shift--; }
        }
    }
    void Factor(int p, int i) {
        long v = paths[p].rem, a = bank.nodes[i].v;
        if (a <= 1) return;
        Offset(p, Math.Abs(v - a), i, v > a ? '+' : 'r');
        if (a <= bank.limit - v) Offset(p, a + v, i, '-');
        if (a >= v) return;
        long q = v / a, r = v % a;
        if (r == 0) { Offer(p, q, i, -1, '+'); return; }
        int id = bank.Get(r);
        if (id >= 0) Offer(p, q, i, id, '+');
        if (a - r <= bank.limit - v) { id = bank.Get(a - r); if (id >= 0) Offer(p, q + 1, i, id, '-'); }
    }
    void NearProduct(int p, int i) {
        long v = paths[p].rem, a = bank.nodes[i].v;
        if (a < 2 || a >= v / 4) return;
        long q = v / a;
        foreach (var group in bank.near) {
            int at = LowerBound(group, q);
            for (int k = Math.Max(0, at - 1); k < Math.Min(group.Count, at + 2); k++) {
                long b = group[k].Key; int j = group[k].Value;
                if (b < 2 || b > bank.limit / a) continue;
                long product = a * b;
                if (product == v) { Offer(p, b, i, -1, '+'); continue; }
                int existing = bank.Get(product);
                if (existing >= 0) Offer(p, Math.Abs(v - product), -1, existing, v > product ? '+' : 'r');
                else Offer(p, Math.Abs(v - product), -1, i, v > product ? '+' : 'r', j, 1, -1, -1);
            }
        }
    }
    void Congruent(int p) {
        long v = paths[p].rem;
        for (int j = 0; j < bank.columns.Count; j++) {
            if (bank.columns[j].Count == 0) continue;
            long m = bank.moduli[j]; int scale = bank.Get(m);
            if (v < m * 2) continue;
            for (int up = 0; up < 2; up++) {
                var bin = bank.columns[j][(int)(up == 1 ? (m - v % m) % m : v % m)];
                int at = LowerBoundVal(bin, v);
                for (int k = Math.Max(0, at - 4); k < Math.Min(bin.Count, at + 4); k++) EvalCong(bin[k], up, v, m, scale, p);
                for (int k = 0; k < Math.Min(3, bin.Count); k++) EvalCong(bin[k], up, v, m, scale, p);
            }
        }
    }
    void EvalCong(int id, int up, long v, long m, int scale, int p) {
        long a = bank.nodes[id].v;
        if (up == 1) { if (a <= bank.limit - v) Offer(p, (v + a) / m, scale, id, '-'); }
        else if (a != v) Offer(p, Math.Abs(v - a) / m, scale, id, v > a ? '+' : 'r');
    }
    static long FloorSquare(long n) { long x = (long)Math.Sqrt((double)n); while ((x + 1) * (x + 1) <= n) x++; while (x * x > n) x--; return x; }
    void ExactPower(int p, long n, int bias, char sign) {
        if (n < 4) return;
        long x = FloorSquare(n);
        if (x * x == n) { Offer(p, x, -1, bias, sign, -1, 2, -1, -1); long f = FloorSquare(x); if (f * f == x) Offer(p, f, -1, bias, sign, -1, 4, -1, -1); }
        long cube = (long)Math.Round(Math.Pow(n, 1.0 / 3));
        for (long c = Math.Max(2, cube - 1); c <= cube + 1; c++) if (c * c * c == n) Offer(p, c, -1, bias, sign, -1, 3, -1, -1);
    }
    void PowerNeighborhood(int p) {
        long v = paths[p].rem;
        ExactPower(p, v, -1, '+');
        foreach (int i in bank.zero) {
            long a = bank.nodes[i].v;
            if (a != v) ExactPower(p, Math.Abs(v - a), i, v > a ? '+' : 'r');
            if (a <= bank.limit - v) ExactPower(p, a + v, i, '-');
        }
        long center = FloorSquare(v);
        foreach (var level in bank.near) {
            int at = LowerBound(level, center);
            for (int j = Math.Max(0, at - 2); j < Math.Min(level.Count, at + 2); j++) {
                long x = level[j].Key; int id = level[j].Value;
                if (x < 2 || x > bank.limit / x || x * x == v) continue;
                Offer(p, Math.Abs(v - x * x), -1, id, v > x * x ? '+' : 'r', id, 1, -1, -1);
            }
        }
    }
    public void Expand(int p) {
        long v = paths[p].rem;
        foreach (var level in bank.near) {
            int center = LowerBound(level, v);
            for (int k = Math.Max(0, center - 3); k < Math.Min(level.Count, center + 3); k++) {
                long x = level[k].Key; int i = level[k].Value;
                Offer(p, Math.Abs(v - x), -1, i, v > x ? '+' : 'r');
            }
        }
        foreach (int i in bank.zero) { Factor(p, i); if (bank.joinMode1) NearProduct(p, i); }
        foreach (int i in bank.one) if (bank.nodes[i].cost == 1) Factor(p, i);
        if (bank.joinMode2) Congruent(p);
        if (paths[p].cost <= 6) PowerNeighborhood(p);
    }
    public List<Edge> Run(long target, int depthLimit) {
        paths.Add(new Path { rem = target, cost = 0, parent = -1, scale = -1, bias = -1, sign = '+' });
        int direct = bank.Get(target);
        if (direct >= 0) { bestNode = 0; terminal = direct; upper = bank.nodes[direct].cost; }
        if (direct < 0) {
            var frontier = new List<int> { 0 };
            for (int depth = 0; depth < depthLimit && frontier.Count > 0; depth++) {
                next.Clear();
                foreach (int p in frontier) if (paths[p].cost + 3 < upper) Expand(p);
                frontier.Clear();
                foreach (var state in next) if (state.cost + 3 < upper) { visited[state.rem] = state.cost; frontier.Add(paths.Count); paths.Add(state); }
            }
        }
        return Reconstruct(target, bestNode, terminal);
    }
    long NonlinearStage(long x, int exponent, int shift, List<Edge> outp, HashSet<long> seen) {
        if (shift >= 0) {
            bank.Materialize(shift, outp, seen);
            long sum = x + bank.nodes[shift].v;
            if (seen.Add(sum)) outp.Add(new Edge { outv = sum, a = x, b = bank.nodes[shift].v, op = '+' });
            long prod = x * sum;
            if (seen.Add(prod)) outp.Add(new Edge { outv = prod, a = x, b = sum, op = '*' });
            return prod;
        }
        if (exponent == 1) return x;
        long square = x * x;
        if (seen.Add(square)) outp.Add(new Edge { outv = square, a = x, b = x, op = '*' });
        if (exponent == 2) return square;
        long res = exponent == 3 ? square * x : square * square;
        if (seen.Add(res)) outp.Add(new Edge { outv = res, a = square, b = exponent == 3 ? x : square, op = '*' });
        return res;
    }
    public List<Edge> Reconstruct(long target, int lastNode, int lastId) {
        var outp = new List<Edge>();
        if (lastNode < 0) return outp;
        var seen = new HashSet<long>();
        bank.Materialize(lastId, outp, seen);
        long v = bank.nodes[lastId].v;
        for (int p = lastNode; paths[p].parent >= 0; p = paths[p].parent) {
            var s = paths[p];
            v = NonlinearStage(v, s.exponent, s.shift, outp, seen);
            if (s.scale >= 0) { bank.Materialize(s.scale, outp, seen); long a = bank.nodes[s.scale].v; long product = v * a; if (seen.Add(product)) outp.Add(new Edge { outv = product, a = v, b = a, op = '*' }); v = product; }
            if (s.bias >= 0) {
                bank.Materialize(s.bias, outp, seen); long a = bank.nodes[s.bias].v;
                if (s.compound >= 0) { bank.Materialize(s.compound, outp, seen); long b = bank.nodes[s.compound].v; long product = a * b; if (seen.Add(product)) outp.Add(new Edge { outv = product, a = a, b = b, op = '*' }); a = product; }
                long left = s.sign == 'r' ? a : v, right = s.sign == 'r' ? v : a;
                char op = s.sign == 'r' ? '-' : s.sign;
                v = P.Apply(op, left, right);
                if (seen.Add(v)) outp.Add(new Edge { outv = v, a = left, b = right, op = op });
            }
            if (s.denominator >= 0) { bank.Materialize(s.denominator, outp, seen); long d = bank.nodes[s.denominator].v; long before = v; if (v % d != 0) throw new Exception("nonintegral"); v /= d; if (seen.Add(v)) outp.Add(new Edge { outv = v, a = before, b = d, op = '/' }); }
        }
        if (v != target) throw new Exception("invalid reconstruction");
        return outp;
    }
    static int LowerBound(List<KeyValuePair<long, int>> list, long val) {
        int lo = 0, hi = list.Count;
        while (lo < hi) { int mid = (lo + hi) / 2; if (list[mid].Key < val) lo = mid + 1; else hi = mid; }
        return lo;
    }
    int LowerBoundVal(List<int> bin, long v) {
        int lo = 0, hi = bin.Count;
        while (lo < hi) { int mid = (lo + hi) / 2; if (bank.nodes[bin[mid]].v < v) lo = mid + 1; else hi = mid; }
        return lo;
    }
}

class Puzzle {
    public string id; public long limit; public List<long> starts, targets;
    public Dictionary<long, Edge> defs = new Dictionary<long, Edge>();
    public Dictionary<long, char> defop = new Dictionary<long, char>();
    public List<long> order = new List<long>();
    public bool Make(char op, long a, long b) {
        long v = P.Apply(op, a, b);
        if (v < 1 || v > limit) return false;
        if (defs.ContainsKey(v)) return true;
        defs[v] = new Edge { outv = v, a = a, b = b, op = op };
        defop[v] = op; order.Add(v);
        return true;
    }
    public void Commit(List<Edge> plan) {
        foreach (var e in plan) {
            if (!defs.ContainsKey(e.a) || !defs.ContainsKey(e.b)) throw new Exception("ghost operand");
            if (!Make(e.op, e.a, e.b)) throw new Exception("bad make");
        }
    }
}

class Program {
    static Random rng = new Random(17);
    static void AddW(Dictionary<long, double> w, long v, double x) { double cur; w[v] = (w.TryGetValue(v, out cur) ? cur : 0) + x; }
    static List<long> WorkingSet(Puzzle p, Dictionary<long, Edge> warm, List<long> pending, int budget) {
        var weights = new Dictionary<long, double>();
        for (int i = 0; i < p.starts.Count; i++) AddW(weights, p.starts[i], 1000 + (double)(p.starts.Count - i) / Math.Max(1, p.starts.Count));
        for (int i = 0; i < p.order.Count; i++) { long v = p.order[i]; AddW(weights, v, 3.5 * (i + 1) / Math.Max(1, p.order.Count) + rng.Next(1000) / 2000.0); }
        if (warm.Count > 0) foreach (long t in pending) foreach (var e in TracePlan(t, warm, p)) { if (p.defs.ContainsKey(e.a)) AddW(weights, e.a, 2); if (p.defs.ContainsKey(e.b)) AddW(weights, e.b, 2); }
        var order = weights.OrderByDescending(delegate(KeyValuePair<long, double> kv) { return kv.Value; }).ThenBy(delegate(KeyValuePair<long, double> kv) { return kv.Key; }).Select(delegate(KeyValuePair<long, double> kv) { return kv.Key; }).Where(delegate(long v) { return p.defs.ContainsKey(v); }).ToList();
        return order.Take(budget).ToList();
    }
    static void TraceVisit(long v, Dictionary<long, Edge> warm, Puzzle p, List<Edge> result, HashSet<long> seen) {
        if (p.defs.ContainsKey(v) && p.defop[v] == P.NONE) return;
        if (!seen.Add(v)) return;
        Edge e; if (!warm.TryGetValue(v, out e)) return;
        TraceVisit(e.a, warm, p, result, seen);
        TraceVisit(e.b, warm, p, result, seen);
        result.Add(e);
    }
    static List<Edge> TracePlan(long target, Dictionary<long, Edge> warm, Puzzle p) {
        var result = new List<Edge>(); var seen = new HashSet<long>();
        TraceVisit(target, warm, p, result, seen);
        return result;
    }
    static void Setup(Puzzle p) {
        if (!p.defs.ContainsKey(1)) p.Make('/', p.starts[0], p.starts[0]);
        if (!p.defs.ContainsKey(2) && p.limit >= 2) p.Make('+', 1, 1);
        long prev = 2;
        for (int k = 2; k <= 40; k++) { long v = prev * 2; if (v > p.limit || v < prev) break; if (!p.defs.ContainsKey(v)) p.Make('*', prev, 2); prev = v; }
    }
    static void PlanPuzzle(Puzzle p, Dictionary<long, Edge> warm, int leafBudget, int scan, int width, double alpha) {
        foreach (long v in p.starts) { p.defs[v] = new Edge { outv = v, a = v, b = v, op = P.NONE }; p.defop[v] = P.NONE; }
        var pending = new List<long>(p.targets);
        Setup(p);
        var bank = new LiveBank(p.limit, 1800000);
        bank.Extend(WorkingSet(p, warm, pending, leafBudget));
        pending.RemoveAll(delegate(long x) { return p.defs.ContainsKey(x); });
        int guard = 0;
        while (pending.Count > 0 && guard++ < 4000) {
            long bestT = -1; List<Edge> bestPlan = null; int bestCost = int.MaxValue;
            foreach (long t in pending) {
                int ceiling = 40;
                if (warm.Count > 0) { var donor = TracePlan(t, warm, p); ceiling = Math.Min(ceiling, donor.Count + 4); }
                var search = new TargetSearch(bank, scan, ceiling, alpha);
                List<Edge> plan;
                try { plan = search.Run(t, 14); } catch { continue; }
                if (search.bestNode < 0 || plan.Count == 0) continue;
                if (plan.Count < bestCost) { bestCost = plan.Count; bestPlan = plan; bestT = t; }
            }
            if (bestPlan == null) {
                bool progressed = false;
                foreach (long t in pending) {
                    if (warm.Count > 0) { var donor = TracePlan(t, warm, p); if (donor.Count > 0) { try { p.Commit(donor); bank.Extend(new List<long> { t }); progressed = true; break; } catch { } } }
                }
                if (!progressed) break;
                pending.RemoveAll(delegate(long x) { return p.defs.ContainsKey(x); });
                continue;
            }
            try { p.Commit(bestPlan); } catch { pending.Remove(bestT); continue; }
            var newvals = new List<long>();
            foreach (var e in bestPlan) newvals.Add(e.outv);
            bank.Extend(newvals);
            pending.RemoveAll(delegate(long x) { return p.defs.ContainsKey(x); });
        }
    }
    static Dictionary<long, Edge> ActiveGraph(Puzzle p) {
        var graph = new Dictionary<long, Edge>(); var seen = new HashSet<long>();
        foreach (long t in p.targets) {
            var stack = new Stack<long>(); stack.Push(t);
            while (stack.Count > 0) {
                long v = stack.Pop();
                if (p.defs.ContainsKey(v) && p.defop[v] == P.NONE) continue;
                if (!seen.Add(v)) continue;
                Edge e; if (!p.defs.TryGetValue(v, out e)) continue;
                if (e.op == P.NONE) continue;
                graph[v] = e; stack.Push(e.a); stack.Push(e.b);
            }
        }
        return graph;
    }
    static void Main(string[] args) {
        int leaves = args.Length > 0 ? int.Parse(args[0]) : 72;
        int scan = args.Length > 1 ? int.Parse(args[1]) : 1;
        int width = args.Length > 2 ? int.Parse(args[2]) : 4;
        double alpha = args.Length > 3 ? double.Parse(args[3], CultureInfo.InvariantCulture) : 0.18;
        int seed = args.Length > 7 ? int.Parse(args[7]) : 17;
        rng = new Random(seed);
        var stdin = Console.In; var outb = new StringBuilder(); string line;
        while ((line = stdin.ReadLine()) != null) {
            line = line.Trim(); if (line.Length == 0) continue;
            var tok = line.Split(' ');
            string id = tok[0]; long limit = long.Parse(tok[1]);
            int ns = int.Parse(tok[2]), nt = int.Parse(tok[3]);
            var starts = new List<long>(); var targets = new List<long>(); int idx = 4;
            for (int i = 0; i < ns; i++) starts.Add(long.Parse(tok[idx++]));
            for (int i = 0; i < nt; i++) targets.Add(long.Parse(tok[idx++]));
            int warmN = int.Parse(tok[idx++]);
            var warm = new Dictionary<long, Edge>();
            for (int i = 0; i < warmN; i++) {
                var wl = stdin.ReadLine().Trim().Split(' ');
                long v = long.Parse(wl[0]); char op = wl[1][0]; long a = long.Parse(wl[2]), b = long.Parse(wl[3]);
                warm[v] = new Edge { outv = v, a = a, b = b, op = op };
            }
            var p = new Puzzle { id = id, limit = limit, starts = starts, targets = targets };
            try { PlanPuzzle(p, warm, leaves, scan, width, alpha); } catch { }
            var graph = ActiveGraph(p);
            outb.Append(id).Append(' ').Append(graph.Count).Append('\n');
            foreach (var kv in graph) outb.Append(kv.Key).Append(' ').Append(kv.Value.op).Append(' ').Append(kv.Value.a).Append(' ').Append(kv.Value.b).Append('\n');
        }
        Console.Out.Write(outb.ToString());
    }
}