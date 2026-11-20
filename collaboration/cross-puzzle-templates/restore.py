"""Restore the input-independent templates and optionally the exact Git baseline."""
from pathlib import Path
import argparse,gzip,hashlib,json,subprocess

HERE=Path(__file__).resolve().parent
ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('out',type=Path);ap.add_argument('--git-root',type=Path)
a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=True)
design=json.loads((HERE/'design.json').read_bytes());raw=gzip.decompress((HERE/'library.json.gz').read_bytes())
(a.out/'library.json').write_bytes(raw)
for name,templates in json.loads(raw)['vocabulary'].items():
    lines=[]
    for t in templates:
        values=[t['variables'],len(t['steps'])]
        for step in t['steps']:values.extend(step)
        lines.append(' '.join(map(str,values)))
    (a.out/(name+'.txt')).write_text('\n'.join(lines)+'\n',encoding='utf8',newline='\n')
for name,ids in design['groups'].items():
    assert hashlib.sha256(('\n'.join(ids)+'\n').encode()).hexdigest()==design['group_sha256'][name]
if a.git_root:
    raw=subprocess.check_output(['git','-C',str(a.git_root),'show',design['scored_parent_commit']+':submission.csv'])
    assert hashlib.sha256(raw).hexdigest()==design['scored_parent_sha256']
    (a.out/'parent.csv').write_bytes(raw)
print('template arms and four split hashes verified')
