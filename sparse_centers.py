"""Buy shared recovered factors only when their combined target routes justify them."""
import argparse
from collections import Counter,defaultdict
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path

from center_hierarchy import neighbors
from crossover_lns import load_solver
from elf import read_puzzles,read_submission
from graph import active_graph,first_recipes


def literals(t,row,inner,derived,seeds):
    a,b,k,r,d,e=(row[x] for x in ("a","b","k","r","d","e"))
    c=a*b;partial={};ingredients=set()
    def build(x):
        if x in seeds or x in partial or x in ingredients:return
        if x not in derived:ingredients.add(x);return
        op,left,right=derived[x];build(left);build(right);partial[x]=(op,left,right)
    if c in derived or c in (a,b):build(c)
    else:build(a);build(b);partial[c]=("*",a,b)
    if not inner:d=0;e=r
    x=c+d;middle=x*k
    if min(x,middle)<=0:return None
    if d:ingredients.add(abs(d));partial[x]=("+" if d>0 else "-",c,abs(d))
    if k!=1:ingredients.add(k);partial[middle]=("*",x,k)
    if e:ingredients.add(abs(e));partial[t]=("+" if e>0 else "-",middle,abs(e))
    ingredients-=seeds|partial.keys()
    return partial,ingredients


def assignment(menus,prices,fallback):
    def improve(start):
        selected=start.copy();uses=Counter();builds=Counter()
        def adjust(t,choice,sign):
            if choice==-1:return fallback[t]*sign
            row,flags,ingredients=menus[t][choice];amount=0.
            for x in flags|ingredients:
                prior=0 if not uses[x] else (1. if builds[x] else prices.get(x,1.))
                uses[x]+=sign
                if x in flags:builds[x]+=sign
                new=0 if not uses[x] else (1. if builds[x] else prices.get(x,1.))
                amount+=new-prior
            return amount
        total=sum(adjust(t,i,1) for t,i in selected.items())
        for epoch in range(5):
            changes=0
            for t in sorted(selected,key=lambda t:(-len(menus[t]) if epoch%2 else len(menus[t]),t)):
                before=selected[t];total+=adjust(t,before,-1)
                best=before;minimum=float('inf')
                for i in (before,-1,*range(len(menus[t]))):
                    delta=adjust(t,i,1);adjust(t,i,-1)
                    if delta+.00001<minimum:best=i;minimum=delta
                total+=adjust(t,best,1);selected[t]=best;changes+=best!=before
            if not changes:break
        return total,selected
    roots=[{t:0 for t in menus},{t:-1 for t in menus}]
    support=Counter((r["a"],r["b"]) for group in menus.values() for r,_,_ in group)
    roots.append({t:max(range(len(g)),key=lambda i:support[g[i][0]["a"],g[i][0]["b"]]) for t,g in menus.items()})
    return min((improve(r) for r in roots),key=lambda pair:pair[0])[1]


def optimize(task):
    p,old,record,premium=task
    cp=load_solver();model=cp.CpModel()
    dag={v:(op,a,b) for v,op,a,b in record["derived"]}
    seeds=set(p.seeds);price=neighbors(p)
    graph=first_recipes(p,old)
    ancestries={t:set(active_graph(p,graph,(t,))) for t in p.targets}
    users=Counter(x for an in ancestries.values() for x in an)
    fallback={t:premium+sum(1/users[x] for x in an) for t,an in ancestries.items()}
    recipes=defaultdict(list);menus=defaultdict(list);cost={};bytarget=defaultdict(list)
    for row in [*record["targets"],*record.get("alternatives",())]:
        bytarget[row["t"]].append(row)
    fees=[];usage=defaultdict(list);provides=defaultdict(list);defaults={}
    for t,rs in bytarget.items():
        fallback_flag=model.new_bool_var("");chosen=[fallback_flag];defaults[t]=fallback_flag
        fees.append(round(50*fallback[t])*fallback_flag)
        seen=set()
        for row in rs:
            for inner in (False,True):
                info=literals(t,row,inner,dag,seeds)
                if info is None:continue
                partial,ls=info
                if max(partial,default=1)>p.limit:continue
                key=frozenset(partial),frozenset(ls)
                if key in seen:continue
                seen.add(key)
                flag=model.new_bool_var("");chosen.append(flag);recipes[t].append((flag,row))
                menus[t].append((row,frozenset(partial)-seeds,frozenset(ls)))
                for x in partial.keys()-seeds:
                    usage[x].append(flag);provides[x].append(flag)
                for x in ls:
                    usage[x].append(flag)
                    cost[x]=max(.5,price(x))
        model.add_exactly_one(chosen)
    for x,consumers in usage.items():
        flag=model.new_bool_var("")
        for v in consumers:model.add_implication(v,flag)
        # Exposing a center inside one target makes it available at output
        # cost to another target that otherwise sees it as an opaque literal.
        if x in cost:
            built=model.new_bool_var("")
            if provides[x]:model.add(built<=sum(provides[x]))
            else:model.add(built==0)
            costly=model.new_bool_var("");model.add(costly>=flag-built)
            fees.append(round(50*max(0,cost[x]-1))*costly)
            fees.append(50*flag)
        else:fees.append(50*flag)
    local=assignment(menus,cost,fallback)
    for t,variants in recipes.items():
        model.add_hint(defaults[t],int(local[t]==-1))
        for i,(flag,r) in enumerate(variants):model.add_hint(flag,int(local[t]==i))
    model.minimize(sum(fees));solver=cp.CpSolver();solver.parameters.num_search_workers=1
    solver.parameters.max_time_in_seconds=.65;solver.parameters.max_deterministic_time=.1
    solver.parameters.random_seed=43045
    status=solver.solve(model)
    selected=[]
    for t,variants in recipes.items():
        if status in (cp.OPTIMAL,cp.FEASIBLE):
            i=next((j for j,(f,r) in enumerate(variants) if solver.value(f)),-1)
        else:i=local[t]
        if i>=0:selected.append(variants[i][1])
    if len(selected)<2:return None
    dependencies={};separate=set()
    def keep(x):
        if x in dependencies or x in separate:return
        if x not in dag:separate.add(x);return
        op,a,b=dag[x];keep(a);keep(b);dependencies[x]=(op,a,b)
    for r in selected:
        a,b=r["a"],r["b"]
        if a*b in dag:keep(a*b)
        else:keep(a);keep(b)
    hubs=sorted(separate-seeds)
    if not hubs:return None
    return dict(id=p.id,hubs=hubs,targets=selected,alternatives=[],total=len(p.targets),
                derived=[[v,*root] for v,root in dependencies.items()],multi_stage=True,
                fit=sum(r.get("weight",0) for r in selected),screened=len(record["targets"]))


def main():
    a=argparse.ArgumentParser(description=__doc__)
    for name in ("data","baseline","models","output"):a.add_argument(name,type=Path)
    a.add_argument("--workers",type=int,default=2);a.add_argument("--premium",type=float,default=2.4);a=a.parse_args()
    puzzles={p.id:p for p in read_puzzles(a.data)};base=read_submission(a.baseline)
    rows=[json.loads(s) for s in a.models.read_text().splitlines()]
    n=0
    with ProcessPoolExecutor(a.workers) as pool,a.output.open("w",encoding="utf8") as f:
        for row in pool.map(optimize,((puzzles[m["id"]],base[m["id"]],m,a.premium) for m in rows),chunksize=1):
            if row:f.write(json.dumps(row,separators=(",",":"))+"\n");f.flush();n+=1
    print(n,"recovered target groups")


if __name__=="__main__":main()
