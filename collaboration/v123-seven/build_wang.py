"""Rebuild the exact retained-pool modification from its licensed upstream sources."""
import argparse,hashlib,json,os,subprocess
from pathlib import Path

def digest(b):
    return hashlib.sha256(b).hexdigest()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--repo",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--compiler",default="g++")
    args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    cfg=json.loads(Path(__file__).with_name("design.json").read_bytes())
    def blob(name):
        return subprocess.check_output(["git","-C",str(args.repo),"show","aca4989fad3a364af53362841790b7e65d935f12:generative/wang/"+name])
    headers=("common.inc","compact.inc","cross.inc","recipe_lookup.inc","fast_perturb.inc","cache_lookup.inc","cache_perturb.inc","main.inc")
    for name in headers:(out/name).write_bytes(blob(name))
    raw=blob("incremental.cpp")
    assert digest(raw)=="7a0d5327d0883e04c80c42761d7ec53e6cc3fbc45b36e0700bf5b1900dc09e8f"
    text=raw.decode();anchor="std::vector<Graph> pool;";assert text.count(anchor)==1
    text=text.replace(anchor,anchor+"""
        for(size_t i=1;i<tapes.size();++i) pool.push_back(graph_from(tapes[i]));
        const auto retained=pool.size();
        if(retained) {
            Graph initial;
            if(crossover(champion,pool,initial,best)) { champion=initial; trial=initial; }
        }
""")
    old="if(pool.size()>12)pool.erase(pool.begin()+rng()%5);";assert text.count(old)==1
    text=text.replace(old,"if(pool.size()>12) { const auto count=pool.size()-retained; pool.erase(pool.begin()+retained+rng()%count); }")
    src=out/"incremental.cpp";src.write_bytes(text.replace("\n","\r\n").encode())
    sh=digest(src.read_bytes());assert sh==cfg["Wang"]["source_sha256"]
    exe=out/("incremental.exe" if os.name=="nt" else "incremental")
    subprocess.run([args.compiler,"-O3","-std=c++17"]+(["-static"] if os.name=="nt" else [])+["-I",str(out),str(src),"-o",str(exe)],env=dict(os.environ,TEMP=str(out),TMP=str(out)),check=True)
    exe.with_suffix(".build.json").write_text(json.dumps({"source_sha256":sh,"binary_sha256":digest(exe.read_bytes())},indent=2)+"\n",encoding="utf8")
    print(exe,sh)

if __name__=="__main__":main()
