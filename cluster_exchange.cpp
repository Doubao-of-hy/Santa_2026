// Remove a cluster of old intermediates, ground the entire remaining value
// set under all legal recipes, then synthesize missing outputs in marginal cost.
#define main offset_closure_standalone
#include "offset_closure.cpp"
#undef main
#include <set>
#include <random>

struct Indexed {int v,a,b;char op;};
struct Cluster {
    I cap;vector<I> seeds,goals,values;vector<Step> tape;
    unordered_map<I,int> idx;
    vector<int> roots,wanted,optional;
    vector<char> hard;
    vector<Indexed> edges;
    vector<vector<int>> links,consumers,parents;
    mt19937 rng;
    int examined=0,attempted=0,won=0;
    vector<vector<Step>> best;
    int id(I x){
        auto [it,ok]=idx.emplace(x,values.size());
        if(ok)values.push_back(x);return it->second;
    }
    void init(){
        for(I x:seeds)roots.push_back(id(x));for(auto &e:tape)id(e.v);
        for(I x:goals)wanted.push_back(id(x));
        int n=values.size();hard.resize(n);consumers.resize(n);parents.resize(n);links.resize(n);
        for(int v:roots)hard[v]=1;for(int t:wanted)hard[t]=1;
        for(int x=0;x<n;x++)if(!hard[x])optional.push_back(x);
        for(auto&e:tape){
            int v=idx.at(e.v),a=idx.at(e.a),b=idx.at(e.b);
            edges.push_back({v,a,b,e.op});
            parents[v].push_back(a);consumers[a].push_back(v);
            if(a!=b){parents[v].push_back(b);consumers[b].push_back(v);}
        }
        for(int i=0;i<n;i++)for(int j=0;j<=i;j++)forward(values[i],values[j],cap,[&](Step e){
            if(e.v==e.a||e.v==e.b)return;auto it=idx.find(e.v);
            if(it!=idx.end())edges.push_back({it->second,idx.at(e.a),idx.at(e.b),e.op});
        });
        for(int x:optional){
            for(int a:parents[x])if(!hard[a])links[x].push_back(a);
            for(int t:consumers[x]){
                if(!hard[t])links[x].push_back(t);
                // Sibling operands of the same output can be replaced jointly.
                for(int a:parents[t])if(!hard[a]&&a!=x)links[x].push_back(a);
            }
        }
    }
    struct Trial {long long rank;int kind;vector<int> banned;};
    vector<Trial> groups(int budget){
        vector<Trial> pool;set<vector<int>> unique;
        vector<int> centers=optional;shuffle(centers.begin(),centers.end(),rng);
        for(int focus:centers){
            for(int method=0;method<4;method++){
                vector<int> group={focus},choices;
                if(method==2||method==3){
                    choices=optional;
                    sort(choices.begin(),choices.end(),[&](int a,int b){
                        if(method==2)return abs(a-focus)<abs(b-focus);
                        return abs(values[a]-values[focus])<abs(values[b]-values[focus]);
                    });
                }else{
                    vector<int> front{focus};set<int> visited{focus};
                    for(int d=0;d<4&&!front.empty();d++){
                        vector<int> next;
                        for(int x:front)for(int y:links[x])if(visited.insert(y).second)next.push_back(y);
                        if(method==0)shuffle(next.begin(),next.end(),rng);
                        else stable_sort(next.begin(),next.end(),[&](int a,int b){return consumers[a].size()<consumers[b].size();});
                        choices.insert(choices.end(),next.begin(),next.end());front=move(next);
                    }
                }
                for(int x:choices){
                    if(x==focus)continue;group.push_back(x);
                    int z=group.size();
                    if(z==3||z==5||z==8||z==11){
                        auto sorted=group;sort(sorted.begin(),sorted.end());
                        if(unique.insert(sorted).second){
                            int shared=0,other=0;
                            for(int v:group){shared+=min(3,(int)consumers[v].size());for(int a:links[v])other+=binary_search(sorted.begin(),sorted.end(),a);}
                            long long merit=int(rng()%1000)+65*other/z-15*shared/z;
                            pool.push_back({merit,method,move(sorted)});
                        }
                    }
                    if(z>=11)break;
                }
            }
        }
        stable_sort(pool.begin(),pool.end(),[](auto&a,auto&b){return a.rank>b.rank;});
        // Fill independently by cluster shape and size. This retains mixed
        // groups of shared constants as well as private chains.
        vector<Trial> chosen;unordered_map<int,int> buckets;
        for(auto &t:pool){
            int bucket=t.kind*16+t.banned.size();
            if(buckets[bucket]>=1+budget/16)continue;
            buckets[bucket]++;chosen.push_back(move(t));if(int(chosen.size())>=budget)break;
        }
        return chosen;
    }
    vector<Step> trim(const vector<Step>& built){
        unordered_map<I,Step> recipe;
        for(Step e:built)recipe.emplace(e.v,e);
        unordered_set<I> seen(seeds.begin(),seeds.end());
        vector<Step> out;
        auto visit=[&](auto&&self,I v)->void{
            if(seen.count(v))return;
            auto e=recipe.at(v);self(self,e.a);self(self,e.b);seen.insert(v);out.push_back(e);
        };
        for(auto t:goals)visit(visit,t);return out;
    }
    void examine(const vector<int>& banned,int width,int depth){
        int n=values.size();vector<bool> allow(n,true),known(n);
        for(int x:banned)allow[x]=false;
        for(int r:roots)known[r]=true;
        vector<Step> built;
        size_t previous;
        do{
            previous=built.size();
            for(const Indexed&e:edges)if(allow[e.v]&&!known[e.v]&&known[e.a]&&known[e.b]){
                known[e.v]=true;built.push_back({values[e.v],values[e.a],values[e.b],e.op});
            }
        }while(previous!=built.size());
        bool missing=false;for(int t:wanted)if(!known[t])missing=true;
        ++examined;
        if(missing){
            Solver synth;synth.cap=cap;synth.width=width;synth.depth=depth;synth.upper=banned.size();synth.required=0;
            for(int x=0;x<n;x++)if(known[x])synth.anchors.push_back(values[x]);
            else if(allow[x]){
                if(synth.goals.size()>=63)return;
                if(hard[x])synth.required|=Mask(1)<<synth.goals.size();
                synth.goals.push_back(values[x]);
            }
            if(!synth.required)return;
            for(int x:banned)synth.hints.push_back(values[x]);
            ++attempted;synth.run();
            if(!synth.solved)return;
            built.insert(built.end(),synth.answer.begin(),synth.answer.end());
        }
        auto result=trim(built);if(result.size()>=tape.size())return;
        ++won;best.push_back(move(result));
        stable_sort(best.begin(),best.end(),[](auto&a,auto&b){return a.size()<b.size();});
        if(best.size()>5)best.pop_back();
    }
};
int main(int argc,char**argv){
    ios::sync_with_stdio(false);cin.tie(nullptr);
    string name;int ns,nt,ng;
    while(cin>>name){
        Cluster k;cin>>k.cap>>ns>>nt>>ng;k.seeds.resize(ns);k.goals.resize(nt);
        for(I&v:k.seeds)cin>>v;for(I&v:k.goals)cin>>v;
        for(int i=0;i<ng;i++){Step e;cin>>e.v>>e.op>>e.a>>e.b;k.tape.push_back(e);}
        unsigned seed=37963;for(char c:name)seed=seed*131+unsigned(c);k.rng.seed(seed);
        k.init();auto trials=k.groups(argc>1?stoi(argv[1]):32);
        int width=argc>2?stoi(argv[2]):6,depth=argc>3?stoi(argv[3]):3;
        for(auto &group:trials)k.examine(group.banned,width,depth);
        cout<<name<<' '<<k.examined<<' '<<k.attempted<<' '<<k.won<<' '<<k.best.size()<<'\n';
        for(auto &pg:k.best){cout<<pg.size()<<'\n';for(auto&e:pg)cout<<e.v<<' '<<e.op<<' '<<e.a<<' '<<e.b<<'\n';}
    }
}
