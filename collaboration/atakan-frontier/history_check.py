"""Reproduce the author's known v14-to-v15 gain on 0185 without executing notebook cells."""
import argparse
import ast
import base64
import json
import struct
import urllib.request
import zlib
from pathlib import Path
from run import D,HERE,OFFICIAL,sha,trial,read_puzzles

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--cache',type=Path)
    args=ap.parse_args();v=D['kernels']['15']
    if args.cache:
        blob=args.cache.read_bytes()
    else:
        url='https://www.kaggle.com/kernels/scriptcontent/'+str(v['run'])+'/download'
        with urllib.request.urlopen(url,timeout=45) as f:blob=f.read()
    assert sha(blob)==v['sha256']
    values={}
    for cell in json.loads(blob)['cells']:
        if cell['cell_type']!='code':continue
        for s in ast.parse(''.join(cell['source'])).body:
            if isinstance(s,ast.Assign) and isinstance(s.targets[0],ast.Name) and s.targets[0].id in ('V14_TAPE','V14_HASH','PAIRED_AUDIT'):
                values[s.targets[0].id]=ast.literal_eval(s.value)
    unpack=lambda x:zlib.decompress(base64.b85decode(x))
    raw=unpack(values['V14_TAPE']);assert sha(raw)==values['V14_HASH']
    k='scored_0185';at=0;target=185
    while at<len(raw):
        i,n=struct.unpack_from('<HH',raw,at);at+=4
        if i==target:break
        at+=3*n
    assert i==target
    t=[]
    for j in range(n):
        word=int.from_bytes(raw[at:at+3],'little');at+=3
        t.append(('+-*/'[word&3],(word>>2)&63,(word>>8)&63,(word>>14)&63))
    orig=json.loads(unpack(values['PAIRED_AUDIT']))['runs']['frontier-v15-full']['changed'][k]
    D['arms']['v15-author-control']=list(map(int,orig[2]['profile']))
    p=next(p for p in read_puzzles(OFFICIAL) if p.id==k)
    r,_=trial(p,t,'v15-author-control')
    assert [r['before'],r['after']]==orig[:2]==[148,146]
    out={'kernel':371328068,'id':k,'config':orig[2]['profile'],'published_control':orig[:2],'replay':r,'official_puzzle_sha256':sha(OFFICIAL.read_bytes())}
    (HERE/'positive-control.json').write_text(json.dumps(out,indent=1)+'\n',encoding='utf8')
    print(k,*orig[:2])
if __name__=='__main__':main()
