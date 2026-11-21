using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;

internal struct Calculation
{
    internal char Op;
    internal long Left;
    internal long Right;

    internal Calculation(char op, long left, long right)
    {
        Op = op;
        Left = left;
        Right = right;
    }
}

internal struct Step
{
    internal char Op;
    internal int Left;
    internal int Right;
    internal int Destination;

    internal Step(char op, int left, int right, int destination)
    {
        Op = op;
        Left = left;
        Right = right;
        Destination = destination;
    }
}

internal struct BridgeUse
{
    internal long Pivot;
    internal long Anchor;
    internal Calculation Root;

    internal BridgeUse(long pivot, long anchor, Calculation root)
    {
        Pivot = pivot;
        Anchor = anchor;
        Root = root;
    }
}

internal sealed class AssociativeIsland
{
    internal long Root;
    internal bool Product;
    internal readonly List<long> Terms = new List<long>();
    internal readonly HashSet<long> Remove = new HashSet<long>();
}

internal struct AssociativeUse
{
    internal AssociativeIsland Island;
    internal int Left;
    internal int Right;

    internal AssociativeUse(AssociativeIsland island, int left, int right)
    {
        Island = island;
        Left = left;
        Right = right;
    }
}

internal sealed class RelationSearch
{
    private const int PairAlternativeLimit = 12;
    private readonly long[] seeds;
    private readonly HashSet<long> seedSet;
    private readonly HashSet<long> targets;
    private readonly long limit;
    private readonly int registers;
    private readonly int depth;
    private readonly int maxPasses;
    private readonly int maxNeutral;
    private readonly bool additiveSharing;
    private readonly bool productSharing;
    private readonly bool commonFactors;
    private readonly bool wideBridges;
    private readonly bool affineOnly;
    private Dictionary<long, Calculation> graph;
    private Dictionary<long, int> rank;
    private Dictionary<long, List<long>> users;
    private Dictionary<long, Calculation> pairs;
    private Dictionary<long, List<Calculation>> pairAlternatives;
    private Dictionary<long, Dictionary<long, List<long>>> remainders;

    private RelationSearch(long[] seeds, long[] targets, long limit, int registers,
                           int depth, int maxPasses, int maxNeutral, bool additiveSharing,
                           bool productSharing, bool commonFactors, bool wideBridges,
                           bool affineOnly, Step[] original)
    {
        this.seeds = seeds;
        this.seedSet = new HashSet<long>(seeds);
        this.targets = new HashSet<long>(targets);
        this.limit = limit;
        this.registers = registers;
        this.depth = depth;
        this.maxPasses = maxPasses;
        this.maxNeutral = maxNeutral;
        this.additiveSharing = additiveSharing;
        this.productSharing = productSharing;
        this.commonFactors = commonFactors;
        this.wideBridges = wideBridges;
        this.affineOnly = affineOnly;
        this.graph = new Dictionary<long, Calculation>();
        this.rank = new Dictionary<long, int>();

        var values = new long[registers];
        Array.Copy(seeds, values, seeds.Length);
        foreach (Step step in original)
        {
            var calculation = new Calculation(step.Op, values[step.Left], values[step.Right]);
            long value = Evaluate(calculation);
            if (value == 0)
                throw new ArgumentException("Invalid input program");
            if (!seedSet.Contains(value) && !graph.ContainsKey(value))
            {
                rank.Add(value, rank.Count);
                graph.Add(value, calculation);
            }
            values[step.Destination] = value;
        }
        TrimGraph();
    }

    private long Evaluate(Calculation calculation)
    {
        long left = calculation.Left;
        long right = calculation.Right;
        if (left == 0 || right == 0)
            return 0;
        switch (calculation.Op)
        {
            case '+': return left <= limit - right ? left + right : 0;
            case '-': return left > right ? left - right : 0;
            case '*': return left <= limit / right ? left * right : 0;
            case '/': return left % right == 0 ? left / right : 0;
            default: return 0;
        }
    }

    private void MarkLive(long value, HashSet<long> live)
    {
        if (seedSet.Contains(value) || !live.Add(value))
            return;
        var calculation = graph[value];
        MarkLive(calculation.Left, live);
        MarkLive(calculation.Right, live);
    }

    private void TrimGraph()
    {
        var live = new HashSet<long>();
        foreach (long value in targets)
            MarkLive(value, live);
        foreach (long value in graph.Keys.Where(value => !live.Contains(value)).ToArray())
            graph.Remove(value);
    }

    private void BuildUsers()
    {
        users = new Dictionary<long, List<long>>();
        foreach (long value in graph.Keys)
            users.Add(value, new List<long>());
        foreach (var entry in graph)
        {
            var calculation = entry.Value;
            if (graph.ContainsKey(calculation.Left))
                users[calculation.Left].Add(entry.Key);
            if (calculation.Right != calculation.Left && graph.ContainsKey(calculation.Right))
                users[calculation.Right].Add(entry.Key);
        }
    }

    private void MarkDescendants(long value, HashSet<long> blocked)
    {
        if (!blocked.Add(value))
            return;
        foreach (long child in users[value])
            MarkDescendants(child, blocked);
    }

