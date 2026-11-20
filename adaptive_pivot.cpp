// After buying one helper, ground the entire unpaid old subgraph before
// looking for the second. Newly recovered old operands can change the repair.
#define PIVOT_LIBRARY
#include "pivot_bridge.cpp"
struct Adaptive : PivotBridge {
    struct Reference {int helper,operand;};
    vector<vector<Reference>> from;
    vector<char> isGoal;
    unordered_map<I,vector<Edge>> everyBirth;
    int firstTrials=0,bridges=0;
    void setup(){
        populate();from.resize(n);isGoal.assign(n,0);for(int g:goalids)isGoal[g]=1;
        for(int id=0;id<int(extras.size());id++)if(!extras[id].birth.empty())
            for(auto e:extras[id].use)from[e.v].push_back({id,e.a==n?e.b:e.a});
        for(int a=0;a<n;a++)for(int b=0;b<=a;b++)arithmetic(values[a],values[b],cap,[&](Op e){
            if(!lookup.count(e.v))everyBirth[e.v].push_back({n,e.a==values[a]?a:b,e.b==values[b]?b:a,e.op});
        });
    }
    Op op(Edge e,I h){
        auto val=[&](int v){return v==n?h:values[v];};
        return {val(e.v),val(e.a),val(e.b),e.op};
    }
    void adapt(const Case& trial,int maxFirst){
        attempts++;vector<U> have(n),allow(n,1);
        unordered_set<I> banned;
        for(int v:trial.banned){allow[v]=0;banned.insert(values[v]);}
        for(int s:seedids)have[s]=1;close(have,allow);
        if(have[trial.pivot])return;
        unordered_map<int,int> rank;
        for(int i=0;i<n;i++)if(allow[i]&&!have[i])for(auto ref:from[i])
            if(ref.operand==n||have[ref.operand])rank[ref.helper]+=1+2*isGoal[i]+5*(i==trial.pivot);
        vector<pair<int,int>> queue;queue.reserve(rank.size());
        for(auto [id,r]:rank){
            bool reachable=false;for(auto birth:extras[id].birth)if(have[birth.a]&&have[birth.b]){reachable=true;break;}
            if(reachable)queue.push_back({r*10+min(8,int(extras[id].use.size())),id});
        }
        sort(queue.rbegin(),queue.rend());if(queue.size()>size_t(maxFirst))queue.resize(maxFirst);
        for(auto [r,id]:queue){
            firstTrials++;const auto& c=extras[id];I h=c.value;
            vector<U> next=have;vector<Op> extra;
            for(auto e:c.birth)if(have[e.a]&&have[e.b]){extra.push_back(op(e,h));break;}
            for(auto e:c.use)extra.push_back(op(e,h));
            bool grew;
            do{grew=false;for(auto e:c.use){
                if(!next[e.v]&&allow[e.v]&&(e.a==n||next[e.a])&&(e.b==n||next[e.b])){
                    next[e.v]=1;grew=true;
                }
            }if(grew)close(next,allow);}while(grew);
            if(next[trial.pivot]){bridges++;witnessBridge(trial,extra);continue;}
            vector<I> anchors;for(int i=0;i<n;i++)if(next[i]&&!have[i])anchors.push_back(values[i]);
            for(int i=0;i<n;i++)if(have[i])anchors.push_back(values[i]);anchors.push_back(h);
            unordered_map<I,Op> withH;for(I a:anchors)arithmetic(a,h,cap,[&](Op e){withH.emplace(e.v,e);});
            bool found=false;
            joins(values[trial.pivot],anchors,[&](I x,Op last){
                if(found||banned.count(x)||lookup.count(x)||x==h)return;
                auto foundH=withH.find(x);
                if(foundH!=withH.end()){extra.push_back(foundH->second);}
                else{
                    auto it=everyBirth.find(x);if(it==everyBirth.end())return;
                    auto birth=find_if(it->second.begin(),it->second.end(),[&](Edge e){return next[e.a]&&next[e.b];});
                    if(birth==it->second.end())return;
                    extra.push_back(op(*birth,x));
                }
                extra.push_back(last);found=true;bridges++;witnessBridge(trial,extra);
            });
        }
    }
    void search(int maxCases,int numFirst,int perRoot,unsigned seed){
        setup();vector<vector<Case>> pool;
        for(int i=0;i<n;i++){
            if(find(seedids.begin(),seedids.end(),i)!=seedids.end())continue;
            auto can=removable(i);if(can.size()<banCount)continue;
            auto cases=screen(i,can,180,perRoot);if(!cases.empty())pool.push_back(move(cases));
        }
        mt19937 rng(seed);shuffle(pool.begin(),pool.end(),rng);
        for(int j=0;j<perRoot&&attempts<maxCases;j++)for(auto& root:pool){
            if(j<int(root.size()))adapt(root[j],numFirst);if(attempts>=maxCases)break;
        }
    }
};
int main(int argc,char**argv){
    ios::sync_with_stdio(false);cin.tie(nullptr);string id;int ns,nt,nop;
    while(cin>>id){
        Adaptive s;cin>>s.cap>>ns>>nt>>nop;s.seeds.resize(ns);s.goals.resize(nt);
        for(auto&v:s.seeds)cin>>v;for(auto&v:s.goals)cin>>v;
        for(int i=0;i<nop;i++){Op e;cin>>e.v>>e.op>>e.a>>e.b;s.original.push_back(e);}
        unsigned seed=61379;for(char c:id)seed=seed*137+unsigned(c);
        s.search(argc>1?stoi(argv[1]):30,argc>2?stoi(argv[2]):18,argc>3?stoi(argv[3]):4,seed);
        cout<<id<<' '<<s.attempts<<' '<<s.firstTrials<<' '<<s.bridges<<' '<<s.winners.size()<<'\n';
        for(auto& tape:s.winners){cout<<tape.size()<<'\n';for(auto e:tape)cout<<e.v<<' '<<e.op<<' '<<e.a<<' '<<e.b<<'\n';}
    }
}
