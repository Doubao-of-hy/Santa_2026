using System;
using System.Collections.Generic;
using System.Linq;

// A basis consists of live values outside the removed expression. Build all one-step
// values, then join them in both directions at a requested number or near its factors.
internal sealed class ConeSearch
{
    private struct Edge
    {
        public long Out, A, B;
        public char Op;
        public Edge(long value, char op, long a, long b)
        { Out = value; Op = op; A = a; B = b; }
    }

    private struct Plan
    {
        public Edge[] Edges;
        public int Rank;
    }

    private readonly long target, limit;
    private readonly int cap, effort;
    private readonly long[] atoms;
    private readonly Dictionary<long, int> bias = new Dictionary<long, int>();
    private readonly Dictionary<long, Edge> bank = new Dictionary<long, Edge>();
    private readonly Dictionary<long, Edge> two = new Dictionary<long, Edge>();
    private readonly List<Plan> best = new List<Plan>();
    private long[] sorted;

    private ConeSearch(long target, long limit, int cost, int effort, long[] atoms)
    {
        this.target = target; this.limit = limit; this.cap = cost; this.atoms = atoms;
        this.effort = effort;
        for (int i = 0; i < atoms.Length; ++i) bias[atoms[i]] = i;
        foreach (long a in atoms) bank[a] = new Edge(a, '.', 0, 0);
        for (int i = 0; i < atoms.Length; ++i)
        for (int j = 0; j <= i; ++j)
        {
            long a = atoms[i], b = atoms[j], lo = Math.Min(a,b), hi = Math.Max(a,b);
            if (a <= limit-b) Add(a+b,'+',a,b);
            if (hi > lo) Add(hi-lo,'-',hi,lo);
            if (a <= limit/b) Add(a*b,'*',a,b);
            if (hi%lo == 0) Add(hi/lo,'/',hi,lo);
        }
        sorted = bank.Keys.OrderBy(x => x).ToArray();
    }

    private void Add(long v, char op, long a, long b)
    {
        if (!bank.ContainsKey(v)) bank.Add(v, new Edge(v,op,a,b));
    }

    // Given a proposed result and a known operand, return a valid inverse join.
    private Edge Join(long v, long a)
    {
        long b;
        if (v>a && bank.ContainsKey(b=v-a)) return new Edge(v,'+',a,b);
        if (a>v && bank.ContainsKey(b=a-v)) return new Edge(v,'-',a,b);
        if (v<=limit-a && bank.ContainsKey(b=v+a)) return new Edge(v,'-',b,a);
        if (a>1 && v%a==0 && bank.ContainsKey(b=v/a)) return new Edge(v,'*',a,b);
        if (a>v && a%v==0 && bank.ContainsKey(b=a/v)) return new Edge(v,'/',a,b);
        if (a>1 && v<=limit/a && bank.ContainsKey(b=v*a)) return new Edge(v,'/',b,a);
        return new Edge();
    }

    private bool Two(long v)
    {
        if (bank.ContainsKey(v)) return true;
        Edge e;
        if (two.TryGetValue(v,out e)) return e.Out != 0;
        foreach (long a in atoms)
        {
            e = Join(v,a);
            if (e.Out != 0) break;
        }
        two[v]=e;
        return e.Out != 0;
    }

    private void Expand(long v, List<Edge> edges, HashSet<long> seen, ref int rank)
    {
        if (!seen.Add(v)) return;
        int penalty;
        if (bias.TryGetValue(v,out penalty)) { rank += penalty; return; }
        Edge e;
        if (!bank.TryGetValue(v,out e)) e=two[v];
        Expand(e.A,edges,seen,ref rank); Expand(e.B,edges,seen,ref rank);
        edges.Add(e);
    }

