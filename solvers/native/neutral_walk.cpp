// Explore both sides of neutral arithmetic substitutions before selecting
// improvements. Value sets identify distinct states of the implicit graph.
#define main value_exchange_entry
#include "value_exchange.cpp"
#undef main
#include <set>

using Tape=vector<Op>;
#ifdef WALK_FORCED
constexpr bool activeFunding=true;
#else
constexpr bool activeFunding=false;
#endif
#ifdef WALK_CROSSOVER
#include "neutral_crossover.hpp"
#endif
struct State {Tape tape;vector<I> key;int salt;};
vector<I> signature(const Tape& tape){
    vector<I> values;values.reserve(tape.size());
    for(auto e:tape)values.push_back(e.v);sort(values.begin(),values.end());return values;
}
int separated(const vector<I>& a,const vector<I>& b){
    size_t i=0,j=0;int shared=0;
    while(i<a.size()&&j<b.size()){
        if(a[i]<b[j])i++;else if(a[i]>b[j])j++;else{shared++;i++;j++;}
    }
    return int(a.size()+b.size())-2*shared;
}
int main(int argc,char**argv){
    ios::sync_with_stdio(false);cin.tie(nullptr);string id;int ns,nt,nop;
    const int depth=argc>1?stoi(argv[1]):6, width=argc>2?stoi(argv[2]):4, fanout=argc>3?stoi(argv[3]):6;
    while(cin>>id){
        I cap;cin>>cap>>ns>>nt>>nop;vector<I> seeds(ns),goals(nt);
        for(I& x:seeds)cin>>x;for(I& x:goals)cin>>x;
        Tape original(nop);for(auto& e:original)cin>>e.v>>e.op>>e.a>>e.b;
        unsigned seed=85071;for(char c:id)seed=seed*137+unsigned(c);
        mt19937 rng(seed);vector<I> first=signature(original);
        vector<State> beam{{original,first,0}};set<vector<I>> visited{first},printed;
        vector<Tape> winners;int expanded=0,distinct=1,uphill=0,low=nop;
        for(int d=0;d<depth&&!beam.empty();d++){
            vector<State> next;
            auto put=[&](Tape t){
                    if(t.empty())return;
                    auto key=signature(t);
                    if(int(t.size())<nop&&printed.insert(key).second){
                        winners.push_back(t);
                        stable_sort(winners.begin(),winners.end(),[](const Tape&a,const Tape&b){return a.size()<b.size();});
                        if(winners.size()>8)winners.pop_back();
                        low=min(low,int(t.size()));
                    }
                    if(int(t.size())>low+(activeFunding?2:1)||!visited.insert(key).second)return;
                    distinct++;next.push_back({move(t),move(key),int(rng()%45)});
            };
            for(auto& node:beam){
                Search s;s.cap=cap;s.seeds=seeds;s.goals=goals;s.original=move(node.tape);
                expanded++;uphill+=int(s.original.size())>low;
                s.run(56,36,fanout,rng(),d%3==1,activeFunding);
                for(auto& trial:s.winners)put(move(trial));
                for(auto& neighbor:s.neighbors)put(move(neighbor));
            }
#ifdef WALK_CROSSOVER
            // Select the most distinct equally competitive candidates. Each
            // parent belongs to the same puzzle and the same credited source.
            vector<tuple<int,int,int>> match;
            for(int j=1;j<int(next.size());j++)for(int i=0;i<j;i++){
                int distance=separated(next[i].key,next[j].key);
                if(distance<3)continue;
                int cost=int(next[i].tape.size()+next[j].tape.size())-2*low;
                int merit=24*min(distance,20)-26*cost+int(rng()%20);
                match.emplace_back(merit,i,j);
            }
            sort(match.rbegin(),match.rend());
            unordered_map<int,int> reused;int tried=0;
            for(auto [merit,i,j]:match){
                if(reused[i]>=2||reused[j]>=2)continue;
                reused[i]++;reused[j]++;SubsetBreeder breeder;
                put(breeder.run(seeds,goals,cap,next[i].tape,next[j].tape,rng));
                if(++tried==max(3,width))break;
            }
#endif
            beam.clear();
            while(!next.empty()&&int(beam.size())<width){
                int best=-1,score=-1000000;
                for(int i=0;i<int(next.size());i++){
                    const auto& node=next[i];if(int(node.tape.size())>low+(activeFunding?2:1))continue;
                    int spread=min(14,separated(node.key,first));
                    for(const auto& chosen:beam)spread=min(spread,separated(node.key,chosen.key));
                    int penalty=activeFunding?(d%3==2?21:40):60;
                    int merit=7*spread+node.salt-penalty*(int(node.tape.size())-low);
                    if(merit>score){score=merit;best=i;}
                }
                if(best<0)break;
                beam.push_back(move(next[best]));swap(next[best],next.back());next.pop_back();
            }
        }
        cout<<id<<' '<<expanded<<' '<<distinct<<' '<<uphill<<' '<<winners.size()<<'\n';
        for(auto& tape:winners){cout<<tape.size()<<'\n';for(auto e:tape)cout<<e.v<<' '<<e.op<<' '<<e.a<<' '<<e.b<<'\n';}
    }
}
