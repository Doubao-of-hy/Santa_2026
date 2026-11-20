"""Independently replay the merged frozen submission and summarize the paired trial."""
import argparse
import csv
import json
import tempfile
from collections import Counter
from pathlib import Path
from experiment import HERE, PROJECT, CURRENT, MODES, digest, gitfile, records
from checkpoint import independent_score
from elf import check, read_puzzles, read_submission, write_submission


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--puzzles',type=Path,default=PROJECT/'data/puzzles.csv')
    args=parser.parse_args()
    design=json.loads((HERE/'design.json').read_bytes())
    trials=json.loads((HERE/'rows.json').read_bytes())
    base=records(gitfile(CURRENT,'public-assisted/submission.csv'))
    programs={k:tuple(tuple(op) for op in json.loads(row['program'])) for k,row in base.items()}
    assert sum(map(len,programs.values()))==134324
    wins=read_submission(HERE/'shorter.csv')
    sources=records((HERE/'shorter.origins.csv').read_bytes())
    assert set(sources)==set(wins)
    assert len(trials)==100
    assert {(t['id'],t['arm']) for t in trials}=={(k,arm) for k in design['rows'] for arm in MODES}
    puzzles=read_puzzles(args.puzzles)
    index={p.id:p for p in puzzles}
    counts=Counter()
    for k in design['rows']:
        scores={t['arm']:t['after'] for t in trials if t['id']==k}
        original=len(programs[k]);wanted=min(scores.values())
        assert original>=wanted and (k in wins)==(wanted<original)
        if wanted<original:
            assert check(index[k],wins[k])==wanted==int(sources[k]['instructions'])
            for mode in MODES:
                if scores[mode]==wanted:counts[mode+' attained a selected win']+=1
    with tempfile.TemporaryDirectory(dir=HERE) as tmp:
        combined=Path(tmp)/'combined.csv'
        n=write_submission(combined,puzzles,programs|wins)
        steps=independent_score(args.puzzles,combined)
        assert sum(steps)==n and len(steps)==1000
        sha=digest(combined.read_bytes())
    summary={'release_base':CURRENT,'base':134324,'combined':n,'combined_sha256':sha,
             'verified_puzzles':len(steps),'own_score_claim':False,'savings':134324-n,
             'rows':{k:{'before':len(programs[k]),'after':len(wins[k]),'source':sources[k]['source']} for k in sorted(wins)},
             'cohort_baseline':sum(len(programs[k]) for k in design['rows']),
             'arms':{m:{'wins':sum(t['after']<t['before'] for t in trials if t['arm']==m),
                        'savings':sum(t['before']-t['after'] for t in trials if t['arm']==m),
                        'wall_seconds_sum':round(sum(t['seconds'] for t in trials if t['arm']==m),3)} for m in MODES},
             'parents_per_row_including_incumbent':dict(sorted(Counter(len(v) for v in design['rows'].values()).items())),
             'normalized_output_sha256':digest((HERE/'shorter.csv').read_bytes()),
             'origins_sha256':digest((HERE/'shorter.origins.csv').read_bytes())}
    print(json.dumps(summary,indent=1))
    (HERE/'verification.json').write_text(json.dumps(summary,indent=1)+'\n',encoding='utf8')

if __name__=='__main__':main()
