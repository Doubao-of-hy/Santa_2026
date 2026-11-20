// Reprice every value of two derivations. In each of 64 lanes forbid another
// optional value, retaining a ban exactly when all targets still ground.
#define main value_exchange_entry
#include "value_exchange.cpp"
#undef main
#include <set>
using Tape=vector<Op>;
struct DonorDelete : Search {
    struct Elite {int cost;vector<char> present;Tape tape;};
    vector<Elite> elite;set<vector<I>> seen;
    int achieved=0,tries=0,waves=0;
    void enter(Tape tape){
        vector<I> sig;vector<char> present(n);
        for(auto e:tape){sig.push_back(e.v);present[lookup.at(e.v)]=1;}
        sort(sig.begin(),sig.end());if(!seen.insert(sig).second)return;
        elite.push_back({int(tape.size()),move(present),move(tape)});
        stable_sort(elite.begin(),elite.end(),[](const Elite&a,const Elite&b){return a.cost<b.cost;});
        if(elite.size()>12)elite.pop_back();
    }
    U rooted(const vector<U>& allow){
        vector<U> have(n);for(int s:seedids)have[s]=~U(0);U changed;
        do{changed=0;for(const auto&e:base){
            U got=allow[e.v]&have[e.a]&have[e.b]&~have[e.v];
            changed|=got;have[e.v]|=got;
        }}while(changed);
        U all=~U(0);for(int t:goalids)all&=have[t];return all;
    }
    void population(const Tape& first,const Tape& donor,int cycles,unsigned seed,bool keepElite=false){
        original=first;unordered_set<I> added;
        for(auto e:first)added.insert(e.v);for(auto e:donor)if(added.insert(e.v).second)original.push_back(e);
        populate(false);enter(first);enter(donor);
        vector<int> choices;
        for(auto& b:batches){
            U ok=b.live;for(int g:goalids)ok&=b.reach[g];
            while(ok){int k=__builtin_ctzll(ok);ok&=ok-1;choices.push_back(b.banned[k]);}
        }
        if(choices.empty())return;
        vector<char> mainSet(n),donorSet(n);
        for(auto e:first)mainSet[lookup.at(e.v)]=1;
        for(auto e:donor)donorSet[lookup.at(e.v)]=1;
        mt19937 rng(seed);
        for(int pass=0;pass<cycles;pass++){
            vector<vector<int>> order(64);
            for(int lane=0;lane<64;lane++){
                const auto& guide=pass?elite[rng()%min<size_t>(6,elite.size())].present:(lane%8<6?mainSet:donorSet);
                vector<pair<int,int>> scores;
                int bias=(lane%8==7)?0:(lane%8==6?340:(pass?650+rng()%1100:700+rng()%1100));
                for(int v:choices){
                    int ranking=int(rng()%1000)+(guide[v]?0:bias);
                    // A few in-use nodes lead the wave. They can force the
                    // alternative derivation to reveal a compact route.
                    if(guide[v]&&rng()%max(8,3+int(choices.size())/(1+lane%5))==0)ranking+=2500;
                    scores.push_back({ranking,v});
                }
                sort(scores.rbegin(),scores.rend());
                for(auto s:scores)order[lane].push_back(s.second);
            }
            vector<U> allow(n,~U(0));
            for(int j=0;j<int(choices.size());j++){
                for(int lane=0;lane<64;lane++)allow[order[lane][j]]&=~(U(1)<<lane);
                U failure=~rooted(allow);
                while(failure){int lane=__builtin_ctzll(failure);failure&=failure-1;allow[order[lane][j]]|=U(1)<<lane;}
            }
            vector<pair<int,int>> ranking;
            for(int lane=0;lane<64;lane++){
                int cost=original.size();for(int v:choices)cost-=!(allow[v]&(U(1)<<lane));ranking.push_back({cost,lane});
            }
            sort(ranking.begin(),ranking.end());
            for(auto [cost,lane]:ranking){
                if(cost>elite.front().cost+2&&elite.size()>=8)break;
                vector<int> banned;for(int v:choices)if(!(allow[v]&(U(1)<<lane)))banned.push_back(v);
                auto tape=witness(nullptr,banned);if(tape.empty())throw runtime_error("failed to reconstruct donor union");
                enter(move(tape));
            }
            waves++;tries+=64*choices.size();
        }
        for(auto& e:elite)if(e.tape.size()<first.size()){
            achieved++;if(keepElite)winners.push_back(e.tape);else winners.push_back(move(e.tape));
        }
    }
};
#ifndef DONOR_DELETE_LIBRARY
int main(int argc,char**argv){
    ios::sync_with_stdio(false);cin.tie(nullptr);string id;int ns,nt,n1,n2;
    while(cin>>id){
        DonorDelete s;cin>>s.cap>>ns>>nt>>n1>>n2;s.seeds.resize(ns);s.goals.resize(nt);
        for(I&v:s.seeds)cin>>v;for(I&v:s.goals)cin>>v;
        Tape a(n1),b(n2);for(auto t:{&a,&b})for(auto&e:*t)cin>>e.v>>e.op>>e.a>>e.b;
        unsigned seed=72923;for(char c:id)seed=seed*137+unsigned(c);
        s.population(a,b,argc>1?stoi(argv[1]):6,seed);
        cout<<id<<' '<<s.waves<<' '<<s.tries<<' '<<s.achieved<<' '<<s.winners.size()<<'\n';
        for(auto& tape:s.winners){cout<<tape.size()<<'\n';for(auto&e:tape)cout<<e.v<<' '<<e.op<<' '<<e.a<<' '<<e.b<<'\n';}
    }
}
#endif
