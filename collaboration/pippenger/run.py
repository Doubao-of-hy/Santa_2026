from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import argparse
import hashlib
import json
import sys

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "elf.py").is_file())
sys.path.insert(0, str(ROOT))
from elf import Puzzle, check, read_puzzles
from graph import active_graph, compile_graph
from forward import Builder


def trial(p, radix, block, control):
    builder = Builder(p)
    graph = builder.build(radix, block, control)
    active = active_graph(p, graph)
    tape = compile_graph(p, active, attempts=4, schedule_width=2, recompute=True)
    meta = {"radix": radix, "block": block, "control": control, "dag": len(active),
            "equal_columns": builder.saved_columns, "instructions": None}
    if tape is not None:
        meta["instructions"] = check(p, tape)
        meta["sha256"] = hashlib.sha256(json.dumps(tape,separators=(",",":")).encode()).hexdigest()
    return meta, tape


def measure(arg):
    p, spec = arg
    rows = []
    best = {}
    for radix in (2,4,8):
        for block in (1,2,3,4):
            control = block == 1
            stats, tape = trial(p, radix, block, control)
            arm = "direct" if control else "bucket"
            if tape is not None and (arm not in best or len(tape) < len(best[arm])):
                best[arm] = tape
            rows.append(stats)
    record = {"id":p.id, "parent":spec["length"], "phase":spec["phase"], "runs":rows,
              "best":{arm:len(tape) for arm,tape in best.items()}}
    return record, best


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--puzzles", type=Path, required=True)
    parser.add_argument("--phase", choices=("development","holdout"), required=True)
    parser.add_argument("--output", type=Path, default=HERE)
    args=parser.parse_args()
    design = json.loads((HERE / "design.json").read_bytes())
    puzzles = {p.id:p for p in read_puzzles(args.puzzles)}
    sample = [(puzzles[s["id"]],s) for s in design["rows"] if s["phase"]==args.phase]
    output_dir = args.output / args.phase
    output_dir.mkdir(parents=True, exist_ok=True)
    records = []
    with ProcessPoolExecutor(4) as pool:
        for rec,best in pool.map(measure,sample,chunksize=1):
            records.append(rec)
            for arm,t in best.items():
                if len(t)<rec["parent"]:
                    (output_dir/(rec["id"]+"-"+arm+".json")).write_text(json.dumps(t),encoding="utf8")
    (output_dir/"rows.json").write_text(json.dumps(records,indent=2)+"\n",encoding="utf8")
    summary = {"rows":len(records)}
    for arm in ("direct","bucket"):
        available=[r for r in records if arm in r["best"]]
        summary[arm]={"replayed":len(available),"score_on_available":sum(r["best"][arm] for r in available),
                      "parent_on_available":sum(r["parent"] for r in available),
                      "wins":{r["id"]:[r["parent"],r["best"][arm]] for r in available if r["best"][arm]<r["parent"]}}
    matched=[r for r in records if len(r["best"])==2]
    summary["matched"]={"rows":len(matched),"shorter":sum(r["best"]["bucket"]<r["best"]["direct"] for r in matched),
                        "equal":sum(r["best"]["bucket"]==r["best"]["direct"] for r in matched),
                        "longer":sum(r["best"]["bucket"]>r["best"]["direct"] for r in matched)}
    (output_dir/"result.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf8")
    print(args.phase,summary,flush=True)


if __name__=="__main__":
    main()
