// Positive integer synthesis by bounded reverse search over an evolving dictionary.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

internal struct Operation
{
    internal readonly long Value, A, B;
    internal readonly char Code;
    internal Operation(long value, char code, long a, long b)
    { Value = value; Code = code; A = a; B = b; }
}

internal struct Split
{
    internal readonly long Scale, Quotient, Residue, Product;
    internal readonly bool Subtract;
    internal readonly int Estimate;
    internal readonly long Child;
    internal Split(long scale, long q, long residue, long product, bool subtract, int estimate, long child)
    { Scale = scale; Quotient = q; Residue = residue; Product = product; Subtract = subtract;
      Estimate = estimate; Child = child; }
}

internal struct RegisterStep
{
    internal readonly char Code;
    internal readonly int Left, Right, Destination;
    internal RegisterStep(char code, int left, int right, int destination)
    { Code = code; Left = left; Right = right; Destination = destination; }
}

internal sealed class Synthesis
{
    private readonly long upper;
    private readonly int variant, width, depth;
    private readonly int registerCount;
    private readonly long radix;
    private readonly List<long> known = new List<long>();
    private readonly HashSet<long> seen = new HashSet<long>();
    private readonly List<Operation> graph = new List<Operation>();
    private readonly Dictionary<long, Operation> cheap = new Dictionary<long, Operation>();
    private readonly Dictionary<long, Operation> secondary = new Dictionary<long, Operation>();
    private readonly Dictionary<long, List<Split>> hints = new Dictionary<long, List<Split>>();
    private readonly Dictionary<long, List<Operation>>[] memo;
    private long[] scales, operands, atomicQuotients, secondaryScales = new long[0];
    private readonly Dictionary<long, int> bank = new Dictionary<long, int>();
    private readonly Dictionary<long, int> lastUse = new Dictionary<long, int>();
    private readonly Dictionary<long, int> hits = new Dictionary<long, int>();
    private readonly HashSet<long> covered = new HashSet<long>();
    private readonly HashSet<long> protectedValues = new HashSet<long>();
    internal readonly List<RegisterStep> Instructions = new List<RegisterStep>();
    private bool Resident { get { return variant >= 30; } }

    internal Synthesis(long limit, long[] seeds, int searchVariant, int searchWidth, int searchDepth,
                       int registers)
    {
        upper = limit; variant = searchVariant; width = searchWidth; depth = searchDepth;
        registerCount = registers;
        memo = Enumerable.Range(0, depth + 1)
            .Select(_ => new Dictionary<long, List<Operation>>()).ToArray();
        radix = new long[] {1024, 4096, 729, 256, 2048, 625}[variant % 6];
        foreach (long seed in seeds) Introduce(seed);
        Commit(new Operation(1, '/', seeds[0], seeds[0]));
        if (radix <= upper)
        {
            BuildConstant(radix);
            long last = radix;
            while (last <= upper / last && last < (1L << 30))
            {
                Commit(new Operation(last * last, '*', last, last));
                last *= last;
            }
        }
        foreach (long value in new long[] {2, 3, 4, 5, 8, 16, 32, 64, 128})
            if (value <= upper) BuildConstant(value);
        if (variant >= 6) FillSecondary();
        if (Resident)
        {
            for (int i = 0; i < seeds.Length; i++)
            {
                if (!bank.ContainsKey(seeds[i])) bank[seeds[i]] = i;
                covered.Add(seeds[i]);
            }
            protectedValues.UnionWith(known);
            Wire(graph);
        }
    }

