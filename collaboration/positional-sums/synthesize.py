"""Construct entire arithmetic programs from a matrix of signed positional digits."""
from collections import Counter, defaultdict
from itertools import combinations
from math import isqrt
from pathlib import Path
import argparse, json, sys

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p/'elf.py').exists())
sys.path.insert(0,str(ROOT))
from elf import arithmetic, check, read_puzzles, write_submission
from graph import active_graph, compile_graph


class Builder:
    def __init__(self, puzzle):
        self.p = puzzle
        self.seeds = set(puzzle.seeds)
        self.graph = {}
        self.choices = {}
        self.cost = {}
        self.put('/', puzzle.seeds[0], puzzle.seeds[0])

    def put(self, op, a, b):
        v = arithmetic(op, a, b)
        if not 0<v<=self.p.limit:
            raise ValueError((a,op,b))
        if v not in self.graph and v not in self.seeds:
            self.graph[v] = op, a, b
        return v

    def prepare_digits(self, last):
        # Dynamic programming over increasing integer literals. Quotients and
        # differences of starting values are allowed even if an input is large.
        direct = {s:None for s in self.seeds}
        for a in self.seeds:
            for b in self.seeds:
                for v,op in ((a+b,'+'),(a-b,'-'),(a*b,'*'),(a//b if a%b==0 else 0,'/')):
                    if 0<v<=last and v not in direct:direct[v]=op,a,b
        for v in range(1,last+1):
            choices = []
            if v in self.seeds:
                self.cost[v]=0
                continue
            if v==1:
                self.cost[v]=int(v not in self.seeds)
                continue
            if v in direct:choices.append((1,direct[v]))
            for a in range(1,min(v//2,32)+1):
                b=v-a
                choices.append((1+self.cost[b]+(0 if a==b else self.cost[a]),('+',b,a)))
            for a in range(2,isqrt(v)+1):
                if v%a:continue
                b=v//a
                choices.append((1+self.cost[b]+(0 if a==b else self.cost[a]),('*',b,a)))
            self.cost[v],self.choices[v]=min(choices)

    def literal(self,v):
        if v in self.seeds or v in self.graph:return v
        op,a,b=self.choices[v]
        self.literal(a);self.literal(b)
        return self.put(op,a,b)

    def power(self, b, exponent):
        v=b**exponent
        if exponent<=1:return self.literal(v)
        if v in self.seeds or v in self.graph:return v
        a=self.power(b,exponent//2)
        z=self.put('*',a,a)
        return self.put('*',z,b) if exponent%2 else z

    def add(self, a, b):
        if a+b==0:return 0
        if a*b>0:
            c=self.put('+',abs(a),abs(b))
        else:
            c=self.put('-',max(abs(a),abs(b)),min(abs(a),abs(b)))
        return c if a+b>0 else -c


def positions(t,b,representation,w,limit):
    x=t;j=0;terms=[]
    while x:
        if representation=='naf':
            if x%2:
                d=x%(1<<w)
                if d>=(1<<(w-1)):d-=1<<w
            else:d=0
        else:
            d=x%b
            if representation=='balanced' and d>b//2:d-=b
        if d:terms.append((j,d))
        x=(x-d)//b;j+=1
    if any(abs(d)*b**j>limit for j,d in terms):
        return positions(t,b,'unsigned',w,limit)
    return terms


def pairkey(a,b):
    pair=tuple(sorted((a,b)))
    return min(pair,tuple(sorted((-a,-b))))


def compress(rows, builder):
    limit=builder.p.limit
    while True:
        count=Counter()
        for row in rows:
            count.update({pairkey(a,b) for a,b in combinations(row,2) if 0<abs(a+b)<=limit})
        if not count:break
        keys=[k for k,n in count.items() if n>=2]
        if not keys:break
        def rank(k):
            known=abs(sum(k)) in builder.graph or abs(sum(k)) in builder.seeds
            return count[k]+known,count[k],-abs(sum(k)),-abs(k[0])
        a,b=max(sorted(keys),key=rank)
        for values in rows:
            for sign in (1,-1):
                x,y=a*sign,b*sign
                if x not in values or y not in values or (x==y and values.count(x)<2):continue
                values.remove(x);values.remove(y);values.append(builder.add(x,y));break


def candidate(p, spec, group, cse):
    base,form,width=spec
    b=Builder(p)
    matrix=[positions(t,base,form,width,p.limit) for t in p.targets]
    b.prepare_digits(max(base,max(abs(d) for row in matrix for _,d in row)))
    b.literal(base)
    rows=[]
    for data in matrix:
        values=[]
        if group:
            buckets=defaultdict(list)
            for j,d in data:buckets[abs(d)].append(b.power(base,j)*(1 if d>0 else -1))
            parts=[]
            for digit,places in buckets.items():
                if len(places)==1 or abs(sum(places))*digit>p.limit:
                    parts.extend((digit,x) for x in places);continue
                # Largest opposite-sign combinations first to keep intermediate values legal.
                stash=places[:]
                while len(stash)>1:
                    j,k=min(((j,k) for j,k in combinations(range(len(stash)),2) if abs(stash[j]+stash[k])<=p.limit),key=lambda jk:abs(stash[jk[0]]+stash[jk[1]]))
                    tail=stash.pop(k);head=stash.pop(j);new=b.add(head,tail)
                    if new:stash.append(new)
                if stash:parts.append((digit,stash[0]))
        else:
            parts=[(abs(d),b.power(base,j)*(1 if d>0 else -1)) for j,d in data]
        for digit,x in parts:
            v=abs(x) if digit==1 else b.put('*',b.literal(digit),abs(x))
            values.append(v if x>0 else -v)
        rows.append(values)
    if cse:compress(rows,b)
    for t,values in zip(p.targets,rows):
        while len(values)>1:
            def rank(pair):
                x,y=pair;s=abs(values[x]+values[y])
                return s>p.limit,s not in b.seeds and s not in b.graph,s
            j,k=min(combinations(range(len(values)),2),key=rank)
            y=values.pop(k);x=values.pop(j);new=b.add(x,y)
            if new:values.append(new)
        assert values==[t]
    g=active_graph(p,b.graph)
    return g


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('puzzles',type=Path)
    ap.add_argument('out',type=Path)
    ap.add_argument('ids',nargs='+')
    a=ap.parse_args();puzzles={p.id:p for p in read_puzzles(a.puzzles)}
    a.out.mkdir(parents=True,exist_ok=True)
    for i in a.ids:
        p=puzzles['scored_'+i.zfill(4)]
        specs=[(b,f,0) for b in (3,5,9,16,27,32,49,64,125,128,256) for f in ('unsigned','balanced')]
        specs += [(2,'naf',w) for w in (3,4,5,6,7,8,9,10,11,12)]
        record={};witness={}
        for arm in ('ordinary','shared'):
            choices=[]
            for spec in specs:
                for group in ((False,) if arm=='ordinary' else (False,True)):
                    g=candidate(p,spec,group,arm=='shared')
                    choices.append((len(g),spec,group,g))
            choices.sort(key=lambda x:x[:3]);best=best_tape=None
            for score,spec,group,g in choices:
                if best is not None and score>=best[0]:break
                tape=compile_graph(p,g,attempts=4,recompute=True,schedule_width=3)
                if tape is not None and (best is None or len(tape)<best[0]):
                    best=(check(p,tape),spec,group,score);best_tape=tape
            assert best_tape is not None
            record[arm]={'physical':best[0],'base':best[1][0],'form':best[1][1],'width':best[1][2],'group':best[2],'winning_graph_size':best[3],'minimum_graph_size':choices[0][0],'variants':len(choices)}
            witness[arm]=best_tape
        for arm,tape in witness.items():write_submission(a.out/(i+'-'+arm+'.csv'),[p],{p.id:tape})
        (a.out/(i+'.json')).write_text(json.dumps(record,indent=2)+'\n',encoding='utf8')
        print(i,record,flush=True)

if __name__=='__main__':main()
