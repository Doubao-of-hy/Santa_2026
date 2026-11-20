#define main quotient_main
#include "quotient.cpp"
#undef main
#include "integer_factors.hpp"
#include <map>
#include <cmath>
static unordered_map<I,vector<pair<I,I>>> divisor_cache;
static const vector<pair<I,I>>& pairs_for(I n) {
    auto it=divisor_cache.find(n);
    if(it!=divisor_cache.end())return it->second;
    auto ds=factors::divisors(n);vector<pair<I,I>> out;
    for(auto v:ds)if(v>1&&v<=n/v)out.emplace_back(v,n/v);
    sort(out.rbegin(),out.rend());
    return divisor_cache.emplace(n,move(out)).first->second;
}
struct Try {int rank;I n,a,b,r;char kind;Path pre;};
struct Factored:Solver{
    using Solver::Solver;
    void merge(Path& p,const Path& h) const{
        for(auto e:h)if(!contains(p,e.v))p.push_back(e);
    }
    void accept(Path& best,I t,I r,char how,I n,I a,I b,const Path& left,const Path& right){
        Path candidate=left;merge(candidate,right);
        if(!contains(candidate,n))candidate.push_back({n,a,b,'*'});
        if(!contains(candidate,t)&&how){
            if(how=='+')candidate.push_back({t,n,r,'+'});
            else if(how=='-')candidate.push_back({t,n,r,'-'});
            else candidate.push_back({t,r,n,'-'});
        }
        consider(best,move(candidate));
    }
    Path solve_factored(I t){
        Path best=join(t,true);if(!best.empty()&&best.size()<=2)return best;
        vector<Try> deferred;unordered_set<I> visited;
        auto visit=[&](I n,I r,char how){
            if(n<4||!visited.insert(n).second)return;
            for(auto [a,b]:pairs_for(n)){
                if((r==a||r==b)&&!how)continue;
                Path left=join(a,false),right=join(b,false);
                bool hasA=known.count(a)||!left.empty(),hasB=known.count(b)||!right.empty();
                if(hasA&&hasB)accept(best,t,r,how,n,a,b,left,right);
                else if(hasA||hasB){
                    I x=hasA?a:b,y=hasA?b:a;auto& p=hasA?left:right;
                    int rank=int(p.size())*30+int(how!=0)*10+64-__builtin_clzll(y);
                    deferred.push_back({rank,n,x,y,r,how,p});
                }
            }
        };
        visit(t,0,0);
        for(auto r:free){
            if(t>r)visit(t-r,r,'+');
            if(t<=cap-r)visit(t+r,r,'-');
            if(r>t)visit(r-t,r,'~');
        }
        if(!best.empty()&&best.size()<=3)return best;
        sort(deferred.begin(),deferred.end(),[](const Try& a,const Try& b){
            if(a.rank!=b.rank)return a.rank<b.rank;
            if(a.b!=b.b)return a.b<b.b;
            return a.n<b.n;
        });
        map<I,Path> hard;
        for(auto& z:deferred){
            if(!hard.count(z.b)){
                if(hard.size()>=40)continue;
                hard[z.b]=join(z.b,true);
            }
            auto& suffix=hard[z.b];
            if(!suffix.empty())accept(best,t,z.r,z.kind,z.n,z.a,z.b,z.pre,suffix);
        }
        return best;
    }
};
int main(){
    ios::sync_with_stdio(false);cin.tie(nullptr);
    I cap;int n,m,mode;
    while(cin>>cap>>n>>m>>mode){
        vector<I> a(n),goals(m);for(I& x:a)cin>>x;for(I& x:goals)cin>>x;
        Path path;unordered_set<I> known(a.begin(),a.end());bool ok=true;
        for(I t:goals){
            if(known.count(t))continue;
            Factored solver(cap,a);auto p=mode?solver.solve_factored(t):solver.join(t,true);
            if(p.empty()){ok=false;break;}
            for(auto x:p)if(known.insert(x.v).second){path.push_back(x);a.push_back(x.v);}
        }
        cout<<(ok?(int)path.size():-1)<<'\n';
        if(ok)for(auto e:path)cout<<e.v<<' '<<e.op<<' '<<e.a<<' '<<e.b<<'\n';
    }
}
