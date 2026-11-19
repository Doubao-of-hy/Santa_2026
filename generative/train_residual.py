"""Learn a backward-search cost estimate from independently generated arithmetic programs."""
import argparse
import csv
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import random
import sqlite3
import subprocess

os.environ.setdefault("OPENBLAS_NUM_THREADS","1")
import numpy as np

from run_source import ROOT, compile_engine, compiler_path
from elf import read_puzzles, read_submission, sha256
from graph import first_recipes


def stages(puzzle, program, seed):
    rng=random.Random(seed)
    graph=first_recipes(puzzle,program)
    order=list(graph)
    if len(order)<16:return []
    rounds=[]
    for stage,pos in enumerate([min(14,len(order)//5),len(order)//3,2*len(order)//3]):
        prefix=order[:pos]
        leaves=list(dict.fromkeys((*puzzle.seeds,*[v for v in prefix[-60:] if v<65536],
                    *prefix[-40:],*rng.sample(prefix,min(14,len(prefix))))))[:64]
        # Indices of all operations required in the observed DAG. This is an
        # achievable bound from just these leaves even if several values share
        # expensive ancestors.
        costs=dict.fromkeys(leaves,0)
        for i,(v,(_,a,b)) in enumerate(graph.items()):
            if v not in costs:costs[v]=costs[a]|costs[b]|(1<<i)
        future=[v for v in order[pos:] if 2<costs[v].bit_count()<25]
        rng.shuffle(future)
        queries={v:(costs[v].bit_count(),int(i<8)) for i,v in enumerate(future[:30])}
        # On-policy residuals often differ from literal graph nodes. Sample
        # quotients and differences and label them using a teacher search.
        factors=[v for v in leaves if 2<=v<2**27]
        for _ in range(8):
            if not factors:break
            t=rng.choice(puzzle.targets); f=rng.choice(factors)
            x=rng.choice([t//f,(t+f-1)//f,abs(t-f)])
            if x>1:queries.setdefault(x,(999,1))
        row=[puzzle.id,stage,puzzle.limit,len(leaves),len(queries),*leaves]
        for x,(upper,teacher) in queries.items():row.extend((x,upper,teacher))
        rounds.append(" ".join(map(str,row)))
    return rounds


def sample(exe,puzzle,program):
    rows=stages(puzzle,program,9021+int(puzzle.id.split("_")[-1]))
    if not rows:return ""
    run=subprocess.run([exe],input="\n".join(rows)+"\n",capture_output=True,text=True,check=True)
    return run.stdout


def best_split(x,errors,weights,subset,thresholds):
    y=errors[subset];w=weights[subset]
    if len(y)==0:return 0,0,np.array([],dtype=bool)
    total=w.sum();sum_y=w@y
    best=(-1.,0,0.)
    for j,grid in enumerate(thresholds):
        xx=x[subset,j]
        for threshold in grid:
            mask=xx<=threshold
            nl=w[mask].sum();nr=total-nl
            if min(nl,nr)<6:continue
            sy=w[mask]@y[mask]
            improvement=sy*sy/nl+(sum_y-sy)**2/nr-sum_y**2/total
            if improvement>best[0]:best=(improvement,j,threshold)
    _,j,threshold=best
    return j,threshold,x[subset,j]<=threshold


def fit(data,model,report):
    rows=list(csv.reader(data.splitlines()))
    nums=np.asarray([r[2:] for r in rows],dtype=np.float64)
    y=nums[:,0];x=nums[:,1:];ids=np.array([int(r[0].split("_")[-1]) for r in rows])
    train=np.where(ids%5!=0)[0];test=np.where(ids%5==0)[0]
    if min(len(train),len(test))<20:raise ValueError("not enough examples")
    # Reduce the leverage of loose upper bounds while preserving all stages.
    weights=1./(1.+np.maximum(0,y-10)*.07)
    initial=np.average(y[train],weights=weights[train])
    pred=np.full(len(y),initial)
    thresholds=[np.unique(np.quantile(x[train,j],np.linspace(.04,.96,14))) for j in range(x.shape[1])]
    lines=[]
    for _ in range(38):
        errors=np.clip(y-pred,-4,4)
        j,t,mask=best_split(x,errors,weights,train,thresholds)
        splits=[(j,t)];leaves=[]
        for side in [True,False]:
            branch=train[mask==side]
            jj,tt,mm=best_split(x,errors,weights,branch,thresholds)
            splits.append((jj,tt))
            for lower in [True,False]:
                segment=branch[mm==lower]
                leaves.append(.16*np.average(errors[segment],weights=weights[segment]) if len(segment) else 0)
        high=x[:,j]>t
        selected=np.where(high,2+(x[:,splits[2][0]]>splits[2][1]),(x[:,splits[1][0]]>splits[1][1]).astype(int))
        pred+=np.array(leaves)[selected]
        lines.append(" ".join([*(f"{jj} {tt:.8g}" for jj,tt in splits),*(f"{v:.9g}" for v in leaves)]))
    model.write_text(f"{initial:.9g} {len(lines)}\n"+"\n".join(lines)+"\n",encoding="ascii")
    metrics={"samples":len(y),"puzzles":int(len(set(ids))),"training":len(train),"held_out":len(test),
             "held_out_original_mae":float(np.abs(.18*x[test,0]-y[test]).mean()),
             "held_out_model_mae":float(np.abs(pred[test]-y[test]).mean()),
             "held_out_withheld_by_puzzle":True,"model_sha256":sha256(model)}
    report.update(metrics);print(json.dumps(metrics),flush=True)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("programs",type=Path);ap.add_argument("model",type=Path)
    ap.add_argument("--rows",type=int,default=180);ap.add_argument("--jobs",type=int,default=2)
    args=ap.parse_args()
    puzzles=read_puzzles(ROOT/"data/puzzles.csv")
    programs=read_submission(args.programs)
    rows=[p for p in puzzles if p.id in programs and len(programs[p.id])>=25]
    random.Random(5003).shuffle(rows);rows=rows[:args.rows]
    exe,_,_=compile_engine("rank-samples",compiler_path(None))
    signature=sha256(args.programs)+sha256(exe)+sha256(Path(__file__))
    db=sqlite3.connect(args.model.with_suffix(".sqlite"))
    db.execute("CREATE TABLE IF NOT EXISTS samples (run TEXT,id TEXT,data TEXT,PRIMARY KEY(run,id))")
    cached=dict(db.execute("SELECT id,data FROM samples WHERE run=?",(signature,)))
    with ThreadPoolExecutor(args.jobs) as pool:
        tasks={pool.submit(sample,str(exe),p,programs[p.id]):p.id for p in rows if p.id not in cached}
        for task in as_completed(tasks):
            pid=tasks[task];out=task.result();cached[pid]=out
            db.execute("INSERT INTO samples VALUES(?,?,?)",(signature,pid,out));db.commit()
            if len(cached)%30==0:print(f"{len(cached)} puzzles sampled",flush=True)
    db.close()
    report={"source":str(args.programs),"source_sha256":sha256(args.programs),"teacher_sha256":sha256(exe)}
    fit("".join(cached[p.id] for p in rows),args.model,report)
    args.model.with_suffix(".json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")


if __name__=="__main__":
    main()