    private HashSet<long> FindRemovable(long pivot, long second = 0)
    {
        var remove = new HashSet<long> { pivot };
        var removedUsers = new Dictionary<long, int>();
        var pending = new Stack<long>();
        pending.Push(pivot);
        if (second > 0 && remove.Add(second))
            pending.Push(second);
        while (pending.Count > 0)
        {
            var calculation = graph[pending.Pop()];
            MarkRemovable(calculation.Left, removedUsers, remove, pending);
            if (calculation.Left != calculation.Right)
                MarkRemovable(calculation.Right, removedUsers, remove, pending);
        }
        return remove;
    }

    private void MarkRemovable(long value, Dictionary<long, int> removedUsers,
                               HashSet<long> remove, Stack<long> pending)
    {
        if (seedSet.Contains(value) || targets.Contains(value))
            return;
        int used;
        removedUsers.TryGetValue(value, out used);
        removedUsers[value] = ++used;
        if (used == users[value].Count && remove.Add(value))
            pending.Push(value);
    }

    private void IndexPair(char op, long left, long right)
    {
        var calculation = new Calculation(op, left, right);
        long value = Evaluate(calculation);
        if (value == 0 || value == left || value == right)
            return;
        if (!pairs.ContainsKey(value))
        {
            pairs.Add(value, calculation);
            return;
        }
        List<Calculation> alternatives;
        if (!pairAlternatives.TryGetValue(value, out alternatives))
        {
            alternatives = new List<Calculation>();
            pairAlternatives.Add(value, alternatives);
        }
        if (alternatives.Count < PairAlternativeLimit)
            alternatives.Add(calculation);
    }

    private void BuildPairs(long[] values)
    {
        pairs = new Dictionary<long, Calculation>(values.Length * values.Length);
        pairAlternatives = new Dictionary<long, List<Calculation>>();
        remainders = null;
        for (int i = 0; i < values.Length; ++i)
        {
            long left = values[i];
            for (int j = 0; j <= i; ++j)
            {
                long right = values[j];
                IndexPair('+', left, right);
                IndexPair('*', left, right);
                IndexPair('-', left, right);
                IndexPair('/', left, right);
            }
        }
    }

    // For each anchor, enumerate x = anchor op missing or missing op anchor.
    private int Invert(long x, long anchor, long[] missing, Calculation[] roots)
    {
        int count = 0;
        if (x > anchor)
        {
            missing[count] = x - anchor;
            roots[count++] = new Calculation('+', anchor, x - anchor);
        }
        if (x <= limit - anchor)
        {
            missing[count] = x + anchor;
            roots[count++] = new Calculation('-', x + anchor, anchor);
        }
        if (anchor > x)
        {
            missing[count] = anchor - x;
            roots[count++] = new Calculation('-', anchor, anchor - x);
        }
        if (anchor > 1 && x % anchor == 0)
        {
            missing[count] = x / anchor;
            roots[count++] = new Calculation('*', anchor, x / anchor);
        }
        if (anchor > 1 && x <= limit / anchor)
        {
            missing[count] = x * anchor;
            roots[count++] = new Calculation('/', x * anchor, anchor);
        }
        if (x > 1 && anchor % x == 0)
        {
            missing[count] = anchor / x;
            roots[count++] = new Calculation('/', anchor, anchor / x);
        }
        return count;
    }

    private bool FindOne(long value, HashSet<long> available, Calculation[] workRoots,
                         long[] workMissing, out Calculation recipe)
    {
        if (!pairs.TryGetValue(value, out recipe))
            return false;
        if (available.Contains(recipe.Left) && available.Contains(recipe.Right))
            return true;
        List<Calculation> alternatives;
        if (!pairAlternatives.TryGetValue(value, out alternatives))
            return false;
        foreach (Calculation option in alternatives)
        {
            if (available.Contains(option.Left) && available.Contains(option.Right))
            {
                recipe = option;
                return true;
            }
        }
        if (alternatives.Count < PairAlternativeLimit)
            return false;
        foreach (long anchor in available)
        {
            int count = Invert(value, anchor, workMissing, workRoots);
            for (int i = 0; i < count; ++i)
            {
                if (available.Contains(workMissing[i]))
                {
                    recipe = workRoots[i];
                    return true;
                }
            }
        }
        return false;
    }

    private bool CanIntroduce(long value, HashSet<long> remove)
    {
        return !seedSet.Contains(value) && (!graph.ContainsKey(value) || remove.Contains(value));
    }

    private static long ExactSquareRoot(long value)
    {
        long root = (long)Math.Round(Math.Sqrt(value));
        return root > 0 && value % root == 0 && value / root == root ? root : 0;
    }

    private Dictionary<long, Calculation> FindTwo(long value, long pivot, HashSet<long> available,
                                                  HashSet<long> remove, long[] missing,
                                                  Calculation[] roots, long[] scratchMissing,
                                                  Calculation[] scratchRoots)
    {
        Calculation inner;
        long squareRoot = ExactSquareRoot(value);
        if (squareRoot > 1 &&
            squareRoot != pivot && CanIntroduce(squareRoot, remove) &&
            FindOne(squareRoot, available, scratchRoots, scratchMissing, out inner))
        {
            return new Dictionary<long, Calculation>
            {
                { value, new Calculation('*', squareRoot, squareRoot) },
                { squareRoot, inner }
            };
        }
        long half = value / 2;
        if (value % 2 == 0 && half != pivot && CanIntroduce(half, remove) &&
            FindOne(half, available, scratchRoots, scratchMissing, out inner))
        {
            return new Dictionary<long, Calculation>
            {
                { value, new Calculation('+', half, half) },
                { half, inner }
            };
        }
        if (value == 1)
            return null;
        foreach (long anchor in available)
        {
            int count = Invert(value, anchor, missing, roots);
            for (int i = 0; i < count; ++i)
            {
                long middle = missing[i];
                if (middle != value && middle != pivot && CanIntroduce(middle, remove) &&
                    FindOne(middle, available, scratchRoots, scratchMissing, out inner))
                    return new Dictionary<long, Calculation> { { value, roots[i] }, { middle, inner } };
            }
        }
        return null;
    }

