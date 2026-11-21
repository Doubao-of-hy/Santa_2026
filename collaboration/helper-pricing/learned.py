"""Learn which new arithmetic values occur in shorter historical independent programs."""
import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import os
import subprocess
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT/"generative/arsen_v15")]
from elf import check, read_puzzles, sha256, write_submission
from paid_helpers import paid_alternatives
from recipe_milp import read_graph
from recombine2026 import solve

OLD = "1fb2d8c"
NEW = "99b48016ec3c71d97569e8325e021797f5ac1737"
CANDIDATES = 160
PICKS = 12


def digest(obj):
    return hashlib.sha256(json.dumps(obj, separators=(",", ":")).encode()).hexdigest()


def frozen(rev, filename):
    raw = subprocess.check_output(["git", "show", rev+":"+filename], cwd=ROOT)
    return {r["id"]: r for r in csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))}


def tape(row):
    return tuple(tuple(x) for x in json.loads(row["program"]))


def features(p, row, program):
    options = paid_alternatives(row, program, CANDIDATES, return_plans=True)
    seeds = set(p.seeds)
    goals = set(p.targets)
    graph = read_graph(p.seeds, program)
    pos = dict.fromkeys(seeds,0) | {v:j for j,v in enumerate(graph,1)}
    scale = max(1,len(graph))
    results = []
    for rank, (v, plans) in enumerate(options):
        gain, count, (op,x,y), wins = plans[0]
        saved = [mask.bit_count() for mask,_ in wins.values()]
        recipe_ops = Counter(r[0] for _,r in wins.values())
        nbits = v.bit_length()
        vals = [
            math.log1p(rank),math.log1p(gain),math.log1p(count),
            math.log1p(max(saved)),sum(saved)/(1+gain),len(goals.intersection(wins))/(1+count),
            max(pos[x],pos[y])/scale,min(pos[x],pos[y])/scale,
            float(x in seeds)+float(y in seeds),float(x==y),
            nbits/p.limit.bit_length(),v.bit_count()/nbits,math.log1p(len(plans)),
            sum(pos[t] for t in wins)/(scale*count),
            min(pos[t] for t in wins)/scale, max(pos[t] for t in wins)/scale,
            *[float(op==z) for z in "+-*/"], *[recipe_ops[z]/count for z in "+-*/"],
            float(v<=64),float(v%2==0),float(v%3==0),float(v%5==0),
            abs(x.bit_length()-y.bit_length())/p.limit.bit_length(),
        ]
        edges = set()
        for _,_,birth,uses in plans:
            edges.add((*birth,v))
            edges.update((*recipe,t) for t,(_,recipe) in uses.items())
        results.append((v,vals,sorted(edges)))
    return results


def examples(job):
    p,row,old,new = job
    better = set(read_graph(p.seeds,new)) - set(read_graph(p.seeds,old))
    opts=features(p,row,old)
    return p.id,[(v,x,int(v in better)) for v,x,_ in opts]


def fit(train):
    import numpy as np
    from scipy.optimize import minimize
    from scipy.special import expit
    pairs=[]
    for pid,opts in train.items():
        pos=[x for _,x,y in opts if y]
        neg=[(v,x) for v,x,y in opts if not y]
        if not pos or not neg:
            continue
        neg=neg[:10]+sorted(neg[10:],key=lambda a:digest([pid,a[0]]))[:20]
        for x in pos[:6]:
            for _,y in neg:pairs.append(np.asarray(x)-y)
    if not pairs:
        raise ValueError("No distinct historical positive and negative examples")
    a=np.stack(pairs);scale=np.maximum(0.05,np.sqrt((a*a).mean(axis=0)));a/=scale
    def loss(w):
        s=a@w
        return np.logaddexp(0,-s).mean()+.015*(w@w), -a.T@expit(-s)/len(s)+.03*w
    result=minimize(loss,np.zeros(a.shape[1]),jac=True,method="L-BFGS-B")
    if not result.success:raise RuntimeError(result.message)
    return (result.x/scale).tolist(),len(pairs)


def ranking_accuracy(data,weights):
    matched=0
    scores=[0,0]
    rr=[0.,0.]
    for _,rows in data.items():
        if not any(y for _,_,y in rows):
            continue
        matched+=1
        learned=sorted(rows,key=lambda v:-sum(a*b for a,b in zip(v[1],weights)))
        for j,order in enumerate((rows,learned)):
            best=next(k for k,(_,_,y) in enumerate(order,1) if y)
            scores[j]+=int(best<=PICKS)
            rr[j]+=1/best
    return dict(puzzles=len(data),with_enumerated_positive=matched,top12_hit=scores,reciprocal_rank_sum=rr)


