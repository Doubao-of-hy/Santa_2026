// SPDX-License-Identifier: Apache-2.0
// Original exhaustive depth-three cut repair with positive exact inverse joins.
#define main cut_main
// solver_v3 names its own main, so rename only its main with a wrapper macro.
#include "recovered/solver.cpp"
#undef main

struct Definition {I v,a,b;char op;};
using Plan=vector<Definition>;

vector<char> retained(Graph &g,int stop) {
    vector<char> live(g.nodes.size());
    function<void(int)> go=[&](int k){if(live[k])return;live[k]=1;auto r=g.nodes[k];if(k!=stop&&r.op){go(r.left);go(r.right);}};
    for(int k:g.goals)go(k);return live;
}
Graph clean(Graph &g) {
    Graph h;h.limit=g.limit;vector<int> ids(g.nodes.size(),-1);vector<char> active(g.nodes.size());
    for(int s:g.seeds){ids[s]=h.add(g.nodes[s].value);h.seeds.push_back(ids[s]);}
    function<int(int)> visit=[&](int k){if(ids[k]>=0)return ids[k];if(active[k])throw runtime_error("cycle");active[k]=1;auto r=g.nodes[k];int a=visit(r.left),b=visit(r.right);ids[k]=h.make(r.op,a,b);active[k]=0;return ids[k];};
    for(int k:g.goals)h.goals.push_back(visit(k));
    for(auto&r:h.nodes)if(r.op)r.cost=min(1000,1+h.nodes[r.left].cost+(r.left==r.right?0:h.nodes[r.right].cost));return h;
}

struct Join {
    I limit;vector<I> leaves;unordered_set<I> free;unordered_map<I,Definition> one;
    template<class F> void inverses(I v,I a,F f) {
        if(v>a)f(v-a,Definition{v,a,v-a,'+'});
        if(a>v)f(a-v,Definition{v,a,a-v,'-'});
        if(v<=limit-a)f(v+a,Definition{v,v+a,a,'-'});
        if(v%a==0)f(v/a,Definition{v,a,v/a,'*'});
        if(a%v==0)f(a/v,Definition{v,a,a/v,'/'});
        if(v<=limit/a)f(v*a,Definition{v,v*a,a,'/'});
    }
    Join(Graph&g,vector<int> ids):limit(g.limit) {
        for(int k:ids){I v=g.nodes[k].value;leaves.push_back(v);free.insert(v);}
        one.reserve(leaves.size()*leaves.size()*3);
        auto add=[&](I v,I a,I b,char op){if(v>0&&v<=limit&&!free.count(v))one.emplace(v,Definition{v,a,b,op});};
        for(int i=0;i<(int)leaves.size();i++)for(int j=0;j<=i;j++) {
            I a=leaves[i],b=leaves[j];add(a+b,a,b,'+');if(a!=b)add(abs(a-b),max(a,b),min(a,b),'-');
            if(a<=limit/b)add(a*b,a,b,'*');if(a%b==0)add(a/b,a,b,'/');if(b%a==0)add(b/a,b,a,'/');
        }
    }
    bool cheap(I v,Plan &p) {
        if(free.count(v))return true;auto it=one.find(v);if(it==one.end())return false;p.push_back(it->second);return true;
    }
    bool two(I v,Plan &p) {
        if(cheap(v,p))return true;
        I r=sqrtl((long double)v);while((__int128)r*r<v)r++;
        if((__int128)r*r==v&&cheap(r,p)){p.push_back({v,r,r,'*'});return true;}
        for(I a:leaves) {
            bool found=false;
            inverses(v,a,[&](I u,Definition d){if(found||u==v)return;Plan q;if(cheap(u,q)){q.push_back(d);p=move(q);found=true;}});
            if(found)return true;
        }return false;
    }
    bool three(I v,Plan &p,int variant) {
        if(two(v,p))return true;
        I r=sqrtl((long double)v);while((__int128)r*r<v)r++;
        if((__int128)r*r==v&&two(r,p)){p.push_back({v,r,r,'*'});return true;}
        // Balanced two-branch expressions, with duplicate constructions merged.
        vector<I> mids;for(auto &kv:one)mids.push_back(kv.first);sort(mids.begin(),mids.end());
        if(variant%2)reverse(mids.begin(),mids.end());
        for(I a:mids) {
            bool found=false;
            inverses(v,a,[&](I u,Definition d){if(found||u==v)return;Plan q;if(cheap(u,q)){
                if(u!=a)q.push_back(one.at(a));q.push_back(d);p=move(q);found=true;
            }});if(found)return true;
        }
        if(variant%2)reverse(leaves.begin(),leaves.end());
        for(I a:leaves) {
            bool found=false;
            inverses(v,a,[&](I u,Definition d){if(found||u==v)return;Plan q;if(two(u,q)){q.push_back(d);p=move(q);found=true;}});
            if(found)return true;
        }return false;
    }
};

