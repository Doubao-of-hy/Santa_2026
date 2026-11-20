"""Validate seed substitution, exact division, and bounds using an independent Python enumerator."""
from pathlib import Path
from itertools import permutations
from tempfile import TemporaryDirectory
import argparse,json,random
from evaluate import instantiate
from elf import Puzzle

def main():
    ap=argparse.ArgumentParser();ap.add_argument('library',type=Path);ap.add_argument('exe',type=Path);ap.add_argument('out',type=Path)
    a=ap.parse_args();book=json.loads((a.library/'library.json').read_bytes());rng=random.Random(781046)
    observed=[]
    with TemporaryDirectory(dir=a.out.parent) as d:
        for case in range(9):
            arm=('frequent','rare','scrambled')[case%3]
            inds=sorted(rng.sample(range(len(book['vocabulary'][arm])),32))
            raw=(a.library/(arm+'.txt')).read_text().splitlines();subset=Path(d)/'subset.txt'
            subset.write_text('\n'.join(raw[i] for i in inds)+'\n')
            seeds=tuple(rng.sample(range(3,90),3+int(case%2)))
            cap=[10**7,10**13,10**18][case%3]
            p=Puzzle('parity_'+str(case),seeds,(),cap);native,stats=instantiate(p,subset,a.exe.resolve())
            slow=set(); valid=0
            for ix in inds:
                row=book['vocabulary'][arm][ix]
                for binding in permutations(seeds,row['variables']):
                    vals=[]
                    for op,l,r in row['steps']:
                        x=binding[-l-1] if l<0 else vals[l];y=binding[-r-1] if r<0 else vals[r]
                        if op=='/':
                            if x%y:break
                            z=x//y
                        elif op=='*':z=x*y
                        elif op=='+':z=x+y
                        else:z=x-y
                        if not 0<z<=cap:break
                        vals.append(z)
                    else:
                        valid+=1
                        if z>=2 and z not in seeds:slow.add(z)
            assert slow==native.keys() and valid==stats['valid']
            observed.append({'arm':arm,'cap':cap,**stats})
    a.out.write_text(json.dumps(observed,indent=2)+'\n')
    print('distinct',sum(x['unique'] for x in observed),'trials',sum(x['attempted'] for x in observed),'valid',sum(x['valid'] for x in observed))

if __name__=='__main__':main()