    private void Wire(List<Operation> plan)
    {
        var remaining = new Dictionary<long, int>();
        foreach (var op in plan)
            foreach (long operand in op.A == op.B ? new[] {op.A} : new[] {op.A, op.B})
                remaining[operand] = remaining.ContainsKey(operand) ? remaining[operand] + 1 : 1;
        var occupied = new bool[registerCount];
        foreach (int position in bank.Values) occupied[position] = true;
        foreach (var op in plan)
        {
            remaining[op.A]--;
            if (op.A != op.B) remaining[op.B]--;
            if (bank.ContainsKey(op.Value)) continue;
            int left = bank[op.A], right = bank[op.B];
            Touch(op.A);
            if (op.A != op.B) Touch(op.B);
            int destination = Array.IndexOf(occupied, false);
            if (destination < 0)
            {
                long victim = 0;
                double lowest = double.MaxValue;
                foreach (long value in bank.Keys)
                {
                    int future;
                    if (protectedValues.Contains(value)
                        || (remaining.TryGetValue(value, out future) && future > 0)) continue;
                    int timestamp, uses;
                    lastUse.TryGetValue(value, out timestamp);
                    hits.TryGetValue(value, out uses);
                    double priority = timestamp + (variant % 3 == 0 ? uses * 8 : uses * 3);
                    if (variant % 3 == 1 && value < (1L << 21)) priority += 35;
                    if (priority < lowest) { victim = value; lowest = priority; }
                }
                if (victim == 0) throw new InvalidOperationException("register pressure within one plan");
                destination = bank[victim];
                bank.Remove(victim);
                lastUse.Remove(victim);
                hits.Remove(victim);
            }
            occupied[destination] = true;
            bank[op.Value] = destination;
            lastUse[op.Value] = Instructions.Count;
            covered.Add(op.Value);
            Instructions.Add(new RegisterStep(op.Code, left, right, destination));
            if (Instructions.Count > 4096) throw new InvalidOperationException("instruction limit");
        }
        known.Clear();
        seen.Clear();
        cheap.Clear();
        foreach (var entry in bank.OrderBy(entry => entry.Value)) Introduce(entry.Key);
    }

    private void Touch(long value)
    {
        lastUse[value] = Instructions.Count;
        int uses;
        hits.TryGetValue(value, out uses);
        hits[value] = uses + 1;
    }

    private void PutSecondary(long value, char code, long a, long b)
    {
        if (value > 0 && value <= upper && !seen.Contains(value)
            && !cheap.ContainsKey(value) && !secondary.ContainsKey(value))
            secondary[value] = new Operation(value, code, a, b);
    }

    private void FillSecondary()
    {
        foreach (long value in cheap.Keys.OrderBy(v => v))
            foreach (long root in known)
            {
                long a = Math.Max(value, root), b = Math.Min(value, root);
                PutSecondary(a + b, '+', a, b);
                PutSecondary(a - b, '-', a, b);
                if (a <= upper / b) PutSecondary(a * b, '*', a, b);
                if (a % b == 0) PutSecondary(a / b, '/', a, b);
            }
        secondaryScales = secondary.Keys.Where(v => v > 31)
            .GroupBy(Bits).SelectMany(group =>
            {
                long[] sorted = group.OrderBy(v => v).ToArray();
                if (sorted.Length <= 28) return sorted;
                return Enumerable.Range(0, 28)
                    .Select(index => sorted[(index * sorted.Length + variant % 28) / 28]);
            }).ToArray();
    }

    private void PutCheap(long value, char code, long a, long b)
    {
        if (value > 0 && value <= upper && !seen.Contains(value) && !cheap.ContainsKey(value))
            cheap[value] = new Operation(value, code, a, b);
    }

    private void Introduce(long value)
    {
        if (!seen.Add(value)) return;
        cheap.Remove(value);
        known.Add(value);
        foreach (long other in known)
        {
            long a = Math.Max(value, other), b = Math.Min(value, other);
            PutCheap(a + b, '+', a, b);
            PutCheap(a - b, '-', a, b);
            if (a <= upper / b) PutCheap(a * b, '*', a, b);
            if (a % b == 0) PutCheap(a / b, '/', a, b);
        }
    }

    private void Commit(Operation op)
    {
        if (seen.Contains(op.Value)) return;
        graph.Add(op);
        Introduce(op.Value);
    }

    private bool Atom(long value)
    { return value == 0 || seen.Contains(value) || cheap.ContainsKey(value) || secondary.ContainsKey(value); }

    private int AtomCost(long value)
    { return value == 0 || seen.Contains(value) ? 0 : cheap.ContainsKey(value) ? 1 : 2; }

    private void AppendAtom(List<Operation> operations, long value)
    {
        Operation operation;
        if (value == 0 || seen.Contains(value) || operations.Any(op => op.Value == value)) return;
        if (cheap.TryGetValue(value, out operation))
            operations.Add(operation);
        else if (secondary.TryGetValue(value, out operation))
        {
            AppendAtom(operations, operation.A);
            AppendAtom(operations, operation.B);
            operations.Add(operation);
        }
    }