int main(int argc,char**argv) {
    int rounds=argc>1?stoi(argv[1]):2, variant=argc>2?stoi(argv[2]):0;
    string id;I limit;int ns,nt;
    while(cin>>id>>limit>>ns>>nt) {
        Graph g;g.limit=limit;
        for(int i=0;i<ns;i++){I x;cin>>x;g.seeds.push_back(g.add(x));}
        vector<I> targets(nt);for(I&x:targets)cin>>x;
        int n;cin>>n;vector<int> bank(48,-1);for(int i=0;i<ns;i++)bank[i]=g.seeds[i];
        vector<array<int,4>> best;
        for(int i=0;i<n;i++){char op;int a,b,d;cin>>op>>a>>b>>d;bank[d]=g.make(op,bank[a],bank[b]);best.push_back({op,a,b,d});}
        for(I x:targets)g.goals.push_back(g.at.at(x));g=clean(g);
        for(int round=0;round<rounds;round++) {
            vector<I> order;for(auto r:g.nodes)if(r.op)order.push_back(r.value);
            if((round+variant)%2)reverse(order.begin(),order.end());bool changed=false;
            for(I target:order) {
                if(!g.at.count(target))continue;int k=g.at.at(target);auto live=retained(g,k);
                int removed=1;for(int j=0;j<(int)live.size();j++)removed+=!live[j]&&g.nodes[j].op;
                if(removed<2)continue;
                vector<int> memo(g.nodes.size(),-1);
                function<bool(int)> dep=[&](int v){if(v==k)return true;if(memo[v]>=0)return (bool)memo[v];auto r=g.nodes[v];return (bool)(memo[v]=r.op&&(dep(r.left)||dep(r.right)));};
                vector<int> ids;for(int j=0;j<(int)live.size();j++)if((live[j]||!g.nodes[j].op)&&!dep(j))ids.push_back(j);
                Join join(g,ids);Plan plan;
                bool ok=removed==2?join.cheap(target,plan):removed==3?join.two(target,plan):join.three(target,plan,variant);
                if(!ok||plan.size()>=removed)continue;
                Graph h=g;h.at.clear();for(int j:ids)h.at[h.nodes[j].value]=j;
                try {
                    for(auto d:plan)h.make(d.op,h.at.at(d.a),h.at.at(d.b));
                    h.nodes[k]=h.nodes[h.at.at(target)];h=clean(h);
                    if(h.nodes.size()<g.nodes.size()){g=move(h);changed=true;}
                }catch(exception&e){throw runtime_error(string("patch:")+e.what());}
            }
            if(!changed)break;
        }
        mt19937 rng(20261119);auto goals=g.goals;
        for(int s=0;s<24;s++) {
            if(s==1)reverse(goals.begin(),goals.end());else if(s>1)shuffle(goals.begin(),goals.end(),rng);
            auto out=allocate(g,goals,s%2);if(out.size()<best.size())best=move(out);
        }
        cout<<id<<" [";for(int i=0;i<(int)best.size();i++){if(i)cout<<',';auto r=best[i];cout<<"[\""<<char(r[0])<<"\","<<r[1]<<','<<r[2]<<','<<r[3]<<']';}cout<<"]"<<endl;
    }
}