    private Step[] TryReplace(
        HashSet<long> remove, Dictionary<long, Calculation> replacement, int previousLength,
        bool trim = false)
    {
        var previousGraph = graph;
        graph = new Dictionary<long, Calculation>(graph);
        foreach (long value in remove)
            graph.Remove(value);
        foreach (var recipe in replacement)
            graph.Add(recipe.Key, recipe.Value);
        if (trim)
            TrimGraph();
        var candidate = graph.Count < previousLength ? TryAllocate() : null;
        if (candidate != null)
        {
            foreach (long value in replacement.Keys)
                if (!rank.ContainsKey(value) && graph.ContainsKey(value))
                    rank.Add(value, rank[PivotForNewValue(value)]);
            return candidate;
        }
        graph = previousGraph;
        BuildUsers();
        return null;
    }

    private Step[] TryBridges(long[] values, int previousLength)
    {
        var bridges = new Dictionary<long, List<BridgeUse>>();
        var missing = new long[6];
        var roots = new Calculation[6];
        var innerMissing = new long[6];
        var innerRoots = new Calculation[6];
        foreach (long pivot in graph.Keys)
        {
            foreach (long anchor in values)
            {
                if (pivot == anchor)
                    continue;
                int count = Invert(pivot, anchor, missing, roots);
                for (int i = 0; i < count; ++i)
                {
                    long middle = missing[i];
                    if (seedSet.Contains(middle) || graph.ContainsKey(middle) ||
                        (!wideBridges && !pairs.ContainsKey(middle)))
                        continue;
                    List<BridgeUse> uses;
                    if (!bridges.TryGetValue(middle, out uses))
                    {
                        uses = new List<BridgeUse>();
                        bridges.Add(middle, uses);
                    }
                    uses.Add(new BridgeUse(pivot, anchor, roots[i]));
                }
            }
        }
        foreach (var bridge in bridges.Where(entry => entry.Value.Count >= 2)
                                      .OrderByDescending(entry => pairs.ContainsKey(entry.Key))
                                      .ThenByDescending(entry => entry.Value.Count))
        {
            var uses = bridge.Value;
            for (int i = 0; i < uses.Count; ++i)
            {
                BridgeUse first = uses[i];
                for (int j = 0; j < i; ++j)
                {
                    BridgeUse second = uses[j];
                    if (first.Pivot == second.Pivot)
                        continue;
                    var remove = FindRemovable(first.Pivot, second.Pivot);
                    if (remove.Count <= 3)
                        continue;
                    var blocked = new HashSet<long>();
                    MarkDescendants(first.Pivot, blocked);
                    MarkDescendants(second.Pivot, blocked);
                    blocked.UnionWith(remove);
                    if (blocked.Contains(first.Anchor) || blocked.Contains(second.Anchor))
                        continue;
                    var available = new HashSet<long>(values.Where(value => !blocked.Contains(value)));
                    Calculation inner;
                    Dictionary<long, Calculation> replacement;
                    if (FindOne(bridge.Key, available, roots, missing, out inner))
                    {
                        replacement = new Dictionary<long, Calculation> { { bridge.Key, inner } };
                    }
                    else if (wideBridges && remove.Count > 4)
                    {
                        replacement = FindTwo(bridge.Key, first.Pivot, available, remove,
                                              roots: roots, missing: missing,
                                              scratchRoots: innerRoots, scratchMissing: innerMissing);
                        if (replacement == null || replacement.ContainsKey(second.Pivot))
                            continue;
                    }
                    else
                    {
                        continue;
                    }
                    replacement.Add(first.Pivot, first.Root);
                    replacement.Add(second.Pivot, second.Root);
                    var candidate = TryReplace(remove, replacement, previousLength);
                    if (candidate != null)
                        return candidate;
                }
            }
        }
        return null;
    }

    private Step[] TryInvertedEdges(long[] values, int previousLength)
    {
        var missing = new long[6];
        var inverses = new Calculation[6];
        foreach (var entry in graph.ToArray())
        {
            long output = entry.Key;
            Calculation recipe = entry.Value;
            if (recipe.Left == recipe.Right)
                continue;
            for (int side = 0; side < 2; ++side)
            {
                long input = side == 0 ? recipe.Left : recipe.Right;
                long anchor = side == 0 ? recipe.Right : recipe.Left;
                // Rebuilding the original input pays off only when it must survive
                // separately from this output's recipe.
                if (!graph.ContainsKey(input) ||
                    (!targets.Contains(input) && users[input].Count == 1))
                    continue;
                var remove = FindRemovable(input, output);
                if (remove.Count < 3)
                    continue;
                int candidates = Invert(input, output, missing, inverses);
                for (int i = 0; i < candidates; ++i)
                {
                    if (missing[i] != anchor)
                        continue;
                    Calculation inverse = inverses[i];
                    var blocked = new HashSet<long>();
                    MarkDescendants(input, blocked);
                    blocked.UnionWith(remove);
                    if (blocked.Contains(anchor))
                        break;
                    var available = new HashSet<long>(values.Where(value => !blocked.Contains(value)));
                    var replacement = FindReplacement(output, Math.Min(depth, remove.Count - 2),
                                                      available, remove);
                    if (replacement == null || replacement.ContainsKey(input))
                        break;
                    replacement.Add(input, inverse);
                    var candidate = TryReplace(remove, replacement, previousLength);
                    if (candidate != null)
                        return candidate;
                    break;
                }
            }
        }
        return null;
    }

