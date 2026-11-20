#include <algorithm>
#include <array>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <numeric>
#include <random>
#include <map>
#include <set>
#include <unordered_map>
#include <unordered_set>
#include <vector>
using namespace std;
using V=vector<int>;
struct Step {int v,a,b;};
using Path=vector<Step>;
int lim,nstart,global_best;
V seeds,goals; mt19937 gen;
vector<unsigned char> old_helper; bool guided=false;
int pick(int n){return uniform_int_distribution<int>(0,n-1)(gen);}
double unit(){return generate_canonical<double,24>(gen);}
template<class F> void ops(int a,int b,F f){
    if(a<b)swap(a,b);
    if(a+b<=lim)f(a+b); if(a!=b)f(a-b);
    if(a<=lim/b)f(a*b); if(!(a%b))f(a/b);
}
template<class F> void reverse_op(int t,int a,F f){
    if(t==a)return;
    if(t>a)f(t-a);else f(a-t);
    if(t+a<=lim)f(t+a); if(t<=lim/a)f(t*a);
    if(!(t%a))f(t/a); if(!(a%t))f(a/t);
}
struct Node{int a,b,cost;};
vector<int> tag;vector<Node> nodes; int stamp=0;
vector<unsigned> sample_tag; unsigned sample_round;
vector<int> pressure_tag; int pressure_round;
bool has(int x){return tag[x]==stamp;}
void put(int v,int a,int b,int depth,V &layer){
    if(has(v))return;
    tag[v]=stamp;nodes[v]={a,b,depth};layer.push_back(v);
}
void make_bank(V anchors, V& all,V& direct,V& two){
    ++stamp;shuffle(anchors.begin(),anchors.end(),gen);
    for(int a:anchors)put(a,0,0,0,all);
    for(int i=0;i<anchors.size();++i)for(int j=0;j<=i;++j)
        ops(anchors[i],anchors[j],[&](int y){put(y,anchors[i],anchors[j],1,direct);});
    shuffle(direct.begin(),direct.end(),gen);
    for(int x:direct){
        for(int a:anchors)ops(x,a,[&](int y){put(y,x,a,2,two);});
        ops(x,x,[&](int y){put(y,x,x,2,two);});
    }
    all.insert(all.end(),direct.begin(),direct.end()); all.insert(all.end(),two.begin(),two.end());
    if(anchors.size()<=8){
        V third;shuffle(two.begin(),two.end(),gen);
        for(int x:two){
            for(int a:anchors)ops(x,a,[&](int y){put(y,x,a,3,third);});
            ops(x,x,[&](int y){put(y,x,x,3,third);});
        }
        for(int i=0;i<direct.size();++i)for(int j=0;j<i;++j)
            ops(direct[i],direct[j],[&](int y){put(y,direct[i],direct[j],3,third);});
        all.insert(all.end(),third.begin(),third.end());
    }
}
Path trim(const Path& pg,const V& wanted){
    unordered_set<int> used(wanted.begin(),wanted.end()); Path ret;
    for(auto i=pg.rbegin();i!=pg.rend();++i)if(used.count(i->v)){
        ret.push_back(*i); used.insert(i->a);used.insert(i->b);
    }
    reverse(ret.begin(),ret.end());return ret;
}
struct Context{
    double best=1e9,noise=0,share=0,like=0;Path path;
    void try_path(const Step* s,int n){
        ++sample_round; int ncost=0,np=0,old_cost=0;
        for(int i=0;i<n;i++){
            int v=s[i].v;
            if(sample_tag[v]==sample_round || (has(v)&&nodes[v].cost==0))continue;
            sample_tag[v]=sample_round;ncost++;np+=pressure_tag[v]==pressure_round;old_cost+=old_helper[v];
        }
        if(!ncost)return;
        double score=ncost-.35*share*np+(guided?1.2*old_cost:0);
        if(score>best+noise)return;
        score+=noise*unit();
        if(score>=best)return;
        best=score;path.clear();++sample_round;
        for(int i=0;i<n;i++)if(sample_tag[s[i].v]!=sample_round && !(has(s[i].v)&&nodes[s[i].v].cost==0)){
            sample_tag[s[i].v]=sample_round;path.push_back(s[i]);
        }
    }
};
int unfold(int v,Step*out){
    if(nodes[v].cost==0)return 0;
    const auto&a=nodes[v];
    int k=unfold(a.a,out);
    if(a.a!=a.b)k+=unfold(a.b,out+k);
    out[k]={v,a.a,a.b};return k+1;
}
Path route(const V&anchors,int target,const Path&fallback,const V&hints){
    V all,direct,two;
    make_bank(anchors,all,direct,two);
    Context c;c.noise=unit()*3.0;c.share=unit();
    ++pressure_round;
    if(pick(5))for(int v:hints)pressure_tag[v]=pressure_round;
    if(!fallback.empty()){
        unordered_set<int> need{target};
        Path rest;
        for(auto j=fallback.rbegin();j!=fallback.rend();++j){
            if(!need.count(j->v) || (has(j->v)&&nodes[j->v].cost==0))continue;
            rest.push_back(*j);need.insert(j->a);need.insert(j->b);
        }
        reverse(rest.begin(),rest.end());if(!rest.empty())c.try_path(rest.data(),rest.size());
    }
    V scan=direct;scan.insert(scan.end(),anchors.begin(),anchors.end());
    auto test=[&](int r,int a,bool self=false){
        if(r==target&&a)return;
        auto price=[&](int x,int y){
            if(!has(x)||!has(y)||x==r||y==r||x==target||y==target)return;
            Step data[48];int k=unfold(x,data);
            if(x!=y)k+=unfold(y,data+k);
            data[k++]={r,x,y};
            if(a)data[k++]={target,r,self?r:a};
            c.try_path(data,k);
        };
        if(has(r)){
            Step data[48];int k=unfold(r,data);
            if(a)data[k++]={target,r,self?r:a};
            if(k)c.try_path(data,k);
        }
        if(r%2==0)price(r/2,r/2);
        int sq=(int)sqrt(r);if(sq*sq==r)price(sq,sq);
        const V& items=a?scan:all;
        for(int x:items)reverse_op(r,x,[&](int y){if(y<=lim)price(x,y);});
        if(a)for(int x=2;x<=r/x;++x)if(!(r%x))price(x,r/x);
    };
    test(target,0);
    for(int a:anchors)reverse_op(target,a,[&](int r){test(r,a);});
    if(target%2==0)test(target/2,target/2,true);
    int sq=(int)sqrt(target);if(sq*sq==target)test(sq,sq,true);
    return c.path;
}
uint64_t key(const Path& p){
    uint64_t h=0;for(auto s:p){uint64_t x=s.v+0x9e3779b97f4a7c15ULL;
        x=(x^(x>>30))*0xbf58476d1ce4e5b9ULL; x=(x^(x>>27))*0x94d049bb133111ebULL; h^=x^(x>>31);}
    return h;
}
void report(int it,const Path& p){
    cout<<"WIN "<<it<<" "<<p.size()<<endl;for(auto s:p)cout<<s.v<<" "<<s.a<<" "<<s.b<<"\n";cout<<flush;
}
Path prune(Path path){
    if(path.size()+seeds.size()>60)return path;
    V vals=seeds;
    for(auto s:path)vals.push_back(s.v);
    int n=vals.size();
    vector<vector<uint64_t>> make(n);
    unordered_map<int,int> idx;
    for(int i=0;i<n;++i)idx[vals[i]]=i;
    for(int i=0;i<n;++i)for(int j=0;j<=i;++j)
        ops(vals[i],vals[j],[&](int v){
            auto it=idx.find(v);
            if(it!=idx.end()&&it->second>=nstart&&it->second!=i&&it->second!=j)
                make[it->second].push_back((1ULL<<i)|(1ULL<<j));});
    uint64_t start=(1ULL<<nstart)-1, goal=0;
    for(int v:goals)goal|=1ULL<<idx.at(v);
    V helpers;
    for(int i=nstart;i<n;++i)if(!(goal>>i&1))helpers.push_back(i);
    auto close=[&](uint64_t forbid,Path* save){
        uint64_t available=start;
        for(;;){
            auto old=available;
            for(int i=nstart;i<n;++i){
                if((available|forbid)>>i&1)continue;
                for(auto need:make[i])if((available&need)==need){
                    available|=1ULL<<i;
                    if(save){int a=__builtin_ctzll(need),b=63-__builtin_clzll(need);save->push_back({vals[i],vals[a],vals[b]});}
                    break;
                }
            }
            if((goal&available)==goal)return true;
            if(available==old)return false;
        }
    };
    int repeat=2;
    for(int j=0;j<repeat;++j){
        shuffle(helpers.begin(),helpers.end(),gen);
        uint64_t forbid=0;
        for(int i:helpers){uint64_t m=forbid|(1ULL<<i);if(close(m,nullptr))forbid=m;}
        if(n-nstart-__builtin_popcountll(forbid)<(int)path.size()){
            Path out;close(forbid,&out);path=trim(out,goals);
        }
    }
    return path;
}

