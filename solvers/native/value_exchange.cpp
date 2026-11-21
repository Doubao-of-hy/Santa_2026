// Evaluate one-in, two-out exchanges on the entire arithmetic value set.
// Each bit is a different banned old value. A feasible two-deletion pair must
// be feasible in both corresponding single-deletion lanes.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <queue>
#include <random>
#include <unordered_map>
#include <unordered_set>
#include <vector>
using namespace std;
using I=long long;
using U=uint64_t;
struct Op {I v,a,b;char op;};
struct Edge {int v,a,b;char op;};
template<class F>void arithmetic(I a,I b,I cap,F f){
    if(a<=cap-b)f(Op{a+b,a,b,'+'});
    if(a>b)f(Op{a-b,a,b,'-'});
    if(b>a)f(Op{b-a,b,a,'-'});
    if(a<=cap/b)f(Op{a*b,a,b,'*'});
    if(a>=b && a%b==0)f(Op{a/b,a,b,'/'});
    if(b>a&&b%a==0)f(Op{b/a,b,a,'/'});
}
template<class F>void inverse(I t,I a,I cap,F f){
    if(t>a)f(t-a,Op{t,t-a,a,'+'});
    if(a>t)f(a-t,Op{t,a,a-t,'-'});
    if(t<=cap-a)f(t+a,Op{t,t+a,a,'-'});
    if(t%a==0)f(t/a,Op{t,t/a,a,'*'});
    if(t<=cap/a)f(t*a,Op{t,t*a,a,'/'});
    if(a%t==0)f(a/t,Op{t,a,a/t,'/'});
}
struct Extra {I value;vector<Edge> birth,use;};
struct Batch {vector<int> banned;U live;vector<U> reach,allowed;};
struct Candidate {int gain;int id;vector<int> removed;};
struct Probe {long long score; int which,ban;};
struct Search {
    I cap;
    vector<I> seeds,goals,values;
    vector<Op> original;
    unordered_map<I,int> lookup;
    vector<vector<int>> use;
    vector<Edge> base;
    vector<int> goalids,seedids,optional;
    vector<Extra> extras;
    vector<Batch> batches;
    unordered_map<I,int> idx;
    int n;
    vector<vector<Op>> winners;
    vector<vector<Op>> neighbors;
    int singles=0,pairs=0,eligible=0,probes=0;
    int at(I v){auto [it,ok]=lookup.emplace(v,values.size());if(ok)values.push_back(v);return it->second;}
    int external(I v){
        auto [it,ok]=idx.emplace(v,extras.size());if(ok)extras.push_back({v,{},{}});
        return it->second;
    }
    void populate(bool includeExtras=true){
        for(I v:seeds)seedids.push_back(at(v));
        for(auto e:original)at(e.v);
        for(I v:goals)goalids.push_back(at(v));
        n=values.size();use.resize(n);
        vector<bool> forced(n,false);for(int v:goalids)forced[v]=true;for(int v:seedids)forced[v]=true;
        for(int v=0;v<n;v++)if(!forced[v])optional.push_back(v);
        // A newly purchased value is useful only if at least one old value
        // can consume it. This numerical inverse also finds helpers far beyond
        // the small-domain search and does not require a preset palette.
        if(includeExtras)for(int t=0;t<n;t++)if(find(seedids.begin(),seedids.end(),t)==seedids.end()){
            for(int a=0;a<n;a++)if(a!=t)inverse(values[t],values[a],cap,[&](I h,Op e){
                if(lookup.count(h))return;
                auto &c=extras[external(h)];
                int l=e.a==h?n:a,r=e.b==h?n:a;
                c.use.push_back({t,l,r,e.op});
            });
            if(values[t]%2==0){
                I h=values[t]/2;if(!lookup.count(h))extras[external(h)].use.push_back({t,n,n,'+'});
            }
            I h=(I)sqrt((long double)values[t]);
            while(h+1<=values[t]/(h+1))h++;while(h>values[t]/h)h--;
            if(h*h==values[t]&&!lookup.count(h))extras[external(h)].use.push_back({t,n,n,'*'});
        }
        for(int a=0;a<n;a++)for(int b=0;b<=a;b++)arithmetic(values[a],values[b],cap,[&](Op e){
            if(e.v==e.a||e.v==e.b)return;
            int l=e.a==values[a]?a:b,r=e.b==values[b]?b:a;
            auto it=lookup.find(e.v);
            if(it!=lookup.end()){
                int i=base.size(),v=it->second;base.push_back({v,l,r,e.op});
                use[l].push_back(i);if(l!=r)use[r].push_back(i);
            }else if(includeExtras){
                auto candidate=idx.find(e.v);if(candidate!=idx.end())extras[candidate->second].birth.push_back({n,l,r,e.op});
            }
        });
        for(int i=0;i<(int)optional.size();i+=64){
            Batch b;b.banned.assign(optional.begin()+i,optional.begin()+min(i+64,(int)optional.size()));
            b.live=b.banned.size()==64?~U(0):(U(1)<<b.banned.size())-1;
            b.reach.assign(n,0);b.allowed.assign(n,b.live);
            for(size_t j=0;j<b.banned.size();j++)b.allowed[b.banned[j]]^=U(1)<<j;
            for(int s:seedids)b.reach[s]=b.live;
            bool change=true;
            while(change){change=false;for(const auto& e:base){
                U mask=b.reach[e.a]&b.reach[e.b]&b.allowed[e.v]&~b.reach[e.v];
                if(mask){b.reach[e.v]|=mask;change=true;}
            }}
            batches.push_back(move(b));
        }
    }
    U helped(const Batch& batch,const Extra* extra,int& partial,bool granted=false,vector<U>* reachedGoals=nullptr)const{
        U all=batch.live;
        for(int t:goalids)all&=batch.reach[t];
        if(reachedGoals){reachedGoals->clear();for(int t:goalids)reachedGoals->push_back(batch.reach[t]);}
        if(!extra)return all;
        U h=granted?batch.live:0;if(!granted)for(auto&e:extra->birth)h|=batch.reach[e.a]&batch.reach[e.b];
        h&=~all;if(!h)return all;
        bool engaged=false;
        for(const auto&e:extra->use){
            U v=h&batch.allowed[e.v]&~batch.reach[e.v];
            if(e.a!=n)v&=batch.reach[e.a];if(e.b!=n)v&=batch.reach[e.b];
            if(v){engaged=true;break;}
        }
        if(!engaged)return all;
        vector<U> reach=batch.reach;
        vector<int> todo;
        auto change=[&](const Edge&e,U mask){
            U got=mask&batch.allowed[e.v]&~reach[e.v];
            if(got){reach[e.v]|=got;todo.push_back(e.v);partial+=__builtin_popcountll(got);}
        };
        for(;;){
            for(auto&e:extra->use)change(e,h&(e.a==n?h:reach[e.a])&(e.b==n?h:reach[e.b]));
            if(todo.empty())break;
            while(!todo.empty()){
                int v=todo.back();todo.pop_back();
                for(int i:use[v]){auto &e=base[i];change(e,reach[e.a]&reach[e.b]);}
            }
        }
        if(reachedGoals){reachedGoals->clear();for(int t:goalids)reachedGoals->push_back(reach[t]);}
        all=batch.live;for(int t:goalids)all&=reach[t];return all;
    }
    vector<Op> witness(const Extra*extra,const vector<int>& bans,int forcedRecipient=-1){
        vector<char> enabled(n+1,1),known(n+1,0);
        for(int b:bans)enabled[b]=0;
        for(int s:seedids)known[s]=1;
        vector<Edge> recipe(n+1,{-1,-1,-1,0});vector<int> sequence;
        auto accept=[&](const Edge&e){
            if(enabled[e.v]&&!known[e.v]&&known[e.a]&&known[e.b]){
                recipe[e.v]=e;known[e.v]=1;sequence.push_back(e.v);
            }
        };
        size_t last;
        do{
            last=sequence.size();
            if(extra){for(auto&e:extra->birth)accept(e);for(auto&e:extra->use)accept(e);}
            for(auto&e:base)if(e.v!=forcedRecipient)accept(e);
        }while(last!=sequence.size());
        for(int t:goalids)if(!known[t])return {};
        vector<char> need(n+1,0);for(int t:goalids)need[t]=1;
        for(auto it=sequence.rbegin();it!=sequence.rend();++it)if(need[*it]){
            auto&e=recipe[*it];need[e.a]=need[e.b]=1;
        }
        vector<Op> result;
        auto val=[&](int x){return x==n?extra->value:values[x];};
        for(int x:sequence)if(need[x]){auto&e=recipe[x];result.push_back({val(x),val(e.a),val(e.b),e.op});}
        return result;
    }
    void record(vector<Op> pg){
        if(pg.empty()||pg.size()>=original.size())return;
        winners.push_back(move(pg));
        stable_sort(winners.begin(),winners.end(),[](auto&a,auto&b){return a.size()<b.size();});
        if(winners.size()>4)winners.pop_back();
    }
    void run(int maxTests,int maxPairs,int look=0,unsigned randomSeed=0,bool neutralOnly=false,bool forcedFunding=false){
        populate();
        auto removable=[&](const Extra*c,int& partial){
            vector<int> list;
            for(auto &batch:batches){
                U bits=helped(batch,c,partial);
                while(bits){int j=__builtin_ctzll(bits);bits&=bits-1;list.push_back(batch.banned[j]);}
            }
            return list;
        };
        int ignored=0;auto free=removable(nullptr,ignored);
        for(int v:free)record(witness(nullptr,{v}));
        // If the starting set was not deletion-minimal, individual witnesses
        // are still valid. Penalize these already-removable vertices in ranking.
        unordered_set<int> unchanged(free.begin(),free.end());
        vector<Candidate> offers;
        vector<Probe> even,funded;
        for(size_t j=0;j<extras.size();j++){
            auto &c=extras[j];if(c.birth.empty())continue;
            ++eligible;int partial=0;auto xs=removable(&c,partial);
            int changed=0;for(int x:xs)changed+=!unchanged.count(x);
            if(look && (partial || changed)){
                int merit=partial+int(min<size_t>(c.birth.size(),25))+2*int(min<size_t>(c.use.size(),25));
                if(changed){
                    for(int x:xs)if(!unchanged.count(x))even.push_back({merit,(int)j,x});
                }
                funded.push_back({merit,(int)j,-1});
            }
            if(xs.size()<2)continue;
            if(changed)offers.push_back({5*changed+int(xs.size()),(int)j,move(xs)});
        }
        singles=offers.size();
        stable_sort(offers.begin(),offers.end(),[&](const Candidate&a,const Candidate&b){
            return a.gain!=b.gain?a.gain>b.gain:extras[a.id].value<extras[b.id].value;
        });
        for(auto &offer:offers){
            if(++probes>maxTests)break;
            auto&candidate=extras[offer.id];auto&xs=offer.removed;
            stable_sort(xs.begin(),xs.end(),[&](int a,int b){return unchanged.count(a)<unchanged.count(b);});
            int tested=0;
            for(size_t i=0;i<xs.size()&&tested<maxPairs;i++)for(size_t j=0;j<i&&tested<maxPairs;j++){
                if(unchanged.count(xs[j])&&unchanged.count(xs[i]))continue;
                ++tested;++pairs;
                auto pg=witness(&candidate,{xs[j],xs[i]});
                if(pg.empty())continue;
                auto bans=vector<int>{xs[j],xs[i]};
                for(int x:xs)if(x!=xs[j]&&x!=xs[i]){
                    bans.push_back(x);auto next=witness(&candidate,bans);
                    if(next.empty())bans.pop_back();else pg=move(next);
                }
                record(move(pg));tested=maxPairs;
            }
        }
        if(!look)return;
        if(randomSeed){
            mt19937 rng(randomSeed);
            for(auto& p:even)p.score=4*min(p.score,200LL)+int(rng()%1800);
            for(auto& p:funded)p.score=4*min(p.score,200LL)+int(rng()%1800);
        }
        auto order=[](const Probe&a,const Probe&b){return a.score!=b.score?a.score>b.score:a.which<b.which;};
        sort(even.begin(),even.end(),order);sort(funded.begin(),funded.end(),order);
        unordered_set<int> added,removed;
        const int neutralQuota=neutralOnly?look:(forcedFunding?look/2:look*2/3+1);
        for(auto p:even){
            if(int(neighbors.size())>=neutralQuota)break;
            if(added.count(p.which)||removed.count(p.ban))continue;
            auto pg=witness(&extras[p.which],{p.ban});
            if(pg.size()!=original.size())continue;
            neighbors.push_back(move(pg));added.insert(p.which);removed.insert(p.ban);
        }
        // Temporarily fund one additional intermediary. In the next pass it
        // can participate in operands for another intermediary before either
        // needs to pay for its own insertion with a deletion.
        if(neutralOnly)return;
        for(auto p:funded){
            if(int(neighbors.size())>=look)break;
            if(!added.insert(p.which).second)continue;
            auto &c=extras[p.which];
            if(forcedFunding){
                // Require an existing recipient to obtain a new, genuinely
                // active operand. Barring its other recipes preserves exact
                // rootedness while allowing a paid step during the walk.
                size_t shift=(randomSeed+p.which)%c.use.size();
                for(size_t j=0;j<c.use.size();j++){
                    int v=c.use[(j+shift)%c.use.size()].v;
                    auto trial=witness(&c,{},v);
                    if(trial.empty()||trial.size()>original.size()+1)continue;
                    if(none_of(trial.begin(),trial.end(),[&](Op e){return e.v==c.value;}))continue;
                    if(trial.size()<original.size())record(trial);
                    neighbors.push_back(move(trial));break;
                }
                continue;
            }
            auto g=original;
            auto e=c.birth.front();g.push_back({c.value,values[e.a],values[e.b],e.op});
            neighbors.push_back(move(g));
        }
    }
};
int main(int argc,char**argv){
    ios::sync_with_stdio(false);cin.tie(nullptr);
    string id;int ns,nt,nr;
    while(cin>>id){
        Search s;cin>>s.cap>>ns>>nt>>nr;s.seeds.resize(ns);s.goals.resize(nt);
        for(I&v:s.seeds)cin>>v;for(I&v:s.goals)cin>>v;
        for(int i=0;i<nr;i++){Op e;cin>>e.v>>e.op>>e.a>>e.b;s.original.push_back(e);}
        int tests=argc>1?stoi(argv[1]):72,pairs=argc>2?stoi(argv[2]):40,look=argc>3?stoi(argv[3]):0;
        s.run(tests,pairs,look);
        for(auto &snapshot:s.neighbors){
            Search child;child.cap=s.cap;child.seeds=s.seeds;child.goals=s.goals;
            child.original=move(snapshot);child.run(tests,pairs,0);
            s.eligible+=child.eligible;s.singles+=child.singles;s.pairs+=child.pairs;
            for(auto &pg:child.winners)s.record(move(pg));
        }
        cout<<id<<' '<<s.eligible<<' '<<s.singles<<' '<<s.pairs<<' '<<s.winners.size()<<'\n';
        for(auto &pg:s.winners){cout<<pg.size()<<'\n';for(auto&e:pg)cout<<e.v<<' '<<e.op<<' '<<e.a<<' '<<e.b<<'\n';}
    }
    return 0;
}
