"""Finite-value arithmetic pool and rooted reachability checks used in the paired follow-up."""
from collections import defaultdict
from itertools import combinations_with_replacement, combinations
from pysat.card import CardEnc, EncType
from pysat.solvers import Solver
from tiny import encode


def outputs(a,b,limit):
    lo,hi=sorted((a,b))
    return {n for n in (a+b,a*b,hi-lo,hi//lo if hi%lo==0 else 0) if 0<n<=limit and n!=a and n!=b}


def reverse(t,b,limit):
    return {v for v in (t-b,b-t,t+b,t*b,t//b if t%b==0 else 0,b//t if b%t==0 else 0)
            if 0<v<=limit and v!=t and b!=t}


class Pool:
    def __init__(self,p,pool,cap,sparse_order):
        self.p=p
        starts=set(p.seeds)
        goals=set(p.targets)-starts
        self.x={v:i for i,v in enumerate(sorted(set(pool)-starts),1)}
        raw=defaultdict(set)
        for a,b in combinations_with_replacement(pool,2):
            for v in outputs(a,b,p.limit):
                if v in self.x:raw[v].add(tuple(sorted({a,b}-starts)))
        self.choices={}
        self.solver=Solver(name='cadical195')
        self.visited=set()
        last=len(self.x)
        order={}
        def before(a,b):
            nonlocal last
            key=(a,b) if a<b else (b,a)
            if key not in order:
                last+=1;order[key]=last
            return order[key] if a<b else -order[key]
        for v,x in self.x.items():
            terms=raw[v]
            if () in terms:
                terms=[()]
            else:
                solo={q[0]for q in terms if len(q)==1}
                terms=sorted(q for q in terms if len(q)<2 or not solo.intersection(q))
            offers=[]
            for required in terms:
                last+=1;lit=last;offers.append((required,lit))
                self.solver.add_clause([-lit,x])
                for u in required:
                    self.solver.add_clause([-lit,self.x[u]])
                    if sparse_order:self.solver.add_clause([-lit,before(u,v)])
            self.solver.add_clause([-x,*[lit for req,lit in offers]])
            self.choices[v]=offers
        if sparse_order:
            edges=defaultdict(set)
            for a,b in order:edges[a].add(b)
            for a,b in order:
                for c in edges[a]&edges[b]:
                    ab,bc,ac=order[a,b],order[b,c],order[a,c]
                    self.solver.add_clause([-ab,-bc,ac])
                    self.solver.add_clause([ab,bc,-ac])
        for v in goals:self.solver.add_clause([self.x[v]])
        helpers=[x for v,x in self.x.items()if v not in goals]
        if cap<len(helpers):
            self.solver.append_formula(CardEnc.atmost(helpers,bound=cap,top_id=last,encoding=EncType.seqcounter))
        self.cuts=0
        self.cyclic_models=0

    def entrance(self,group):
        frozen=frozenset(group)
        if not group or frozen in self.visited:return
        self.visited.add(frozen)
        outside=[lit for v in group for required,lit in self.choices[v] if frozen.isdisjoint(required)]
        g=frozen.intersection(self.p.targets)
        if g:self.solver.add_clause(outside)
        else:
            for v in group:self.solver.add_clause([-self.x[v],*outside])
        self.cuts+=1

    def solve(self,keep,old,conflicts,iterations):
        self.solver.set_phases([int(x) if v in old else -int(x) for v,x in self.x.items()])
        for _ in range(iterations):
            self.solver.conf_budget(conflicts)
            result=self.solver.solve_limited(assumptions=[self.x[v]for v in keep])
            if result is not True:return None,'UNSAT_POOL' if result is False else 'UNKNOWN'
            model=set(self.solver.get_model())
            chosen={v for v,x in self.x.items()if x in model}
            reached=set(self.p.seeds);seq=[]
            while set(self.p.targets)-reached:
                new=[v for v in sorted(chosen-reached)if any(reached.issuperset(req) for req,_ in self.choices[v])]
                if not new:break
                seq.extend(new);reached.update(new)
            if reached.issuperset(self.p.targets):
                return encode(self.p,tuple(seq)),'FOUND'
            self.cyclic_models+=1
            need=chosen-reached
            self.entrance(need)
            # Closure among only the selected value variables lacked a root.
            # A goal or helper inside each disconnected group must enter via
            # some recipe with all inputs outside that group.
            links={v:set()for v in need}
            for v in need:
                for req,_ in self.choices[v]:
                    if chosen.issuperset(req):
                        for u in set(req)&need:links[v].add(u);links[u].add(v)
            todo=set(need)
            while todo:
                comp={todo.pop()};front=set(comp)
                while front:
                    more=set.union(set(),*(links[v]for v in front))&todo
                    todo-=more;comp|=more;front=more
                self.entrance(comp)
        return None,'CUT_LIMIT'