    private Dictionary<long, Calculation> FindReplacement(long pivot, int budget,
                                                          HashSet<long> available,
                                                          HashSet<long> remove)
    {
        var scratchMissing = new long[6];
        var scratchRoots = new Calculation[6];
        Calculation inner;
        if (FindOne(pivot, available, scratchRoots, scratchMissing, out inner))
            return new Dictionary<long, Calculation> { { pivot, inner } };
        if (budget < 2)
            return null;

        var missing = new long[6];
        var roots = new Calculation[6];
        var two = FindTwo(pivot, pivot, available, remove, missing, roots, scratchMissing, scratchRoots);
        if (two != null)
            return two;
        if (budget < 3)
            return null;

        var outerMissing = new long[6];
        var outerRoots = new Calculation[6];
        long squareRoot = ExactSquareRoot(pivot);
        if (squareRoot > 1 && CanIntroduce(squareRoot, remove))
        {
            two = FindTwo(squareRoot, pivot, available, remove, missing, roots, scratchMissing, scratchRoots);
            if (two != null)
            {
                two.Add(pivot, new Calculation('*', squareRoot, squareRoot));
                return two;
            }
        }
        long half = pivot / 2;
        if (pivot % 2 == 0 && CanIntroduce(half, remove))
        {
            two = FindTwo(half, pivot, available, remove, missing, roots, scratchMissing, scratchRoots);
            if (two != null)
            {
                two.Add(pivot, new Calculation('+', half, half));
                return two;
            }
        }
        foreach (long anchor in available)
        {
            int count = Invert(pivot, anchor, outerMissing, outerRoots);
            for (int i = 0; i < count; ++i)
            {
                long middle = outerMissing[i];
                if (middle == pivot || !CanIntroduce(middle, remove))
                    continue;
                two = FindTwo(middle, pivot, available, remove, missing, roots, scratchMissing, scratchRoots);
                if (two != null)
                {
                    two.Add(pivot, outerRoots[i]);
                    return two;
                }
            }
        }

        // Join two pair results. Looking up each inverse is cheaper than pairing the
        // whole intermediate catalogue with itself.
        foreach (var edge in pairs)
        {
            if (edge.Key == pivot || !CanIntroduce(edge.Key, remove))
                continue;
            Calculation first = edge.Value;
            if ((!available.Contains(first.Left) || !available.Contains(first.Right)) &&
                !FindOne(edge.Key, available, scratchRoots, scratchMissing, out first))
                continue;
            int count = Invert(pivot, edge.Key, missing, roots);
            for (int i = 0; i < count; ++i)
            {
                long middle = missing[i];
                if (middle == pivot || middle == edge.Key || !CanIntroduce(middle, remove) ||
                    !FindOne(middle, available, scratchRoots, scratchMissing, out inner))
                    continue;
                return new Dictionary<long, Calculation>
                {
                    { pivot, roots[i] },
                    { edge.Key, first },
                    { middle, inner }
                };
            }
        }
        return budget >= 4 ? FindAffine(pivot, available, remove) : null;
    }

    private void IndexRemainders()
    {
        var known = seedSet.Concat(graph.Keys).ToArray();
        remainders = new Dictionary<long, Dictionary<long, List<long>>>();
        foreach (long scale in known)
        {
            if (scale < 64 || scale > limit / 2)
                continue;
            var byRemainder = new Dictionary<long, List<long>>();
            foreach (long value in known)
            {
                long remainder = value % scale;
                List<long> group;
                if (!byRemainder.TryGetValue(remainder, out group))
                {
                    group = new List<long>();
                    byRemainder.Add(remainder, group);
                }
                group.Add(value);
            }
            remainders.Add(scale, byRemainder);
        }
    }

