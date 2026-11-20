// Generate a compact, diverse set of individually constructible integers for
// a joint physical subprogram model. The model may choose any number of them.
#define main value_exchange_main
#include "value_exchange.cpp"
#undef main
#include <map>
#include <array>
int main(int argc,char**argv){
    ios::sync_with_stdio(false);cin.tie(nullptr);string id;int ns,nt,nop;
    while(cin>>id){
        Search s;cin>>s.cap>>ns>>nt>>nop;s.seeds.resize(ns);s.goals.resize(nt);
        for(auto&v:s.seeds)cin>>v;for(auto&v:s.goals)cin>>v;
        for(int i=0;i<nop;i++){Op e;cin>>e.v>>e.op>>e.a>>e.b;s.original.push_back(e);}s.populate();
        unsigned seed=79319;for(char ch:id)seed=seed*137+unsigned(ch);mt19937 rng(seed);
        struct Ingredient{int rank,id,tier;vector<U> mask;};
        vector<Ingredient> pool;vector<U> baseline;int ignored=0;
        for(auto& b:s.batches)baseline.push_back(s.helped(b,nullptr,ignored));
        for(int k=0;k<int(s.extras.size());k++){
            auto& h=s.extras[k];if(h.birth.empty())continue;
            vector<U> masks;int singles=0,partial=0;
            for(int i=0;i<int(s.batches.size());i++){U bits=s.helped(s.batches[i],&h,partial)&~baseline[i];
                singles+=__builtin_popcountll(bits);masks.push_back(bits);}
            int tier=singles?0:partial?1:2;
            if(tier==2&&h.use.size()<3)continue;
            int rank=60*min(4,singles)+3*min(24,partial)+3*min(10,int(h.use.size()))+int(rng()%29);
            pool.push_back({rank,k,tier,move(masks)});
        }
        sort(pool.begin(),pool.end(),[](auto& a,auto& b){return a.rank>b.rank;});
        int total=argc>1?stoi(argv[1]):72;array<int,3> counts{};map<vector<U>,int> repeated;
        vector<Op> out;
        for(auto& p:pool){
            int quota=p.tier==0?total/2:p.tier==1?total*2/5:total-total/2-total*2/5;
            if(counts[p.tier]>=quota)continue;auto& h=s.extras[p.id];
            if(!p.tier&&repeated[p.mask]++>max(2,total/18))continue;
            auto e=*min_element(h.birth.begin(),h.birth.end(),[](auto a,auto b){return max(a.a,a.b)<max(b.a,b.b);});
            out.push_back({h.value,s.values[e.a],s.values[e.b],e.op});counts[p.tier]++;
        }
        cout<<out.size()<<'\n';for(auto e:out)cout<<e.v<<' '<<e.op<<' '<<e.a<<' '<<e.b<<'\n';
    }
}
