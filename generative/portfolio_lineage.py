"""Keep per-puzzle upstream credits when local extraction has several eligible donors."""
import argparse
import csv
import json
from pathlib import Path

from run_source import ROOT
from elf import read_submission,sha256


def credits(path):
    with path.open(encoding="utf-8-sig",newline="") as f:
        return {r["id"]:r for r in csv.DictReader(f)}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("programs",type=Path);ap.add_argument("--label",required=True)
    ap.add_argument("--prior",nargs=2,action="append",default=[],metavar=("CSV","ORIGINS"))
    ap.add_argument("--release",nargs=3,action="append",default=[],metavar=("LABEL","CSV","CREDITS"))
    ap.add_argument("--local",type=Path,action="append",default=[])
    ap.add_argument("--notice",type=Path,action="append",default=[])
    a=ap.parse_args();tapes=read_submission(a.programs);donors=[];files={}
    for name,raw in a.prior:
        path=Path(name);credit=Path(raw);data=read_submission(path);rows=credits(credit)
        if not data.keys()<=rows.keys():raise ValueError(f"missing credits for {path}")
        donors.append((data,{i:(r["source"],r["upstream_source"]) for i,r in rows.items()}))
        files[str(path)]=sha256(path);files[str(credit)]=sha256(credit)
    for label,name,raw in a.release:
        path=Path(name);credit=Path(raw);data=read_submission(path);rows=credits(credit)
        if any(len(t)!=int(rows[i]["instructions"]) for i,t in data.items()):raise ValueError(path)
        donors.append((data,{i:(label,r["source"]) for i,r in rows.items()}))
        files[str(path)]=sha256(path);files[str(credit)]=sha256(credit)
    for path in a.local:
        data=read_submission(path)
        donors.append((data,dict.fromkeys(data,("local construction","Generated from official puzzle inputs"))))
        files[str(path)]=sha256(path)
    for path in a.notice:files[str(path)]=sha256(path)
    dest=a.programs.with_suffix(".origins.csv")
    counts={"identical":0,"mixed":0}
    with dest.open("w",encoding="utf8",newline="") as f:
        writer=csv.writer(f);writer.writerow(("id","source","upstream_source","instructions"))
        for i,t in tapes.items():
            match=next((cs[i] for data,cs in donors if data.get(i)==t),None)
            if match:
                counts["identical"]+=1;name,by=match
            else:
                counts["mixed"]+=1;name=a.label
                options=dict.fromkeys(f"{cs[i][0]} — {cs[i][1]}" for data,cs in donors if i in data)
                by="Eligible per-puzzle sources: "+" | ".join(options)
                if a.notice:by+=" | Additional credited upstream projects: "+", ".join(str(f) for f in a.notice)
            writer.writerow((i,name,by,len(t)))
    metadata={"programs":str(a.programs),"sha256":sha256(a.programs),"credits_sha256":sha256(dest),
              "label":a.label,"rows":len(tapes),**counts,"lineage_inputs":files,
              "interpretation":"Identical programs retain their recorded authors. For recombined programs the list documents eligible per-puzzle upstream programs without assigning individual arithmetic instructions."}
    dest.with_suffix(".json").write_text(json.dumps(metadata,indent=2)+"\n",encoding="utf8")
    print(str(dest),counts)


if __name__=="__main__":
    main()