    private Dictionary<long, Calculation> FindAffine(long target, HashSet<long> available,
                                                     HashSet<long> remove)
    {
        if (remainders == null)
            IndexRemainders();
        var missing = new long[6];
        var roots = new Calculation[6];
        var scratchMissing = new long[6];
        var scratchRoots = new Calculation[6];
        foreach (var entry in remainders)
        {
            long scale = entry.Key;
            if (!available.Contains(scale))
                continue;
            long residue = target % scale;
            for (int sign = 0; sign < 2; ++sign)
            {
                long residualRemainder = sign == 0 || residue == 0 ? residue : scale - residue;
                List<long> residuals;
                if (!entry.Value.TryGetValue(residualRemainder, out residuals))
                    continue;
                foreach (long residual in residuals)
                {
                    if (!available.Contains(residual))
                        continue;
                    // The required product is a multiple of the chosen scale. Its
                    // complement must itself be reachable in two new instructions.
                    long product = sign == 0 ? Math.Abs(target - residual) : target + residual;
                    long quotient = product / scale;
                    if (product > limit || quotient <= 1 || quotient == product || quotient == target ||
                        product == target || !CanIntroduce(product, remove) ||
                        !CanIntroduce(quotient, remove))
                        continue;
                    var subtree = FindTwo(quotient, target, available, remove,
                                          missing, roots, scratchMissing, scratchRoots);
                    if (subtree == null || subtree.ContainsKey(product))
                        continue;
                    subtree.Add(product, new Calculation('*', scale, quotient));
                    Calculation root;
                    if (sign == 1)
                        root = new Calculation('-', product, residual);
                    else if (target > residual)
                        root = new Calculation('+', product, residual);
                    else
                        root = new Calculation('-', residual, product);
                    subtree.Add(target, root);
                    return subtree;
                }
            }
        }
        return null;
    }

    private static bool IsAssociative(Calculation recipe, bool product)
    {
        return product ? recipe.Op == '*' : recipe.Op == '+' || recipe.Op == '-';
    }

    private void CollectTerms(long value, int sign, AssociativeIsland island)
    {
        if (island.Terms.Count > 10)
            return;
        Calculation recipe;
        if (graph.TryGetValue(value, out recipe) && IsAssociative(recipe, island.Product) &&
            (value == island.Root || (!targets.Contains(value) && users[value].Count == 1 &&
                                      recipe.Left != recipe.Right)))
        {
            island.Remove.Add(value);
            CollectTerms(recipe.Left, sign, island);
            CollectTerms(recipe.Right, recipe.Op == '-' ? -sign : sign, island);
        }
        else
        {
            island.Terms.Add(sign * value);
        }
    }

    private long JoinTerms(long left, long right, bool product)
    {
        if (!product)
            return left + right;
        return left <= limit / right ? left * right : 0;
    }

    private static Calculation CombineTerms(long left, long right, bool product)
    {
        if (product)
            return new Calculation('*', left, right);
        if ((left > 0) == (right > 0))
            return new Calculation('+', Math.Abs(left), Math.Abs(right));
        long a = Math.Abs(left);
        long b = Math.Abs(right);
        return new Calculation('-', Math.Max(a, b), Math.Min(a, b));
    }

    private bool RebuildTerms(AssociativeUse use, HashSet<long> remove,
                              HashSet<long> blocked, Dictionary<long, Calculation> recipes)
    {
        var terms = new List<long>();
        var original = use.Island.Terms;
        bool product = use.Island.Product;
        terms.Add(JoinTerms(original[use.Left], original[use.Right], product));
        for (int i = 0; i < original.Count; ++i)
            if (i != use.Left && i != use.Right)
                terms.Add(original[i]);
        return ComposeTerms(terms, use.Island.Root, product, remove, blocked, recipes);
    }

    private bool CanReuse(long value, HashSet<long> remove, HashSet<long> blocked)
    {
        return seedSet.Contains(value) ||
               (graph.ContainsKey(value) && !remove.Contains(value) && !blocked.Contains(value));
    }

    private bool ComposeTerms(List<long> terms, long root, bool product, HashSet<long> remove,
                              HashSet<long> blocked, Dictionary<long, Calculation> recipes)
    {
        // Only choose intermediates below the cap, with positive stored magnitude.
        // Try the smallest-magnitude joins first to limit pressure at the upper bound.
        while (terms.Count > 1)
        {
            int bestLeft = -1;
            int bestRight = -1;
            long bestPriority = long.MaxValue;
            long bestValue = 0;
            bool bestReuse = false;
            for (int i = 0; i < terms.Count; ++i)
                for (int j = 0; j < i; ++j)
                {
                    long value = Math.Abs(JoinTerms(terms[i], terms[j], product));
                    if (value == 0 || value > limit ||
                        (terms.Count > 2 && value == root))
                        continue;
                    bool reuse = CanReuse(value, remove, blocked);
                    if (!reuse && (recipes.ContainsKey(value) || !CanIntroduce(value, remove)))
                        continue;
                    long priority = reuse ? value - limit : value;
                    if (priority >= bestPriority)
                        continue;
                    bestLeft = i;
                    bestRight = j;
                    bestValue = value;
                    bestPriority = priority;
                    bestReuse = reuse;
                }
            if (bestLeft == -1)
                return false;
            long first = terms[bestLeft];
            long second = terms[bestRight];
            if (!bestReuse)
                recipes.Add(bestValue, CombineTerms(first, second, product));
            terms[bestRight] = JoinTerms(first, second, product);
            terms.RemoveAt(bestLeft);
        }
        return terms[0] == root;
    }