struct Cell {
    vector<Path> examples;
    unordered_set<uint64_t> seen;
    long long visits = 0;
    int first = -1;
};
map<pair<int,int>,Cell> frontier;
void note(const Path& path,int iteration) {
    if(path.size()>34)return;
    int old=0;
    for(const auto& step:path)old+=old_helper[step.v];
    auto& cell=frontier[{int(path.size()),old}];
    if(!cell.visits)cell.first=iteration;
    ++cell.visits;
    auto hash=key(path);
    if(!cell.seen.insert(hash).second)return;
    if(cell.examples.size()<8)cell.examples.push_back(path);
    else cell.examples[(hash>>8)%cell.examples.size()]=path;
}
Path choose_novel() {
    double penalty=.4+2.1*unit(), best=1e9;
    vector<const Cell*> eligible;
    for(auto &item:frontier){
        auto [steps,old]=item.first;
        double loss=steps+penalty*max(0,old-4);
        best=min(best,loss);
    }
    double tolerance=pick(4)==0?2.5:.75;
    for(auto &item:frontier){
        auto [steps,old]=item.first;
        if(steps+penalty*max(0,old-4)<=best+tolerance)eligible.push_back(&item.second);
    }
    const auto& bin=eligible[pick(eligible.size())]->examples;
    return bin[pick(bin.size())];
}