    private void Propose(Edge first, Edge last)
    {
        var edges = new List<Edge>(6);
        var seen = new HashSet<long>();
        int rank=0;
        if (first.Out!=0)
        {
            Expand(first.A,edges,seen,ref rank); Expand(first.B,edges,seen,ref rank);
            if (!seen.Add(first.Out)) return;
            edges.Add(first);
        }
        if (last.Out!=0)
        {
            Expand(last.A,edges,seen,ref rank); Expand(last.B,edges,seen,ref rank);
            if (!seen.Add(last.Out)) return;
            edges.Add(last);
        }
        if (edges.Count>cap || edges.Count==0 || edges[edges.Count-1].Out!=target) return;
        int key=edges.Count*100000+rank;
        if (best.Count==6 && key>=best[5].Rank) return;
        foreach (var p in best)
            if (p.Edges.Length==edges.Count && p.Edges.Zip(edges,(x,y) =>
                x.Out==y.Out && x.Op==y.Op && x.A==y.A && x.B==y.B).All(s=>s)) return;
        best.Add(new Plan {Edges=edges.ToArray(), Rank=key});
        best.Sort((x,y)=>x.Rank.CompareTo(y.Rank));
        if (best.Count>6) best.RemoveAt(6);
    }

    private void Exact(long v, Edge last, bool balanced)
    {
        Edge e;
        if (bank.TryGetValue(v,out e))
        {
            if (e.Op!='.') Propose(e,last);
            else if(last.Out!=0) Propose(new Edge(),last);
        }
        foreach (long a in balanced ? sorted : atoms)
        {
            e=Join(v,a);
            if (e.Out!=0) Propose(e,last);
        }
    }

    private void Scales()
    {
        int queries=0;
        foreach(long m in sorted)
        {
            if (m<=1 || m>limit/2) continue;
            long q=target/m;
            if (q<2 || q>sorted[sorted.Length-1]+1) continue;
            int i=Array.BinarySearch(sorted,q);
            if(i<0) i=~i;
            bool atom=bias.ContainsKey(m);
            int spread=atom ? 4+effort*2 : 1+effort;
            for(int k=Math.Max(0,i-spread); k<Math.Min(sorted.Length,i+spread+1); ++k)
            {
                long x=sorted[k];
                if(x<2 || x>limit/m) continue;
                long prod=m*x, rem=Math.Abs(target-prod);
                if(rem==0 || rem==target || prod==target) continue;
                if(!bank.ContainsKey(rem))
                {
                    if(!atom || Math.Abs(k-i)>effort || queries>=1000*effort) continue;
                    ++queries;
                    if(!Two(rem)) continue;
                }
                var product=new Edge(prod,'*',m,x);
                if(bank.ContainsKey(prod)) product=new Edge();
                var last=prod<target ? new Edge(target,'+',prod,rem) : new Edge(target,'-',prod,rem);
                Propose(product,last);
            }
        }
    }

    private void Run()
    {
        Exact(target,new Edge(),true);
        if(cap>=3)
        {
            Scales();
            int index=0;
            foreach(long a in atoms)
            {
                bool full = effort>=2 && index++ < 3*effort;
                if(target>a) Exact(target-a,new Edge(target,'+',target-a,a),full);
                if(a>target) Exact(a-target,new Edge(target,'-',a,a-target),full);
                if(target<=limit-a) Exact(target+a,new Edge(target,'-',target+a,a),full);
                if(a>1 && target%a==0) Exact(target/a,new Edge(target,'*',target/a,a),full);
            }
        }
        Console.WriteLine(best.Count);
        foreach (var p in best)
        {
            Console.WriteLine(p.Edges.Length);
            foreach (var e in p.Edges)
                Console.WriteLine(e.Out+" "+e.Op+" "+e.A+" "+e.B);
        }
    }

    private static void Main()
    {
        string line;
        while((line=Console.ReadLine())!=null)
        {
            long[] cfg=Array.ConvertAll(line.Split(' '),long.Parse);
            long[] inputs=Array.ConvertAll(Console.ReadLine().Split(' '),long.Parse);
            new ConeSearch(cfg[0],cfg[1],(int)cfg[2],(int)cfg[3],inputs).Run();
        }
    }
}
