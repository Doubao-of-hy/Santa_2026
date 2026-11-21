// Find the same unknown base after removing an independently chosen scale and
// offset from several large integers. Rebuild all profitable consumers jointly.
#define main smooth_interval_entry
#include "smooth_windows.cpp"
#undef main
#include <memory>
#include <numeric>
using U=uint64_t;
struct Branch {I k,r;int weight;};
struct Member {int root;vector<Branch> options;};
struct Hub {I v;U mask;vector<Member> members;int score;};
struct Row {
    I cap;
    int radius,limit;
    vector<I> seeds,goals,roots;
    vector<Edge> graph;
    unordered_map<I,Edge> recipes;
    unordered_map<I,int> order;
    vector<int> perroot;
    vector<I> scales;
    vector<Branch> small;
    unique_ptr<Search> any;
    struct Cut {int dropped;vector<I> free;};
    map<U,Cut> cuts;
    vector<pair<int,Plan>> proposals;
    long long collisions=0;
    Cut makecut(U mask){
        unordered_set<I> removed;
        for(size_t i=0;i<roots.size();++i)if(mask&(U(1)<<i))removed.insert(roots[i]);
        vector<I> stack=goals;unordered_set<I> keep;
        while(!stack.empty()){
            I v=stack.back();stack.pop_back();
            if(removed.count(v)||!recipes.count(v)||!keep.insert(v).second)continue;
            auto e=recipes.at(v);stack.push_back(e.a);stack.push_back(e.b);
        }
        unordered_set<I> available(seeds.begin(),seeds.end());
        vector<I> free=seeds;
        for(auto e:graph)if(keep.count(e.out)&&available.count(e.a)&&available.count(e.b)){
            free.push_back(e.out);available.insert(e.out);
        }
        return {int(graph.size()-keep.size()),move(free)};
    }
    const Cut& cut(U mask){
        auto it=cuts.find(mask);if(it!=cuts.end())return it->second;
        return cuts.emplace(mask,makecut(mask)).first->second;
    }
    template<class F>void options(int t,F fn){
        I x=roots[t];
        for(I k:scales){
            if(k> (x+radius)/4096)break;
            I first=max(I(4096),(max(I(1),x-radius)+k-1)/k);
            I last=min(cap/k,(min(cap,x+radius))/k);
            int kcost=k==1?0:any->basic(k).cost;
            for(I h=first;h<=last;++h){
                I r=x-h*k;
                if(h==x || (r && abs(r)==x))continue;
                int rw=r?small[abs(r)].weight:0;
                if(rw>1)continue;
                int w=int(k!=1)+int(r!=0)+kcost+rw;
                if(w>=perroot[t]+3)continue;
                fn(h,Branch{k,r,w});
            }
        }
    }
    void prepare(){
        vector<I> full=seeds;
        for(auto e:graph){
            order[e.out]=int(full.size());recipes[e.out]=e;full.push_back(e.out);
        }
        any=make_unique<Search>(cap,-1,0,radius,0,full);
        vector<I> list=full;
        for(auto kv:any->one)list.push_back(kv.first);
        list.push_back(1);sort(list.begin(),list.end());
        list.erase(unique(list.begin(),list.end()),list.end());scales=move(list);
        small.resize(radius+1);
        for(int i=1;i<=radius;++i)small[i].weight=any->basic(i).cost;
        for(size_t i=0;i<roots.size();++i)perroot.push_back(cut(U(1)<<i).dropped);
    }
    static void merge_edges(Plan& out,unordered_set<I>& made,const Plan& add){
        for(auto e:add)if(made.insert(e.out).second)out.push_back(e);
    }
    static bool derive(Search& local,I x,Plan& out,unordered_set<I>& made){
        if(made.count(x))return true;
        if(local.cheap(x).cost>2)return false;
        local.append(x,{},out,made);return true;
    }
    bool hubplan(Search& local,const Hub& h,U group,Plan& result){
        I x=h.v;
        unordered_set<I> made=local.paid;
        if(derive(local,x,result,made))return true;
        // Invert a complete observed branch. A preserved target can anchor its
        // own latent scale, even if its original register schedule never did.
        vector<Plan> alternatives;
        for(auto& m:h.members){
            I t=roots[m.root];
            if((group&(U(1)<<m.root))||!local.paid.count(t))continue;
            for(auto b:m.options){
                Plan plan;auto known=local.paid;
                if(b.k!=1&&!derive(local,b.k,plan,known))continue;
                if(b.r && !derive(local,abs(b.r),plan,known))continue;
                I prod=x*b.k;
                if(b.r && known.insert(prod).second)plan.push_back({prod,t,abs(b.r),b.r>0?'-':'+'});
                if(b.k!=1 && known.insert(x).second)plan.push_back({x,prod,b.k,'/'});
                if(known.count(x))alternatives.push_back(move(plan));
            }
        }
        for(I a:local.atoms){
            auto tryx=[&](I b,char op,bool first){
                if(b==x||b<1||b>cap||local.cheap(b).cost>2)return;
                Plan plan;auto known=local.paid;derive(local,b,plan,known);
                plan.push_back({x,first?b:a,first?a:b,op});alternatives.push_back(move(plan));
            };
            if(x>a)tryx(x-a,'+',true);
            if(x<=cap-a)tryx(x+a,'-',true);
            if(a>x)tryx(a-x,'-',false);
            if(x%a==0)tryx(x/a,'*',true);
            if(x<=cap/a)tryx(x*a,'/',true);
            if(a%x==0)tryx(a/x,'/',false);
            if(!alternatives.empty()&&alternatives.back().size()<=3)break;
        }
        if(alternatives.empty())return false;
        result=*min_element(alternatives.begin(),alternatives.end(),[](auto&a,auto&b){return a.size()<b.size();});
        return true;
    }
    void materialize(Search& local,const Hub& h,U group,int threshold){
        Plan proposal;if(!hubplan(local,h,group,proposal))return;
        unordered_set<I> made=local.paid;
        for(auto e:proposal)made.insert(e.out);
        if(int(proposal.size())>=threshold)return;
        for(auto&m:h.members)if(group&(U(1)<<m.root)){
            I t=roots[m.root];if(made.count(t))continue;
            bool have=false;Plan best;
            for(auto b:m.options){
                Plan path;auto known=made;
                if(b.k!=1 && !derive(local,b.k,path,known))continue;
                if(b.r && !derive(local,abs(b.r),path,known))continue;
                I product=h.v*b.k;
                if(b.k!=1 && known.insert(product).second)path.push_back({product,h.v,b.k,'*'});
                if(b.r && known.insert(t).second)path.push_back({t,product,abs(b.r),b.r>0?'+':'-'});
                if(!have||path.size()<best.size()){best=move(path);have=true;}
            }
            if(!have)return;
            merge_edges(proposal,made,best);
            if(int(proposal.size())>=threshold)return;
        }
        proposals.emplace_back(threshold-int(proposal.size()),move(proposal));
    }
    void run(){
        prepare();
        unordered_map<I,U> mask;
        for(int i=0;i<(int)roots.size();++i)options(i,[&](I h,Branch){mask[h]|=U(1)<<i;});
        unordered_map<I,Hub> hubs;
        for(auto entry:mask)if(__builtin_popcountll(entry.second)>=2){
            hubs.emplace(entry.first,Hub{entry.first,entry.second,{},0});
        }
        collisions=hubs.size();if(hubs.empty())return;
        mask.clear();mask.rehash(0);
        for(int i=0;i<(int)roots.size();++i)options(i,[&](I h,Branch b){
            auto it=hubs.find(h);if(it==hubs.end())return;
            auto& members=it->second.members;
            if(members.empty()||members.back().root!=i)members.push_back({i,{}});
            auto& choices=members.back().options;
            choices.push_back(b);
            stable_sort(choices.begin(),choices.end(),[](Branch a,Branch b){return a.weight<b.weight;});
            if(choices.size()>3)choices.pop_back();
        });
        // A provisional price ranks competing centers of the same cluster. The
        // actual graph prices below use only retained, cycle-free operands.
        map<U,vector<pair<int,I>>> groups;
        for(auto& kv:hubs){
            auto& h=kv.second;
            vector<U> subsets{h.mask};
            for(auto m:h.members)subsets.push_back(h.mask^(U(1)<<m.root));
            for(auto group:subsets){
                int raw=0;for(auto &m:h.members)if(group&(U(1)<<m.root))raw+=m.options[0].weight;
                int cheap=min(3,any->basic(h.v).cost);
                int gain=cut(group).dropped-raw-cheap;
                if(gain < -2)continue;
                groups[group].emplace_back(gain,h.v);
            }
        }
        vector<pair<int,U>> selected;
        for(auto& g:groups){
            auto& rows=g.second;sort(rows.rbegin(),rows.rend());
            if(rows.size()>32)rows.resize(32);
            selected.emplace_back(rows[0].first,g.first);
        }
        sort(selected.rbegin(),selected.rend());
        if(int(selected.size())>limit)selected.resize(limit);
        for(auto [score,group]:selected){
            auto& c=cut(group);if(c.dropped<=2)continue;
            Search local(cap,-1,0,radius,0,c.free);
            for(auto [estimate,anchor]:groups.at(group))materialize(local,hubs.at(anchor),group,c.dropped);
        }
        stable_sort(proposals.begin(),proposals.end(),[](const auto&a,const auto&b){return a.first>b.first;});
        if(proposals.size()>64)proposals.resize(64);
    }
};
int main(int argc,char**argv){
    if(argc!=3)return 2;
    ios::sync_with_stdio(false);cin.tie(nullptr);
    Row r;int ns,nt,nr,n;
    if(!(cin>>r.cap>>ns>>nt>>nr>>n))return 0;
    auto read=[&](int n,vector<I>& data){for(int i=0;i<n;++i){I x;cin>>x;data.push_back(x);}};
    read(ns,r.seeds);read(nt,r.goals);read(nr,r.roots);
    if(r.roots.size()>63)return 3;
    for(int i=0;i<n;++i){Edge e;cin>>e.out>>e.op>>e.a>>e.b;r.graph.push_back(e);}
    r.radius=stoi(argv[1]);r.limit=stoi(argv[2]);r.run();
    cout<<r.collisions<<' '<<r.proposals.size()<<'\n';
    for(auto& p:r.proposals){cout<<p.first<<' '<<p.second.size()<<'\n';for(auto e:p.second)cout<<e.out<<' '<<e.op<<' '<<e.a<<' '<<e.b<<'\n';}
}
