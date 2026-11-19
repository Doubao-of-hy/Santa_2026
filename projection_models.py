"""Offer competing recovered bases and intermediate corrections in the same synthesis."""
import argparse
from collections import Counter,defaultdict
import json
from math import log2
from pathlib import Path


def build(models):
    choices=defaultdict(dict);hubs=set();support=Counter()
    for model in models:
        hubs.update(model["hubs"])
        for r in model["targets"]:
            t,a,b,k,e=(r[n] for n in ("t","a","b","k","r"))
            if t!=k*a*b+e:raise ValueError((model["id"],t))
            pair=tuple(sorted((a,b)))
            key=(*pair,k)
            choices[t][key]=r
            support[pair]+=1
    def simple(x):return 0 if abs(x)<=1 else .6+abs(x).bit_length()*.14
    def rating(r):
        a,b=sorted((r["a"],r["b"]));k=r["k"]
        expense=simple(k)+min(simple(r["r"]),simple(r["d"])+simple(r["e"])+.55)
        weight=.6*log2(1+support[(a,b)])+.12*min(15.,r.get("weight",0))
        return expense-weight
    # Alternatives across distinct model families can have compatible table
    # cells even when the fit procedure picked another cell for that target.
    for t,opts in choices.items():
        for a,b in support:
            center=a*b
            k=(t+center//2)//center
            if k<1 or k>10000000 or (a,b,k) in opts:continue
            r=t-k*center
            d=(2*r+k)//(2*k);e=r-k*d
            rare=min(abs(r),max(abs(d),abs(e)))
            if rare>128 or center<max(1024,128*(rare+1)**2):continue
            opts[a,b,k]=dict(t=t,a=a,b=b,k=k,r=r,d=d,e=e,weight=4)
    main=[];others=[]
    for t in sorted(choices):
        ranked=sorted(choices[t].values(),key=rating)[:4]
        main.append(ranked[0]);others.extend(ranked[1:])
    return dict(id=models[0]["id"],hubs=sorted(hubs),targets=main,alternatives=others,
                total=models[0]["total"],multi_stage=True)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("output",type=Path);ap.add_argument("sources",nargs="+",type=Path)
    args=ap.parse_args();bank=defaultdict(list)
    for f in args.sources:
        for s in f.read_text().splitlines():
            if s:
                item=json.loads(s);bank[item["id"]].append(item)
    with args.output.open("w") as out:
        n=t=k=0
        for row in sorted(bank):
            m=build(bank[row])
            if not m["targets"]:continue
            out.write(json.dumps(m,separators=(",",":"))+"\n");n+=1;t+=len(m["targets"]);k+=len(m["alternatives"])
        print(n,"puzzles",t,"modeled targets",k,"alternate cell assignments")
if __name__=="__main__":main()
