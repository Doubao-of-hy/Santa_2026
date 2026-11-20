"""Run the frozen, equal-wall-budget three-way comparison."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
from pathlib import Path
import argparse,csv,gzip,hashlib,io,json,os,subprocess,sys,time

HERE=Path(__file__).resolve().parent
ROOT=Path(os.environ.get("SANTA_PROJECT",next((str(p) for p in HERE.parents if (p/"elf.py").is_file()),"."))).resolve()
sys.path.insert(0,str(ROOT))
from elf import check,read_puzzles,write_submission
from checkpoint import independent_score

def sha(b):return hashlib.sha256(b).hexdigest()
def fingerprint(t):return sha(json.dumps(t,separators=(",",":")).encode())
def stream(rows):return "\n".join(" ".join(map(str,r)) for r in rows)+"\n"
def unpack(words):
    assert len(words)%4==0
    return tuple((words[k],*map(int,words[k+1:k+4])) for k in range(0,len(words),4))

def search(p,parent,arm,args):
    true=[tuple(map(tuple,x["program"])) for x in parent]
    for t,src in zip(true,parent):
        assert fingerprint(t)==src["sha256"]
        check(p,t)
    start=time.monotonic();deadline=start+24
    best=true[0];main=best;exchanges=[];chosen="parent";restart=0
    if arm=="B":
        inp=stream([[p.id,p.limit,len(p.seeds),len(p.targets),len(main),*p.seeds,*p.targets],*main])
        at=time.monotonic()
        try:
            proc=subprocess.run([str(args.atakan),*map(str,[4,14,4,6,13,257])],input=inp,text=True,capture_output=True,timeout=min(12,deadline-time.monotonic()),check=True)
            rows=proc.stdout.splitlines();pid,n,*_ = rows[0].split()
            main=unpack(" ".join(rows[1:]).split());assert pid==p.id and check(p,main)==int(n)<=len(best)
            if len(main)<len(best):best=main;chosen="Atakan"
            exchanges.append(dict(method="Atakan",finished=True,before=len(true[0]),after=len(main),sha256=fingerprint(main),seconds=round(time.monotonic()-at,4)))
        except subprocess.TimeoutExpired:exchanges.append(dict(method="Atakan",finished=False,seconds=round(time.monotonic()-at,4)))
    parents=[main] if arm=="C" else list(dict.fromkeys([main,*true[1:]]))
    fixed=[[len(p.seeds),*p.seeds],[len(p.targets),*sorted(p.targets)],[len(parents)]]
    for t in parents:fixed.extend([[len(t)],*t])
    while deadline-time.monotonic()>.035:
        seed=83011600+int(p.id[-4:])+restart*1009
        inp=stream([[1],[p.limit,p.registers,240,0,seed],*fixed])
        at=time.monotonic()
        try:
            proc=subprocess.run([str(args.wang)],input=inp,text=True,capture_output=True,timeout=max(.001,deadline-at),check=True)
        except subprocess.TimeoutExpired:
            exchanges.append(dict(method="Wang",seed=seed,finished=False,seconds=round(time.monotonic()-at,4)));break
        words=proc.stdout.split();candidate=unpack(words[1:]);assert check(p,candidate)==int(words[0])<=len(main)
        if len(candidate)<len(best):best=candidate;chosen="Wang seed "+str(seed)
        exchanges.append(dict(method="Wang",seed=seed,finished=True,after=len(candidate),sha256=fingerprint(candidate),seconds=round(time.monotonic()-at,4)))
        restart+=1
    return {"before":len(true[0]),"after":len(best),"chosen":chosen,"seconds":round(time.monotonic()-start,4),"program_sha256":fingerprint(best),"runs":exchanges},best

def rowjob(idx,p,parent,args):
    order="ABC"[idx%3:]+"ABC"[:idx%3];results={};tapes={}
    for arm in order:
        results[arm],tapes[arm]=search(p,parent,arm,args)
        r=results[arm];print(p.id,arm,r["before"],r["after"],r["chosen"],len(r["runs"]),flush=True)
    return p.id,{"order":order,"arms":results},tapes

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--data",type=Path,default=ROOT/"data/puzzles.csv")
    ap.add_argument("--repo",type=Path,default=Path("E:/Codex/Santa2026-GitHub"))
    ap.add_argument("--atakan",type=Path,default=HERE/"build/frontier.exe")
    ap.add_argument("--wang",type=Path,default=ROOT/"work/creative/notebook-frontier-134311/reproduction/incremental.exe")
    ap.add_argument("--rebuilt",action="store_true",help="Accept a local Wang binary built from the fixed source by build_wang.py")
    ap.add_argument("--inputs",type=Path,default=HERE/"inputs.json.gz")
    ap.add_argument("--output",type=Path,default=HERE/"runs")
    args=ap.parse_args();args.atakan=args.atakan.resolve();args.wang=args.wang.resolve()
    design=json.loads((HERE/"design.json").read_bytes())
    assert sha(args.data.read_bytes())==design["official_sha256"]
    if args.rebuilt:
        receipt=json.loads(args.wang.with_suffix(".build.json").read_bytes())
        assert receipt["source_sha256"]==design["Wang"]["source_sha256"]
        assert receipt["binary_sha256"]==sha(args.wang.read_bytes())
    else:
        assert sha(args.wang.read_bytes())==design["Wang"]["binary_sha256"]
    if args.inputs.resolve()==(HERE/"inputs.json.gz").resolve():assert sha(args.inputs.read_bytes())==design["input_bundle_sha256"]
    def git(filename):return subprocess.check_output(["git","-C",str(args.repo),"show",design["commit"]+":public-assisted/"+filename])
    raw=git("submission.csv");assert sha(raw)==design["baseline_sha256"]
    base={r["id"]:tuple(map(tuple,json.loads(r["program"]))) for r in csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))}
    bank=json.loads(gzip.decompress(args.inputs.read_bytes()));ps=read_puzzles(args.data);puzzles={p.id:p for p in ps}
    results={};arms={a:{} for a in "ABC"};out=args.output;out.mkdir(exist_ok=True,parents=True)
    with ThreadPoolExecutor(3) as pool:
        todo=[pool.submit(rowjob,n,puzzles[i],banks,args) for n,(i,banks) in enumerate(sorted(bank.items()))]
        for f in as_completed(todo):
            i,r,tapes=f.result();results[i]=r
            (out/(i+".json")).write_text(json.dumps(r,indent=2)+"\n",encoding="utf8")
            for arm,t in tapes.items():
                if len(t)<len(base[i]):arms[arm][i]=t
    summary={};merged={}
    for arm in "ABC":
        for i,t in arms[arm].items():
            if i not in merged or len(t)<len(merged[i][1]):merged[i]=(arm,t)
    changes={i:t for i,(_,t) in merged.items()}
    for label,patch in list(arms.items())+[("union",changes)]:
        full=out/(label+"-full.csv");total=write_submission(full,ps,base|patch)
        independent=independent_score(args.data,full);assert len(independent)==1000 and sum(independent)==total
        summary[label]=dict(score=total,sha256=sha(full.read_bytes()),winners={i:[len(base[i]),len(t)] for i,t in patch.items()},double_replayed=1000)
        if label!="union" or not patch:full.unlink()
    cid=[p for p in ps if p.id in changes];write_submission(out/"shorter.csv",cid,changes)
    with (out/"shorter.origins.csv").open("w",encoding="utf8",newline="") as f:
        wr=csv.writer(f);wr.writerow(("id","source","upstream_source","instructions"))
        for p in cid:
            arm,t=merged[p.id];row=results[p.id]["arms"][arm]
            parents=bank[p.id][:1] if arm=="C" or row["chosen"]=="Atakan" else bank[p.id]
            inherited="; ".join(x["origin"]+" ("+x["credit"]+")" for x in parents)
            authors="Wang Jakie v5; E-Max AI retained-pool search"
            if arm=="B":authors="Atakan Aldemir v30, inherited v15 whole-graph dependency"+("; "+authors if row["chosen"]!="Atakan" else "")
            wr.writerow((p.id,"Local registered public-assisted arm "+arm,authors+"; "+inherited,len(t)))
    result={"utc":datetime.now(timezone.utc).isoformat(),"design_sha256":sha((HERE/"design.json").read_bytes()),"input_sha256":sha(args.inputs.read_bytes()),
            "parent":design["commit"],"before":134285,"Atakan_binary":sha(args.atakan.read_bytes()),"Wang_binary":sha(args.wang.read_bytes()),"score":summary,
            "runs":{a:{"completed_wang":sum(q["method"]=="Wang" and q["finished"] for r in results.values() for q in r["arms"][a]["runs"]),
                       "completed_atakan":sum(q["method"]=="Atakan" and q["finished"] for r in results.values() for q in r["arms"][a]["runs"]),
                       "wall_seconds":round(sum(r["arms"][a]["seconds"] for r in results.values()),4)} for a in "ABC"}}
    (out/"result.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf8");print("completed",summary,flush=True)
if __name__=="__main__":main()
