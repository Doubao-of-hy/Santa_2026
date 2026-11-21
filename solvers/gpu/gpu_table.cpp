// Flat numeric dictionary for the shallow operand levels of the GPU search.
#include <algorithm>
#include <cstdint>
#include <limits>
#include <vector>

using U64=std::uint64_t;
using U32=std::uint32_t;
struct Entry {U64 v,mask; U32 l,r; unsigned char op;};

class Unique {
    std::vector<U64> keys;
    std::vector<U32> rows;
    std::size_t fill=0;
    std::size_t slot(U64 k) const {
        U64 h=k*0x9e3779b97f4a7c15ULL;
        h^=h>>29;
        std::size_t p=h&(keys.size()-1);
        while(keys[p] && keys[p]!=k) p=(p+1)&(keys.size()-1);
        return p;
    }
    void resize() {
        auto old_keys=std::move(keys); auto old_rows=std::move(rows);
        keys.assign(old_keys.size()*2,0); rows.resize(keys.size());
        for(std::size_t i=0;i<old_keys.size();++i) if(old_keys[i]) {
            auto p=slot(old_keys[i]); keys[p]=old_keys[i]; rows[p]=old_rows[i];
        }
    }
public:
    Unique():keys(8192,0),rows(8192) {}
    U32 insert(U64 key,U32 row) {
        if(fill*10>=keys.size()*7) resize();
        auto p=slot(key);
        if(keys[p]) return rows[p];
        keys[p]=key;rows[p]=row;++fill;
        return std::numeric_limits<U32>::max();
    }
    void reindex(const std::vector<Entry>& list,std::size_t begin) {
        for(std::size_t i=begin;i<list.size();++i) rows[slot(list[i].v)]=U32(i);
    }
};

struct Output {
    std::vector<U64> values;
    std::vector<U32> left,right;
    std::vector<unsigned char> op;
    U32 n0=0,n1=0;
};

extern "C" __declspec(dllexport) Output* gpu_build(const U64* seeds,const U64* masks,U32 n,U64 limit) {
    auto* result=new Output;
    std::vector<Entry> v;
    Unique seen;
    for(U32 i=0;i<n;++i) {seen.insert(seeds[i],i);v.push_back({seeds[i],masks[i],0,0,0});}
    U32 cutoff=n;
    auto add=[&](U64 val,U32 i,U32 j,unsigned char op) {
        if(!val||val>limit) return;
        U32 p=seen.insert(val,U32(v.size()));
        U64 mask=v[i].mask|v[j].mask;
        if(p==std::numeric_limits<U32>::max()) v.push_back({val,mask,i,j,op});
        else if(p>=cutoff && mask!=v[p].mask && __builtin_popcountll(mask)<__builtin_popcountll(v[p].mask))
            v[p]={val,mask,i,j,op};
    };
    auto combine=[&](unsigned char op,U32 i,U32 j) {
        U64 a=v[i].v,b=v[j].v;
        if(a<b) {std::swap(i,j);std::swap(a,b);}
        if(op==1) add(a+b,i,j,op);
        else if(op==2 && a>b) add(a-b,i,j,op);
        else if(op==3 && a<=limit/b) add(a*b,i,j,op);
        else if(op==4 && a%b==0) add(a/b,i,j,op);
    };
    for(unsigned char op=1;op<=4;++op)
        for(U32 i=0;i<n;++i) for(U32 j=i;j<n;++j) combine(op,i,j);
    std::sort(v.begin()+n,v.end(),[](Entry a,Entry b){return a.v<b.v;});
    seen.reindex(v,n);
    result->n0=n;result->n1=cutoff=U32(v.size());
    for(unsigned char op=1;op<=4;++op) {
        for(U32 i=n;i<cutoff;++i) for(U32 j=0;j<n;++j) combine(op,i,j);
        for(U32 i=n;i<cutoff;++i) combine(op,i,i);
    }
    std::sort(v.begin()+cutoff,v.end(),[](Entry a,Entry b){return a.v<b.v;});
    result->values.reserve(v.size());result->op.reserve(v.size());
    result->left.reserve(v.size());result->right.reserve(v.size());
    for(auto& e:v) {
        result->values.push_back(e.v);result->left.push_back(e.l);
        result->right.push_back(e.r);result->op.push_back(e.op);
    }
    return result;
}
extern "C" __declspec(dllexport) void gpu_views(Output* p,U32* sizes,const U64** values,
        const unsigned char** ops,const U32** left,const U32** right) {
    sizes[0]=p->n0;sizes[1]=p->n1;sizes[2]=U32(p->values.size());
    *values=p->values.data();*ops=p->op.data();*left=p->left.data();*right=p->right.data();
}
extern "C" __declspec(dllexport) void gpu_free(Output* p) {delete p;}
