// Find short exact products, optionally constructing both factors from one intermediate.
#include <algorithm>
#include <array>
#include <cstdint>
#include <iostream>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

using Value = std::int64_t;
struct Edge { Value out, left, right; char op; };
using Plan = std::vector<Edge>;

template<class Emit>
void inverse(Value goal, Value a, Value limit, Emit emit) {
    if(goal>a) emit(goal-a,Edge{goal,a,goal-a,'+'});
    if(a>goal) emit(a-goal,Edge{goal,a,a-goal,'-'});
    if(goal+a<=limit) emit(goal+a,Edge{goal,goal+a,a,'-'});
    if(goal%a==0) emit(goal/a,Edge{goal,a,goal/a,'*'});
    if(a%goal==0) emit(a/goal,Edge{goal,a,a/goal,'/'});
    if(goal<=limit/a) emit(goal*a,Edge{goal,goal*a,a,'/'});
}
bool append(Plan &plan, Edge e){
    for(const auto &old:plan) if(old.out==e.out) return true;
    if(e.out==e.left || e.out==e.right) return false;
    plan.push_back(e);
    return true;
}
struct Supply {
    const std::vector<Value> &anchors;
    Value limit;
    std::unordered_set<Value> paid;
    std::unordered_map<Value,Edge> direct;
    std::unordered_map<Value,Plan> cache;
    std::unordered_set<Value> unavailable;
    Supply(const std::vector<Value> &aa,Value l):anchors(aa),limit(l),paid(aa.begin(),aa.end()){
        auto add=[&](Value v,char o,Value a,Value b){
            if(!paid.count(v) && v!=a && v!=b) direct.emplace(v,Edge{v,a,b,o});
        };
        for(size_t i=0;i<anchors.size();i++) for(size_t j=0;j<=i;j++){
            Value a=std::min(anchors[i],anchors[j]),b=std::max(anchors[i],anchors[j]);
            if(a+b<=limit)add(a+b,'+',a,b);
            if(b>a)add(b-a,'-',b,a);
            if(a<=limit/b)add(a*b,'*',a,b);
            if(b%a==0)add(b/a,'/',b,a);
        }
    }
    bool get(Value x,Plan &out){
        out.clear();
        if(paid.count(x))return true;
        auto hit=direct.find(x);
        if(hit!=direct.end()){out.push_back(hit->second);return true;}
        auto known=cache.find(x);
        if(known!=cache.end()){out=known->second;return true;}
        if(unavailable.count(x))return false;
        auto use=[&](Value h,Edge e){
            if(!out.empty() || h==x)return;
            auto it=direct.find(h);
            if(it!=direct.end())out={it->second,e};
        };
        if(x%2==0)use(x/2,{x,x/2,x/2,'+'});
        for(Value a:anchors){
            inverse(x,a,limit,use);
            if(!out.empty())break;
        }
        if(out.empty()){unavailable.insert(x);return false;}
        cache.emplace(x,out);
        return true;
    }
};
struct Found {Plan plan; bool shared;};
int main(){
    std::ios::sync_with_stdio(false);std::cin.tie(nullptr);
    int cuts;
    if(!(std::cin>>cuts))return 0;
    for(int k=0;k<cuts;k++){
        Value limit,root;int count,rows,budget,shared,max_out;
        std::cin>>limit>>root>>count>>rows>>budget>>shared>>max_out;
        std::vector<Value> anchors(count);
        for(auto &a:anchors) std::cin>>a;
        Supply supply(anchors,limit);
        std::vector<Found> hits;
        std::uint64_t joint=0;
        for(int row=0;row<rows;row++){
            Value n,f,g,a,b;char op;
            std::cin>>n>>f>>g>>op>>a>>b;
            auto finish=[&](Plan plan,bool linked){
                if(!supply.paid.count(n) && !append(plan,{n,f,g,'*'}))return;
                if(n!=root && !append(plan,{root,a,b,op})) return;
                if(plan.empty() || plan.back().out!=root || (int)plan.size()>budget)return;
                // Entries must be computable in order. A residual or anchor can
                // otherwise accidentally depend on the output it is meant to build.
                for(size_t i=0;i<plan.size();i++){
                    for(Value input:{plan[i].left,plan[i].right}){
                        if(supply.paid.count(input))continue;
                        size_t j=0;while(j<i && plan[j].out!=input)j++;
                        if(j==i)return;
                    }
                }
                hits.push_back({std::move(plan),linked});
            };
            Plan pf,pg;
            if(supply.get(f,pf) && supply.get(g,pg)){
                Plan plan=pf;
                for(auto e:pg) append(plan,e);
                finish(plan,false);
            }
            if(!shared || f==g || supply.paid.count(f) || supply.paid.count(g))continue;
            for(Value anchor:anchors){
                inverse(f,anchor,limit,[&](Value h,Edge lhs){
                    if(h==f || h==g || h==n || h==root || supply.paid.count(h))return;
                    inverse(g,h,limit,[&](Value y,Edge rhs){
                        if(!supply.paid.count(y) || y==g)return;
                        Plan plan;
                        if(!supply.get(h,plan))return;
                        if(!append(plan,lhs) || !append(plan,rhs))return;
                        joint++;finish(plan,true);
                    });
                });
            }
        }
        std::stable_sort(hits.begin(),hits.end(),[](const Found &x,const Found &y){
            return x.plan.size()<y.plan.size();
        });
        std::vector<Found> keep;
        std::unordered_set<std::uint64_t> seen;
        for(auto &hit:hits){
            std::uint64_t sig=0;
            for(auto &e:hit.plan){
                auto a=e.left,b=e.right;
                if((e.op=='+' || e.op=='*') && a>b)std::swap(a,b);
                std::uint64_t h=1469598103934665603ULL;
                for(auto v:std::array<std::uint64_t,4>{(std::uint64_t)e.out,(std::uint64_t)a,(std::uint64_t)b,(std::uint64_t)e.op})
                    h=(h^v)*1099511628211ULL;
                sig^=h;
            }
            if(!seen.insert(sig).second)continue;
            keep.push_back(std::move(hit));
            if((int)keep.size()>=max_out)break;
        }
        std::cout<<keep.size()<<" "<<joint<<" "<<hits.size()<<"\n";
        for(const auto &hit:keep){
            std::cout<<hit.plan.size()<<" "<<hit.shared<<"\n";
            for(auto e:hit.plan)std::cout<<e.out<<" "<<e.op<<" "<<e.left<<" "<<e.right<<"\n";
        }
    }
}
