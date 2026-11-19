// Beam search over entire multi-target partial programs. Each transition is
// evaluated by actually completing the other goals with alternative routes.
#define RUDOLPH_NO_MAIN
#include "rudolph.cpp"
#include <random>

struct Step {Int out;char op;Int a,b;};
using Route=vector<Step>;
struct Choice {Int goal;Route steps;};

Route original_route(const Puzzle& source,const Puzzle& partial,Int goal){
    Route path;set<Int> visited;
    auto walk=[&](auto&& self,Int v)->void{
        if(partial.have.count(v)||!visited.insert(v).second)return;
        auto s=source.def.at(v);
        self(self,s[1]);self(self,s[2]);path.push_back({v,char(s[0]),s[1],s[2]});
    };
    walk(walk,goal);return path;
}
void apply_route(Puzzle& state,const Route& r){
    for(auto step:r)if(!state.have.count(step.out)){
        if(!state.have.count(step.a)||!state.have.count(step.b)||
           state.make(step.op,step.a,step.b)!=step.out)throw runtime_error("unmaterializable route");
    }
}
vector<Int> leaves_for(const Puzzle& partial,const Puzzle& reference,const vector<Int>& pending,int capacity){
    map<Int,int> uses;
    for(Int t:pending)for(auto s:original_route(reference,partial,t)){
        for(Int v:{s.a,s.b})if(partial.have.count(v))++uses[v];
    }
    vector<Int> candidates(partial.have.begin(),partial.have.end());
    map<Int,int> position;
    for(int i=0;i<(int)partial.order.size();++i)position[partial.order[i]]=i+1;
    set<Int> seeds(partial.starts.begin(),partial.starts.end());
    auto priority=[&](Int v){
        return 250*seeds.count(v)+55*min(4,uses[v])+int(v<=512)*55+
               (v<65536?24:0)+30*position[v]/int(1+partial.order.size());
    };
    stable_sort(candidates.begin(),candidates.end(),[&](Int a,Int b){
        auto x=priority(a),y=priority(b);return x==y?a<b:x>y;
    });
    if((int)candidates.size()>capacity)candidates.resize(capacity);
    return candidates;
}
vector<Choice> options(Puzzle& state,const Puzzle& reference,const vector<Int>& pending,
                       Dict& d,int capacity,int alt_count){
    d.lim=state.lim;d.known=&state.have;d.build(leaves_for(state,reference,pending,capacity));
    vector<Choice> candidates;
    for(Int target:pending){
        if(state.have.count(target))continue;
        candidates.push_back({target,original_route(reference,state,target)});
        Search search(d);search.run(target);
        if(search.end<0)continue;
        state.pick(d,search);
        vector<array<int,3>> finishes{{search.best,search.end,search.term}};
        stable_sort(search.cands.begin(),search.cands.end(),[](auto a,auto b){return a[0]<b[0];});
        for(auto c:search.cands)if(c[1]!=search.end)finishes.push_back(c);
        search.cands.clear();
        set<vector<Int>> signatures;
        int checked=0;
        for(auto f:finishes){
            if(++checked>60||int(signatures.size())>=alt_count)break;
            search.end=f[1];search.term=f[2];
            Puzzle temp=state;
            if(temp.unwind(d,search)!=target)throw runtime_error("trace reconstruction failed");
            Route route;vector<Int> sig;
            for(size_t i=state.order.size();i<temp.order.size();++i){
                Int v=temp.order[i];auto s=temp.def.at(v);
                route.push_back({v,char(s[0]),s[1],s[2]});sig.push_back(v);
            }
            sort(sig.begin(),sig.end());
            if(signatures.insert(std::move(sig)).second)candidates.push_back({target,std::move(route)});
        }
    }
    return candidates;
}
void complete(Puzzle& state,const vector<Choice>& options,int order_mode){
    // Routes can be merged safely because a value computed in the partial
    // program is always available to subsequent routes. Count each value once.
    while(true){
        const Choice* pick=nullptr;double best=1e30;
        map<Int,int> freq;
        if(order_mode)for(auto &c:options)if(!state.have.count(c.goal))
            for(auto s:c.steps)if(!state.have.count(s.out))++freq[s.out];
        for(auto &c:options)if(!state.have.count(c.goal)){
            double score=0;
            for(auto s:c.steps)if(!state.have.count(s.out)){
                score+=1.;
                if(order_mode)score-=.13*min(3,freq[s.out]-1);
            }
            if(score<best){best=score;pick=&c;}
        }
        if(!pick)break;
        apply_route(state,pick->steps);
    }
}
uint64_t signature(const Puzzle& p){
    uint64_t h=0x2342625553c21a1ULL;
    for(Int v:p.have){
        uint64_t z=uint64_t(v)*0xd1b54a32d192ed03ULL;
        z^=z>>31;h=(h^z)*0x9e3779b97f4a7c15ULL;
    }
    return h;
}
vector<Int> select_block(const Puzzle& reference,int width,int round,mt19937& rng){
    vector<pair<Int,set<Int>>> roots;
    map<Int,int> counts;
    for(Int t:reference.targets){
        if(find(reference.starts.begin(),reference.starts.end(),t)!=reference.starts.end())continue;
        Puzzle empty;empty.have.insert(reference.starts.begin(),reference.starts.end());
        set<Int> branch;
        for(auto s:original_route(reference,empty,t)){branch.insert(s.out);++counts[s.out];}
        roots.push_back({t,move(branch)});
    }
    vector<Int> result;
    if(roots.empty())return result;
    shuffle(roots.begin(),roots.end(),rng);
    set<Int> near;
    while(!roots.empty() && (int)result.size()<width){
        int pick=0;double best=-1e30;
        for(int i=0;i<(int)roots.size();++i){
            double gain=0;
            for(Int x:roots[i].second){
                if(near.count(x))gain+=2./counts[x];
                if(counts[x]==1)gain+=(round%3==2?.12:.6);
            }
            gain+=double(rng()%1000)/1000.*(round%3==0?.5:3.0);
            if(gain>best){best=gain;pick=i;}
        }
        result.push_back(roots[pick].first);
        near.insert(roots[pick].second.begin(),roots[pick].second.end());
        roots.erase(roots.begin()+pick);
    }
    return result;
}
void search_block(const Puzzle& reference,const vector<Int>& block,int width,int capacity,
                  Dict& d,vector<array<int,4>>& best,mt19937& rng){
    set<Int> movable(block.begin(),block.end());
    Puzzle init;init.lim=reference.lim;init.starts=reference.starts;init.targets=reference.targets;
    init.have.insert(init.starts.begin(),init.starts.end());
    set<Int> frozen;
    for(Int t:init.targets)if(!movable.count(t))
        for(auto s:original_route(reference,init,t))frozen.insert(s.out);
    for(Int v:reference.order)if(frozen.count(v)){
        auto r=reference.def.at(v);init.make(char(r[0]),r[1],r[2]);
    }
    vector<Puzzle> beam{std::move(init)};
    for(size_t depth=0;depth<block.size() && !beam.empty();++depth){
        struct Node{double rank;uint64_t key;Puzzle state;};
        vector<Node> next;
        set<uint64_t> seen;
        for(auto &state:beam){
            vector<Int> pending;for(Int t:block)if(!state.have.count(t))pending.push_back(t);
            if(pending.empty())continue;
            vector<Choice> routes=options(state,reference,pending,d,capacity,3);
            for(auto &c:routes){
                Puzzle child=state;apply_route(child,c.steps);
                uint64_t key=signature(child);if(!seen.insert(key).second)continue;
                Puzzle trial=child;complete(trial,routes,int(depth%2));
                int logical=trial.closure(0,false).size();
                if(logical<(int)best.size()){
                    auto tape=trial.compile();
                    if(!tape.empty() && tape.size()<best.size())best=move(tape);
                }
                int novel=0;
                for(Int x:child.order)if(!reference.have.count(x))++novel;
                // Use a physical completion bound for selection, with a small
                // novelty allowance to cross neutral target assignments.
                double rank=logical-.18*min(novel,12)+.001*(rng()%700);
                next.push_back({rank,key,std::move(child)});
            }
        }
        sort(next.begin(),next.end(),[](const Node& a,const Node& b){return a.rank<b.rank;});
        if(int(next.size())>width)next.resize(width);
        beam.clear();for(auto &n:next)beam.push_back(std::move(n.state));
    }
}
#ifndef TRAJECTORY_NO_MAIN
int main(int argc,char** argv){
    int width=argc>1?atoi(argv[1]):3, block=argc>2?atoi(argv[2]):5;
    int rounds=argc>3?atoi(argv[3]):2,cap=argc>4?atoi(argv[4]):64;
    WIDTH=argc>5?atoi(argv[5]):6;SLACK=2;RATIONAL_LIFTS=0;
    string line;Dict dictionary;
    while(getline(cin,line))if(!line.empty()){
        istringstream in(line);string pid;Puzzle source;
        int ns,nt,len;in>>pid>>source.lim>>ns>>nt;
        source.starts.resize(ns);source.targets.resize(nt);
        for(auto &v:source.starts)in>>v;for(auto &v:source.targets)in>>v;
        if(!(in>>len))throw runtime_error("local parent trace required");
        auto best=source.read_tape(in,len);
        mt19937 rng(uint32_t(stoul(pid.substr(pid.find_last_of('_')+1)))+7479);
        for(int r=0;r<rounds;++r){
            auto picked=select_block(source,block,r,rng);
            if(!picked.empty())search_block(source,picked,width,cap,dictionary,best,rng);
        }
        cout<<pid<<" [";
        for(size_t i=0;i<best.size();++i){auto s=best[i];if(i)cout<<',';
            cout<<"[\""<<char(s[0])<<"\","<<s[1]<<','<<s[2]<<','<<s[3]<<']';}
        cout<<"]\n"<<flush;
    }
}
#endif
