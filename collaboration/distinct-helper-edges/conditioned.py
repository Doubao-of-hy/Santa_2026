"""Reuse fixed first-helper partitions and verify all leaves before increasing a lower bound."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from cliques import resolve
from sorted_quads import audit
from screen import capacities


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def stamp(values):
    return sha((",".join(map(str,sorted(values)))+"\n").encode())


def canonical(obj):
    return (json.dumps(obj,sort_keys=True,separators=(",",":"))+"\n").encode()


def evidence(labels,forbidden,limit):
    m,s,w=resolve(labels,forbidden,limit)
    other={}
    a,w2=audit(labels,forbidden,limit,other)
    if {m,a}=={"ABSENT","PRESENT"}:
        raise AssertionError((m,a,w,w2))
    return dict(labels=len(labels),labels_sha256=stamp(labels),forbidden=len(forbidden),
                forbidden_sha256=stamp(forbidden),mobius=m,ordered=a,
                mobius_counts=s,ordered_counts=other,mobius_witness=w,ordered_witness=w2)


def check_tree(p,record,prior):
    from conditioned_certificate import frontier
    from domain_bounds import domains
    goal=set(p.targets)
    missing=len(goal-set(p.seeds))
    leaves=[]
    def visit(known,node,path):
        closed,next_values=frontier(known,goal,p.limit)
        assert goal-closed
        if node["kind"]=="partition":
            assert node["active_count"]==len(closed) and node["active_sha256"]==stamp(closed)
            assert node["next_count"]==len(next_values) and node["next_sha256"]==stamp(next_values)
            used=set()
            for idx,group in enumerate(node["groups"]):
                values=set(group["values"])
                assert values and sorted(values)==group["values"] and values<=next_values and not used&values
                used.update(values)
                visit(closed|values,group["proof"],path+[idx])
            assert used==next_values
            return
        assert node["kind"]=="rooted_capacity", "the frozen packs should contain only rooted capacity leaves"
        k=node["k"]
        assert type(k) is int and k>=0
        spec=SimpleNamespace(seeds=tuple(sorted(closed)),targets=p.targets,limit=p.limit)
        allowed=closed if k==0 else dict(domains(spec,k,record["cap"]))[k]
        assert len(allowed)==node["domain_count"] and stamp(allowed)==node["domain_sha256"]
        s,original,upper=capacities(spec,allowed)
        assert original==node["h"] and original>0 and s
        base=missing+len(path)+k
        assert base+original>=record["lower"]
        leaves.append(dict(path=path,k=k,base=base,plain=base+original,potential=base+upper,
                           labels=set(s),forbidden=allowed|goal))
    visit(set(p.seeds),record["tree"],[])
    baseline=min(x["plain"] for x in leaves)
    potential=min(x["potential"] for x in leaves)
    branch_count=len(leaves)
    summary=dict(tree_sha256=sha(canonical(record)),original=record["lower"],raw_plain=baseline,
                 potential=potential,leaves=branch_count,closed=prior)
    cached={}
    for threshold in range(potential,prior,-1):
        needs=[x for x in leaves if x["plain"]<threshold]
        if not needs:
            summary.update(closed=threshold,ordinary_only=True)
            return summary
        union=set.union(*(x["labels"] for x in needs))
        common=set.intersection(*(x["forbidden"] for x in needs))
        def prove(s,f):
            pair=stamp(s),stamp(f)
            if pair not in cached:
                cached[pair]=evidence(s,f,p.limit)
            return cached[pair]
        shared=prove(union,common)
        permitted=shared["mobius"]==shared["ordered"]=="ABSENT"
        details=[]
        for leaf in leaves:
            report=dict(path=leaf["path"],k=leaf["k"],plain=leaf["plain"],potential=leaf["potential"],
                        labels_sha256=stamp(leaf["labels"]),forbidden_sha256=stamp(leaf["forbidden"]))
            if leaf["plain"]>=threshold:
                report["uses"]="ordinary"
            elif permitted:
                assert leaf["labels"]<=union and common<=leaf["forbidden"]
                report["uses"]="shared-negative"
            else:
                local=prove(leaf["labels"],leaf["forbidden"])
                if not local["mobius"]==local["ordered"]=="ABSENT":
                    break
                report.update(uses="leaf-negative",proof=local)
            details.append(report)
        else:
            assert len(details)==branch_count
            summary.update(closed=threshold,common=shared,leaf_proofs=details)
            return summary
    return summary


def solve(entry):
    repo,p,trees,prior=entry
    sys.path.insert(0,str(repo))
    results=[]
    for file,record in trees:
        out=check_tree(p,record,prior);out["pack"]=file;results.append(out)
    return dict(id=p.id,prior=prior,lower=max([prior]+[x["closed"] for x in results]),trees=results)


def load(repo,official,base):
    cfg=json.loads((base/"conditioned-design.json").read_bytes())
    snapshot=cfg["snapshot"]
    def get(name):
        return subprocess.check_output(["git","-C",str(repo),"show",snapshot+":"+name])
    assert sha(official.read_bytes())==cfg["puzzles_sha256"]
    raw=get("proofs/local/proofs/conditioned-bounds.json")
    manifest=json.loads(raw)
    assert sha(raw)==cfg["source_manifest_sha256"] and manifest["packs"]==cfg["packs"]
    rows={}
    for pack,expected in manifest["packs"].items():
        blob=get("proofs/local/proofs/"+pack)
        assert sha(blob)==expected
        for pid,record in json.loads(gzip.decompress(blob)).items():
            rows.setdefault(pid,[]).append((pack,record))
    plain=(base/"full-certificates.json").read_bytes()
    assert sha(plain)==cfg["plain_certificates_sha256"]
    stronger={pid:r["lower"] for pid,r in json.loads(plain)["rows"].items()}
    original={r["id"]:r for r in csv.DictReader(io.StringIO(get("collaboration/puzzle-bounds.csv").decode()))}
    previous={pid:max(stronger.get(pid,0),int(row["certified_lower"])) for pid,row in original.items()}
    return cfg,rows,previous,original


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo",type=Path,required=True);ap.add_argument("--puzzles",type=Path,required=True)
    ap.add_argument("--jobs",type=int,default=4);ap.add_argument("--out",type=Path,required=True)
    ap.add_argument("--receipt",type=Path,help="verify only the rows in this existing certificate")
    ap.add_argument("--extension",type=Path,help="use the separately frozen extension subset")
    ap.add_argument("--batch",type=int)
    a=ap.parse_args();base=Path(__file__).resolve().parent
    cfg,trees,prior,original=load(a.repo,a.puzzles,base)
    sys.path.insert(0,str(a.repo))
    from elf import read_puzzles
    puzzles={p.id:p for p in read_puzzles(a.puzzles)}
    stored=None
    if a.receipt:
        stored=json.loads(a.receipt.read_bytes())
        ids=[x["id"] for x in stored["rows"]]
    elif a.extension:
        extension=json.loads(a.extension.read_bytes())
        assert extension["pilot_design_sha256"]==sha((base/"conditioned-design.json").read_bytes())
        assert set(extension["ids"]).isdisjoint(r["id"] for r in cfg["pilot"])
        assert len(set(extension["ids"]))==len(extension["ids"])
        ids=extension["ids"]
        if a.batch is not None:
            n=extension["batch_size"];ids=ids[(a.batch-1)*n:a.batch*n]
    else:
        ids=[r["id"] for r in cfg["pilot"]]
    assert ids and len(set(ids))==len(ids) and "scored_0926" not in ids
    out=dict(design_sha256=sha((base/"conditioned-design.json").read_bytes()),rows=[])
    def keep():
        tmp=a.out.with_suffix(".tmp");tmp.write_bytes((json.dumps(out,separators=(",",":"))+"\n").encode());tmp.replace(a.out)
    with ProcessPoolExecutor(a.jobs) as pool:
        for r in pool.map(solve,[(a.repo,puzzles[k],trees[k],prior[k]) for k in ids]):
            assert r["lower"]<=int(original[r["id"]]["best_verified_upper"])
            out["rows"].append(r)
            if not stored:
                keep()
            print(r["id"],r["prior"],r["lower"],flush=True)
    if stored:
        assert out==stored
    keep()


if __name__=="__main__":
    main()
