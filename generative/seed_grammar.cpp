// Enumerate all straight-line computations of at most four instructions from a few roots.
#include <algorithm>
#include <cstdint>
#include <iostream>
#include <set>
#include <unordered_map>
#include <unordered_set>
#include <vector>
using namespace std;
using I=int64_t;
struct Edge {I v,a,b;char op;};
struct Pairs {
    I limit;
    template<class F> void each(I a,I b,F collect){
        if(a<=limit-b)collect(Edge{a+b,a,b,'+'});
        if(a>b)collect(Edge{a-b,a,b,'-'});
        if(b>a)collect(Edge{b-a,b,a,'-'});
        if(a<=limit/b)collect(Edge{a*b,a,b,'*'});
        if(a%b==0)collect(Edge{a/b,a,b,'/'});
        if(b%a==0 && b!=a)collect(Edge{b/a,b,a,'/'});
    }
};
struct Search:Pairs {
    vector<I> roots,values,goals;
    unordered_map<I,int> wanted;
    vector<vector<Edge>> best;
    vector<Edge> path;
    set<pair<I,I>> pairs;
    int depth;
    explicit Search(I lim,int d):Pairs{lim},depth(d){}
    void record(Edge e){
        auto f=wanted.find(e.v);if(f==wanted.end())return;
        auto &r=best[f->second];
        if(!r.empty() && r.size()<=path.size()+1)return;
        r=path;r.push_back(e);
    }
    void extend(int remaining){
        if(remaining==1){
            // If the final operation did not consume the most recent new value,
            // a shorter program already occurs at an earlier depth.
            I last=values.back();
            for(I b:values)each(last,b,[&](Edge e){record(e);});
            return;
        }
        unordered_set<I> visited(values.begin(),values.end());
        vector<Edge> candidates;
        for(size_t i=0;i<values.size();++i)for(size_t j=0;j<=i;++j)
            each(values[i],values[j],[&](Edge e){
                if(visited.insert(e.v).second)candidates.push_back(e);
            });
        for(Edge e:candidates){
            record(e);
            if(path.size()==1 && !pairs.emplace(min(e.v,path[0].v),max(e.v,path[0].v)).second)continue;
            path.push_back(e);values.push_back(e.v);
            extend(remaining-1);
            values.pop_back();path.pop_back();
        }
    }
    void run(){
        values=roots;best.resize(goals.size());
        for(int i=0;i<(int)goals.size();++i)wanted[goals[i]]=i;
        extend(depth);
        for(size_t i=0;i<goals.size();++i){
            int length=find(roots.begin(),roots.end(),goals[i])!=roots.end()?0:
                best[i].empty()?-1:int(best[i].size());
            cout<<goals[i]<<" "<<length;
            if(length>0)for(auto e:best[i])cout<<" "<<e.v<<" "<<e.op<<" "<<e.a<<" "<<e.b;
            cout<<"\n";
        }
    }
};
int main(){
    ios::sync_with_stdio(false);cin.tie(nullptr);
    I lim;int n,t,d;
    while(cin>>lim>>n>>t>>d){
        if(d<2||d>4||n<1)return 2;
        Search s(lim,d);I v;
        for(int i=0;i<n;i++){cin>>v;s.roots.push_back(v);}
        for(int i=0;i<t;i++){cin>>v;s.goals.push_back(v);}
        s.run();
    }
}
