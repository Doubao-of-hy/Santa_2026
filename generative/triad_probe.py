"""Compare three-target relations in labeled practice puzzles against two matched controls."""
import argparse
import csv
import json
import random
import subprocess
from collections import Counter,defaultdict
from concurrent.futures import ThreadPoolExecutor
from math import gcd
from pathlib import Path

from run_source import ROOT
from elf import read_puzzles,sha256

def jitter(t,cap,used,rng):
    if t<4096:return t
    width=max(90,t//64)
    low=-(min(width,t-4096)//30)
    high=min(width,cap-t)//30
    for _ in range(64):
        u=t+30*rng.randint(low,high)
        if 4096<=u<=cap and u!=t and u not in used:return u
    return t


def make_controls(ps,labels):
    candidates=defaultdict(list)
    for p in ps:
        family,tier=labels[p.id]
        for t in p.targets:
            if t>=4096:
                for tag in ((tier,gcd(t,210)),(tier,gcd(t,6)),(None,gcd(t,6)),(None,0)):
                    candidates[family,t.bit_length(),tag].append((t,p.id))
    pools={}
    for p in ps:
        family,tier=labels[p.id]
        for t in p.targets:
            if t<4096:continue
            for tag in ((tier,gcd(t,210)),(tier,gcd(t,6)),(None,gcd(t,6)),(None,0)):
                others={u for u,pid in candidates[family,t.bit_length(),tag]
                        if pid!=p.id and u!=t and u<=p.limit}
                if len(others)>=5 or tag==(None,0):
                    pools[p.id,t]=sorted(others,key=lambda u:abs(u-t))[:24]
                    break
    return pools


def trial(args):
    kind,rep,ps,pools,exe=args
    lines=[];fallback=0
    for p in ps:
        used=set();values=[]
        rng=random.Random(f"triad-v1/{kind}/{rep}/{p.id}")
        if kind=="gapshuffle":
            sorted_values=sorted(p.targets)
            gaps=[b-a for a,b in zip(sorted_values,sorted_values[1:])]
            bins=defaultdict(list)
            for i,gap in enumerate(gaps):bins[gap.bit_length()//3].append(i)
            for group in bins.values():
                samples=[gaps[i] for i in group];rng.shuffle(samples)
                for i,v in zip(group,samples):gaps[i]=v
            values=[sorted_values[0]]
            for g in gaps:values.append(values[-1]+g)
            lines.append(" ".join(map(str,(kind,p.id,p.limit,len(p.seeds),len(values),*p.seeds,*values))))
            continue
        ts=sorted(p.targets);boundaries={}
        for j,t in enumerate(ts):
            distances=[abs(t-u) for u in ts[max(0,j-1):j+2] if u!=t]
            boundaries[t]=min(distances,default=t)//3
        for t in p.targets:
            if kind=="actual" or t<4096:u=t
            elif kind=="jitter":u=jitter(t,p.limit,used,rng)
            elif kind=="localgap":
                width=min(t//64,boundaries[t])
                stride=30 if width>=30 else 1
                low=-(min(width,t-4096)//stride);high=min(width,p.limit-t)//stride
                choices=high-low
                if choices:
                    step=rng.randrange(low,high);step+=step>=0
                    u=t+stride*step
                else:u=t
            else:
                group=[x for x in pools[p.id,t] if x not in used]
                if group:u=rng.choice(group)
                else:u=jitter(t,p.limit,used,rng);fallback+=1
            values.append(u);used.add(u)
        if len(used)!=len(values):raise ValueError(f"{kind} duplicate surrogate in {p.id}")
        lines.append(" ".join(map(str,(kind,p.id,p.limit,len(p.seeds),len(values),*p.seeds,*values))))
    data="\n".join(lines)+"\n"
    proc=subprocess.run([str(exe)],input=data,capture_output=True,text=True,check=True)
    rows={}
    for line in proc.stdout.splitlines():
        _,pid,*counts=line.split();rows[pid]=list(map(int,counts))
    if len(rows)!=len(ps):raise ValueError("incomplete probe")
    return kind,rep,rows,fallback


def aggregate(rows,ids):
    out=Counter()
    for pid in ids:
        n,raw,ones,triples,exact,rank2,joint=rows[pid]
        if n<3:continue
        out["eligible_puzzles"]+=1;out["raw_identities"]+=raw
        out["unscaled_identities"]+=ones;out["triples"]+=triples;out["exact_triples"]+=exact
        out["puzzles_with_triple"]+=int(triples>0)
        out["puzzles_with_exact_triple"]+=int(exact>0)
        out["puzzles_with_rank2_same_triple"]+=int(rank2>0)
        out["puzzles_with_overlapping_triples"]+=int(joint>0)
    return dict(out)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("practice",type=Path);ap.add_argument("exe",type=Path);ap.add_argument("output",type=Path)
    ap.add_argument("--rounds",type=int,default=99);ap.add_argument("--jobs",type=int,default=4)
    a=ap.parse_args();ps=read_puzzles(a.practice)
    with a.practice.open(encoding="utf-8-sig") as f:
        labels={r["id"]:(r["family"],r["design_tier"]) for r in csv.DictReader(f)}
    pools=make_controls(ps,labels)
    groups={"all":[p.id for p in ps]}
    for fam in sorted({x[0] for x in labels.values()}):
        ids=sorted(p.id for p in ps if labels[p.id][0]==fam)
        groups[fam]=ids
        for split,part in (("A",ids[::2]),("B",ids[1::2])):groups.setdefault(split,[]).extend(part)
    _,_,actual,_=trial(("actual",0,ps,pools,a.exe.resolve()))
    report={name:{"actual":aggregate(actual,ids)} for name,ids in groups.items()}
    raw={"actual":actual};fallbacks={}
    for kind in ("jitter","exchange","localgap","gapshuffle"):
        summary=defaultdict(lambda:defaultdict(list));fallbacks[kind]=[]
        with ThreadPoolExecutor(a.jobs) as pool:
            work=((kind,r,ps,pools,a.exe.resolve()) for r in range(a.rounds))
            for _,r,rows,fallback in pool.map(trial,work):
                fallbacks[kind].append(fallback)
                for name,ids in groups.items():
                    for metric,value in aggregate(rows,ids).items():summary[name][metric].append(value)
        for name,metrics in summary.items():
            report[name][kind]={}
            for metric,vals in metrics.items():
                vals.sort();observed=report[name]["actual"].get(metric,0)
                report[name][kind][metric]={"mean":sum(vals)/len(vals),"min":vals[0],"max":vals[-1],
                                            "upper_tail_p":(1+sum(x>=observed for x in vals))/(1+len(vals))}
    evidence={"practice_sha256":sha256(a.practice),"scanner_sha256":sha256(a.exe),
              "driver_sha256":sha256(Path(__file__)),"scanner_source_sha256":sha256(Path(__file__).with_name("target_triads.cpp")),
              "rounds_per_control":a.rounds,"metrics":report,"fallbacks":fallbacks,"per_puzzle":raw}
    a.output.write_text(json.dumps(evidence,indent=2),encoding="utf8")
    for name in ("all","A","B","shared","multiplicative","mixed","independent"):
        d=report[name]
        print(name,[(k,d["actual"].get(k,0),
                    round(d["jitter"].get(k,{}).get("mean",0),2),
                    round(d["exchange"].get(k,{}).get("mean",0),2))
                    for k in ("puzzles_with_triple","puzzles_with_overlapping_triples",
                              "puzzles_with_rank2_same_triple")],flush=True)

if __name__=="__main__":main()