def apply(job):
    p,row,prog,weights,lane=job
    opts=features(p,row,prog)
    ranked=sorted(opts,key=lambda v:-sum(a*b for a,b in zip(v[1],weights)))
    result={"id":p.id,"lane":lane,"before":len(prog),"parent":digest(prog),"arms":{}}
    for name,chosen in [("structural",opts[:PICKS]),("learned",ranked[:PICKS])]:
        extras=sorted({edge for _,_,edges in chosen for edge in edges})
        t,stats=solve(row,[[list(op) for op in prog]],budget=.35,slack=0,helpers=0,seed=20261121,extra=extras)
        t=tuple(map(tuple,t));assert check(p,t)==len(t)<=len(prog)
        result["arms"][name]=dict(score=len(t),helpers=[v for v,_,_ in chosen],status=stats["status"],
                                      **({"program":t} if len(t)<len(prog) else {}))
    return result


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--puzzles",type=Path,required=True)
    cli.add_argument("--out",type=Path,required=True)
    cli.add_argument("--jobs",type=int,default=4)
    a=cli.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    assert sha256(a.puzzles)=="b0c70d849eca078a0e1cf9a4f7b47fd40b7435663f6f84de6725f84724500428"
    ps=read_puzzles(a.puzzles)
    with a.puzzles.open(encoding="utf-8-sig",newline="") as f:fields={v["id"]:v for v in csv.DictReader(f)}
    old=frozen(OLD,"submission.csv");new=frozen(NEW,"submission.csv")
    pub=frozen(NEW,"public-assisted/submission.csv")
    sequence=sorted((p for p in ps if 45<=len(tape(old[p.id]))<=225),key=lambda p:digest(["helper-learning-1",p.id]))
    production=sequence[:56]
    history=[p for p in sequence[56:] if len(tape(new[p.id]))<len(tape(old[p.id]))]
    training=history[:290];evaluation=history[290:380]
    design=dict(old=OLD,new=NEW,training=[p.id for p in training],evaluation=[p.id for p in evaluation],
                production=[p.id for p in production],candidates=CANDIDATES,picks=PICKS,selection_budget=.35)
    (a.out/"design.json").write_bytes((json.dumps(design,indent=2)+"\n").encode())
    cache=a.out/"history.json.gz"
    if cache.is_file():
        data=json.loads(gzip.decompress(cache.read_bytes()))
        assert set(data)=={p.id for p in training+evaluation}
    else:
        jobs=[(p,fields[p.id],tape(old[p.id]),tape(new[p.id])) for p in training+evaluation]
        with ProcessPoolExecutor(a.jobs) as pool:data=dict(pool.map(examples,jobs,chunksize=3))
        cache.write_bytes(gzip.compress(json.dumps(data,separators=(",",":")).encode(),mtime=0))
    weights,n=fit({p.id:data[p.id] for p in training})
    stats=ranking_accuracy({p.id:data[p.id] for p in evaluation},weights)
    model=dict(training_pairs=n,weights=weights,evaluation=stats)
    (a.out/"model.json").write_bytes((json.dumps(model,indent=2)+"\n").encode())
    print("historical evaluation",stats,"training pairs",n,flush=True)
    for lane,table in [("public",pub),("own",new)]:
        dest=a.out/(lane+".json.gz")
        if dest.is_file():
            rows=json.loads(gzip.decompress(dest.read_bytes()))
        else:
            jobs=[(p,fields[p.id],tape(table[p.id]),weights,lane) for p in production]
            with ProcessPoolExecutor(a.jobs) as pool:rows=list(pool.map(apply,jobs,chunksize=1))
            dest.write_bytes(gzip.compress(json.dumps(rows,separators=(",",":")).encode(),mtime=0))
        wins={};gains=Counter()
        for q,row in zip(production,rows,strict=True):
            t=tape(table[q.id]);assert row["id"]==q.id and row["parent"]==digest(t)
            for name,rec in row["arms"].items():
                candidate=tuple(map(tuple,rec.get("program",t)))
                assert check(q,candidate)==rec["score"];gains[name]+=len(t)-len(candidate)
                if len(candidate)<len(wins.get(q.id,t)):wins[q.id]=candidate
        write_submission(a.out/(lane+".csv"),[p for p in ps if p.id in wins],wins)
        summary=dict(arm_savings=dict(gains),combined=sum(len(tape(table[k]))-len(t) for k,t in wins.items()),
                     wins={k:len(t) for k,t in wins.items()})
        (a.out/(lane+".json")).write_bytes((json.dumps(summary,indent=2)+"\n").encode())
        print(lane,summary,flush=True)


if __name__=="__main__":
    main()
