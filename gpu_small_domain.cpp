// Exact helper-set search in the entire bounded small integer domain.
#include <algorithm>
#include <array>
#include <bitset>
#include <cstdint>
#include <iostream>
#include <set>
#include <unordered_set>
#include <vector>
using namespace std;
using I=long long;
constexpr int top=512;
using Set=bitset<top+1>;
struct Edge {int v;char op;I a,b;};

template<class F> void combine(I a,I b,int cap,F f){
    if(a<=cap-b)f(int(a+b),'+',a,b);
    if(a!=b && abs(a-b)<=cap)f(int(abs(a-b)),'-',max(a,b),min(a,b));
    if(a<=cap/b)f(int(a*b),'*',a,b);
    if(a%b==0 && a/b<=cap)f(int(a/b),'/',a,b);
    if(a!=b && b%a==0 && b/a<=cap)f(int(b/a),'/',b,a);
}

struct State {Set known,near;vector<int> values;};
struct Solver {
    int cap,upper,limit,states=0,complete=-1; bool exhausted=false,found=false;
    Set goals;vector<I> anchors;vector<int> small_seeds,chosen,best;
    vector<Set> static_near;
    vector<array<uint16_t,5>> table;
    unordered_set<uint64_t> seen;

    void init(){
        table.resize((cap+1)*(cap+1));static_near.resize(cap+1);
        for(int v=1;v<=cap;v++){
            for(I x:anchors)combine(v,x,cap,[&](int h,char,I,I){static_near[v].set(h);});
            for(int w=1;w<=v;w++){
                auto &out=table[v*(cap+1)+w];int n=0;
                combine(v,w,cap,[&](int h,char,I,I){out[n++]=h;});
                table[w*(cap+1)+v]=out;
            }
        }
    }
    void add(State&s,int v)const{
        s.known.set(v);s.near|=static_near[v];s.values.push_back(v);
        for(int w:s.values){auto &out=table[v*(cap+1)+w];
            for(int h:out){if(!h)break;s.near.set(h);}}
    }
    void close(State&s)const{
        for(;;){Set update=s.near&goals&~s.known;if(update.none())return;
            for(int v=update._Find_first();v<=cap;v=update._Find_next(v))add(s,v);}
    }
    uint64_t key()const{
        // Up to six values in [1,512] fit exactly in ten bits apiece.
        vector<int> sorted=chosen;sort(sorted.begin(),sorted.end());uint64_t k=0;
        for(int v:sorted)k=(k<<10)|uint64_t(v);return k;
    }
    bool explore(const State& s,int remaining){
        if((goals&~s.known).none()){best=chosen;return true;}
        if(!remaining)return false;
        if(++states>limit){exhausted=true;return false;}
        if(chosen.size()>1 && !seen.insert(key()).second)return false;
        Set next=s.near&~s.known;vector<pair<int,int>> moves;
        for(int h=next._Find_first();h<=cap;h=next._Find_next(h)){
            State test=s;add(test,h);int immediate=(test.near&goals&~s.known).count();
            if(!immediate&&remaining==1)continue;
            if(immediate){close(test);if((goals&~test.known).none()){
                best=chosen;best.push_back(h);return true;}}
            if(remaining>1)moves.emplace_back(-int((test.known&goals).count()),h);
        }
        sort(moves.begin(),moves.end());
        for(auto [score,h]:moves){State test=s;add(test,h);close(test);chosen.push_back(h);
            bool won=explore(test,remaining-1);chosen.pop_back();if(won)return true;
            if(exhausted)return false;}
        return false;
    }
    vector<Edge> solution(){
        vector<I> values=anchors;Set allowed=goals,known;vector<Edge> records;
        for(int v:small_seeds){values.push_back(v);known.set(v);}
        for(int h:best)allowed.set(h);
        for(size_t i=0;i<values.size() && (goals&~known).any();i++){
            for(size_t j=0;j<=i;j++)combine(values[i],values[j],cap,[&](int v,char op,I a,I b){
                if(allowed.test(v) && !known.test(v)){
                    known.set(v);values.push_back(v);records.push_back({v,op,a,b});}});
        }
        if((goals&~known).any())throw runtime_error("closure replay mismatch");
        return records;
    }
    void run(){
        init();State original;
        for(size_t i=0;i<anchors.size();i++)for(size_t j=0;j<=i;j++)
            combine(anchors[i],anchors[j],cap,[&](int v,char,I,I){original.near.set(v);});
        for(int v:small_seeds)add(original,v);close(original);
        complete=0;
        if((goals&~original.known).none()){found=true;return;}
        for(int depth=1;depth<=min(6,upper-1);depth++){
            seen.clear();states=0;
            if(explore(original,depth)){complete=depth;found=true;return;}
            if(exhausted)return;complete=depth;
        }
    }
};

int main(){
    ios::sync_with_stdio(false);cin.tie(nullptr);
    string id;int cap,ns,ng,ub,limit;
    while(cin>>id>>cap>>ns>>ng>>ub>>limit){
        Solver s{};s.cap=cap;s.upper=ub;s.limit=limit;
        if(cap>top||cap<1||ub<1)return 2;
        for(int i=0;i<ns;i++){I v;cin>>v;if(v<=cap)s.small_seeds.push_back(int(v));else s.anchors.push_back(v);}
        for(int i=0;i<ng;i++){int v;cin>>v;s.goals.set(v);}
        s.run();vector<Edge> pg;
        if(s.found)pg=s.solution();
        cout<<id<<' '<<s.complete<<' '<<s.exhausted<<' '<<pg.size()<<'\n';
        for(auto e:pg)cout<<e.v<<' '<<e.op<<' '<<e.a<<' '<<e.b<<'\n';cout<<flush;
    }
}
