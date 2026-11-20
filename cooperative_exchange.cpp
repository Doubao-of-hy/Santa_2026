// Test simultaneous purchases of independently grounded integers. Single-ban
// reachability suggests complementary pairs; the final three bans are exact.
#define STAGED_LIBRARY
#include "staged_exchange.cpp"
#include <map>
struct Offer {int id,merit;vector<U> saved,active,profile;};
struct Cooperative : Staged {
    int offers=0,pairTrials=0;
    U active(const Batch& b,const Extra& e){
        U rooted=0;
        for(auto birth:e.birth)rooted|=b.reach[birth.a]&b.reach[birth.b];
        U gain=0;
        for(auto out:e.use){
            U available=b.allowed[out.v]&~b.reach[out.v];
            if(out.a!=n)available&=b.reach[out.a];if(out.b!=n)available&=b.reach[out.b];
            gain|=available;
        }
        return rooted&gain;
    }
    vector<Edge> joint(const Extra& a,const Extra& b){
        vector<Edge> out=a.birth;out.insert(out.end(),a.use.begin(),a.use.end());
        for(auto e:b.birth){e.v=n+1;out.push_back(e);}
        for(auto e:b.use){if(e.a==n)e.a++;if(e.b==n)e.b++;out.push_back(e);}
        arithmetic(a.value,b.value,cap,[&](Op e){
            auto it=lookup.find(e.v);if(it!=lookup.end())out.push_back({it->second,e.a==a.value?n:n+1,e.b==a.value?n:n+1,e.op});
        });
        auto bridge=[&](I src,int source,I dest,int target){
            for(int i=0;i<n;i++)arithmetic(src,values[i],cap,[&](Op e){
                if(e.v==dest)out.push_back({target,e.a==src?source:i,e.b==src?source:i,e.op});
            });
            arithmetic(src,src,cap,[&](Op e){if(e.v==dest)out.push_back({target,source,source,e.op});});
        };
        bridge(a.value,n,b.value,n+1);bridge(b.value,n+1,a.value,n);return out;
    }
    vector<int> singles2(const vector<Edge>& additional){
        vector<int> available;
        for(const auto& batch:batches){
            vector<U> have=batch.reach,allow=batch.allowed;
            have.resize(n+2);allow.resize(n+2,batch.live);
            U changed;
            auto propagate=[&](const vector<Edge>& edges){
                for(auto e:edges){U got=allow[e.v]&have[e.a]&have[e.b]&~have[e.v];changed|=got;have[e.v]|=got;}
            };
            do{changed=0;propagate(additional);propagate(base);}while(changed);
            U all=batch.live;for(int t:goalids)all&=have[t];
            while(all){int k=__builtin_ctzll(all);all&=all-1;available.push_back(batch.banned[k]);}
        }
        return available;
    }
    void runPair(int maxOffers,int maxPairs,int triples,unsigned seed){
        populate();vector<Offer> raw;vector<U> baseline;int dummy=0;
        for(auto& b:batches)baseline.push_back(helped(b,nullptr,dummy));
        mt19937 rng(seed);
        for(int id=0;id<int(extras.size());id++){
            auto& e=extras[id];if(e.birth.empty())continue;
            Offer offer{id,0,{},{},{}};int partial=0,count=0,actCount=0;
            for(int j=0;j<int(batches.size());j++){
                U mask=active(batches[j],e)&~baseline[j];
                offer.active.push_back(mask);actCount+=__builtin_popcountll(mask);
                U solved=mask?helped(batches[j],&e,partial)&~baseline[j]:0;
                count+=__builtin_popcountll(solved);offer.saved.push_back(solved);
            }
#ifdef COOPERATIVE_PARTIAL
            if(!count&&(actCount<2||partial<3))continue;
#else
            if(!count)continue;
#endif
            offer.merit=70*count+min(actCount,24)+min(partial,60)/4+int(rng()%20);
            raw.push_back(move(offer));
        }
        offers=raw.size();
        sort(raw.begin(),raw.end(),[](const Offer&a,const Offer&b){return a.merit>b.merit;});
        vector<Offer> menu;map<vector<U>,int> copies;
        int neutral=0;
        for(auto& o:raw){
#ifdef COOPERATIVE_PARTIAL
            bool full=any_of(o.saved.begin(),o.saved.end(),[](U x){return x!=0;});
            if(full&&neutral>=maxOffers/2)continue;
            vector<U> bucket=full?o.saved:o.active;bucket.push_back(full);
            if(copies[bucket]++>=(maxOffers/25+1))continue;
            neutral+=full;
            for(auto& b:batches){vector<U> goals;int cost=0;helped(b,&extras[o.id],cost,false,&goals);
                o.profile.insert(o.profile.end(),goals.begin(),goals.end());
            }
#else
            if(copies[o.saved]++>=(maxOffers/18+2))continue;
#endif
            menu.push_back(move(o));if(int(menu.size())>=maxOffers)break;
        }
        vector<tuple<int,int,int>> ordered;
        for(int a=1;a<int(menu.size());a++)for(int b=0;b<a;b++){
            int unique=0,common=0,potential=0,guaranteed=0;
            for(int i=0;i<int(batches.size());i++){
                auto sa=menu[a].saved[i],sb=menu[b].saved[i];
                unique+=__builtin_popcountll(sa^sb);common+=__builtin_popcountll(sa&sb);
                potential+=__builtin_popcountll((menu[a].active[i]&menu[b].active[i])&~(sa|sb));
#ifdef COOPERATIVE_PARTIAL
                U cover=batches[i].live&~baseline[i];int offset=i*goalids.size();
                for(int g=0;g<int(goalids.size());g++)cover&=(menu[a].profile[offset+g]|menu[b].profile[offset+g]);
                guaranteed+=__builtin_popcountll(cover&~(sa|sb));
#endif
            }
            if((!unique&&!guaranteed)||unique+common+potential<3)continue;
            int merit=44*min(unique,5)+15*min(common,4)+18*min(potential,5)+int(rng()%22);
            merit+=85*min(5,guaranteed);
            ordered.emplace_back(merit,a,b);
        }
        sort(ordered.rbegin(),ordered.rend());
        for(auto [merit,i,j]:ordered){
            if(pairTrials>=maxPairs)break;pairTrials++;
            auto& a=extras[menu[i].id];auto& b=extras[menu[j].id];
            auto more=joint(a,b);auto valid=singles2(more);
            if(valid.size()<3)continue;
            assessEdges(more,valid,a.value,b.value,triples);
        }
    }
};
int main(int argc,char**argv){
    ios::sync_with_stdio(false);cin.tie(nullptr);string id;int ns,nt,nop;
    while(cin>>id){
        Cooperative s;cin>>s.cap>>ns>>nt>>nop;s.seeds.resize(ns);s.goals.resize(nt);
        for(auto&v:s.seeds)cin>>v;for(auto&v:s.goals)cin>>v;
        for(int i=0;i<nop;i++){Op e;cin>>e.v>>e.op>>e.a>>e.b;s.original.push_back(e);}
        unsigned seed=51983;for(char c:id)seed=seed*137+unsigned(c);
        s.runPair(argc>1?stoi(argv[1]):80,argc>2?stoi(argv[2]):260,argc>3?stoi(argv[3]):60,seed);
        cout<<id<<' '<<s.offers<<' '<<s.pairTrials<<' '<<s.lanes<<' '<<s.winners.size()<<'\n';
        for(auto& tape:s.winners){cout<<tape.size()<<'\n';for(auto e:tape)cout<<e.v<<' '<<e.op<<' '<<e.a<<' '<<e.b<<'\n';}
    }
}
