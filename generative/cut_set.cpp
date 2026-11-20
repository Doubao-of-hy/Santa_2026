// Find small reachable sets of intermediate values in windows of a donor graph.
// Input and witnesses use the same bank format as shrink_select.py.
#include <algorithm>
#include <cstdint>
#include <iostream>
#include <limits>
#include <map>
#include <numeric>
#include <random>
#include <set>
#include <unordered_set>
#include <vector>
using namespace std;
struct Edge{int dst,a,b;};
struct Proposal{int a,b;};
struct Case{vector<int> holes;double priority;};

struct Solver{
    int n,limit,visits=0,maxVisits,maxWindow=23;
    vector<Edge> edges;
    vector<int> seeds,targets,base,root,freeTag,paidTag,doneTag,recipe,cutTag;
    vector<vector<int>> ways,uses;
    vector<unsigned char> isSeed,forbid;
    vector<int> floor,chosen,answer;
    vector<vector<int>> elites;
    mt19937 rng;
    int tick=0,cutTick=0;
    set<vector<int>> visited;
    Solver(int n,unsigned seed):n(n),base(n,-1),freeTag(n),paidTag(n),doneTag(n),recipe(n),cutTag(n),
        ways(n),uses(n),isSeed(n),forbid(n),floor(n),rng(seed){}
    void add(int d,int a,int b){
        int id=edges.size();edges.push_back({d,a,b});ways[d].push_back(id);
    }
    vector<int> trace(const vector<int>& parent) const{
        vector<unsigned char> color(n);vector<int> out;
        auto visit=[&](auto&& self,int x)->bool{
            if(isSeed[x]||color[x]==2)return true;
            if(color[x]==1||parent[x]<0)return false;
            color[x]=1;auto e=edges[parent[x]];
            if(!self(self,e.a)||!self(self,e.b))return false;
            out.push_back(parent[x]);color[x]=2;return true;
        };
        for(int t:targets)if(!visit(visit,t))return {};
        return out;
    }
    vector<Proposal> entries(int start,int tag,int remaining){
        // Every rootable superset must enter the cut using an edge from outside.
        // Close the cut under already enabled rules until entering always costs
        // at least one extra operand. Either unresolved operand is a valid blocker.
        int stamp=++cutTick;
        vector<int> part{start};cutTag[start]=stamp;
        for(size_t i=0;i<part.size();++i)for(int id:ways[part[i]]){
            auto e=edges[id];
            if(cutTag[e.a]==stamp||cutTag[e.b]==stamp || forbid[e.a]||forbid[e.b])continue;
            if(!freeTag[e.a] && paidTag[e.a]!=tag)continue;
            if(!freeTag[e.b] && paidTag[e.b]!=tag)continue;
            int x=(!freeTag[e.a]&&doneTag[e.a]!=tag)?e.a:e.b;
            if(!freeTag[e.b] && doneTag[e.b]!=tag && ways[e.b].size()<ways[x].size())x=e.b;
            cutTag[x]=stamp;part.push_back(x);
        }
        vector<Proposal> options;
        set<pair<int,int>> seen;
        for(int x:part)for(int id:ways[x]){
            auto e=edges[id];
            if(cutTag[e.a]==stamp||cutTag[e.b]==stamp||forbid[e.a]||forbid[e.b])continue;
            if(floor[e.a]>limit||floor[e.b]>limit)continue;
            int a=(!freeTag[e.a]&&paidTag[e.a]!=tag)?e.a:-1;
            int b=(!freeTag[e.b]&&paidTag[e.b]!=tag)?e.b:-1;
            if(a<0)swap(a,b);
            if(a==b)b=-1;
            if(a<0)continue;
            if(b>=0&&remaining<2)continue;
            if(b>=0&&b<a)swap(a,b);
            if(seen.emplace(a,b).second)options.push_back({a,b});
        }
        options.erase(remove_if(options.begin(),options.end(),[&](auto p){
            return p.b>=0 && (seen.count({p.a,-1})||seen.count({p.b,-1}));
        }),options.end());
        return options;
    }
    bool dfs(){
        if(++visits>maxVisits)return false;
        int tag=++tick;
        for(int x:chosen)paidTag[x]=tag;
        vector<int> key=chosen;sort(key.begin(),key.end());
        if(!visited.insert(move(key)).second)return false;
        bool changed=true;
        while(changed){
            changed=false;
            for(int x:chosen)if(doneTag[x]!=tag){
                for(int id:ways[x]){
                    auto e=edges[id];
                    if((freeTag[e.a]||doneTag[e.a]==tag)&&(freeTag[e.b]||doneTag[e.b]==tag)){
                        recipe[x]=id;doneTag[x]=tag;changed=true;break;
                    }
                }
            }
        }
        if(all_of(root.begin(),root.end(),[&](int x){return freeTag[x]||doneTag[x]==tag;})){
            auto candidate=base;
            for(int x:chosen)if(doneTag[x]==tag)candidate[x]=recipe[x];
            answer=trace(candidate);return !answer.empty();
        }
        int remaining=limit-int(chosen.size());
        if(remaining<=0)return false;
        vector<Proposal> best;
        vector<int> ask;
        for(int x:chosen)if(doneTag[x]!=tag)ask.push_back(x);
        stable_sort(ask.begin(),ask.end(),[&](int a,int b){return ways[a].size()<ways[b].size();});
        for(int x:ask){
            auto opts=entries(x,tag,remaining);
            if(opts.empty())return false;
            if(best.empty()||opts.size()<best.size())best=move(opts);
            if(best.size()==1)break;
        }
        auto rank=[&](int x){return x<0?0:floor[x]*5-int(base[x]>=0)*3;};
        stable_sort(best.begin(),best.end(),[&](auto a,auto b){
            return int(a.b>=0)*10+rank(a.a)+rank(a.b)<int(b.b>=0)*10+rank(b.a)+rank(b.b);
        });
        for(auto p:best){
            chosen.push_back(p.a);if(p.b>=0)chosen.push_back(p.b);
            if(dfs())return true;
            if(p.b>=0)chosen.pop_back();chosen.pop_back();
            if(visits>=maxVisits)break;
        }
        return false;
    }
    bool test(const vector<int>& holes,const vector<int>& initial){
        vector<unsigned char> boundary(n),kept(n),require(n);
        for(int h:holes)boundary[h]=1;
        auto keep=[&](auto&& self,int x)->void{
            if(isSeed[x]||kept[x])return;
            if(boundary[x]){require[x]=1;return;}
            kept[x]=1;auto e=edges[base[x]];self(self,e.a);self(self,e.b);
        };
        for(int t:targets)keep(keep,t);
        root.clear();for(int x:holes)if(require[x])root.push_back(x);
        if(root.empty())return false;
        fill(freeTag.begin(),freeTag.end(),0);fill(forbid.begin(),forbid.end(),0);
        for(int s:seeds)freeTag[s]=1;
        int fixed=0;
        for(int id:initial){
            auto e=edges[id];if(!kept[e.dst])continue;
            ++fixed;
            if(freeTag[e.a]&&freeTag[e.b])freeTag[e.dst]=1;else forbid[e.dst]=1;
        }
        limit=int(initial.size())-fixed-1;
        if(limit<int(root.size())||limit>maxWindow)return false;
        // Longest prerequisite-chain length is a lower bound on extra values.
        fill(floor.begin(),floor.end(),10000);
        for(int i=0;i<n;i++)if(freeTag[i])floor[i]=0;
        bool changed=true;
        while(changed){
            changed=false;
            for(auto e:edges){
                if(forbid[e.dst])continue;
                int k=1+max(floor[e.a],floor[e.b]);
                if(k<floor[e.dst] && k<=limit){floor[e.dst]=k;changed=true;}
            }
        }
        for(int t:root)if(floor[t]>limit)return false;
        visited.clear();chosen=root;answer.clear();visits=0;
        if(!dfs()||answer.size()>=initial.size())return false;
        for(int id:answer)base[edges[id].dst]=id;
        elites.push_back(answer);return true;
    }
    void run(int rounds){
        for(int pass=0;pass<3;pass++){
            auto initial=trace(base);if(initial.empty())return;
            for(auto &x:uses)x.clear();
            for(int id:initial){auto e=edges[id];uses[e.a].push_back(e.dst);if(e.a!=e.b)uses[e.b].push_back(e.dst);}
            vector<Case> cases;set<vector<int>> seen;
            auto push=[&](vector<int> v,double priority){
                sort(v.begin(),v.end());v.erase(unique(v.begin(),v.end()),v.end());
                if(!v.empty() && seen.insert(v).second)cases.push_back({move(v),priority+double(rng()%1000)/1000.});
            };
            if(n<=24)push(targets,100);
            for(int t:targets)push({t},4);
            // Two unrelated outputs may both be cheaper once the same new
            // intermediate has been paid for. Pair them before random windows.
            vector<char> live(n);
            for(int id:initial)live[edges[id].dst]=1;
            vector<vector<int>> consumers(n);
            for(int id:initial){
                int out=edges[id].dst;
                set<int> helpers;
                auto add=[&](int x){if(!live[x]&&!isSeed[x])helpers.insert(x);};
                for(int way:ways[out]){
                    auto e=edges[way];
                    for(int x:{e.a,e.b})if(!live[x]&&!isSeed[x]){
                        add(x);
                        for(int child:ways[x]){
                            add(edges[child].a);add(edges[child].b);
                        }
                    }
                }
                for(int x:helpers)consumers[x].push_back(out);
            }
            map<pair<int,int>,int> votes;
            for(auto& xs:consumers)if(xs.size()>=2 && xs.size()<=6){
                for(size_t i=1;i<xs.size();i++)for(size_t j=0;j<i;j++)
                    votes[minmax(xs[i],xs[j])]+=8-xs.size();
            }
            vector<pair<int,pair<int,int>>> ranked;
            for(auto& [pair,count]:votes)ranked.emplace_back(count,pair);
            sort(ranked.rbegin(),ranked.rend());
            for(int i=0;i<min(int(ranked.size()),rounds/3);i++){
                auto [a,b]=ranked[i].second;push({a,b},5+.02*min(16,ranked[i].first));
            }
            for(int id:initial){
                auto e=edges[id];push({e.dst},1.5+min(2,int(ways[e.dst].size())/4)*.33);
                if(uses[e.dst].size()>=2 && uses[e.dst].size()<=5){
                    push(uses[e.dst],4.5);
                    vector<int> deeper;
                    for(int u:uses[e.dst]){
                        if(uses[u].size()==1)deeper.push_back(uses[u][0]);else deeper.push_back(u);
                    }
                    push(deeper,4);
                }
            }
            for(size_t i=1;i<targets.size();i++){
                int j=int(rng()%i);push({targets[i],targets[j]},2.8);
            }
            sort(cases.begin(),cases.end(),[](const Case&a,const Case&b){return a.priority>b.priority;});
            bool changed=false;int tried=0;
            for(auto c:cases){
                if(tried++>=rounds)break;
                if(test(c.holes,initial)){changed=true;break;}
            }
            if(!changed)return;
        }
    }
};
int main(int argc,char**argv){
    ios::sync_with_stdio(false);cin.tie(nullptr);
    int n,m,ns,nt,nd;unsigned seed;if(!(cin>>n>>m>>ns>>nt>>nd>>seed))return 2;
    Solver s(n,seed);s.maxVisits=700;
    for(int i=0,x;i<ns;i++){cin>>x;s.seeds.push_back(x);s.isSeed[x]=1;}
    for(int i=0,x;i<nt;i++){cin>>x;if(!s.isSeed[x])s.targets.push_back(x);}
    for(int i=0,d,a,b;i<m;i++){cin>>d>>a>>b;s.add(d,a,b);}
    for(int i=0;i<nd;i++){
        int k;cin>>k;for(int j=0,id;j<k;j++){cin>>id;if(i==0)s.base[s.edges[id].dst]=id;}
    }
    if(argc>2 && string(argv[2])=="--whole"){
        s.maxVisits=argc>3?stoi(argv[3]):10000000;
        if(argc>4)s.maxWindow=stoi(argv[4]);
        while(s.test(s.targets,s.trace(s.base))){}
    }else s.run(argc>1?stoi(argv[1]):95);
    cout<<s.elites.size()<<'\n';
    for(auto &sol:s.elites){cout<<sol.size();for(int id:sol)cout<<' '<<id;cout<<'\n';}
    return 0;
}
