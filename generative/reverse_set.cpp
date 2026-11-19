// Reduce several required values backwards together. A not-yet-built residual
// of one goal may act as the quotient or an additive anchor of another goal.
#define TRAJECTORY_NO_MAIN
#include "trajectory.cpp"
#include <functional>

struct ReverseSet {
    using Def=map<Int,Step>;
    struct Node {Def defs;vector<Int> unknown;double rank;uint64_t key;};
    const Puzzle& source;
    Puzzle frozen;
    vector<Int> roots;
    Dict& dictionary;
    map<Int,Route> materializers;
    int width,level_limit;

    ReverseSet(const Puzzle& input,vector<Int> block,Dict& dict,int capacity,int w,int levels)
        :source(input),roots(move(block)),dictionary(dict),width(w),level_limit(levels){
        set<Int> released(roots.begin(),roots.end()),retained;
        frozen.starts=input.starts;frozen.targets=input.targets;frozen.lim=input.lim;
        frozen.have.insert(input.starts.begin(),input.starts.end());
        for(Int g:input.targets)if(!released.count(g))
            for(auto s:original_route(input,frozen,g))retained.insert(s.out);
        for(Int v:input.order)if(retained.count(v)){
            auto r=input.def.at(v);frozen.make(char(r[0]),r[1],r[2]);
        }
        dictionary.lim=input.lim;dictionary.known=&frozen.have;
        dictionary.build(leaves_for(frozen,source,roots,capacity));
    }
    Route finish(Int v) {
        auto known=materializers.find(v);
        if(known!=materializers.end())return known->second;
        Puzzle p=frozen;
        int idx=dictionary.h.get(v);
        if(idx>=0)p.mat(dictionary,idx);
        else {
            Search s(dictionary);s.run(v);
            if(s.end>=0)p.unwind(dictionary,s);else p.binary(v);
        }
        Route path;
        for(size_t i=frozen.order.size();i<p.order.size();++i){
            auto out=p.order[i];auto r=p.def.at(out);
            path.push_back({out,char(r[0]),r[1],r[2]});
        }
        if(source.have.count(v)){
            Route prior=original_route(source,frozen,v);
            if(prior.size()<=path.size())path=move(prior);
        }
        materializers[v]=path;return path;
    }
    Node inspect(Def graph) {
        unordered_set<Int> seen,active;
        vector<Int> unknown;double score=0;uint64_t key=0;
        function<bool(Int)> visit=[&](Int v){
            if(frozen.have.count(v)||seen.count(v))return true;
            if(!active.insert(v).second)return false;
            auto it=graph.find(v);
            if(it!=graph.end()){
                auto s=it->second;
                if(!visit(s.a)||!visit(s.b))return false;
                score+=1;key^=uint64_t(v)*0x9e3779b97f4a7c15ULL ^ uint64_t(s.a+31*s.op)*0xc6a4a7935bd1e995ULL;
            }else{
                int d=dictionary.h.get(v);
                if(d>=0)score+=dictionary.e[d].cost;
                else {
                    unknown.push_back(v);
                    auto found=materializers.find(v);
                    double predicted=2.+dictionary.estimate(v);
                    score+=found==materializers.end()?predicted:.6*found->second.size()+.4*predicted;
                }
            }
            active.erase(v);seen.insert(v);return true;
        };
        for(Int v:roots)if(!visit(v))return {{},{},1e30,0};
        sort(unknown.rbegin(),unknown.rend());
        return {move(graph),move(unknown),score,key};
    }
    int complete(const Node& state,vector<array<int,4>>& best){
        Def merged=state.defs;
        for(Int x:state.unknown){
            for(auto s:finish(x))merged.try_emplace(s.out,s);
        }
        Puzzle out=frozen;unordered_set<Int> stack;
        function<bool(Int)> emit=[&](Int v){
            if(out.have.count(v))return true;
            if(!stack.insert(v).second)return false;
            auto it=merged.find(v);
            if(it==merged.end()){
                auto extras=finish(v);for(auto s:extras)merged.try_emplace(s.out,s);
                it=merged.find(v);if(it==merged.end())return false;
            }
            auto s=it->second;
            if(!emit(s.a)||!emit(s.b))return false;
            if(out.make(s.op,s.a,s.b)!=v)throw runtime_error("invalid joint identity");
            stack.erase(v);return true;
        };
        for(Int r:roots)if(!emit(r))return 10000;
        int length=out.closure(0,false).size();
        if(length<(int)best.size()){
            auto tape=out.compile();if(!tape.empty()&&tape.size()<best.size())best=move(tape);
        }
        return length-int(frozen.order.size());
    }
    vector<Route> transitions(const Node& node,Int x){
        vector<Route> alt;
        auto lone=finish(x);
        if(!lone.empty()){alt.push_back({lone.back()});alt.push_back(lone);}
        if(source.have.count(x)){
            auto previous=original_route(source,frozen,x);
            if(!previous.empty())alt.push_back({previous.back()});
        }
        auto product=[&](Int y,Int m,Int lift){
            if(m<1 || y>frozen.lim/m || x>frozen.lim/lift)return;
            Int scaled=x*lift,w=m*y,delta=abs(w-scaled);
            if(m==1 && lift==1 && delta==0)return;
            if(delta>=x || (m!=1&&m>=x) || (w==x&&lift!=1))return;
            Route r;
            if(m!=1)r.push_back({w,'*',y,m});
            if(delta)r.push_back({scaled,w<scaled?'+':'-',w,delta});
            if(lift!=1)r.push_back({x,'/',scaled,lift});
            if(!r.empty()&&r.back().out==x)alt.push_back(move(r));
        };
        for(Int y:node.unknown)if(y!=x){
            for(Int lift:{1LL,2LL,3LL,4LL,5LL,8LL}){
                if(x>frozen.lim/lift)continue;
                if(lift!=1 && dictionary.h.get(lift)<0)continue;
                Int q=x*lift/y;
                product(y,q,lift);product(y,q+1,lift);
                if(lift!=1)continue;
                product(y,1,1);
                if(q>2)for(int layer=0;layer<2;++layer){
                    const auto& sorted=dictionary.layer(layer);
                    int at=dictionary.lower_index(q,layer);
                    for(int j=max(0,at-1);j<min(int(sorted.size()),at+2);++j)
                        product(y,sorted[j].first,1);
                }
            }
        }
        // Pull one known radix out without immediately completing the
        // quotient. It stays in the shared pending set for other goals.
        vector<pair<double,Route>> scaled;
        for(int i=0;i<dictionary.n0;++i){
            Int m=dictionary.e[i].v;if(m<2||m>=x)continue;
            Int q=x/m,r=x%m;
            for(int above=0;above<2;++above){
                Int residual=above?m-r:r;
                if(above && (r==0 || residual>frozen.lim-x))continue;
                int ri=residual?dictionary.h.get(residual):0;
                if(residual&&ri<0)continue;
                Int quotient=q+above,w=m*quotient;
                if(quotient<2)continue;
                Route steps{{w,'*',m,quotient}};
                if(residual)steps.push_back({x,above?'-':'+',w,residual});
                double h=steps.size()+(residual?dictionary.e[ri].cost:0)+dictionary.estimate(quotient);
                scaled.push_back({h,move(steps)});
            }
        }
        stable_sort(scaled.begin(),scaled.end(),[](const auto&a,const auto&b){return a.first<b.first;});
        for(int i=0;i<min<int>(4,scaled.size());++i)alt.push_back(move(scaled[i].second));
        return alt;
    }
    void run(vector<array<int,4>>& best){
        vector<Node> beam{inspect({})};
        set<uint64_t> visited;
        for(int level=0;level<level_limit&&!beam.empty();++level){
            vector<Node> next;
            for(const auto& state:beam){
                if(state.unknown.empty()){complete(state,best);continue;}
                Int x=state.unknown.front();
                for(auto &route:transitions(state,x)){
                    auto defs=state.defs;
                    for(auto s:route)if(!frozen.have.count(s.out))defs.try_emplace(s.out,s);
                    Node trial=inspect(move(defs));
                    if(trial.rank<1e20 && visited.insert(trial.key).second)next.push_back(move(trial));
                }
            }
            sort(next.begin(),next.end(),[](const Node&a,const Node&b){return a.rank<b.rank;});
            if(int(next.size())>width*3)next.resize(width*3);
            for(auto &state:next){
                int bound=complete(state,best);
                state.rank=.68*bound+.32*state.rank;
            }
            sort(next.begin(),next.end(),[](const Node&a,const Node&b){return a.rank<b.rank;});
            if(int(next.size())>width)next.resize(width);
            beam=move(next);
        }
    }
};
int main(int argc,char** argv){
    int beam=argc>1?atoi(argv[1]):3,block=argc>2?atoi(argv[2]):7;
    int repeats=argc>3?atoi(argv[3]):2, leaves=argc>4?atoi(argv[4]):60,depth=argc>5?atoi(argv[5]):12;
    WIDTH=3;SLACK=2;DISTANCE_GUIDE=true;Dict d;
    string line;
    while(getline(cin,line))if(!line.empty()){
        istringstream input(line);string id;Puzzle p;int n,t,count;
        input>>id>>p.lim>>n>>t;p.starts.resize(n);p.targets.resize(t);
        for(Int &x:p.starts)input>>x;for(Int& x:p.targets)input>>x;
        if(!(input>>count))return 2;
        auto best=p.read_tape(input,count);
        mt19937 rng(stoul(id.substr(id.find_last_of('_')+1))+41775);
        for(int i=0;i<repeats;++i){
            auto roots=select_block(p,block,i,rng);
            ReverseSet run(p,move(roots),d,leaves,beam,depth);run.run(best);
        }
        cout<<id<<" [";
        for(size_t i=0;i<best.size();++i){auto s=best[i];if(i)cout<<',';
            cout<<"[\""<<char(s[0])<<"\","<<s[1]<<','<<s[2]<<','<<s[3]<<']';}
        cout<<"]\n"<<flush;
    }
}