    private void BuildConstant(long value)
    {
        if (seen.Contains(value)) return;
        Operation operation;
        if (cheap.TryGetValue(value, out operation)) { Commit(operation); return; }
        long half = value / 2;
        BuildConstant(half);
        Commit(new Operation(2 * half, '+', half, half));
        if (value % 2 != 0) Commit(new Operation(value, '+', 2 * half, 1));
    }

    private bool Inverse(long target, long anchor, bool requireAtom, out Operation operation)
    {
        long right = target - anchor;
        if (right > 0 && (requireAtom ? Atom(right) : seen.Contains(right)))
        { operation = new Operation(target, '+', anchor, right); return true; }
        right = target + anchor;
        if (right <= upper && (requireAtom ? Atom(right) : seen.Contains(right)))
        { operation = new Operation(target, '-', right, anchor); return true; }
        right = anchor - target;
        if (right > 0 && (requireAtom ? Atom(right) : seen.Contains(right)))
        { operation = new Operation(target, '-', anchor, right); return true; }
        if (target % anchor == 0)
        {
            right = target / anchor;
            if (requireAtom ? Atom(right) : seen.Contains(right))
            { operation = new Operation(target, '*', anchor, right); return true; }
        }
        if (target <= upper / anchor)
        {
            right = target * anchor;
            if (requireAtom ? Atom(right) : seen.Contains(right))
            { operation = new Operation(target, '/', right, anchor); return true; }
        }
        if (anchor % target == 0)
        {
            right = anchor / target;
            if (requireAtom ? Atom(right) : seen.Contains(right))
            { operation = new Operation(target, '/', anchor, right); return true; }
        }
        operation = new Operation();
        return false;
    }

    private List<Operation> Join(long value, bool allowTwoAtoms)
    {
        var plan = new List<Operation>();
        if (Atom(value)) { AppendAtom(plan, value); return plan; }
        Operation operation;
        List<Operation> best = null;
        foreach (long anchor in known)
            if (Inverse(value, anchor, true, out operation))
            {
                plan = new List<Operation>();
                AppendAtom(plan, operation.A);
                AppendAtom(plan, operation.B);
                plan.Add(operation);
                if (plan.Count <= 2) return plan;
                if (best == null || plan.Count < best.Count) best = plan;
            }
        if (best != null) return best;
        if (allowTwoAtoms)
            foreach (long anchor in operands)
                if (Inverse(value, anchor, true, out operation))
                {
                    plan = new List<Operation>();
                    AppendAtom(plan, operation.A);
                    AppendAtom(plan, operation.B);
                    plan.Add(operation);
                    if (plan.Count <= 3) return plan;
                    if (best == null || plan.Count < best.Count) best = plan;
                }
        return best;
    }

    private List<Operation> Realize(long value, Split split, List<Operation> child)
    {
        var result = child == null ? new List<Operation>() : new List<Operation>(child);
        if (split.Scale == 0)
        {
            result.Add(new Operation(value, split.Subtract ? '-' : '+', split.Product, split.Residue));
            return result;
        }
        AppendAtom(result, split.Scale);
        if (Atom(split.Quotient)) AppendAtom(result, split.Quotient);
        if (Atom(split.Residue)) AppendAtom(result, split.Residue);
        if (Atom(split.Product)) AppendAtom(result, split.Product);
        else if (!result.Any(op => op.Value == split.Product))
            result.Add(new Operation(split.Product, '*', split.Quotient, split.Scale));
        if (split.Residue != 0)
            result.Add(new Operation(value, split.Subtract ? '-' : '+', split.Product, split.Residue));
        return result;
    }

    private static int Bits(long value)
    {
        int bits = 0;
        if (value >= 1L << 32) { value >>= 32; bits += 32; }
        if (value >= 1L << 16) { value >>= 16; bits += 16; }
        if (value >= 1L << 8) { value >>= 8; bits += 8; }
        if (value >= 1L << 4) { value >>= 4; bits += 4; }
        if (value >= 1L << 2) { value >>= 2; bits += 2; }
        if (value >= 1L << 1) { value >>= 1; bits += 1; }
        return value == 0 ? bits : bits + 1;
    }