    private Step[] TryAssociativeSharing(int previousLength, bool product)
    {
        var joins = new Dictionary<long, List<AssociativeUse>>();
        foreach (var entry in graph)
        {
            long value = entry.Key;
            if (!IsAssociative(entry.Value, product) ||
                (!targets.Contains(value) && users[value].Count == 1 &&
                 IsAssociative(graph[users[value][0]], product)))
                continue;
            var island = new AssociativeIsland { Root = value, Product = product };
            CollectTerms(value, 1, island);
            if (island.Terms.Count < 3 || island.Terms.Count > 10)
                continue;
            for (int i = 0; i < island.Terms.Count; ++i)
                for (int j = 0; j < i; ++j)
                {
                    long join = Math.Abs(JoinTerms(island.Terms[i], island.Terms[j], product));
                    if (join == 0 || join > limit || island.Remove.Contains(join))
                        continue;
                    List<AssociativeUse> uses;
                    if (!joins.TryGetValue(join, out uses))
                    {
                        uses = new List<AssociativeUse>();
                        joins.Add(join, uses);
                    }
                    uses.Add(new AssociativeUse(island, i, j));
                }
        }
        foreach (var join in joins.OrderByDescending(entry => entry.Value.Count))
        {
            var uses = join.Value;
            if (graph.ContainsKey(join.Key) || seedSet.Contains(join.Key))
            {
                foreach (AssociativeUse use in uses)
                {
                    var blocked = new HashSet<long>();
                    MarkDescendants(use.Island.Root, blocked);
                    if (blocked.Contains(join.Key))
                        continue;
                    var recipes = new Dictionary<long, Calculation>();
                    if (!RebuildTerms(use, use.Island.Remove, blocked, recipes))
                        continue;
                    var candidate = TryReplace(use.Island.Remove, recipes, previousLength, trim: true);
                    if (candidate != null)
                        return candidate;
                }
                continue;
            }
            for (int i = 0; i < uses.Count; ++i)
                for (int j = 0; j < i; ++j)
                {
                    AssociativeUse first = uses[i];
                    AssociativeUse second = uses[j];
                    if (first.Island.Root == second.Island.Root)
                        continue;
                    var remove = new HashSet<long>(first.Island.Remove);
                    remove.UnionWith(second.Island.Remove);
                    var blocked = new HashSet<long>();
                    MarkDescendants(first.Island.Root, blocked);
                    MarkDescendants(second.Island.Root, blocked);
                    var terms = first.Island.Terms;
                    var shared = CombineTerms(terms[first.Left], terms[first.Right], product);
                    var recipes = new Dictionary<long, Calculation> { { join.Key, shared } };
                    if (!RebuildTerms(first, remove, blocked, recipes) ||
                        !RebuildTerms(second, remove, blocked, recipes))
                        continue;
                    var candidate = TryReplace(remove, recipes, previousLength, trim: true);
                    if (candidate != null)
                        return candidate;
                }
        }
        return null;
    }

    private bool ExclusiveProduct(long value, AssociativeIsland island, out Calculation recipe)
    {
        return graph.TryGetValue(value, out recipe) && recipe.Op == '*' &&
               !targets.Contains(value) && users[value].All(island.Remove.Contains) &&
               island.Terms.Count(term => Math.Abs(term) == value) == 1;
    }

    private Step[] TryCommonFactors(int previousLength)
    {
        foreach (var entry in graph.ToArray())
        {
            long output = entry.Key;
            if (!IsAssociative(entry.Value, false))
                continue;
            var island = new AssociativeIsland { Root = output };
            CollectTerms(output, 1, island);
            if (island.Terms.Count > 10)
                continue;
            for (int i = 0; i < island.Terms.Count; ++i)
            {
                long first = island.Terms[i];
                Calculation a;
                if (!ExclusiveProduct(Math.Abs(first), island, out a))
                    continue;
                for (int j = 0; j < i; ++j)
                {
                    long second = island.Terms[j];
                    Calculation b;
                    if (Math.Abs(first) == Math.Abs(second) ||
                        !ExclusiveProduct(Math.Abs(second), island, out b))
                        continue;
                    for (int swap = 0; swap < 2; ++swap)
                    {
                        long factor = swap == 0 ? a.Left : a.Right;
                        long left = Math.Sign(first) * (swap == 0 ? a.Right : a.Left);
                        long right;
                        if (factor == b.Left)
                            right = Math.Sign(second) * b.Right;
                        else if (factor == b.Right)
                            right = Math.Sign(second) * b.Left;
                        else
                            continue;
                        long sum = Math.Abs(left + right);
                        long joined = Math.Abs(first + second);
                        if (sum == 0 || sum > limit || joined == 0 || joined > limit)
                            continue;
                        var remove = new HashSet<long>(island.Remove) { Math.Abs(first), Math.Abs(second) };
                        if (remove.Contains(Math.Abs(left)) || remove.Contains(Math.Abs(right)) ||
                            remove.Contains(factor))
                            continue;
                        var blocked = new HashSet<long>();
                        MarkDescendants(output, blocked);
                        var recipes = new Dictionary<long, Calculation>();
                        if (!CanReuse(sum, remove, blocked))
                        {
                            if (!CanIntroduce(sum, remove) || sum == joined || sum == output)
                                continue;
                            recipes.Add(sum, CombineTerms(left, right, false));
                        }
                        if (!CanReuse(joined, remove, blocked))
                        {
                            if (!CanIntroduce(joined, remove) || (joined == output && island.Terms.Count != 2))
                                continue;
                            recipes.Add(joined, new Calculation('*', sum, factor));
                        }
                        var terms = new List<long> { first + second };
                        for (int k = 0; k < island.Terms.Count; ++k)
                            if (k != i && k != j)
                                terms.Add(island.Terms[k]);
                        if (!ComposeTerms(terms, output, false, remove, blocked, recipes))
                            continue;
                        var candidate = TryReplace(remove, recipes, previousLength, trim: true);
                        if (candidate != null)
                            return candidate;
                    }
                }
            }
        }
        return null;
    }

