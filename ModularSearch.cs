using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

internal struct ModularRecipe
{
    internal readonly long Output, A, B;
    internal readonly char Operation;

    internal ModularRecipe(long output, char operation, long a, long b)
    {
        Output = output;
        Operation = operation;
        A = a;
        B = b;
    }
}

internal struct ModularSplit : IComparable<ModularSplit>
{
    internal readonly long Radix, Quotient, Delta;
    internal readonly int Cost;

    internal ModularSplit(long radix, long quotient, long delta, int cost)
    {
        Radix = radix;
        Quotient = quotient;
        Delta = delta;
        Cost = cost;
    }

    public int CompareTo(ModularSplit other)
    {
        int comparison = Cost.CompareTo(other.Cost);
        if (comparison != 0) return comparison;
        comparison = Radix.CompareTo(other.Radix);
        if (comparison != 0) return comparison;
        comparison = Quotient.CompareTo(other.Quotient);
        return comparison != 0 ? comparison : Delta.CompareTo(other.Delta);
    }
}

internal sealed class ModularPlanner
{
    private static readonly List<ModularRecipe> Empty = new List<ModularRecipe>();
    private readonly long limit;
    private readonly int width, depth, span;
    private readonly HashSet<long> known = new HashSet<long>();
    private readonly List<long> order = new List<long>();
    private readonly List<ModularRecipe> graph = new List<ModularRecipe>();
    private readonly Dictionary<long, ModularRecipe> atoms = new Dictionary<long, ModularRecipe>();
    private readonly Dictionary<long, List<ModularRecipe>>[] cache;
    private readonly Dictionary<long, List<ModularRecipe>> binaryCache = new Dictionary<long, List<ModularRecipe>>();
    private long[] radices = new long[0];
    private int[] radixCosts;
    private Dictionary<long, List<long>>[] columns;

    internal ModularPlanner(long[] seeds, long maximum, int searchWidth, int searchDepth, int residueSpan,
                            IEnumerable<ModularRecipe> warm, long[] targets, bool tuneRadices)
    {
        limit = maximum;
        width = searchWidth;
        depth = searchDepth;
        span = residueSpan;
        cache = Enumerable.Range(0, depth + 1).Select(_ => new Dictionary<long, List<ModularRecipe>>()).ToArray();

        foreach (long seed in seeds)
            Commit(new ModularRecipe(seed, ' ', 0, 0));
        Commit(new ModularRecipe(1, '/', seeds[0], seeds[0]));
        if (limit >= 2)
            Commit(new ModularRecipe(2, '+', 1, 1));
        if (limit >= 3)
            Commit(new ModularRecipe(3, '+', 2, 1));

        foreach (long value in new long[] {4, 8, 16, 32, 64, 256, 1024, 1 << 16, 1 << 20, 1L << 32})
        {
            if (value > limit || known.Contains(value)) continue;
            ModularRecipe recipe;
            if (atoms.TryGetValue(value, out recipe)) { Commit(recipe); continue; }
            long half = 1L << ((Bits(value) - 1) / 2), other = value / half;
            AddPower(half);
            AddPower(other);
            Commit(new ModularRecipe(value, '*', half, other));
        }
        foreach (var recipe in warm)
            Commit(recipe);

        var selected = new HashSet<long>(known.Where(value => value >= 16 && value <= 1L << 40));
        long[] bank = known.Concat(atoms.Keys).OrderBy(value => value).ToArray();
        foreach (var group in bank
            .Where(value => value >= 16 && value <= Math.Min(1L << 29, limit / 2)).GroupBy(Bits))
        {
            long[] values = group.ToArray();
            if (tuneRadices)
            {
                foreach (long value in values.OrderByDescending(radix => Coverage(radix, targets, bank)).Take(4))
                    selected.Add(value);
                selected.Add(values[values.Length / 2]);
            }
            else
            {
                foreach (int index in new int[] {values.Length / 6, values.Length / 2, 5 * values.Length / 6})
                    selected.Add(values[index]);
            }
        }
        radices = selected.OrderBy(value => value).ToArray();
        radixCosts = new int[radices.Length];
        columns = radices.Select(_ => new Dictionary<long, List<long>>()).ToArray();
        foreach (long value in bank)
            Index(value);
    }

