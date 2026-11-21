// A donor exchange can be neutral or temporarily more expensive. Continue
// searching the resulting hybrid graph with entirely new arithmetic values.
#define DONOR_DELETE_LIBRARY
#include "donor_delete.cpp"
struct Hybrid {Tape tape;vector<I> vals;int priority;};
int main(int argc,char**argv){
    ios::sync_with_stdio(false);cin.tie(nullptr);string id;int ns,nt,n1,n2;
    int cycles=argc>1?stoi(argv[1]):6,depth=argc>2?stoi(argv[2]):4,width=argc>3?stoi(argv[3]):3;
    while(cin>>id){
        DonorDelete s;cin>>s.cap>>ns>>nt>>n1>>n2;s.seeds.resize(ns);s.goals.resize(nt);Tape a(n1),b(n2);
        for(auto&v:s.seeds)cin>>v;for(auto&v:s.goals)cin>>v;
        for(auto t:{&a,&b})for(auto&e:*t)cin>>e.v>>e.op>>e.a>>e.b;
        unsigned seed=79193;for(char c:id)seed=seed*137+unsigned(c);mt19937 rng(seed);
        s.population(a,b,cycles,seed,true);
        unordered_set<I> first,other;for(auto e:a)first.insert(e.v);for(auto e:b)if(!first.count(e.v))other.insert(e.v);
        vector<Hybrid> states;set<vector<I>> visited;
        vector<Tape> winners=s.winners;int low=n1,seedCount=0,expansions=0,profitable=0;
        auto put=[&](Tape tape,bool start){
            if(tape.empty()||int(tape.size())>low+2)return;
            vector<I> vals;int donors=0;for(auto e:tape){vals.push_back(e.v);donors+=other.count(e.v);}
            if(!donors&&start)return;
            sort(vals.begin(),vals.end());if(!visited.insert(vals).second)return;
            if(int(tape.size())<n1){winners.push_back(tape);low=min(low,int(tape.size()));profitable++;}
            int rank=int(rng()%60)+7*min(8,donors)-50*(int(tape.size())-low);
            states.push_back({move(tape),move(vals),rank});if(start)seedCount++;
        };
        for(auto& v:s.elite)put(move(v.tape),true);
        for(int d=0;d<depth&&!states.empty();d++){
            sort(states.begin(),states.end(),[](const Hybrid&x,const Hybrid&y){return x.priority>y.priority;});
            if(states.size()>size_t(width))states.resize(width);
            vector<Hybrid> selected=move(states);states.clear();
            for(auto& k:selected){
                Search child;child.cap=s.cap;child.goals=s.goals;child.seeds=s.seeds;child.original=move(k.tape);
                child.run(44,30,6,rng(),d%3==1);expansions++;
                for(auto& tape:child.winners)put(move(tape),false);
                for(auto& tape:child.neighbors)put(move(tape),false);
            }
        }
        stable_sort(winners.begin(),winners.end(),[](const Tape&l,const Tape&r){return l.size()<r.size();});
        if(winners.size()>8)winners.resize(8);
        cout<<id<<' '<<seedCount<<' '<<expansions<<' '<<profitable<<' '<<winners.size()<<'\n';
        for(auto& t:winners){cout<<t.size()<<'\n';for(auto&e:t)cout<<e.v<<' '<<e.op<<' '<<e.a<<' '<<e.b<<'\n';}
    }
}
