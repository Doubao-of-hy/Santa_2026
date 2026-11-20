// Applies a symbolic arithmetic program to every injective binding of its
// seed roles. Input is strictly the legal value limit and official seed values.
#include <algorithm>
#include <array>
#include <cstdint>
#include <fstream>
#include <functional>
#include <iostream>
#include <set>
#include <string>
#include <unordered_map>
#include <vector>
using I=int64_t;
struct Op{char op;int a,b;};
struct Pattern{int roles;std::vector<Op> ops;};
struct Witness{int n,index;std::array<int,4> bind;};
int main(int argc,char**argv){
    if(argc<2||argc>3)return 2;
    const bool lift=argc==3 && std::string(argv[2])=="--lift-select";
    std::ifstream f(argv[1]);std::vector<Pattern> patterns;int m,n;
    while(f>>m>>n){Pattern p{m,{}};for(int i=0;i<n;i++){Op o;f>>o.op>>o.a>>o.b;p.ops.push_back(o);}patterns.push_back(p);}
    I cap;int count;while(std::cin>>cap>>count){
        std::vector<I> seeds(count);for(auto &v:seeds)std::cin>>v;
        std::vector<I> available=seeds;
        if(lift){
            std::set<I> extra;
            for(I x:seeds)for(I y:seeds){
                if(x<=cap-y)extra.insert(x+y);
                if(x>y)extra.insert(x-y);
                if(x<=cap/y)extra.insert(x*y);
                if(x%y==0)extra.insert(x/y);
            }
            for(I v:seeds)extra.erase(v);
            available.insert(available.end(),extra.begin(),extra.end());
        }
        std::unordered_map<I,Witness> outputs;
        std::array<int,4> binding{};long long trials=0,valid=0;
        for(int i=0;i<(int)patterns.size();++i){
            auto& p=patterns[i];if(p.roles>count+int(lift))continue;
            std::function<void(int,uint64_t,int)> build=[&](int k,uint64_t used,int extra){
                if(k<p.roles){
                    for(int j=0;j<count;j++)if(!(used>>j&1)){
                        binding[k]=j;build(k+1,used|(uint64_t(1)<<j),extra);
                    }
                    if(lift && extra<0)for(int j=count;j<(int)available.size();j++){
                        binding[k]=j;build(k+1,used,j);
                    }
                    return;
                }
                if(lift&&extra<0)return;
                ++trials;I values[9]{};int ix=0,cost=lift?1:0;
                auto val=[&](int ref){return ref<0?available[binding[-1-ref]]:values[ref];};
                for(auto op:p.ops){
                    I l=val(op.a),r=val(op.b),v;
                    if(op.op=='+'){if(l>cap-r)return;v=l+r;}
                    else if(op.op=='-'){if(l<=r)return;v=l-r;}
                    else if(op.op=='*'){if(l>cap/r)return;v=l*r;}
                    else {if(l%r)return;v=l/r;}
                    if((extra<0||v!=available[extra])&&std::find(seeds.begin(),seeds.end(),v)==seeds.end()&&std::find(values,values+ix,v)==values+ix)++cost;
                    values[ix++]=v;
                }
                ++valid;I v=values[ix-1];
                if(v<2||std::find(seeds.begin(),seeds.end(),v)!=seeds.end())return;
                auto old=outputs.find(v);
                if(old==outputs.end()||cost<old->second.n)outputs[v]={cost,i,binding};
            };
            build(0,0,-1);
        }
        std::cout<<trials<<' '<<valid<<' '<<outputs.size()<<'\n'<<std::flush;
        std::vector<I> keys;
        if(lift){
            // No readback filters arrive until the full, seed-only generation has finished.
            int q;std::cin>>q;I v;for(int j=0;j<q;j++){std::cin>>v;if(outputs.count(v))keys.push_back(v);}
            std::cout<<keys.size()<<'\n';
        }else{
            for(auto& e:outputs)keys.push_back(e.first);
        }
        std::sort(keys.begin(),keys.end());
        for(auto v:keys){auto&w=outputs[v];std::cout<<v<<' '<<w.n<<' '<<w.index;for(int j=0;j<patterns[w.index].roles;j++)std::cout<<' '<<w.bind[j];std::cout<<'\n';}
    }
}