    private int Coverage(long radix, long[] targets, long[] bank)
    {
        var pending = new Dictionary<long, int>();
        var quotients = new HashSet<long>();
        int rating = known.Contains(radix) ? 4 : 0;
        foreach (long target in targets)
        {
            long value = target;
            for (int level = 0; level < 3 && value >= radix * 2; level++)
            {
                long residue = value % radix;
                long key = Math.Min(residue, radix - residue);
                int weight = level == 0 ? 4 : 2;
                if (key == 0)
                    rating += weight;
                else
                {
                    int count;
                    pending.TryGetValue(key, out count);
                    pending[key] = count + weight;
                }
                value /= radix;
                if (known.Contains(value)) rating += 2;
                if (!quotients.Add(value)) rating++;
            }
        }
        foreach (long value in bank)
        {
            if (value > span * radix || pending.Count == 0) break;
            long residue = value % radix;
            long key = Math.Min(residue, radix - residue);
            int weight;
            if (!pending.TryGetValue(key, out weight)) continue;
            rating += weight;
            pending.Remove(key);
        }
        return rating;
    }

    private static int Bits(long value)
    {
        int length = 0;
        if (value >= 1L << 32) { value >>= 32; length += 32; }
        if (value >= 1L << 16) { value >>= 16; length += 16; }
        if (value >= 1L << 8) { value >>= 8; length += 8; }
        if (value >= 1L << 4) { value >>= 4; length += 4; }
        if (value >= 1L << 2) { value >>= 2; length += 2; }
        if (value >= 1L << 1) { value >>= 1; length++; }
        return value == 0 ? length : length + 1;
    }

    private void AddPower(long value)
    {
        if (known.Contains(value)) return;
        long half = value / 2;
        AddPower(half);
        Commit(new ModularRecipe(value, '+', half, half));
    }

    private void Index(long value)
    {
        long threshold = (value - 1) / span + 1;
        if (radices.Length == 0 || threshold > radices[radices.Length - 1])
            return;
        int first = Array.BinarySearch(radices, threshold);
        if (first < 0) first = ~first;
        for (int column = first; column < radices.Length; column++)
        {
            long radix = radices[column];
            long residue = value % radix;
            List<long> values;
            if (!columns[column].TryGetValue(residue, out values))
            {
                values = new List<long>();
                columns[column].Add(residue, values);
            }
            if (!values.Contains(value))
                values.Add(value);
        }
    }

    private void SaveAtom(long output, char operation, long a, long b)
    {
        if (output <= 0 || output > limit || known.Contains(output) || atoms.ContainsKey(output))
            return;
        atoms.Add(output, new ModularRecipe(output, operation, a, b));
        Index(output);
    }

    private void Commit(ModularRecipe operation)
    {
        long value = operation.Output;
        if (!known.Add(value)) return;
        atoms.Remove(value);
        Index(value);
        order.Add(value);
        if (operation.Operation != ' ')
            graph.Add(operation);
        foreach (long other in order)
        {
            long high = Math.Max(value, other), low = Math.Min(value, other);
            SaveAtom(high + low, '+', high, low);
            SaveAtom(high - low, '-', high, low);
            if (high <= limit / low)
                SaveAtom(high * low, '*', high, low);
            if (high % low == 0)
                SaveAtom(high / low, '/', high, low);
        }
    }

    private List<ModularRecipe> Cheap(long value)
    {
        if (value == 0 || known.Contains(value))
            return Empty;
        ModularRecipe operation;
        return atoms.TryGetValue(value, out operation) ? new List<ModularRecipe> { operation } : null;
    }

    private int Estimate(long value)
    {
        if (value == 0 || known.Contains(value))
            return 0;
        if (atoms.ContainsKey(value))
            return 10;
        int bits = Bits(value);
        return 21 + bits + (bits / 10) * 9;
    }

    private List<ModularRecipe> JoinOne(long value, char operation, long a, long b, long pilot)
    {
        var tail = Cheap(pilot);
        if (tail == null) return null;
        var branch = new List<ModularRecipe>(tail);
        branch.Add(new ModularRecipe(value, operation, a, b));
        return branch;
    }

