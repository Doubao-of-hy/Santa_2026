// Reduce feasible sets of arithmetic values with a forward reachability oracle.
#include <algorithm>
#include <cstdint>
#include <iostream>
#include <limits>
#include <queue>
#include <random>
#include <set>
#include <vector>
using namespace std;

struct Edge {int out,a,b;};
struct Witness {vector<int> route,used;uint64_t key=0;};
struct Search {
    int n; vector<Edge> edges;
    vector<vector<int>> users;
    vector<int> seeds,goals,base,required,original;
    vector<unsigned char> initial,remaining,done;
    vector<int> cost,choice;
    mt19937 rng;
    vector<Witness> elite;
    set<uint64_t> emitted;
    explicit Search(int n,unsigned seed):n(n),users(n),required(n),original(n),done(n),cost(n),choice(n),rng(seed){}
    uint64_t mix(uint64_t x) {
        x+=0x9e3779b97f4a7c15ULL;x=(x^(x>>30))*0xbf58476d1ce4e5b9ULL;
        x=(x^(x>>27))*0x94d049bb133111ebULL;return x^(x>>31);
    }
    void add(Edge e) {
        int id=int(edges.size());edges.push_back(e);
        users[e.a].push_back(id);
        if(e.b!=e.a)users[e.b].push_back(id);
        initial.push_back(1+int(e.a!=e.b));
    }
    Witness trace(const vector<int>& parents) {
        vector<unsigned char> seen(n);vector<int> todo=goals,used;
        while(!todo.empty()){
            int v=todo.back();todo.pop_back();
            if(seen[v] || parents[v]==-2)continue;
            if(parents[v]<0)return {};
            seen[v]=1;used.push_back(v);
            Edge e=edges[parents[v]];todo.push_back(e.a);todo.push_back(e.b);
        }
        uint64_t key=0;
        for(int v:used)key^=mix(v);
        return {parents,used,key};
    }
    Witness find(const vector<unsigned char>& allowed,const vector<int>& fee) {
        remaining=initial;
        fill(done.begin(),done.end(),0);fill(cost.begin(),cost.end(),1000000000);
        fill(choice.begin(),choice.end(),-1);
        using Entry=pair<int,int>;
        priority_queue<Entry,vector<Entry>,greater<Entry>> open;
        for(int s:seeds){cost[s]=0;choice[s]=-2;open.emplace(0,s);}
        int missing=int(goals.size());
        while(!open.empty()){
            auto [d,v]=open.top();open.pop();
            if(done[v])continue;
            done[v]=1;
            if(required[v] && --missing==0)break;
            for(int id:users[v]){
                Edge e=edges[id];
                if(!allowed[e.out] || done[e.out] || --remaining[id])continue;
                int next=fee[e.out]+max(cost[e.a],cost[e.b])+min(cost[e.a],cost[e.b])/3;
                next=min(next,900000000);
                if(next>=cost[e.out])continue;
                choice[e.out]=id;cost[e.out]=next;open.emplace(next,e.out);
            }
        }
        return missing?Witness{}:trace(choice);
    }
    void remember(Witness w) {
        if(w.route.empty())return;
        for(const auto &x:elite)if(x.key==w.key)return;
        elite.push_back(move(w));
        stable_sort(elite.begin(),elite.end(),[](const Witness& a,const Witness& b){
            return a.used.size()<b.used.size();
        });
        if(elite.size()>12)elite.pop_back();
    }
    void run(int rounds) {
        if(elite.empty())return;
        int baseline=int(elite[0].used.size());
        vector<int> optional;for(int v=0;v<n;++v)if(!required[v]&&!original[v])optional.push_back(v);
        vector<unsigned char> allowed(n),owned(n),in_current(n);
        for(int sample=0;sample<rounds;sample++){
            size_t chosen=sample%4 ? rng()%min<size_t>(4,elite.size()):rng()%elite.size();
            Witness w=elite[chosen];
            fill(owned.begin(),owned.end(),0);for(int v:w.used)owned[v]=1;
            vector<int> frequency(n),fee(n);
            for(auto &other:elite)for(int v:other.used)++frequency[v];
            for(int v=0;v<n;v++){
                allowed[v]=1;
                fee[v]=(owned[v]?1:11+int(rng()%5)) + (sample%3?0:int(elite.size())-frequency[v]);
            }
            if(sample%3==2 && elite.size()>1){
                auto &mate=elite[rng()%elite.size()];
                for(int v:mate.used)fee[v]=2;
            }
            auto refresh=[&](){
                fill(in_current.begin(),in_current.end(),0);
                for(int v:w.used)in_current[v]=1;
            };
            refresh();
            vector<int> sequence=optional;vector<pair<int,int>> priority;
            int perturb=15+int(rng()%42);
            for(int v:sequence){
                int p=int(rng()%1000);
                if(owned[v] && rng()%100<unsigned(perturb))p-=1250;
                if(sample%2==1)p+=frequency[v]*11;
                priority.emplace_back(p,v);
            }
            sort(priority.begin(),priority.end());
            for(auto [_,v]:priority){
                allowed[v]=0;
                if(!in_current[v])continue;
                auto replacement=find(allowed,fee);
                if(replacement.route.empty()){allowed[v]=1;continue;}
                w=move(replacement);refresh();
                if(int(w.used.size())<=baseline+4)remember(w);
            }
            remember(move(w));
        }
    }
};
int main(int argc,char** argv) {
    ios::sync_with_stdio(false);cin.tie(nullptr);
    int n,m,ns,nt,nd;unsigned seed;
    if(!(cin>>n>>m>>ns>>nt>>nd>>seed))return 2;
    Search s(n,seed);
    for(int i=0,v;i<ns;i++){cin>>v;s.seeds.push_back(v);s.original[v]=1;}
    for(int i=0,v;i<nt;i++){cin>>v;if(!s.required[v])s.goals.push_back(v);s.required[v]=1;}
    for(int i=0;i<m;i++){Edge e;cin>>e.out>>e.a>>e.b;s.add(e);}
    for(int i=0;i<nd;i++){
        int k;cin>>k;vector<int> parent(n,-1);
        for(int v:s.seeds)parent[v]=-2;
        for(int j=0,id;j<k;j++){cin>>id;parent[s.edges[id].out]=id;}
        s.remember(s.trace(parent));
    }
    s.run(argc>1?stoi(argv[1]):65);
    cout<<s.elite.size()<<'\n';
    for(auto &w:s.elite){cout<<w.used.size();for(int v:w.used)cout<<' '<<w.route[v];cout<<'\n';}
}
