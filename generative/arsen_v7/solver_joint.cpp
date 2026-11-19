// SPDX-License-Identifier: Apache-2.0
// Original multi-output private-cone resynthesis. No embedded puzzle programs.
#define CUT_LIBRARY
#include "solver_fast.cpp"

vector<char> joint_live(Graph &g,const vector<int>& roots) {
    vector<char> live(g.nodes.size()),stop(g.nodes.size());for(int r:roots)stop[r]=1;
    function<void(int)> go=[&](int k){if(live[k])return;live[k]=1;auto r=g.nodes[k];if(!stop[k]&&r.op){go(r.left);go(r.right);}};
    for(int k:g.goals)go(k);return live;
}

// Build independently, then merge equal-valued subexpressions. Try each output
// first so later outputs may reuse both its result and its new helper values.
bool synthesize(Graph &g, const vector<int>& roots, int variant, Graph &answer) {
    auto live=joint_live(g,roots);vector<char> stop(g.nodes.size());for(int k:roots)stop[k]=1;
    int removed=roots.size();for(int j=0;j<(int)live.size();j++)removed+=!live[j]&&g.nodes[j].op;
    if(removed<=(int)roots.size()||removed>22)return false;
    vector<int> memo(g.nodes.size(),-1);
    function<bool(int)> dep=[&](int v){if(stop[v])return true;if(memo[v]>=0)return (bool)memo[v];auto r=g.nodes[v];return (bool)(memo[v]=r.op&&(dep(r.left)||dep(r.right)));};
    vector<int> ids;for(int j=0;j<(int)live.size();j++)if((live[j]||!g.nodes[j].op)&&!dep(j))ids.push_back(j);
    if(ids.empty())return false;
    Join initial(g,ids);
    vector<I> goals;for(int k:roots)goals.push_back(g.nodes[k].value);
    auto install=[&](Plan plan)->bool {
        Graph h=g;h.at.clear();for(int j:ids)h.at[h.nodes[j].value]=j;
        for(auto d:plan){if(h.at.count(d.v))continue;if(!h.at.count(d.a)||!h.at.count(d.b))return false;h.make(d.op,h.at.at(d.a),h.at.at(d.b));}
        for(int k:roots){I v=g.nodes[k].value;if(!h.at.count(v))return false;h.nodes[k]=h.nodes[h.at.at(v)];}
        try {h=clean(h);}catch(exception&){return false;}
        if(h.nodes.size()<g.nodes.size()){answer=move(h);return true;}return false;
    };
    // Common new helper: each cut output must be reachable in one instruction
    // using it and an already-retained value. The helper may cost up to 3 ops.
    if(removed>(int)roots.size()+1) {
        map<I,vector<Definition>> candidates;
        I t=goals[0];
        for(I a:initial.leaves)initial.inverses(t,a,[&](I h,Definition d){if(h!=t&&!initial.free.count(h))candidates.try_emplace(h,vector<Definition>{d});});
        for(int k=1;k<(int)goals.size()&&!candidates.empty();k++) {
            unordered_map<I,Definition> next;
            for(I a:initial.leaves)initial.inverses(goals[k],a,[&](I h,Definition d){if(candidates.count(h))next.emplace(h,d);});
            for(auto it=candidates.begin();it!=candidates.end();) {
                auto hit=next.find(it->first);if(hit==next.end())it=candidates.erase(it);
                else {it->second.push_back(hit->second);++it;}
            }
        }
        for(auto &kv:candidates) {
            Plan p;int budget=removed-goals.size()-1;
            bool ok=budget==1?initial.cheap(kv.first,p):budget==2?initial.two(kv.first,p):initial.three(kv.first,p,variant);
            if(!ok)continue;p.insert(p.end(),kv.second.begin(),kv.second.end());
            if(install(p))return true;
        }
    }
    // Cheap sequential repairs expose reuse missed by single-root cuts.
    for(int shift=0;shift<(int)roots.size();shift++) {
        Graph temp=g;temp.at.clear();for(int j:ids)temp.at[temp.nodes[j].value]=j;
        auto available=ids;Plan all;bool fail=false;
        for(int j=0;j<(int)roots.size();j++) {
            I t=goals[(j+shift)%goals.size()];Join join(temp,available);Plan part;
            int budget=min(3,removed-1-(int)all.size()-((int)roots.size()-j-1));
            bool ok=budget<=0?false:budget==1?join.cheap(t,part):budget==2?join.two(t,part):join.three(t,part,variant);
            if(!ok){fail=true;break;}
            for(auto d:part){if(temp.at.count(d.v))continue;int idx=temp.make(d.op,temp.at.at(d.a),temp.at.at(d.b));available.push_back(idx);all.push_back(d);}
        }
        if(!fail&&install(all))return true;
    }
    return false;
}

int main(int argc,char**argv) {
    int rounds=argc>1?stoi(argv[1]):2,variant=argc>2?stoi(argv[2]):0;
    string id;I limit;int ns,nt;
    while(cin>>id>>limit>>ns>>nt) {
        Graph g;g.limit=limit;for(int i=0;i<ns;i++){I x;cin>>x;g.seeds.push_back(g.add(x));}
        vector<I> targets(nt);for(I&x:targets)cin>>x;
        int n;cin>>n;vector<int> bank(48,-1);for(int i=0;i<ns;i++)bank[i]=g.seeds[i];
        vector<array<int,4>> best;
        for(int i=0;i<n;i++){char op;int a,b,d;cin>>op>>a>>b>>d;bank[d]=g.make(op,bank[a],bank[b]);best.push_back({op,a,b,d});}
        for(I x:targets)g.goals.push_back(g.at.at(x));g=clean(g);
        for(int round=0;round<rounds;round++) {
            vector<I> pivots;for(auto r:g.nodes)if(r.op)pivots.push_back(r.value);
            if((round+variant)%2)reverse(pivots.begin(),pivots.end());bool changed=false;
            for(I pivot:pivots) {
                if(!g.at.count(pivot))continue;int k=g.at.at(pivot);
                vector<vector<int>> users(g.nodes.size());vector<char> isgoal(g.nodes.size());for(int t:g.goals)isgoal[t]=1;
                for(int j=0;j<(int)g.nodes.size();j++){auto r=g.nodes[j];if(!r.op)continue;users[r.left].push_back(j);if(r.left!=r.right)users[r.right].push_back(j);}
                if(isgoal[k]||users[k].size()<2||users[k].size()>4)continue;
                vector<int> roots=users[k];bool accepted=false;
                for(int expansion=0;expansion<3&&!accepted;expansion++) {
                    sort(roots.begin(),roots.end());roots.erase(unique(roots.begin(),roots.end()),roots.end());
                    Graph h;if(synthesize(g,roots,variant,h)){g=move(h);changed=true;accepted=true;break;}
                    bool grew=false;
                    for(int &r:roots)if(!isgoal[r]&&users[r].size()==1){r=users[r][0];grew=true;}
                    if(!grew)break;
                }
            }
            if(!changed)break;
        }
        mt19937 rng(20261120);auto goals=g.goals;
        for(int s=0;s<48;s++){if(s==1)reverse(goals.begin(),goals.end());else if(s>1)shuffle(goals.begin(),goals.end(),rng);auto out=allocate(g,goals,s%2);if(out.size()<best.size())best=move(out);}
        cout<<id<<" [";for(int i=0;i<(int)best.size();i++){if(i)cout<<',';auto r=best[i];cout<<"[\""<<char(r[0])<<"\","<<r[1]<<','<<r[2]<<','<<r[3]<<']';}cout<<"]"<<endl;
    }
}
