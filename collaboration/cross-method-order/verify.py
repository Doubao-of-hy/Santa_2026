"""Replay all saved stage tapes and the final 1,000-row submission, using no native solvers."""
import gzip
import json
import tempfile
from pathlib import Path
from experiment import HERE,OFFICIAL,CFG,hash_bytes,digest_tape,git,table,decode,read_puzzles,check,write_submission,independent_score
from elf import read_submission

def main():
    stages=json.loads(gzip.decompress((HERE/'stages.json.gz').read_bytes()))
    report=json.loads((HERE/'rows.json').read_bytes())
    receipt=json.loads((HERE/'verification.json').read_bytes())
    assert hash_bytes((HERE/'stages.json.gz').read_bytes())==receipt['stages_sha256']
    assert hash_bytes((HERE/'shorter.origins.csv').read_bytes())==receipt['origins_sha256']
    base=git(CFG['frozen'],'submission.csv');assert hash_bytes(base)==CFG['submission_sha256']
    programs={k:decode(r['program']) for k,r in table(base).items()}
    ps=read_puzzles(OFFICIAL);pindex={p.id:p for p in ps}
    assert hash_bytes(OFFICIAL.read_bytes())==CFG['official_sha256']
    wins=read_submission(HERE/'shorter.csv')
    for k,row in report.items():
        s=stages[k];p=pindex[k]
        assert digest_tape(programs[k])==digest_tape(s['parent'])
        for t in s.values():assert check(p,t)==len(t)
        for edge in row['stages']:
            assert digest_tape(s[edge['input']])==edge['input_sha256']
            assert digest_tape(s[edge['label']])==edge['output_sha256']
        assert len(s['separate'])==min(len(s['A']),len(s['W']))
        assert row['sequence_advantage']==len(s['separate'])-min(len(s['separate']),len(s['AW']),len(s['WA']))
        if k in wins:assert digest_tape(wins[k])==digest_tape(s[row['selected']])
    assert set(wins)==set(receipt['wins'])
    with tempfile.TemporaryDirectory(dir=HERE) as temp:
        path=Path(temp)/'merged.csv';n=write_submission(path,ps,programs|wins)
        assert n==sum(independent_score(OFFICIAL,path))==receipt['after']
        assert hash_bytes(path.read_bytes())==receipt['merged_sha256']
    print(f'Validated {sum(map(len,stages.values()))} saved stage tapes and {len(ps)} final puzzle programs, {n} instructions')
if __name__=='__main__':main()
