"""Score local fresh-construction outputs, comparing to two frozen Git snapshots only here."""
from pathlib import Path
import argparse,csv,json,subprocess,sys,tempfile
HERE=Path(__file__).resolve().parent
ROOT=next(p for p in HERE.parents if (p/'elf.py').is_file())
sys.path.insert(0,str(ROOT))
from elf import check,read_puzzles,read_submission,sha256,write_submission
from checkpoint import independent_score
BASE='98e392cc24e2fb68ecbf649e400d506205273372'
PILOT=('0680','0012','0573','0324')
HOLDOUT=('0048','0332','0482','0969','0382','0756','0504','0407')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('puzzles',type=Path);ap.add_argument('out',type=Path)
    ap.add_argument('--git-root',type=Path,default=ROOT);ap.add_argument('--run-root',type=Path,default=HERE)
    args=ap.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    ps=read_puzzles(args.puzzles);by={p.id:p for p in ps}
    jobs=[('pilot',PILOT),('head-pilot',PILOT),('head-holdout',HOLDOUT)]
    with tempfile.TemporaryDirectory(dir=args.out) as td:
        tmp=Path(td);frozen={};hashes={}
        for lane,rel in [('own','submission.csv'),('assisted','public-assisted/submission.csv')]:
            path=tmp/(lane+'.csv')
            path.write_bytes(subprocess.check_output(['git','-C',str(args.git_root),'show',BASE+':'+rel]))
            hashes[lane]=sha256(path);frozen[lane]=read_submission(path)
        winners={};sources={};details={};tables={}
        for tag in ('common','screen'):
            folder=args.run_root/tag
            tables[tag]=[];details[tag]={}
            for record in sorted(folder.glob('scored_*.json')):
                pid=record.stem;meta=json.loads(record.read_bytes())
                tape=read_submission(folder/(pid+'.csv'))[pid]
                n=check(by[pid],tape)
                assert n==meta['after']
                tables[tag].append({'id':pid,'independent':len(frozen['own'][pid]),'assisted':len(frozen['assisted'][pid]),**{k:meta[k] for k in ('raw','mixed','after')}})
                details[tag][pid]=meta
                if n<len(frozen['own'][pid]):
                    winners[pid]=tape;sources[pid]=tag+'/'+pid+'.csv'
        for tag,items in jobs:
            d=args.run_root/tag
            details[tag]={};table=[]
            for i in items:
                pid='scored_'+i;report=d/(pid+'.json')
                if not report.exists():continue
                record=json.loads(report.read_bytes())
                keys=['random','adaptive'] if tag=='pilot' else ['random','directed']
                row={'id':pid,'independent':len(frozen['own'][pid]),'assisted':len(frozen['assisted'][pid])}
                for arm in keys:
                    for suffix in ['', '-finished', '-confirmed']:
                        f=d/(pid+'-'+arm+suffix+'.csv')
                        if not f.exists():continue
                        tape=read_submission(f)[pid];n=check(by[pid],tape)
                        row[arm+suffix]=n
                        if n<len(frozen['own'][pid]) and (pid not in winners or n<len(winners[pid])):
                            winners[pid]=tape;sources[pid]=d.name+'/'+f.name
                for suffix in ['finished','confirmed']:
                    f=d/(pid+'-'+suffix+'.json')
                    if f.exists():record[suffix]=json.loads(f.read_bytes())
                details[tag][pid]=record
                table.append(row)
            tables[tag]=table
        patch=args.out/'wins.csv';write_submission(patch,[by[k] for k in sorted(winners)],winners)
        dst=tmp/'whole.csv'
        score=write_submission(dst,ps,frozen['own']|winners)
        assert sum(independent_score(args.puzzles,dst))==score
        report={'official_sha256':sha256(args.puzzles),'commit':BASE,'baseline_hashes':hashes,
                'independent_before':sum(map(len,frozen['own'].values())),'independent_after':score,
                'candidate_sha256':sha256(dst),'wins_sha256':sha256(patch),
                'wins':{i:{'before':len(frozen['own'][i]),'after':len(t),'source':sources[i]} for i,t in winners.items()},
                'tables':tables}
        (args.out/'results.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
        (args.out/'trials.json').write_text(json.dumps(details,separators=(',',':'))+'\n',encoding='utf8')
        print(len(winners),report['independent_before'],score,report['wins'],flush=True)

if __name__=='__main__':main()