    private long ChangeInUse(long value, Calculation previous, int direction)
    {
        if (value == previous.Left || value == previous.Right)
            return 0;
        // A seed or a target is required independently of its users.
        if (seedSet.Contains(value) || targets.Contains(value))
            return direction * (2L * graph.Count + 1);
        return 2L * direction * users[value].Count + 1;
    }

    private long ConcentrationGain(Calculation oldRecipe, Calculation newRecipe)
    {
        long gain = ChangeInUse(newRecipe.Left, oldRecipe, 1) +
                    ChangeInUse(oldRecipe.Left, newRecipe, -1);
        if (newRecipe.Left != newRecipe.Right)
            gain += ChangeInUse(newRecipe.Right, oldRecipe, 1);
        if (oldRecipe.Left != oldRecipe.Right)
            gain += ChangeInUse(oldRecipe.Right, newRecipe, -1);
        return gain;
    }

    private bool TryReroute(long[] values)
    {
        var moves = new List<Tuple<long, long, Calculation>>();
        var missing = new long[6];
        var roots = new Calculation[6];
        foreach (var entry in graph)
        {
            long pivot = entry.Key;
            if (FindRemovable(pivot).Count != 1)
                continue;
            var blocked = new HashSet<long>();
            MarkDescendants(pivot, blocked);
            foreach (long anchor in values)
            {
                if (blocked.Contains(anchor))
                    continue;
                int count = Invert(pivot, anchor, missing, roots);
                for (int i = 0; i < count; ++i)
                {
                    long other = missing[i];
                    if (blocked.Contains(other) || (!seedSet.Contains(other) && !graph.ContainsKey(other)))
                        continue;
                    long gain = ConcentrationGain(entry.Value, roots[i]);
                    if (gain > 0)
                        moves.Add(Tuple.Create(gain, pivot, roots[i]));
                }
            }
        }
        foreach (var move in moves.OrderByDescending(item => item.Item1))
        {
            var replacement = new Dictionary<long, Calculation> { { move.Item2, move.Item3 } };
            if (TryReplace(new HashSet<long> { move.Item2 }, replacement, graph.Count + 1) != null)
                return true;
        }
        return false;
    }

    private Step[] Allocate(int preference)
    {
        BuildUsers();
        var live = new Dictionary<long, int>();
        var remainingUses = new Dictionary<long, int>();
        var dependencies = new Dictionary<long, int>();
        var ready = new List<long>();
        var free = new SortedSet<int>(Enumerable.Range(0, registers));
        for (int i = 0; i < seeds.Length; ++i)
        {
            if (!live.ContainsKey(seeds[i]))
            {
                live.Add(seeds[i], i);
                remainingUses.Add(seeds[i], 0);
                free.Remove(i);
            }
        }
        foreach (var entry in graph)
        {
            Calculation calculation = entry.Value;
            remainingUses.Add(entry.Key, users[entry.Key].Count);
            int waiting = 0;
            if (seedSet.Contains(calculation.Left))
                ++remainingUses[calculation.Left];
            else
                ++waiting;
            if (calculation.Right != calculation.Left)
            {
                if (seedSet.Contains(calculation.Right))
                    ++remainingUses[calculation.Right];
                else
                    ++waiting;
            }
            dependencies.Add(entry.Key, waiting);
            if (waiting == 0)
                ready.Add(entry.Key);
        }
        foreach (long value in seedSet)
            if (remainingUses[value] == 0)
            {
                free.Add(live[value]);
                live.Remove(value);
            }

        var result = new List<Step>();
        while (result.Count < graph.Count)
        {
            int best = -1;
            long bestScore = long.MaxValue;
            for (int i = 0; i < ready.Count; ++i)
            {
                long value = ready[i];
                var calculation = graph[value];
                int dying = remainingUses[calculation.Left] == 1 ? 1 : 0;
                if (calculation.Right != calculation.Left && remainingUses[calculation.Right] == 1)
                    ++dying;
                if (dying == 0 && free.Count == 0)
                    continue;
                int position;
                if (!rank.TryGetValue(value, out position))
                    position = Math.Min(rank[PivotForNewValue(value)], 100000);
                long score = position - preference * dying;
                if (remainingUses[value] == 0)
                    score -= preference;
                if (score < bestScore)
                {
                    best = i;
                    bestScore = score;
                }
            }
            if (best == -1)
                return null;

            long output = ready[best];
            var operation = graph[output];
            int left = live[operation.Left];
            int right = live[operation.Right];
            Release(operation.Left, live, remainingUses, free);
            if (operation.Right != operation.Left)
                Release(operation.Right, live, remainingUses, free);
            int destination = free.Min;
            if (remainingUses[output] != 0)
            {
                live.Add(output, destination);
                free.Remove(destination);
            }
            result.Add(new Step(operation.Op, left, right, destination));
            ready.RemoveAt(best);
            foreach (long child in users[output])
                if (--dependencies[child] == 0)
                    ready.Add(child);
        }
        return result.ToArray();
    }

    private long PivotForNewValue(long value)
    {
        while (!rank.ContainsKey(value))
            value = users[value][0];
        return value;
    }