    private List<ModularRecipe> Join(long value)
    {
        foreach (long anchor in order)
        {
            List<ModularRecipe> branch;
            if (anchor < value)
            {
                branch = JoinOne(value, '+', anchor, value - anchor, value - anchor);
                if (branch != null) return branch;
            }
            else if (anchor > value)
            {
                branch = JoinOne(value, '-', anchor, anchor - value, anchor - value);
                if (branch != null) return branch;
            }
            if (value + anchor <= limit)
            {
                branch = JoinOne(value, '-', value + anchor, anchor, value + anchor);
                if (branch != null) return branch;
            }
            if (anchor > 1 && value % anchor == 0)
            {
                branch = JoinOne(value, '*', anchor, value / anchor, value / anchor);
                if (branch != null) return branch;
            }
            if (anchor > 1 && value <= limit / anchor)
            {
                branch = JoinOne(value, '/', value * anchor, anchor, value * anchor);
                if (branch != null) return branch;
            }
            if (anchor > value && anchor % value == 0)
            {
                branch = JoinOne(value, '/', anchor, anchor / value, anchor / value);
                if (branch != null) return branch;
            }
        }
        return null;
    }

    private List<ModularRecipe> Binary(long value)
    {
        List<ModularRecipe> previous;
        if (binaryCache.TryGetValue(value, out previous)) return previous;
        previous = Cheap(value);
        if (previous != null) return previous;

        long q = value / 2;
        var plan = new List<ModularRecipe>(Binary(q));
        if (!known.Contains(2 * q) && !plan.Any(operation => operation.Output == 2 * q))
            plan.Add(new ModularRecipe(2 * q, '+', q, q));
        if (value % 2 != 0)
            plan.Add(new ModularRecipe(value, '+', 2 * q, 1));
        binaryCache[value] = plan;
        return plan;
    }

    private void Propose(List<ModularSplit> options, long value, long radix, long delta, int scaleCost)
    {
        long product = value - delta, quotient = product / radix;
        if (quotient < 2 || product > limit || Math.Abs(delta) >= value / 2)
            return;
        int cost = Estimate(quotient) + Estimate(Math.Abs(delta)) + scaleCost
            + (known.Contains(product) ? 0 : 10) + (delta == 0 ? 0 : 10);
        var candidate = new ModularSplit(radix, quotient, delta, cost);
        if (options.Count == width && options[width - 1].CompareTo(candidate) <= 0)
            return;
        for (int i = 0; i < options.Count; i++)
            if (options[i].Quotient == quotient && Math.Abs(options[i].Delta) == Math.Abs(delta))
            {
                if (options[i].CompareTo(candidate) <= 0)
                    return;
                options.RemoveAt(i);
                break;
            }
        int position = options.BinarySearch(candidate);
        options.Insert(position < 0 ? ~position : position, candidate);
        if (options.Count > width)
            options.RemoveAt(width);
    }

    private List<ModularSplit> Splits(long value, bool useColumns)
    {
        var options = new List<ModularSplit>();
        for (int i = 0; i < radices.Length; i++)
        {
            long radix = radices[i];
            if (radix > value / 2) break;
            long residue = value % radix, negativeResidue = residue == 0 ? 0 : radix - residue;
            int scaleCost = radixCosts[i];
            Propose(options, value, radix, residue, scaleCost);
            if (residue != 0)
                Propose(options, value, radix, residue - radix, scaleCost);
            if (!useColumns) continue;
            List<long> representatives;
            if (columns[i].TryGetValue(residue, out representatives))
                foreach (long representative in representatives)
                    if (representative != residue)
                        Propose(options, value, radix, representative, scaleCost);
            if (columns[i].TryGetValue(negativeResidue, out representatives))
                foreach (long representative in representatives)
                    if (residue == 0 || representative != negativeResidue)
                        Propose(options, value, radix, -representative, scaleCost);
        }
        return options;
    }

    private static void Append(List<ModularRecipe> plan, IEnumerable<ModularRecipe> branch)
    {
        foreach (var operation in branch)
            if (!plan.Any(current => current.Output == operation.Output))
                plan.Add(operation);
    }

    private List<ModularRecipe> Assemble(long value, ModularSplit split,
                                        List<ModularRecipe> quotient, List<ModularRecipe> residual)
    {
        var plan = new List<ModularRecipe>(quotient);
        Append(plan, residual);
        Append(plan, Cheap(split.Radix));
        long product = split.Radix * split.Quotient;
        if (!plan.Any(operation => operation.Output == product))
        {
            var ready = Cheap(product);
            if (ready != null) Append(plan, ready);
            else plan.Add(new ModularRecipe(product, '*', split.Radix, split.Quotient));
        }
        if (split.Delta != 0)
            plan.Add(new ModularRecipe(value, split.Delta > 0 ? '+' : '-', product, Math.Abs(split.Delta)));
        return plan;
    }