    private void Consider(long value, long d, long q, long r, long product, bool subtract,
                          List<Split> shortlist, ref List<Operation> best)
    {
        if (q < 2 || product > upper || d == value || product == r) return;
        bool qAtomic = Atom(q), rAtomic = Atom(r);
        if (!qAtomic && !rAtomic) return;
        long child = !qAtomic ? q : !rAtomic ? r : 0;
        int local = AtomCost(d) + (qAtomic ? AtomCost(q) : 0) + (rAtomic ? AtomCost(r) : 0)
            + (r != 0 ? 1 : 0) + (Atom(product) ? AtomCost(product) : 1);
        if (child == 0)
        {
            if (best != null && local > best.Count + 2) return;
            var plan = Realize(value, new Split(d, q, r, product, subtract, 0, 0), null);
            if (best == null || plan.Count < best.Count) best = plan;
            return;
        }
        if (best != null && local >= best.Count - 1) return;
        int bits = Bits(child);
        int estimate = local * 50 + (bits <= 17 ? 100 : bits <= 35 ? 170 : 240) + bits;
        if (shortlist.Count == width && estimate >= shortlist[width - 1].Estimate) return;
        int index = -1;
        for (int i = 0; i < shortlist.Count; i++)
            if (shortlist[i].Child == child) { index = i; break; }
        if (index >= 0)
        {
            if (shortlist[index].Estimate <= estimate) return;
            shortlist.RemoveAt(index);
        }
        index = 0;
        while (index < shortlist.Count && shortlist[index].Estimate <= estimate) index++;
        var split = new Split(d, q, r, product, subtract, estimate, child);
        shortlist.Insert(index, split);
        if (shortlist.Count > width) shortlist.RemoveAt(width);
    }

    private List<Operation> Search(long value, int remaining, bool full)
    {
        var cache = memo[remaining];
        List<Operation> best;
        if (cache.TryGetValue(value, out best)) return best;
        best = Join(value, full || value <= 1000000);
        if (best != null && best.Count <= 3) { cache[value] = best; return best; }
        var shortlist = new List<Split>();
        foreach (long d in scales)
        {
            if (d > value / 2) continue;
            long q = value / d, r = value - q * d;
            if (r == 0 || Atom(r) || Atom(q))
                Consider(value, d, q, r, value - r, false, shortlist, ref best);
            long offset = d - r;
            if (r != 0 && offset <= upper - value && (Atom(offset) || Atom(q + 1)))
                Consider(value, d, q + 1, offset, value + offset, true, shortlist, ref best);
            if (variant >= 12 && full && (best == null || best.Count > 4))
            {
                int at = Array.BinarySearch(atomicQuotients, q);
                if (at < 0) at = ~at;
                for (int position = Math.Max(0, at - 1);
                     position <= at && position < atomicQuotients.Length; position++)
                {
                    long near = atomicQuotients[position];
                    if (near == q || near == q + 1 || near > upper / d) continue;
                    long product = near * d;
                    long residue = Math.Abs(value - product);
                    if (residue >= value / 4 || (!Atom(residue) && best != null)) continue;
                    Consider(value, d, near, residue, product, product > value, shortlist, ref best);
                }
            }
        }
        if (variant >= 18 && full && value >= (1L << 35) && (best == null || best.Count > 7))
        {
            foreach (long d in operands)
            {
                if (d < 64) continue;
                if (d > value / 2) break;
                long q = value / d, r = value - q * d;
                if (Atom(r))
                    Consider(value, d, q, r, value - r, false, shortlist, ref best);
                long offset = d - r;
                if (r != 0 && offset <= upper - value && Atom(offset))
                    Consider(value, d, q + 1, offset, value + offset, true, shortlist, ref best);
            }
        }
        if (remaining > 0 && (best == null || best.Count > 3))
        {
            if (variant >= 6)
            {
                foreach (long anchor in known.OrderBy(a => Math.Abs(a - value)).Take(4))
                {
                    long residue = Math.Abs(anchor - value);
                    if (residue >= value / 2 || residue == 0 || Atom(residue)) continue;
                    var candidate = Search(residue, remaining - 1, false);
                    if (candidate == null || (best != null && candidate.Count + 1 >= best.Count)) continue;
                    best = Realize(value, new Split(0, 0, residue, anchor, anchor > value, 0, residue),
                                   candidate);
                }
            }
            foreach (var split in shortlist)
            {
                var child = Search(split.Child, remaining - 1, false);
                if (child == null) continue;
                var plan = Realize(value, split, child);
                if (best == null || plan.Count < best.Count) best = plan;
            }
        }
        cache[value] = best;
        return best;
    }

