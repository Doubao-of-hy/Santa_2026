"""Generate candidate helpers ranked by the dependent computations they can replace."""
from collections import Counter, defaultdict
import json
from recipe_milp import canonical, inverse, ops, read_graph


def paid_alternatives(row,prog,width,return_plans=False):
    starts=json.loads(row['starting_values']); targets=set(json.loads(row['targets'])); cap=int(row['value_limit'])
    graph=read_graph(starts,prog); values=list(dict.fromkeys([*starts,*graph])); known=set(values)
    demand=Counter(p for _,a,b in graph.values() for p in {a,b})
    bits={v:1<<i for i,v in enumerate(values)};closure={v:bits[v] for v in starts};private={v:0 for v in starts}
    for v,(_,a,b) in graph.items():
        closure[v]=bits[v]|closure[a]|closure[b]
        private[v]=0
        for p in {a,b}:
            if p in graph and p not in targets and demand[p]==1:private[v]|=bits[p]|private[p]
    possibilities=defaultdict(list)
    for i,a in enumerate(values):
        for b in values[:i+1]:
            for h,recipe in ops(a,b,cap):
                if h not in known:possibilities[h].append(canonical(recipe))
    uses=defaultdict(list)
    for v in graph:
        if not private[v]:continue
        for c in values:
            if closure[c]&bits[v] or not (private[v]&~closure[c]):continue
            for h,recipe in inverse(v,c,cap):
                if h in possibilities:uses[h].append((v,c,canonical(recipe)))
    ranked=[]
    for h,candidates in uses.items():
        options=[]
        for birth in set(possibilities[h]):
            deps=closure[birth[1]]|closure[birth[2]]; replaced=0; wins={}
            for v,c,recipe in candidates:
                if deps&bits[v]:continue
                saving=private[v]&~(deps|closure[c])
                if not saving:continue
                replaced|=saving
                if v not in wins or wins[v][0].bit_count()<saving.bit_count():wins[v]=(saving,recipe)
            if replaced:
                options.append((replaced.bit_count(),len(wins),birth,wins))
        if not options:continue
        options.sort(key=lambda x:(-x[0],-x[1],x[2]))
        score,nuses=options[0][:2]
        material=[(*o[2],h) for o in options[:3]]
        for _,_,_,win in options[:3]:
            material.extend((*r[1],v) for v,r in win.items())
        ranked.append((score,nuses,h,material,options[:3] if return_plans else None))
    ranked.sort(key=lambda x:(-x[0],-x[1],x[2]))
    if return_plans:return [(h,options) for _,_,h,_,options in ranked[:width]]
    recipes={r for _,_,_,rs,_ in ranked[:width] for r in rs}
    return sorted(recipes)