    private List<ModularRecipe> Search(long value, int remaining)
    {
        var memo = cache[remaining];
        List<ModularRecipe> best;
        if (memo.TryGetValue(value, out best)) return best;
        best = Cheap(value) ?? Join(value);
        if (best != null)
        {
            memo[value] = best;
            return best;
        }
        best = Binary(value);
        if (remaining > 0)
        {
            foreach (ModularSplit split in Splits(value, remaining >= 2))
            {
                var quotient = Search(split.Quotient, remaining - 1);
                if (quotient.Count + 1 >= best.Count) continue;
                var residual = Search(Math.Abs(split.Delta), remaining - 1);
                var candidate = Assemble(value, split, quotient, residual);
                if (candidate.Count < best.Count)
                    best = candidate;
            }
        }
        memo[value] = best;
        return best;
    }

    internal IEnumerable<ModularRecipe> Run(long[] targets, string direction)
    {
        var pending = targets.Distinct().OrderBy(value => value).ToList();
        if (direction == "reverse") pending.Reverse();
        while (pending.Count != 0)
        {
            for (int i = 0; i < radices.Length; i++)
                radixCosts[i] = Estimate(radices[i]);
            int index = direction == "greedy" ? CheapestTarget(pending) : 0;
            long target = pending[index];
            pending.RemoveAt(index);
            if (known.Contains(target)) continue;
            foreach (var memo in cache) memo.Clear();
            binaryCache.Clear();
            List<ModularRecipe> plan = Search(target, depth);
            foreach (var operation in plan)
                Commit(operation);
        }
        return graph;
    }

    private int CheapestTarget(List<long> pending)
    {
        int winner = 0, best = int.MaxValue;
        for (int i = 0; i < pending.Count; i++)
        {
            long target = pending[i];
            if (known.Contains(target) || atoms.ContainsKey(target))
                return i;
            if (Join(target) != null)
            {
                if (best > 20) { winner = i; best = 20; }
                continue;
            }
            if (best == 20)
                continue;
            var options = Splits(target, true);
            int estimate = options.Count == 0 ? 40 + Bits(target) * 3 : options[0].Cost;
            if (estimate < best) { winner = i; best = estimate; }
        }
        return winner;
    }
}

internal static class ModularSearch
{
    private static long[] Values(string input)
    {
        return input.Split(',').Where(field => field.Length != 0)
            .Select(field => long.Parse(field, CultureInfo.InvariantCulture)).ToArray();
    }

    private static IEnumerable<ModularRecipe> Recipes(string input)
    {
        foreach (string cell in input.Split(';'))
        {
            if (cell.Length == 0) continue;
            string[] fields = cell.Split(',');
            yield return new ModularRecipe(long.Parse(fields[0]), fields[1][0],
                                           long.Parse(fields[2]), long.Parse(fields[3]));
        }
    }

    private static void Main(string[] args)
    {
        int width = int.Parse(args[0]), depth = int.Parse(args[1]), span = int.Parse(args[2]);
        int jobs = int.Parse(args[3]);
        string direction = args.Length > 4 ? args[4] : "forward";
        bool tuneRadices = args.Length > 5 && args[5] == "tuned";
        var input = new List<string>();
        for (string line; (line = Console.ReadLine()) != null;)
            input.Add(line);
        string[] output = new string[input.Count];
        Parallel.For(0, input.Count, new ParallelOptions { MaxDegreeOfParallelism = jobs }, row =>
        {
            string[] fields = input[row].Split('\t');
            long[] targets = Values(fields[3]);
            var solver = new ModularPlanner(Values(fields[2]), long.Parse(fields[1]), width, depth,
                                             span, Recipes(fields.Length > 4 ? fields[4] : ""),
                                             targets, tuneRadices);
            var builder = new StringBuilder(fields[0]);
            foreach (var recipe in solver.Run(targets, direction))
                builder.Append('\t').Append(recipe.Output).Append(',').Append(recipe.Operation)
                    .Append(',').Append(recipe.A).Append(',').Append(recipe.B);
            output[row] = builder.ToString();
        });
        foreach (string line in output)
            Console.WriteLine(line);
    }
}