    private void Fallback(long value)
    {
        if (seen.Contains(value)) return;
        var plan = Join(value, false);
        if (plan != null) { foreach (var op in plan) Commit(op); return; }
        if (value <= radix) { BuildConstant(value); return; }
        long q = value / radix, r = value % radix, product = value - r;
        bool subtract = r > radix / 2 && radix - r <= upper - value;
        if (subtract) { q++; r = radix - r; product = value + r; }
        Fallback(q);
        BuildConstant(radix);
        Commit(new Operation(product, '*', q, radix));
        if (r == 0) return;
        BuildConstant(r);
        Commit(new Operation(value, subtract ? '-' : '+', product, r));
    }

    private void PlanLiteral(long value, List<Operation> plan)
    {
        if (value == 0 || seen.Contains(value) || plan.Any(op => op.Value == value)) return;
        if (Atom(value)) { AppendAtom(plan, value); return; }
        long scale = value > radix ? radix : 2;
        long quotient = value / scale, residue = value % scale;
        long product = value - residue;
        bool subtract = scale == radix && residue > scale / 2 && scale - residue <= upper - value;
        if (subtract) { quotient++; residue = scale - residue; product = value + residue; }
        PlanLiteral(quotient, plan);
        if (scale != 2) PlanLiteral(scale, plan);
        if (!seen.Contains(product) && !plan.Any(op => op.Value == product))
            plan.Add(scale == 2 ? new Operation(product, '+', quotient, quotient)
                                : new Operation(product, '*', quotient, scale));
        if (residue == 0) return;
        PlanLiteral(residue, plan);
        plan.Add(new Operation(value, subtract ? '-' : '+', product, residue));
    }

    private void Refresh()
    {
        foreach (var cache in memo) cache.Clear();
        operands = cheap.Keys.Where(v => v > 1).OrderBy(v => v).ToArray();
        if (variant >= 12)
            atomicQuotients = known.Where(v => v > 1).Concat(operands)
                .Concat(secondaryScales).Distinct().OrderBy(v => v).ToArray();
        var buckets = new List<long>[61];
        for (int i = 0; i < buckets.Length; i++) buckets[i] = new List<long>();
        foreach (long candidate in operands)
            if (candidate >= 3) buckets[Bits(candidate)].Add(candidate);
        var selected = new List<long>(known.Where(v => v >= 2));
        foreach (var bucket in buckets)
        {
            int quota = (variant % 6 < 3 ? 44 : 80);
            if (bucket.Count <= quota) selected.AddRange(bucket);
            else
                for (int j = 0; j < quota; j++)
                    selected.Add(bucket[(j * bucket.Count + variant % quota) / quota]);
        }
        scales = selected.Concat(secondaryScales.Where(v => !seen.Contains(v) && !cheap.ContainsKey(v))).ToArray();
    }

    internal List<Operation> Run(long[] targets)
    {
        long[] order = (long[]) targets.Clone();
        Array.Sort(order);
        if (variant % 3 == 1) Array.Reverse(order);
        if (variant % 3 == 2)
        {
            var random = new Random(variant * 167 + 1);
            for (int i = order.Length - 1; i > 0; i--)
            {
                int j = random.Next(i + 1);
                long tmp = order[i]; order[i] = order[j]; order[j] = tmp;
            }
        }
        foreach (long target in order)
        {
            if (variant >= 24 && !Resident) Saturate(order);
            if (Resident ? covered.Contains(target) : seen.Contains(target)) continue;
            Refresh();
            var answer = Search(target, depth, true);
            answer = TryHints(target, answer);
            if (Resident)
            {
                if (answer == null)
                {
                    answer = new List<Operation>();
                    PlanLiteral(target, answer);
                }
                Wire(answer);
            }
            else if (answer == null) Fallback(target);
            else foreach (var op in answer) Commit(op);
        }
        return graph;
    }

    private void Saturate(long[] targets)
    {
        bool change;
        do
        {
            change = false;
            foreach (long target in targets)
            {
                if (seen.Contains(target)) continue;
                var plan = Join(target, false);
                if (plan == null || plan.Count > 2) continue;
                foreach (var operation in plan) Commit(operation);
                change = true;
            }
        } while (change);
    }

