"""Test the independent oracle against exhaustive four-vertex graphs."""
import itertools,json,random
from collections import Counter
from pathlib import Path
from ordered import actual,adjacent,calculate,check_witness,extend
HERE=Path(__file__).resolve().parent

def match(groups,used=frozenset()):
    if not groups:return ()
    opts=min(groups,key=len)
    rest=list(groups);rest.remove(opts)
    for t in opts-used:
        result=match(rest,used|{t})
        if result is not None:return (t,*result)
    return None

def brute(labels,banned,cap):
    all_v=set(range(1,cap+1))-set(banned);labels=set(labels)
    edges={pair:actual(*pair,cap)&labels for pair in itertools.combinations(sorted(all_v),2)}
    for qu in itertools.combinations(sorted(all_v),4):
        rows=list(itertools.combinations(qu,2))
        for skip in rows:
            if match([edges[edge] for edge in rows if edge!=skip]) is not None:return 'PRESENT'
    return 'ABSENT'

def main():
    rng=random.Random(20261120);result=Counter();cases=[]
    for cap in range(5,13):
        for _ in range(48):
            nums=list(range(1,cap+1))
            labels=set(rng.sample(nums,rng.randint(4,min(cap,9))))
            banned=set(rng.sample(nums,rng.randint(0,2)))
            exact=brute(labels,banned,cap);status,w,_=calculate(labels,banned,cap)
            assert status==exact,(cap,labels,banned,status,exact)
            if w:assert check_witness(w,labels,banned,cap)
            result[status]+=1
    for cap in range(5,9):
        for size in range(5,cap+1):
            for labels in itertools.combinations(range(1,cap+1),size):
                blocked={2}
                sol,w,_=calculate(labels,blocked,cap)
                assert sol==brute(labels,blocked,cap)
                if w:assert check_witness(w,labels,blocked,cap)
                cases.append(sol)
    # Restrict to exactly four legal vertices; stress each numeric position of the fourth.
    vertices={2,3,5,7};cap=42;banned=set(range(1,cap+1))-vertices;checks=[]
    for fourth in sorted(vertices):
        a,b,c=sorted(vertices-{fourth})
        pairs=[(a,b),(a,c),(b,c),(a,fourth),(b,fourth)]
        for ll in itertools.product(*(sorted(actual(i,j,cap)) for i,j in pairs)):
            if len(set(ll))!=5:continue
            tri=[(i,j,t) for (i,j),t in zip(pairs,ll)][:3]
            labels=set(ll);lookup=lambda v:adjacent(v,labels,banned,cap)
            certificate=extend(tri,labels,banned,cap,lookup)
            assert certificate and check_witness(certificate,labels,banned,cap)
            assert calculate(labels,banned,cap)[0]=='PRESENT'
            checks.append({'fixed_triangle':[a,b,c],'extra':fourth,'labels':sorted(ll),'witness':certificate});break
    assert len(checks)==4
    assert calculate({5,6,7,8},{},25)[0]=='ABSENT'
    assert calculate(range(1,11),set(range(4,11)),10)[0]=='ABSENT'
    # On a large formal domain, unresolved polynomial identities must not yield an absence certificate.
    # Choose only 3 legal vertices supporting arithmetic, plus one vertex irrelevant to every triangle.
    cap=200;labels={2,3,5,41,47};banned=set(range(1,cap+1))-{101,103,106,199}
    assert brute(labels,banned,cap)=='ABSENT'
    empty,w,stats=calculate(labels,banned,cap)
    assert empty=='UNKNOWN' and w is None and stats['identities']>0
    data={'matched_random':dict(result),'exhaustive_label_sets':dict(Counter(cases)),'forced_fourth_positions':checks,'identity_large_no_witness':empty}
    (HERE/'tiny.json').write_text(json.dumps(data,indent=1)+'\n',encoding='utf8')
    print(dict(result),len(cases),[r['extra'] for r in checks],empty)
if __name__=='__main__':main()
