"""Replay the diamond screen on the two prespecified puzzle panels."""
import argparse, csv, hashlib, io, json, random, subprocess, sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from diamonds import find_diamond, validate, brute
HERE=Path(__file__).resolve().parent

def methods(k4,subset,repo):
    sys.path[:0]=[str(k4),str(subset),str(repo)]

def toy(k4):
    sys.path.insert(0,str(k4))
    rng=random.Random(20261120)
    totals={"PRESENT":0,"ABSENT":0}
    for n in range(5,13):
        for trial in range(48):
            possible=list(range(1,n+1))
            labels=set(rng.sample(possible,rng.randint(4,min(n,9))))
            forbidden=set(rng.sample(possible,rng.randint(0,2)))
            answer,w=find_diamond(labels,forbidden,n)
            assert answer==brute(labels,forbidden,n)
            if w:assert validate(w,n,labels,forbidden)
            totals[answer]+=1
    return totals

def work(args):
    k4, subset, repo, p, row, k4_floor = args
    methods(k4,subset,repo)
    from solvers.proofs.domain_bounds import domains
    from verify import capacity
    from lower_bounds import certificate
    missing,_,helper_low,_=certificate(p)
    assert missing==row["missing"]
    allowed_domains={0:set(p.seeds),**dict(domains(p,min(4,helper_low),3500))}
    states=[]
    for state in row["states"]:
        k=state["k"];targets=set(p.targets);allowed=allowed_domains[k]
        assert hashlib.sha256((",".join(map(str,sorted(allowed)))+"\n").encode()).hexdigest()==state["allowed_sha256"]
        labels=set(state["labels"]);h=k4_floor-missing-k
        if h<4 or h*(h-1)//2<=h*h//4 or len(labels)<=h*h//4:continue
        ignored,terms=capacity(allowed,targets,labels,p.limit,h)
        def ceiling(n):
            u=terms["top_unary"];D=terms["top_degrees"];B=terms["top_pair_bonuses"];M=terms["top_mixed"]
            return n+min(u+min(D//2,B),M//2)
        assert ceiling(h*(h-1)//2)==ignored
        bound=ceiling(h*h//4)
        if bound>=len(labels):continue
        status,w=find_diamond(labels,allowed|targets,p.limit)
        if w:assert validate(w,p.limit,labels,allowed|targets)
        states.append(dict(k=k,h=h,upper_capacity=bound,target_count=len(labels),status=status,witness=w))
    return dict(id=p.id,baseline=k4_floor,strict_lower=k4_floor+int(any(s["status"]=="ABSENT" for s in states)),states=states)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--k4',type=Path,required=True);ap.add_argument('--subset',type=Path,required=True);ap.add_argument('--repo',type=Path,required=True);ap.add_argument('--puzzles',type=Path,required=True);ap.add_argument('--design',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);ap.add_argument('--jobs',type=int,default=3);a=ap.parse_args()
    methods(a.k4,a.subset,a.repo)
    from elf import read_puzzles
    design=json.loads(a.design.read_bytes());assert hashlib.sha256(a.puzzles.read_bytes()).hexdigest()==design["official_sha256"]
    checks=toy(a.k4);print("physical small graphs",checks,flush=True)
    puzzles={p.id:p for p in read_puzzles(a.puzzles)}
    out={"small_graphs":checks}
    saved=(a.k4/"evidence") if (a.k4/"evidence").is_dir() else a.k4
    for phase,key in (("screen","development"),("replicate","holdout")):
        rows=json.loads((saved/(phase+".json")).read_bytes())
        baseline={r['id']:r['certified'] for r in json.loads((saved/(phase+"-dual.json")).read_bytes())}
        assert [r['id'] for r in rows]==design[key]
        with ProcessPoolExecutor(a.jobs) as pool:
            result=list(pool.map(work,[(a.k4,a.subset,a.repo,puzzles[r["id"]],r,baseline.get(r["id"],r["prior"])) for r in rows]))
        out[key]=result
        a.out.write_bytes((json.dumps(out,indent=1)+'\n').encode())
        print(key,"eligible states",sum(len(x["states"]) for x in result),"gains",sum(x["strict_lower"]-x["baseline"] for x in result),flush=True)
if __name__=="__main__": main()
