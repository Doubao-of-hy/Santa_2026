"""Freeze the eight earlier Atakan winners and pair each with one tested unchanged independent row."""
import csv,hashlib,io,json,subprocess
from pathlib import Path
D=Path(__file__).resolve().parent;R=D.parent/'atakan134311'
G=Path('E:/Codex/Santa2026-GitHub');O=Path('E:/Codex/Santa2026/data/puzzles.csv')
REV='243776e870fd4602df8d05340f69ee146cd7339a'
h=lambda b:hashlib.sha256(b).hexdigest()
def git(f):return subprocess.check_output(['git','-C',str(G),'show',REV+':'+f])
def table(b):return {r['id']:r for r in csv.DictReader(io.StringIO(b.decode('utf-8-sig')))}
p=table(O.read_bytes());blob=git('submission.csv');orig=git('origins.csv');rows=table(blob)
old=json.loads((R/'verification.json').read_bytes())['independent']
before=table(subprocess.check_output(['git','-C',str(G),'show','aca4989:submission.csv']))
previous={k:v for k,v in json.loads((R/'details.json').read_bytes()).items() if v['lane']=='independent' and v['arm']=='v30-13'}
wins=sorted(old['wins'])
controls=[r['id'] for r in previous.values() if r['id'] not in wins and rows[r['id']]['program']==before[r['id']]['program']]
def attrs(k):
 t=json.loads(p[k]['targets']);return len(json.loads(rows[k]['program'])),len(t),max(t).bit_length()
remaining=set(controls);pairs={}
# Process the winners that have the fewest exactly matching lengths first.
for w in sorted(wins,key=lambda w:(sum(attrs(x)[0]==attrs(w)[0] for x in controls),w)):
 a=attrs(w)
 def distance(k):
  v=attrs(k);return (abs(v[0]-a[0]),abs(v[1]-a[1]),abs(v[2]-a[2]),h(('at-wang-pair/'+w+'/'+k).encode()))
 c=min(remaining,key=distance);remaining.remove(c);pairs[w]={'positive':w,'matched':c,'positive_length':attrs(w)[0],'matched_length':attrs(c)[0]}
out={'frozen':REV,'base':140734,'submission_sha256':h(blob),'origins_sha256':h(orig),'official_sha256':h(O.read_bytes()),'old_study_design_sha256':h((R/'design.json').read_bytes()),'A':{'source':'Atakan Aldemir v30, Kaggle 371505096; v15 whole-graph dependency as documented in the prior trial','configuration':[4,14,4,6,13,257], 'binary_sha256':h((R/'scratch/v30/frontier.exe').read_bytes())},'W':{'source':'Wang Jakie original incremental, Kaggle 371736767; single tape only','rounds':360,'seed_rule':'6417300 + integer scored suffix','binary_sha256':h(Path('E:/Codex/Santa2026/work/virtual/good10-wang-diff/inc-local.exe').read_bytes())},'groups':list(pairs.values()),'design':'Paired replication across eight prior Atakan improvers and eight distinct previously tested unshortened rows with unchanged physical tape on the new release. Pair by nearest frozen length, then number of targets and largest target bitlength, then a salted stable hash, with rarest exact-length winner matched first. These are outcome-selected and matched groups, not a random population estimate.','arms':['A then W','W then A','A from frozen and W from frozen, take shortest'], 'cost':'Every arm uses exactly one A budget and one W budget per row. Reuse identical method, settings, seeds and input bytes across paths or prior experiments; equal scores alone are not a reuse criterion. Record actual invocations and logical allocation separately.','outcome':'Score and exact physical tape of each initial and intermediate stage. Claim a sequential advantage only if a chain beats the per-row independently-started best. Use one shortest fully checked row per ID; ties prefer separate starts to avoid unnecessary ancestry. This experiment ends after the fixed 16 rows.'}
assert sum(len(json.loads(r['program'])) for r in rows.values())==140734
(D/'design.json').write_text(json.dumps(out,indent=1)+'\n',encoding='utf8')
print(h((D/'design.json').read_bytes()),[(w,v['matched'],v['positive_length'],v['matched_length']) for w,v in pairs.items()])
