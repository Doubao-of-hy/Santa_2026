"""Assemble and replay the public-assisted candidate with its original program license."""
import argparse
import csv
import json
from pathlib import Path
import shutil

from checkpoint import independent_score
from elf import read_puzzles, read_submission, score, sha256, write_submission


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("repairs",nargs="*",type=Path,
                    help="Local rewrites of the licensed Hanif v15 base")
    ap.add_argument("--release-repair",action="append",type=Path,default=[],
                    help="Local rewrite using the selected release and any explicitly credited prior donors")
    ap.add_argument("--v8-repair",action="append",type=Path,default=[],
                    help="Local rewrites of Asterios v8, with its original row credits")
    ap.add_argument("--v10-repair",action="append",type=Path,default=[],
                    help="Local rewrite using Asterios v10 and potentially the earlier v8 portfolio")
    ap.add_argument("--mixed-repair",nargs=2,action="append",default=[],type=Path,
                    metavar=("PROGRAMS","ORIGINS"),
                    help="Rewrite of a credited snapshot, with frozen per-row upstream credits")
    ap.add_argument("--reference",type=Path,
                    help="Versioned arithmetic-program release with audit.json and original row credits")
    args=ap.parse_args()
    root=Path(__file__).resolve().parent
    hanif=root/"work/reference/hanif-v15"
    prior_report=root/"public-assisted/result.json"
    version_used=json.loads(prior_report.read_text(encoding="utf8"))["source_version"] if prior_report.exists() else 13
    source=(args.reference or root/"work/creative"/f"asterios-v{version_used}").resolve()
    audit=json.loads((source/"audit.json").read_text(encoding="utf8"))
    if audit["license"]!="Apache 2.0" or not audit["description"].count("programs"):
        raise ValueError("unexpected release metadata")
    release_number=int(audit["url"].rstrip("/").split("/")[-1])
    with (source/"history.csv").open(encoding="utf-8-sig",newline="") as f:
        release_history=list(csv.DictReader(f))
    catalog=json.loads((source/f"metadata-v{release_number}.json").read_text(encoding="utf8"))
    if (catalog["currentVersionNumber"]!=release_number or catalog["licenseName"]!="Apache 2.0"
            or catalog["ref"]!="asteriospanoras/santa-2026-elf-programs-and-experiments"
            or int(release_history[-1]["total"])!=audit["score"]):
        raise ValueError("downloaded history and release score disagree")
    if release_history[-1]["version"]!=f"v{release_number}" and (
            not audit.get("dataset_version_id") or audit.get("archive_bytes")!=catalog["totalBytes"]):
        raise ValueError("missing evidence linking catalog and internal history versions")
    version=f"Asterios v{release_number}"
    data=root/"data/puzzles.csv"
    dest=root/"public-assisted"
    dest.mkdir(exist_ok=True)
    puzzles=read_puzzles(data)
    base=source/"programs.csv"
    programs=read_submission(base)
    original=score(puzzles,programs)
    if sha256(base)!=audit["normalized_sha256"] or original!=audit["score"]:
        raise ValueError("published archive does not match its receipt")
    raw=source/audit["raw"]
    if sha256(raw)!=audit["raw_sha256"]: raise ValueError("published source manifest mismatch")
    with raw.open(encoding="utf-8-sig",newline="") as f:
        published={r["id"]:(r["source"],int(r["instructions"])) for r in csv.DictReader(f)}
    if set(published)!=set(programs) or any(published[k][1]!=len(v) for k,v in programs.items()):
        raise ValueError("incorrect or absent original per-puzzle credits")
    origins={p.id:version for p in puzzles}
    credits={k:row[0] for k,row in published.items()}
    candidates=[(root/"submission.csv","local from official inputs","independent")]
    candidates.extend((path,path.resolve().relative_to(root).as_posix(),"hanif") for path in args.repairs)
    candidates.extend((path,path.resolve().relative_to(root).as_posix(),"release") for path in args.release_repair)
    candidates.extend((path,path.resolve().relative_to(root).as_posix(),"v8") for path in args.v8_repair)
    candidates.extend((path,path.resolve().relative_to(root).as_posix(),"v10") for path in args.v10_repair)
    mixed={}
    for path,ledger in args.mixed_repair:
        with ledger.open(encoding="utf-8-sig",newline="") as f:
            byrow={r["id"]:r["upstream_source"] for r in csv.DictReader(f)}
        mixed[path]=byrow
        candidates.append((path,path.resolve().relative_to(root).as_posix(),"mixed"))
    legacy=root/"work/creative/asterios-v8"
    with (legacy/"best_programs.csv").open(encoding="utf-8-sig",newline="") as f:
        v8credits={r["id"]:r["source"] for r in csv.DictReader(f)}
    with (root/"work/creative/asterios-v10/best_programs.csv").open(encoding="utf-8-sig",newline="") as f:
        v10credits={r["id"]:r["source"] for r in csv.DictReader(f)}
    # The previous export is a valid continuing incumbent with recorded contributors.
    old=dest/"submission.csv"
    if old.exists():
        recorded=json.loads((dest/"result.json").read_text(encoding="utf8"))
        if sha256(old)!=recorded["sha256"]: raise ValueError("public candidate hash mismatch")
        with (dest/"origins.csv").open(encoding="utf8",newline="") as f:
            prior={r["id"]:r for r in csv.DictReader(f)}
        last=read_submission(old)
        for p in puzzles:
            if len(last[p.id])<=len(programs[p.id]):
                programs[p.id]=last[p.id]
                origins[p.id]=prior[p.id]["source"]
                credits[p.id]=prior[p.id].get("upstream_source","Hanif v15 and its listed authors")
    for path,name,lineage in candidates:
        if not path.exists(): continue
        choices=read_submission(path)
        for p in puzzles:
            proposed=choices.get(p.id)
            if proposed is None: continue
            if len(proposed)<len(programs[p.id]) or (
                    name=="local from official inputs" and len(proposed)==len(programs[p.id])):
                programs[p.id]=proposed; origins[p.id]=name
                if lineage=="independent":credits[p.id]="Generated from official inputs"
                elif lineage=="mixed":credits[p.id]=mixed[path][p.id]
                elif lineage=="hanif":credits[p.id]="Hanif v15 and its listed authors"
                elif lineage=="v10":
                    credits[p.id]=(f"Asterios v10 credits {v10credits[p.id]}. Earlier available donors include "
                                   f"Asterios v8 ({v8credits[p.id]}), Hanif v15 and local programs.")
                else:
                    label=version if lineage=="release" else "Asterios v8"
                    author=published[p.id][0] if lineage=="release" else v8credits[p.id]
                    credits[p.id]=f"{label} credits {author}. Local or Hanif v15 donors may also contribute."
    total=write_submission(old,puzzles,programs)
    if sum(independent_score(data,old))!=total: raise ValueError("replay mismatch")
    shutil.copyfile(hanif/"LICENSE.txt",dest/"LICENSE.txt")
    shutil.copyfile(hanif/"NOTICE.md",dest/"Hanif-v15-NOTICE.md")
    shutil.copyfile(source/"history.csv",dest/"Asterios-history.csv")
    portfolio_url="https://www.kaggle.com/datasets/kindasomethin/santa-2026-exact-portfolio-checkpoints/versions/23"
    portfolio_rows=[pid for pid,credit in credits.items() if "Pratham Jain" in credit]
    portfolio_note=(
        "\nPratham Jain's portfolio documents mixed upstream licensing and keeps the original "
        "terms for its inputs. Its row-attribution table credits the intermediate contributors. "
        f"[Portfolio documentation]({portfolio_url})\n" if portfolio_rows else "")
    (dest/"NOTICE.md").write_text(
        f"# Attribution\n\n{version} is a collection verified and published by Asterios Panoras. "
        f"The original dataset identifies the contributors to each program in its source column. "
        f"The same credits are retained in origins.csv for selected {version} rows.\n\n"
        +audit["description"].split("## Sources and license")[-1].strip()+"\n\n"
        +f"[Original publication]({audit['url']})\n\n"
        +"Earlier local rewrites also used Asterios v8, v10 and v13. Contributors are "
        +"listed in Asterios-history.csv and origins.csv. "
        +"[Version 8](https://www.kaggle.com/datasets/asteriospanoras/santa-2026-elf-programs-and-experiments/versions/8) "
        +"[Version 10](https://www.kaggle.com/datasets/asteriospanoras/santa-2026-elf-programs-and-experiments/versions/10) "
        +"[Version 13](https://www.kaggle.com/datasets/asteriospanoras/santa-2026-elf-programs-and-experiments/versions/13)\n\n"
        +"Local changes include selecting shorter complete programs and resynthesizing arithmetic. "
        +"The contributed Hanif v15 program lineage is recorded in Hanif-v15-NOTICE.md. "
        +"The local solver source credits are under ../generative/NOTICE.md.\n"
        +("Hanif v23 contributed additional programs. [Original notice](Hanif-v23-NOTICE.md) and [license](Hanif-v23-LICENSE.txt).\n" if (dest/"Hanif-v23-NOTICE.md").exists() else "")
        +("Additional rows from Alex Chilton’s Rudolph v67 portfolio retain its release-level authorship. [Rudolph v67](https://www.kaggle.com/datasets/alexchilton/santa-2026-rudolph-programs/versions/67).\n" if any("Rudolph" in v and "release 67" in v for v in credits.values()) else "")
        +("Additional rows from Hanif Noer Rofiq, Kaggle release 24, retain the [original notice](Hanif-v24-NOTICE.md) and [license](Hanif-v24-LICENSE.txt).\n" if (dest/"Hanif-v24-NOTICE.md").exists() else "")
        +("goodpjw2008's release 10 includes his arithmetic search, public inputs, and Wang Jakie's search with E-Max AI's seeded crossover. [Published programs](https://www.kaggle.com/datasets/goodpjw2008/santa-2026-dag-lns-programs/versions/10), [original notice](GoodPJW-v10-NOTICE.md), and [public source list](GoodPJW-v10-public-sources.json).\n" if (dest/"GoodPJW-v10-NOTICE.md").exists() else "")
        +("GoodPJW release 11 contributed shorter complete programs. The release credits Wang Jakie, E-Max AI, and the public sources in its ladder. [Release 11](https://www.kaggle.com/datasets/goodpjw2008/santa-2026-dag-lns-programs/versions/11), [upstream notice](GoodPJW-v11-NOTICE.md), and [public source list](GoodPJW-v11-public-sources.json).\n" if (dest/"GoodPJW-v11-NOTICE.md").exists() else "")
        +("Roman Rozen invites reuse of the verified IceFire output. The selected rows match programs in the attached banks by bikrambasnet1 and E-Max AI. Their upstream credits and pinned public releases are listed in [Roman-Bikram-sources.json](Roman-Bikram-sources.json).\n" if (dest/"Roman-Bikram-sources.json").exists() else "")
        +("GoodPJW dataset release 12 credits Wang Jakie, E-Max AI and its public input contributors. Puzzle 942 uses E-Max AI's diverse graph-pool search. [GoodPJW upstream notice](GoodPJW-v12-NOTICE.md), [public sources](GoodPJW-v12-public-sources.json), and [pinned releases and row improvements](../collaboration/frontier-134285/public-134079/audit.json).\n" if (dest/"GoodPJW-v12-NOTICE.md").exists() else "")
        +("The seven E-Max AI diverse-search programs were regenerated from the author's credited public banks. Six further programs exactly match the Bikram Basnet, Roman Rozen and Alex Chilton releases. [Pinned releases and individual credits](New-frontier-134065.json).\n" if (dest/"New-frontier-134065.json").exists() else "")
        +("Asterios Panoras release 150 and goodpjw2008 release 20 contribute shorter programs. Original authors are credited by puzzle in [origins.csv](origins.csv). [Five pinned releases and individual improvements](Releases-20261121.json), [GoodPJW upstream notice](GoodPJW-v20-NOTICE.md), and [public source list](GoodPJW-v20-public-sources.json).\n" if (dest/"Releases-20261121.json").exists() else "")
        +("Later public-release updates and upstream acknowledgments are listed in [the release log](releases/README.md).\n" if (dest/"releases/README.md").is_file() else "")
        +portfolio_note,encoding="utf8")
    with (dest/"origins.csv").open("w",encoding="utf8",newline="") as f:
        out=csv.writer(f);out.writerow(("id","source","upstream_source","instructions"))
        out.writerows((p.id,origins[p.id],credits[p.id],len(programs[p.id])) for p in puzzles)
    from collections import Counter
    report={"instructions":total,"puzzles":len(puzzles),"sha256":sha256(old),
            "source":audit["url"],
            "source_version":release_number,"source_version_evidence":audit.get("version_evidence","pinned archive history.csv and replayed score"),
            "archive_history_label":release_history[-1]["version"],
            "catalog_metadata_version":audit["metadata_version"],
            "source_program_license":"Apache-2.0","source_steps":original,
            "source_program_license_scope":"License stated by the release publisher. Upstream portfolio inputs retain their original terms.",
            "mixed_portfolio_attribution":{"documentation":portfolio_url,"selected_or_derived_rows":sorted(portfolio_rows)},
            "source_archive_sha256":audit["archive"],"original_credited_csv_sha256":sha256(raw),
            "source_file_sha256":sha256(base),"reduction_from_source":original-total,
            "row_origins":dict(Counter(origins.values())),"independently_replayed":True,
            "submission_status":"local_only"}
    (dest/"result.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    msg=(f"本文件以 Asterios Panoras 在 Kaggle 发布的第 {release_number} 版算式为起点。原版合计 {original:,} 条指令，"
         f"本地逐题比较和重放后的版本为 {total:,} 条。逐题来源见 `origins.csv`，许可证及上游作者说明"
         "见 `LICENSE.txt` 和 `NOTICE.md`。当前结果尚未提交 Kaggle。\n\n"
         f"[公开数据固定版本]({report['source']}) · [比赛规则](https://www.kaggle.com/competitions/santa-2026/rules)\n")
    (dest/"README.md").write_text(msg,encoding="utf8")
    print(total,report["row_origins"],"saved",original-total)


if __name__=="__main__":
    main()
