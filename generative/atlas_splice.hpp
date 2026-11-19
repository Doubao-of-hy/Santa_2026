// Search coordinated replacements of interior arithmetic recipes. A long
// donor may contain a short branch materializable from the current graph.
struct SpliceBank {
    struct Recipe {int out, a, b; Op op;};
    struct State {std::vector<int> choice; int count; uint64_t key; int affinity;};
    struct Patch {int gain, affinity, center; uint64_t tie; std::vector<int> remove, build;};
    std::vector<i64> values;
    std::unordered_map<i64,int> ids;
    std::vector<int> seeds, goals, popularity;
    std::vector<Recipe> recipes;
    std::vector<std::vector<int>> ways, donors;
    std::vector<bool> seed;
    std::vector<int> original_order;
    size_t n;
    bool bridges;

    static uint64_t hash64(uint64_t x) {
        x+=0x9e3779b97f4a7c15ULL;
        x=(x^(x>>30))*0xbf58476d1ce4e5b9ULL;
        x=(x^(x>>27))*0x94d049bb133111ebULL;
        return x^(x>>31);
    }
    int id(i64 v) {
        auto [it,fresh]=ids.emplace(v,int(values.size()));
        if(fresh){values.push_back(v);ways.emplace_back();}
        return it->second;
    }
    int add(int out,Op op,int a,int b,bool required=false) {
        if(out==a || out==b)return -1;
        if((op==OP_ADD||op==OP_MUL) && a>b)std::swap(a,b);
        auto &candidates=ways[out];
        for(int rid:candidates) {
            auto r=recipes[rid];
            if(r.a==a && r.b==b && r.op==op)return rid;
        }
        if(!required && candidates.size()>=48)return -1;
        int index=recipes.size();recipes.push_back({out,a,b,op});candidates.push_back(index);
        return index;
    }
    SpliceBank(const Puzzle &p,const std::vector<std::vector<Instr>>& programs,const std::vector<Instr>& best,bool bridge_mode)
        : bridges(bridge_mode) {
        for(i64 v:p.starts)seeds.push_back(id(v));
        for(i64 v:p.targets)goals.push_back(id(v));
        std::vector<DagGraph> graphs{extract_needed_dag(p,best)};
        for(auto &program:programs)if(!program.empty())graphs.push_back(extract_needed_dag(p,program));
        for(auto &g:graphs)for(i64 v:g.order)id(v);
        n=values.size();seed.assign(n,false);popularity.assign(n,0);
        for(int x:seeds)seed[x]=true;
        for(i64 v:graphs[0].order)original_order.push_back(ids.at(v));
        for(auto &g:graphs){
            std::vector<int> donor(n,-1);
            for(i64 v:g.order){
                auto r=g.defs.at(v);
                int out=ids.at(v);
                donor[out]=add(out,r.op,ids.at(r.a),ids.at(r.b),true);
            }
            if(std::find(donors.begin(),donors.end(),donor)!=donors.end())continue;
            for(size_t i=0;i<n;++i)popularity[i]+=donor[i]>=0;
            donors.push_back(std::move(donor));
        }
        for(int a=0;a<(int)n;++a)for(int b=0;b<=a;++b){
            i64 x=values[a],y=values[b];
            auto offer=[&](i64 v,Op op,int l,int r){
                auto it=ids.find(v);if(it!=ids.end() && !seed[it->second])add(it->second,op,l,r);
            };
            if(x<=p.limit-y)offer(x+y,OP_ADD,a,b);
            if(x>y)offer(x-y,OP_SUB,a,b);
            if(y>x)offer(y-x,OP_SUB,b,a);
            if(x<=p.limit/y)offer(x*y,OP_MUL,a,b);
            if(x%y==0)offer(x/y,OP_DIV,a,b);
            if(y%x==0&&x!=y)offer(y/x,OP_DIV,b,a);
        }
        if(bridges)add_bridges(p);
    }
    void add_bridges(const Puzzle &p) {
        struct Input {int a,b;Op op;};
        struct Hit {int out,anchor;Op op;bool reverse;};
        struct Bridge {std::vector<Input> inputs;std::vector<Hit> hits;int score=0,last=-1;};
        std::vector<int> rank=popularity, frequency(n);
        for(auto &source:donors)for(int r:source)if(r>=0){
            ++frequency[recipes[r].a];
            if(recipes[r].a!=recipes[r].b)++frequency[recipes[r].b];
        }
        for(int i=0;i<(int)n;++i)rank[i]=4*frequency[i]+popularity[i]+1000*seed[i];
        std::vector<int> anchors(n);
        std::iota(anchors.begin(),anchors.end(),0);
        std::sort(anchors.begin(),anchors.end(),[&](int a,int b){return rank[a]!=rank[b]?rank[a]>rank[b]:a<b;});
        anchors.resize(std::min<size_t>(anchors.size(),64));
        std::unordered_map<i64,Bridge> fresh;
        auto capture=[&](i64 v,int a,int b,Op op){
            if(ids.count(v))return;
            auto &options=fresh[v].inputs;
            if(options.size()<2)options.push_back({a,b,op});
        };
        for(size_t ai=0;ai<anchors.size();++ai)for(size_t bi=0;bi<=ai;++bi){
            int a=anchors[ai],b=anchors[bi];i64 x=values[a],y=values[b];
            if(x<=p.limit-y)capture(x+y,a,b,OP_ADD);
            if(x>y)capture(x-y,a,b,OP_SUB);
            if(y>x)capture(y-x,b,a,OP_SUB);
            if(x<=p.limit/y)capture(x*y,a,b,OP_MUL);
            if(x%y==0)capture(x/y,a,b,OP_DIV);
            if(y%x==0&&x!=y)capture(y/x,b,a,OP_DIV);
        }
        auto incumbent=state(donors[0]);std::vector<int> uses(n);
        for(int g:goals)++uses[g];
        for(int q:incumbent.choice)if(q>=0){
            auto r=recipes[q];++uses[r.a];if(r.a!=r.b)++uses[r.b];
        }
        for(int out:original_order){
            int prize=std::min<int>(6,footprint(incumbent,out,uses).size());
            if(prize<2)continue;
            for(int b:anchors){
                if(out==b)continue;
                WBackStep inverses[6];int count=gen_win_inverses(values[out],values[b],p.limit,inverses);
                for(int j=0;j<count;++j){
                    auto step=inverses[j];auto found=fresh.find(step.u);if(found==fresh.end())continue;
                    auto &hub=found->second;
                    if(hub.last!=out){hub.score+=prize;hub.last=out;}
                    if(hub.hits.size()<40)hub.hits.push_back({out,b,step.op,step.rev});
                }
            }
        }
        std::vector<std::pair<int,i64>> chosen;
        for(auto &[v,hub]:fresh)if(hub.score>=3)chosen.push_back({-hub.score,v});
        std::sort(chosen.begin(),chosen.end());
        if(chosen.size()>120)chosen.resize(120);
        for(auto [score,v]:chosen){
            auto &hub=fresh.at(v);int h=id(v);
            for(auto in:hub.inputs)add(h,in.op,in.a,in.b,true);
            for(auto hit:hub.hits)add(hit.out,hit.op,hit.reverse?hit.anchor:h,hit.reverse?h:hit.anchor,true);
        }
        n=values.size();seed.resize(n);popularity.resize(n);
        for(auto &source:donors)source.resize(n,-1);
    }
    State state(std::vector<int> choice)const {
        int count=0,affinity=0;uint64_t key=0;
        for(size_t i=0;i<n;++i)if(choice[i]>=0){
            ++count;affinity+=std::min(popularity[i],5);key^=hash64(choice[i]+1);
        }
        return {std::move(choice),count,key,affinity};
    }
    std::vector<int> footprint(const State& s,int center,const std::vector<int>& uses)const{
        auto left=uses;
        std::vector<int> removed{center};
        for(size_t i=0;i<removed.size();++i){
            auto r=recipes[s.choice[removed[i]]];
            auto release=[&](int x){if(s.choice[x]>=0 && --left[x]==0)removed.push_back(x);};
            release(r.a);if(r.a!=r.b)release(r.b);
        }
        return removed;
    }
    std::vector<Patch> moves(const State& s,int round,int slack){
        std::vector<std::vector<int>> users(n);
        std::vector<int> uses(n);
        for(int g:goals)++uses[g];
        for(int r:s.choice)if(r>=0){
            auto e=recipes[r];
            users[e.a].push_back(e.out);++uses[e.a];
            if(e.a!=e.b){users[e.b].push_back(e.out);++uses[e.b];}
        }
        std::vector<Patch> patches;
        // 0 is absent. 1 is paid. 2 is downstream of the replacement.
        for(int center=0;center<(int)n;++center)if(s.choice[center]>=0 && ways[center].size()>1){
            auto removed=footprint(s,center,uses);int limit=removed.size()+slack;
            std::vector<char> status(n);
            for(size_t i=0;i<n;++i)status[i]=seed[i]||s.choice[i]>=0;
            for(int x:removed)status[x]=0;
            std::vector<int> descendants{center};status[center]=2;
            for(size_t i=0;i<descendants.size();++i)for(int child:users[descendants[i]])
                if(status[child]!=2){status[child]=2;descendants.push_back(child);}
            // Materialize a donor ingredient only until an unchanged, safely
            // reusable value is reached. Retain several different short paths.
            std::unordered_map<int,std::vector<std::vector<int>>> memo;
            auto paths=[&](int x)->const std::vector<std::vector<int>>& {
                auto [it,inserted]=memo.try_emplace(x);
                auto &out=it->second;if(!inserted)return out;
                if(status[x]==1){out.emplace_back();return out;}
                if(status[x]==2)return out;
                std::vector<int> mark(n);int stamp=0;
                auto try_map=[&](const std::vector<int>& source){
                    ++stamp;std::vector<int> seq;
                    auto visit=[&](auto &&self,int v)->bool{
                        if(status[v]==1||mark[v]==stamp)return true;
                        if(status[v]==2||source[v]<0||(int)seq.size()>=limit-1)return false;
                        auto r=recipes[source[v]];
                        if(!self(self,r.a)||!self(self,r.b))return false;
                        mark[v]=stamp;seq.push_back(source[v]);return (int)seq.size()<limit;
                    };
                    if(visit(visit,x) && std::find(out.begin(),out.end(),seq)==out.end())out.push_back(std::move(seq));
                };
                try_map(s.choice);
                for(auto &source:donors)if(source[x]>=0)try_map(source);
                // Synthetic helper recipes are absent from source traces.
                // Search exact one- and two-instruction routes from the paid
                // portion of this particular neighborhood.
                if(bridges)for(int ri:ways[x]){
                    auto r=recipes[ri];
                    if(status[r.a]==1&&status[r.b]==1)out.push_back({ri});
                    else if(status[r.a]!=2&&status[r.b]!=2&&(status[r.a]==1||status[r.b]==1||r.a==r.b)){
                        int z=status[r.a]==1?r.b:r.a;
                        for(int rz:ways[z]){
                            auto e=recipes[rz];
                            if(status[e.a]==1&&status[e.b]==1){
                                out.push_back({rz,ri});break;
                            }
                        }
                    }
                }
                std::stable_sort(out.begin(),out.end(),[](auto &a,auto &b){return a.size()<b.size();});
                if(bridges){
                    std::vector<std::vector<int>> unique;
                    for(auto &option:out)if(std::find(unique.begin(),unique.end(),option)==unique.end()){
                        unique.push_back(std::move(option));if(unique.size()==3)break;
                    }
                    out=std::move(unique);
                }
                if(out.size()>3)out.resize(3);
                return out;
            };
            int old_affinity=0;
            for(int v:removed)old_affinity+=std::min(popularity[v],5);
            for(int alternative:ways[center]){
                auto r=recipes[alternative];
                // The incumbent root recipe can still gain a new path to a
                // private operand, which is also tested at that operand.
                if(alternative==s.choice[center])continue;
                const auto &first=paths(r.a);if(first.empty())continue;
                const auto &second=paths(r.b);if(second.empty())continue;
                for(const auto &a:first)for(const auto &b:second){
                    std::vector<int> built=a;
                    bool conflict=false;
                    for(int ri:b){
                        auto same=std::find_if(built.begin(),built.end(),[&](int other){return recipes[other].out==recipes[ri].out;});
                        if(same==built.end())built.push_back(ri);
                        else if(*same!=ri){conflict=true;break;}
                    }
                    if(conflict || (int)built.size()+1>limit)continue;
                    built.push_back(alternative);
                    int gain=(int)removed.size()-(int)built.size(),affinity=-old_affinity;
                    uint64_t tie=hash64(round+1);
                    for(int ri:built){affinity+=std::min(popularity[recipes[ri].out],5);tie^=hash64(ri+1);}
                    patches.push_back({gain,affinity,center,tie,removed,std::move(built)});
                }
            }
        }
        return patches;
    }
    bool graph_of(const State& s,DagGraph& g)const {
        std::vector<char> mark(n);for(int x:seeds)mark[x]=2;
        auto emit=[&](auto&& self,int x)->bool {
            if(mark[x]==2)return true;
            if(mark[x]==1||s.choice[x]<0)return false;
            mark[x]=1;auto r=recipes[s.choice[x]];
            if(!self(self,r.a)||!self(self,r.b))return false;
            g.order.push_back(values[x]);g.defs[values[x]]={r.op,values[r.a],values[r.b]};
            mark[x]=2;return true;
        };
        for(int x:original_order)if(s.choice[x]>=0 && !emit(emit,x))return false;
        for(int x:goals)if(!emit(emit,x))return false;
        return true;
    }
    void search(const Puzzle& p,std::vector<Instr>& best){
        State start=state(donors[0]);
        std::vector<State> front{start};
        std::unordered_set<uint64_t> seen{start.key};
        int logical=start.count;
        for(int round=0;round<7 && !front.empty();++round){
            std::vector<State> children;
            for(auto &s:front){
                auto options=moves(s,round,2);
                for(int mode=0;mode<2;++mode){
                    std::sort(options.begin(),options.end(),[&](const Patch&a,const Patch&b){
                        int pa=mode ? 2*a.gain+a.affinity : 16*a.gain+a.affinity;
                        int pb=mode ? 2*b.gain+b.affinity : 16*b.gain+b.affinity;
                        return pa!=pb?pa>pb:a.tie<b.tie;
                    });
                    int taken=0;
                    for(auto &patch:options){
                        if(s.count-patch.gain>logical+2)continue;
                        auto choice=s.choice;
                        for(int x:patch.remove)choice[x]=-1;
                        for(int ri:patch.build)choice[recipes[ri].out]=ri;
                        auto next=state(std::move(choice));
                        if(seen.insert(next.key).second){
                            children.push_back(std::move(next));if(++taken>=8)break;
                        }
                    }
                }
            }
            std::sort(children.begin(),children.end(),[&](const State&a,const State&b){
                if(a.count!=b.count)return a.count<b.count;
                if(a.affinity!=b.affinity)return a.affinity>b.affinity;
                return hash64(a.key+round)<hash64(b.key+round);
            });
            if(children.empty())break;
            logical=std::min(logical,children.front().count);
            front.clear();
            for(auto &child:children){
                if(child.count>logical+2)continue;
                // Keep different helper sets among tied alternatives.
                bool duplicate=false;for(const auto& other:front){
                    int diff=0;
                    for(size_t i=0;i<n;++i)diff+=other.choice[i]!=child.choice[i];
                    if(diff<=2&&other.count==child.count){duplicate=true;break;}
                }
                if(duplicate)continue;
                if(child.count<(int)best.size()){
                    DagGraph g;
                    if(graph_of(child,g))dag_reallocate(p,g,best);
                }
                front.push_back(std::move(child));
                if(front.size()>=5)break;
            }
        }
    }
};

std::vector<Instr> splice_puzzle(const Puzzle& p,const std::vector<std::vector<Instr>>& bank,bool bridges){
    std::vector<Instr> best;
    for(auto &program:bank)if(!program.empty()&&(best.empty()||program.size()<best.size()))best=program;
    if(best.size()<=4)return best;
    SpliceBank network(p,bank,best,bridges);network.search(p,best);
    if(!verify_program(p,best))throw std::runtime_error("Invalid spliced program");
    return best;
}
