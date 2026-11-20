// Under selected primary deletions, price a realization by its SET of
// original donor-only values. Repeated uses of a donor cost only once.
#define main value_exchange_entry
#include "value_exchange.cpp"
#undef main
#include <array>
#include <set>
using Tape=vector<Op>;
constexpr int words=8,retain=3;
struct Label{
    array<U,words> bits{};int cost=0;
    bool operator==(const Label& other)const{return bits==other.bits;}
};
struct Labels{
    array<Label,retain> data{};int size=0;
    bool add(const Label& x,int length){
        for(int i=0;i<size;i++){
            if(data[i].cost>x.cost)continue;bool subset=true;
            for(int w=0;w<length;w++)if(data[i].bits[w]&~x.bits[w]){subset=false;break;}
            if(subset)return false;
        }
        for(int i=size-1;i>=0;i--){
            if(data[i].cost<x.cost)continue;bool subset=true;
            for(int w=0;w<length;w++)if(x.bits[w]&~data[i].bits[w]){subset=false;break;}
            if(subset){data[i]=data[size-1];size--;}
        }
        if(size<retain){data[size++]=x;return true;}
        int worst=0;
        for(int i=1;i<size;i++)if(data[i].cost>data[worst].cost)worst=i;
        if(x.cost>=data[worst].cost)return false;
        data[worst]=x;return true;
    }
};
struct DonorLabels : Search {
    vector<int> price,donorOnly;vector<char> primary;int nWords;
    vector<vector<int>> adjacent;int tests=0,feasible=0,changes=0;
    set<vector<I>> recorded;
    struct Rescue {vector<int> banned;Label label;};
    Label unite(const Label& a,const Label& b,int out=-1){
        Label x;
        for(int i=0;i<nWords;i++)x.bits[i]=a.bits[i]|b.bits[i];
        if(out>=0)x.bits[out/64]|=U(1)<<(out%64);
        for(int i=0;i<nWords;i++)x.cost+=__builtin_popcountll(x.bits[i]);
        return x;
    }
    vector<Label> realize(const vector<int>& banned,int maxCost){
        tests++;vector<char> allowed(n,1);for(int v:banned)allowed[v]=0;
        vector<Labels> witnessed(n);Label zero;for(int v:seedids)witnessed[v].add(zero,nWords);
        bool changed;
        do{changed=false;for(const auto& e:base){
            if(!allowed[e.v]||!witnessed[e.a].size||!witnessed[e.b].size)continue;
            auto& dst=witnessed[e.v];if(dst.size==1&&dst.data[0].cost==0)continue;
            for(int i=0;i<witnessed[e.a].size;i++)for(int j=0;j<witnessed[e.b].size;j++){
                auto x=unite(witnessed[e.a].data[i],witnessed[e.b].data[j],price[e.v]);
                if(x.cost<=maxCost&&dst.add(x,nWords))changed=true;
            }
        }}while(changed);
        Labels combined;combined.add(zero,nWords);
        for(int g:goalids){
            if(!witnessed[g].size)return {};
            Labels next;
            for(int i=0;i<combined.size;i++)for(int j=0;j<witnessed[g].size;j++){
                auto x=unite(combined.data[i],witnessed[g].data[j]);if(x.cost<=maxCost)next.add(x,nWords);
            }
            if(!next.size)return {};combined=next;
        }
        feasible++;return vector<Label>(combined.data.begin(),combined.data.begin()+combined.size);
    }
    void actual(const vector<int>& banned,const Label& mask,int incumbent){
        vector<int> denied=banned;
        for(int i=0;i<int(donorOnly.size());i++)if(!(mask.bits[i/64]&(U(1)<<(i%64))))denied.push_back(donorOnly[i]);
        auto tape=witness(nullptr,denied);if(tape.empty())throw runtime_error("unrooted donor label");
        if(int(tape.size())>=incumbent)return;
        vector<I> key;for(auto e:tape)key.push_back(e.v);sort(key.begin(),key.end());
        if(!recorded.insert(key).second)return;
        changes++;winners.push_back(move(tape));
        stable_sort(winners.begin(),winners.end(),[](const Tape&a,const Tape&b){return a.size()<b.size();});
        if(winners.size()>8)winners.pop_back();
    }
    void run(const Tape& parent,const Tape& donor,int maxGroups,int maxCost,unsigned seed){
        unordered_set<I> seen;original=parent;
        for(auto e:parent)seen.insert(e.v);for(auto e:donor)if(seen.insert(e.v).second)original.push_back(e);
        populate(false);primary.assign(n,0);price.assign(n,-1);
        for(int v:seedids)primary[v]=1;for(auto e:parent)primary[lookup.at(e.v)]=1;
        for(int v=0;v<n;v++)if(!primary[v]){price[v]=donorOnly.size();donorOnly.push_back(v);}
        if(donorOnly.empty()||donorOnly.size()>64*words)return;
        nWords=(donorOnly.size()+63)/64;adjacent.resize(n);
        auto link=[&](int a,int b){if(a!=b){adjacent[a].push_back(b);adjacent[b].push_back(a);}};
        for(auto e:parent){int v=lookup.at(e.v),a=lookup.at(e.a),b=lookup.at(e.b);link(v,a);link(v,b);link(a,b);}
        vector<int> deletable;for(auto& b:batches){U free=b.live;for(int t:goalids)free&=b.reach[t];
            while(free){int k=__builtin_ctzll(free);free&=free-1;int v=b.banned[k];if(primary[v])deletable.push_back(v);}
        }
        mt19937 rng(seed);shuffle(deletable.begin(),deletable.end(),rng);
        // A primary singleton can be repaired by a short chain of donor
        // integers even when it cannot be repaired by any one rooted integer.
        vector<Rescue> rescues;set<vector<int>> tried;
        for(int v:deletable){
            if(tests>=maxGroups/2)break;
            vector<int> split{v};auto plans=realize(split,maxCost);tried.insert(split);
            for(auto& label:plans){actual(split,label,parent.size());rescues.push_back({split,label});}
        }
        vector<pair<int,vector<int>>> groups;
        auto offer=[&](vector<int> group,int merit){
            sort(group.begin(),group.end());group.erase(unique(group.begin(),group.end()),group.end());
            if(group.size()>1&&tried.insert(group).second)groups.emplace_back(merit+rng()%40,move(group));
        };
        for(int i=0;i<int(rescues.size());i++)for(int j=0;j<i;j++){
            int a=rescues[i].banned[0],b=rescues[j].banned[0];if(a==b)continue;
            int shared=0;for(int w=0;w<nWords;w++)shared+=__builtin_popcountll(rescues[i].label.bits[w]&rescues[j].label.bits[w]);
            int close=find(adjacent[a].begin(),adjacent[a].end(),b)!=adjacent[a].end();
            if(!shared&&!close)continue;
            int merit=45*shared+35*close-5*(rescues[i].label.cost+rescues[j].label.cost);
            offer({a,b},merit);
            for(int c:adjacent[b])if(c!=a&&find(deletable.begin(),deletable.end(),c)!=deletable.end())offer({a,b,c},merit+15);
        }
        set<int> eligible(deletable.begin(),deletable.end());
        for(int a:deletable)for(int b:adjacent[a])if(eligible.count(b)){
            offer({a,b},20);for(int c:adjacent[b])if(eligible.count(c)&&a!=c){
                offer({a,b,c},30);for(int d:adjacent[c])if(eligible.count(d)&&a!=d&&b!=d)offer({a,b,c,d},35);
            }
        }
        sort(groups.rbegin(),groups.rend());
        for(auto& [rank,split]:groups){
            if(tests>=maxGroups)break;auto plans=realize(split,maxCost);
            for(auto& label:plans)actual(split,label,parent.size());
        }
    }
};
int main(int argc,char**argv){
    ios::sync_with_stdio(false);cin.tie(nullptr);string id;int ns,nt,n1,n2;
    while(cin>>id){
        DonorLabels s;cin>>s.cap>>ns>>nt>>n1>>n2;s.seeds.resize(ns);s.goals.resize(nt);Tape a(n1),b(n2);
        for(auto& v:s.seeds)cin>>v;for(auto&v:s.goals)cin>>v;
        for(auto t:{&a,&b})for(auto&e:*t)cin>>e.v>>e.op>>e.a>>e.b;
        unsigned seed=97219;for(char c:id)seed=seed*137+unsigned(c);
        s.run(a,b,argc>1?stoi(argv[1]):60,argc>2?stoi(argv[2]):6,seed);
        cout<<id<<' '<<s.tests<<' '<<s.feasible<<' '<<s.changes<<' '<<s.winners.size()<<'\n';
        for(auto& tape:s.winners){cout<<tape.size()<<'\n';for(auto&e:tape)cout<<e.v<<' '<<e.op<<' '<<e.a<<' '<<e.b<<'\n';}
    }
}
