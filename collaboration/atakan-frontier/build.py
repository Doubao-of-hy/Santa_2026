"""Build the two fixed, checksum-verified Atakan releases without executing the notebooks."""
import argparse
import ast
import base64
import hashlib
import json
import os
import shutil
import subprocess
import urllib.request
import zlib
from pathlib import Path

HERE=Path(__file__).resolve().parent

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--cxx',default='g++')
    ap.add_argument('--cache',type=Path)
    args=ap.parse_args()
    d=json.loads((HERE/'design.json').read_bytes())
    ledger=json.loads((HERE/'source-hashes.json').read_bytes())
    for version,symbol in [('v15','OPTIMIZER_SOURCES'),('v30','OFFLINE_SOURCE')]:
        info=d['kernels'][version[1:]]; out=HERE/'scratch'/version;out.mkdir(parents=True,exist_ok=True)
        if args.cache:
            blob=(args.cache/(version+'-raw.json')).read_bytes()
        else:
            link='https://www.kaggle.com/kernels/scriptcontent/'+str(info['run'])+'/download'
            with urllib.request.urlopen(link,timeout=45) as response:blob=response.read()
        assert hashlib.sha256(blob).hexdigest()==info['sha256']
        notebook=json.loads(blob);bundle=None
        for cell in notebook['cells']:
            if cell['cell_type']!='code':continue
            for statement in ast.parse(''.join(cell['source'])).body:
                if isinstance(statement,ast.Assign) and isinstance(statement.targets[0],ast.Name) and statement.targets[0].id==symbol:
                    bundle=json.loads(zlib.decompress(base64.b85decode(ast.literal_eval(statement.value))))
        assert bundle
        for source,sha in ledger[version].items():
            raw=bundle[source].encode()
            assert hashlib.sha256(raw).hexdigest()==sha
            (out/source).write_bytes(raw)
        if version=='v30':
            for source,sha in ledger['v30_inherited_v15'].items():
                assert source not in bundle
                path=HERE/'scratch'/'v15'/source
                assert hashlib.sha256(path.read_bytes()).hexdigest()==sha
                shutil.copyfile(path,out/source)
        flags=['-std=c++17','-O3','-pthread']
        if os.name=='nt': flags+=['-static','-march=x86-64','-Wl,--no-insert-timestamp']
        binary='frontier.exe' if os.name=='nt' else 'frontier'
        subprocess.run([args.cxx,*flags,'elf_multiplier_frontier.cpp','-o',binary],cwd=out,check=True,
                       env={**os.environ,'TEMP':str(out),'TMP':str(out),'TMPDIR':str(out)})

if __name__=='__main__':main()
