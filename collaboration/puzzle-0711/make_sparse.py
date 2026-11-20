"""Materialize the sparse integer-bank and parent-recombination profile."""
import argparse
import hashlib
from pathlib import Path
HERE=Path(__file__).resolve().parent
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("output",type=Path)
args=parser.parse_args()
src=(HERE/"balanced.cpp").read_text(encoding="utf-8")
src=src.replace('vector<int> tag;vector<Node> nodes;', """
template<class T> struct Bank {
    vector<T> small;
    unordered_map<int,T> large;
    void resize(int n){small.resize(min(n,500001));}
    T& operator[](int k){return k<small.size()?small[k]:large[k];}
    T get(int k)const{
        if(k<small.size())return small[k];
        auto p=large.find(k);return p==large.end()?T():p->second;
    }
};
Bank<int> tag;Bank<Node> nodes;""")
src=src.replace('vector<unsigned> sample_tag','Bank<unsigned> sample_tag')
src=src.replace('vector<int> pressure_tag','Bank<int> pressure_tag')
src=src.replace('return tag[x]==stamp','return tag.get(x)==stamp')
src=src.replace('++stamp;shuffle(anchors','++stamp;tag.large.clear();nodes.large.clear();sample_tag.large.clear();pressure_tag.large.clear();shuffle(anchors')
src=src.replace('struct Context{',"""
V primes;
V divisors(int n) {
    V ds={1};
    for(int p:primes){
        if(p>n/p)break;
        if(n%p)continue;
        int cnt=ds.size(),mul=1;
        while(n%p==0){
            n/=p;mul*=p;
            for(int j=0;j<cnt;++j)ds.push_back(ds[j]*mul);
        }
    }
    if(n>1){int cnt=ds.size();for(int j=0;j<cnt;++j)ds.push_back(ds[j]*n);}
    return ds;
}
struct Context{""")
src=src.replace('if(a)for(int x=2;x<=r/x;++x)if(!(r%x))price(x,r/x);','if(a)for(int x:divisors(r))if(x>=2 && x<=r/x)price(x,r/x);')
src=src.replace('tag.resize(lim+1);',"""for(int i=2;i<=lim/i;++i){
        bool prime=true;
        for(int q:primes){if(q>i/q)break;if(i%q==0){prime=false;break;}}
        if(prime)primes.push_back(i);
    }
    tag.resize(lim+1);""",1)
src=src.replace('int repeat=2;','int repeat=5;')
src=src.replace('if(n-nstart-__builtin_popcountll(forbid)<(int)path.size())','if(n-nstart-__builtin_popcountll(forbid)<(int)path.size() || (j==0 && n==nstart+path.size()))')
src=src.replace('int num_drop=1+pick(nt);V order=goals;',"""
        if(pick(3)==0){
            int other=lens[pick(lens.size())];auto& os=population[other];
            Path second=os[pick(os.size())];
            unordered_set<int> taken;
            for(auto s:parent)taken.insert(s.v);
            for(auto s:second)if(taken.insert(s.v).second)parent.push_back(s);
            if(parent.size()+seeds.size()<=60)parent=prune(parent);
            else parent=second;
        }
        int num_drop=1+pick(nt);V order=goals;""")

expected='113028ab03293d66b4862bf269ec802d7c3e64c28c12c625407354c14f7b1d38'
assert hashlib.sha256(src.encode("utf-8")).hexdigest()==expected, "unexpected source version"
args.output.write_bytes(src.encode("utf-8"))
print(f"Wrote {args.output} (source SHA-256 {expected})")