    private static void Release(long value, Dictionary<long, int> live,
                                Dictionary<long, int> remainingUses, SortedSet<int> free)
    {
        if (--remainingUses[value] == 0)
        {
            free.Add(live[value]);
            live.Remove(value);
        }
    }

    private Step[] TryAllocate()
    {
        foreach (int preference in new[] { 0, 8, 32, 10000 })
        {
            var result = Allocate(preference);
            if (result != null)
                return result;
        }
        return null;
    }

    private Step[] Optimize(Step[] original)
    {
        Step[] best = original;
        if (graph.Count < original.Length)
        {
            var trimmed = TryAllocate();
            if (trimmed != null)
                best = trimmed;
        }
        int neutralMoves = 0;
        for (int pass = 0; pass < maxPasses; ++pass)
        {
            BuildUsers();
            if (additiveSharing || productSharing || commonFactors)
            {
                var candidate = additiveSharing ? TryAssociativeSharing(best.Length, false) : null;
                if (candidate == null && productSharing)
                    candidate = TryAssociativeSharing(best.Length, true);
                if (candidate == null && commonFactors)
                    candidate = TryCommonFactors(best.Length);
                if (candidate != null)
                {
                    best = candidate;
                    continue;
                }
            }
            if (depth == 0 && !affineOnly)
                break;
            long[] values = seedSet.Concat(graph.Keys).OrderBy(value => value).ToArray();
            var choices = graph.Keys
                .Select(value => new KeyValuePair<long, HashSet<long>>(value, FindRemovable(value)))
                .Where(entry => entry.Value.Count >= (affineOnly ? 5 : 2))
                .OrderByDescending(entry => entry.Value.Count)
                .ThenByDescending(entry => entry.Key)
                .ToArray();
            if (choices.Length == 0 && (affineOnly || (depth < 3 && neutralMoves >= maxNeutral)))
                break;
            BuildPairs(values);
            bool improved = false;
            foreach (var choice in choices)
            {
                long pivot = choice.Key;
                var remove = choice.Value;
                var blocked = new HashSet<long>();
                MarkDescendants(pivot, blocked);
                blocked.UnionWith(remove);
                var available = new HashSet<long>(values.Where(value => !blocked.Contains(value)));
                var replacement = affineOnly
                    ? FindAffine(pivot, available, remove)
                    : FindReplacement(pivot, Math.Min(depth, remove.Count - 1), available, remove);
                if (replacement == null)
                    continue;

                var candidate = TryReplace(remove, replacement, best.Length);
                if (candidate != null)
                {
                    best = candidate;
                    improved = true;
                    break;
                }
            }
            if (!improved && depth >= 3 && !affineOnly)
            {
                var candidate = TryInvertedEdges(values, best.Length) ?? TryBridges(values, best.Length);
                if (candidate != null)
                {
                    best = candidate;
                    improved = true;
                }
            }
            if (!improved)
            {
                if (neutralMoves >= maxNeutral || !TryReroute(values))
                    break;
                ++neutralMoves;
            }
        }
        return best;
    }

    private static string[] ReadFields()
    {
        return Console.ReadLine().Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);
    }

    private static long[] ReadValues()
    {
        return ReadFields().Select(field => long.Parse(field, CultureInfo.InvariantCulture)).ToArray();
    }

    private static int Main(string[] args)
    {
        int depth = args.Length > 0 ? int.Parse(args[0]) : 2;
        int maxPasses = args.Length > 1 ? int.Parse(args[1]) : 20;
        int maxNeutral = args.Length > 2 ? int.Parse(args[2]) : 0;
        bool additiveSharing = args.Length > 3 && bool.Parse(args[3]);
        bool productSharing = args.Length > 4 && bool.Parse(args[4]);
        bool commonFactors = args.Length > 5 && bool.Parse(args[5]);
        bool wideBridges = args.Length > 6 && bool.Parse(args[6]);
        bool affineOnly = args.Length > 7 && bool.Parse(args[7]);
        string header;
        while ((header = Console.ReadLine()) != null)
        {
            var fields = header.Split(' ');
            long limit = long.Parse(fields[0], CultureInfo.InvariantCulture);
            int registers = int.Parse(fields[1], CultureInfo.InvariantCulture);
            int count = int.Parse(fields[2], CultureInfo.InvariantCulture);
            var seeds = ReadValues();
            var targets = ReadValues();
            var steps = new Step[count];
            for (int i = 0; i < count; ++i)
            {
                var parts = ReadFields();
                steps[i] = new Step(parts[0][0], int.Parse(parts[1]), int.Parse(parts[2]), int.Parse(parts[3]));
            }
            Step[] result;
            try
            {
                var search = new RelationSearch(seeds, targets, limit, registers, depth, maxPasses,
                                                maxNeutral, additiveSharing, productSharing, commonFactors,
                                                wideBridges, affineOnly, steps);
                result = search.Optimize(steps);
            }
            catch (Exception error)
            {
                Console.Error.WriteLine(error.GetType().FullName);
                Console.Error.WriteLine(error.StackTrace);
                return 1;
            }
            Console.WriteLine(result.Length);
            foreach (Step step in result)
                Console.WriteLine("{0} {1} {2} {3}", step.Op, step.Left, step.Right, step.Destination);
            Console.Out.Flush();
        }
        return 0;
    }
}
