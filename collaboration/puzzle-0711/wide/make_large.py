# Materialize the 64-bit arithmetic profile from the shared sparse profile.
import argparse,hashlib,re
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('sparse_source',type=Path)
p.add_argument('output',type=Path)
a=p.parse_args()
src=a.sparse_source.read_text(encoding='utf-8')
src=re.sub(r'\bint\b','long long',src)
src=src.replace('long long main(long long argc','int main(int argc').replace('min(n,500001)','min(n,500001LL)')
src=src.replace('for(long long i=2;i<=lim/i;++i)', 'for(long long i=2;i<=lim/i && i<=997;++i)')

digest=hashlib.sha256(src.encode()).hexdigest()
assert digest=='8268d646dbc465406bfaefae08093832b7fd445131dd217b92e098db2268021e', 'unexpected profile source'
a.output.write_bytes(src.encode())
print(digest)