    private List<Operation> TryHints(long value, List<Operation> best)
    {
        List<Split> recipes;
        if (!hints.TryGetValue(value, out recipes) || (best != null && best.Count <= 3)) return best;
        foreach (var hint in recipes)
        {
            var operations = new List<Operation>();
            bool feasible = true;
            var produced = new HashSet<long>();
            var needed = Atom(hint.Product)
                ? new long[] {hint.Product, hint.Residue}
                : new long[] {hint.Scale, hint.Quotient, hint.Residue};
            foreach (long operand in needed)
            {
                if (operand == 0 || seen.Contains(operand) || produced.Contains(operand)) continue;
                if (operand == value && !Atom(operand)) { feasible = false; break; }
                var plan = Search(operand, Math.Min(depth, 1), false);
                if (plan == null) { feasible = false; break; }
                foreach (var op in plan)
                    if (produced.Add(op.Value)) operations.Add(op);
            }
            if (!feasible) continue;
            if (!Atom(hint.Product) && produced.Add(hint.Product))
                operations.Add(new Operation(hint.Product, '*', hint.Scale, hint.Quotient));
            if (hint.Residue != 0 && produced.Add(value))
                operations.Add(new Operation(value, hint.Subtract ? '-' : '+', hint.Product, hint.Residue));
            if (best == null || operations.Count < best.Count) best = operations;
        }
        return best;
    }

    internal void ReadHints(string input)
    {
        if (input.Length == 0) return;
        foreach (string entry in input.Split(';'))
        {
            long[] values = entry.Split(',').Select(s => long.Parse(s, CultureInfo.InvariantCulture)).ToArray();
            long target = values[0], scale = values[1], quotient = values[2], signed = values[3];
            if (scale < 2 || quotient < 2 || scale > upper / quotient) continue;
            long product = scale * quotient;
            if (product + signed != target) continue;
            List<Split> recipes;
            if (!hints.TryGetValue(target, out recipes))
            {
                recipes = new List<Split>();
                hints[target] = recipes;
            }
            recipes.Add(new Split(scale, quotient, Math.Abs(signed), product, signed < 0, 0, 0));
        }
    }

    internal void WarmStart(string input)
    {
        if (input.Length == 0) return;
        var plan = new List<Operation>();
        foreach (string entry in input.Split(';'))
        {
            string[] values = entry.Split(',');
            plan.Add(new Operation(long.Parse(values[0], CultureInfo.InvariantCulture),
                values[1][0], long.Parse(values[2], CultureInfo.InvariantCulture),
                long.Parse(values[3], CultureInfo.InvariantCulture)));
        }
        if (Resident) Wire(plan);
        else foreach (var operation in plan) Commit(operation);
    }
}

internal static class DictionarySearch
{
    private static long[] Values(string input)
    { return input.Length == 0 ? new long[0] :
        input.Split(',').Select(s => long.Parse(s, CultureInfo.InvariantCulture)).ToArray(); }

    private static void Main(string[] args)
    {
        int variant = int.Parse(args[0]), width = int.Parse(args[1]);
        int depth = int.Parse(args[2]), jobs = int.Parse(args[3]);
        var input = new List<string>();
        string line;
        while ((line = Console.ReadLine()) != null) input.Add(line);
        Parallel.ForEach(input, new ParallelOptions { MaxDegreeOfParallelism = jobs }, row =>
        {
            string[] fields = row.Split('\t');
            long limit = long.Parse(fields[1], CultureInfo.InvariantCulture);
            var output = new StringBuilder(fields[0]);
            try
            {
                var search = new Synthesis(limit, Values(fields[2]), variant, width, depth,
                                           int.Parse(fields[6], CultureInfo.InvariantCulture));
                search.WarmStart(fields[4]);
                search.ReadHints(fields[5]);
                var graph = search.Run(Values(fields[3]));
                if (variant >= 30)
                {
                    output.Append("\t@");
                    foreach (var step in search.Instructions)
                        output.AppendFormat(CultureInfo.InvariantCulture, "\t{0},{1},{2},{3}",
                                            step.Code, step.Left, step.Right, step.Destination);
                }
                else
                    foreach (var operation in graph)
                        output.AppendFormat(CultureInfo.InvariantCulture, "\t{0},{1},{2},{3}",
                                            operation.Value, operation.Code, operation.A, operation.B);
            }
            catch (InvalidOperationException) { output.Append("\t!"); }
            Console.WriteLine(output.ToString());
        });
    }
}