int main(int argc,char**argv){
    int nt,parents,seed=stoi(argv[1]),iterations=stoi(argv[2]);gen.seed(seed);
    cin>>lim>>nstart>>nt>>parents>>global_best;seeds.resize(nstart);goals.resize(nt);
    for(int&v:seeds)cin>>v;for(int&v:goals)cin>>v;
    tag.resize(lim+1);nodes.resize(lim+1);sample_tag.resize(lim+1);pressure_tag.resize(lim+1);
    vector<vector<Path>> population(global_best+9);unordered_set<uint64_t> hashes;
    for(int i=0;i<parents;++i){int n;cin>>n;Path p(n);for(auto &s:p)cin>>s.v>>s.a>>s.b;
        hashes.insert(key(p));population[n].push_back(p);}
    guided=argc>3 && string(argv[3])=="guided";
    int nold;cin>>nold;old_helper.resize(lim+1);
    for(int i=0,v;i<nold;++i){cin>>v;old_helper.at(v)=1;}
    for(const auto& bucket:population)for(const auto& p:bucket)note(p,-1);
    auto initial=population;
    for(int it=0;it<iterations;++it){
        vector<int> lens;for(int l=global_best;l<population.size();++l)if(!population[l].empty()){
            int copies=1+(l==global_best?6:l==global_best+1?4:l==global_best+2?2:0);
            while(copies--)lens.push_back(l);
        }
        int len=lens[pick(lens.size())];auto &bucket=population[len];Path parent=bucket[pick(bucket.size())];if(guided && pick(5))parent=choose_novel();
        int num_drop=1+pick(nt);V order=goals;shuffle(order.begin(),order.end(),gen);
        V retained(order.begin()+num_drop,order.end()),hints;
        double hold=unit()*.65;
        if(pick(5)==0)hold=0;
        for(auto s:parent)if(unit()<hold && find(order.begin(),order.begin()+num_drop,s.v)==order.begin()+num_drop)
            retained.push_back(s.v);
        Path curr=trim(parent,retained);V act=seeds;
        for(auto s:curr)act.push_back(s.v);
        for(auto s:parent)if(pick(4))hints.push_back(s.v);
        for(int t:order){
            if(find(act.begin(),act.end(),t)!=act.end())continue;
            auto p=route(act,t,parent,hints);if(p.empty())break;
            for(auto s:p){curr.push_back(s);act.push_back(s.v);}
        }
        if(!all_of(goals.begin(),goals.end(),[&](int v){return find(act.begin(),act.end(),v)!=act.end();}))continue;
        curr=trim(curr,goals);if(curr.size()<=global_best+7)curr=prune(curr);int n=curr.size();
        note(curr,it);
        if(n<global_best){global_best=n;report(it,curr);}
        if(n>global_best+5 || n>=population.size())continue;
        uint64_t k=key(curr);if(!hashes.insert(k).second)continue;
        auto& bank=population[n];
        if(bank.size()<160)bank.push_back(curr);else bank[pick(bank.size())]=curr;
        if(it%2000==0)cerr<<"iter "<<it<<" unique "<<hashes.size()<<" best "<<global_best<<"\n";
    }
    for(auto& item:frontier){
        auto [n,old]=item.first;
        const auto& cell=item.second;
        cout<<"CELL "<<n<<" "<<old<<" "<<cell.visits<<" "<<cell.seen.size()<<" "<<cell.first;
        for(auto step:cell.examples.front())cout<<" "<<step.v;
        cout<<"\n";
    }
    for(int l=global_best;l<=global_best+2;++l){
        for(const auto& path:population[l]){
            cout<<"POOL "<<path.size();
            for(auto s:path)cout<<" "<<s.v;
            cout<<char(10);
        }
    }
    cout<<"END "<<iterations<<" "<<global_best<<" "<<hashes.size();for(int l=global_best;l<(int)population.size();++l)cout<<" "<<l<<":"<<population[l].size();cout<<endl;
}


