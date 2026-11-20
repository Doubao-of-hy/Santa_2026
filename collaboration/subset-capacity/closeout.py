"""Complete the single remaining four-deletion case and check for a second increment on winners."""
import hashlib,itertools,json
from search import HERE,OFFICIAL,Capacity,domains,read_puzzles,maximum_deleted,supported
from domain_bounds import close

def main():
    setup=json.loads((HERE/'closeout-design.json').read_bytes())
    assert hashlib.sha256((HERE/'claims.csv').read_bytes()).hexdigest()==setup['inputs']['claims_sha256']
    pmap={p.id:p for p in read_puzzles(OFFICIAL)}
    claims=json.loads((HERE/'verified.json').read_bytes())['rows']
    out=[]
    for i in ['scored_0270',*sorted(claims)]:
        p=pmap[i];seeds=set(p.seeds);goals=set(p.targets);m=len(goals-seeds)
        records={0:(seeds,None)};previous=close(seeds,goals,p.limit)
        for k,e in domains(p,4,3500):
            records[k]=(e,previous);previous=e
        for k,(e,previous) in records.items():
            is_extra=i=='scored_0270'
            if is_extra and k!=3:continue
            if previous is not None and not goals-previous:continue
            h=6 if is_extra else claims[i]['new']-m-k
            if h<0 or not maximum_deleted(m,sum(t<=min(seeds) for t in goals-seeds),h):continue
            b,inc=supported(p,e);u=len(inc);n=maximum_deleted(u,sum(t<=min(seeds) for t in inc),h)
            if not n:continue
            a=Capacity(p,b,inc);bits=(1<<u)-1
            scan=[4] if is_extra else range(1,n+1)
            row={'id':i,'k':k,'h':h,'tested':0,'max_drop':n,'strict':[],'min_by_deletions':{}}
            for j in scan:
                floor=None
                for delset in itertools.combinations(list(inc),j):
                    s=bits^sum(a.bits[x] for x in delset);val=a.ceiling(s,h);row['tested']+=1
                    floor=val if floor is None else min(floor,val)
                    if val<s.bit_count():row['strict'].append({'deleted':delset,'counted':s.bit_count(),'capacity':val,'new_lower':m+k+h+1});break
                row['min_by_deletions'][j]=floor
                if row['strict']:break
            out.append(row)
    (HERE/'closeout.json').write_text(json.dumps(out,indent=1)+'\n',encoding='utf8')
    print(out)
if __name__=='__main__':main()
