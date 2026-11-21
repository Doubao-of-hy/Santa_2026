// Jointly reach all demanded outputs of an arithmetic circuit region. The beam
// pays for extra helpers; every directly reachable required value is collected.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <map>
#include <set>
#include <unordered_map>
#include <unordered_set>
#include <vector>
using I=std::int64_t;
using Mask=std::uint64_t;
using namespace std;
struct Edge { I out,a,b; char op; };
using Graph=unordered_map<I,Edge>;

struct State {
    vector<Edge> path;
    vector<I> helpers;
    Mask covered=0;
    double rating=0;
};
struct Action { double rating; vector<Edge> path; };

struct Solver {
    I limit;
    int width, depth;
    vector<I> base, goals, ordered;
    unordered_set<I> free;
    Graph warm, pairs;
    unordered_map<I,Mask> goal_bit, potential, warm_users;
    vector<Edge> best;
    int upper;
    Mask all;

    template<class F> void inverse(I t,I x,F consume) const {
        if(t>x) consume(t-x,Edge{t,x,t-x,'+'});
        if(x>t) consume(x-t,Edge{t,x,x-t,'-'});
        if(t<=limit-x) consume(t+x,Edge{t,t+x,x,'-'});
        if(x>1 && t%x==0) consume(t/x,Edge{t,x,t/x,'*'});
        if(x>1 && x<=limit/t) consume(x*t,Edge{t,x*t,x,'/'});
        if(x>t && x%t==0) consume(x/t,Edge{t,x,x/t,'/'});
    }
    template<class F> void combine(I a,I b,F consume) const {
        if(a<=limit-b) consume(Edge{a+b,a,b,'+'});
        if(a>b) consume(Edge{a-b,a,b,'-'});
        if(b>a) consume(Edge{b-a,b,a,'-'});
        if(a<=limit/b) consume(Edge{a*b,a,b,'*'});
        if(a>=b && a%b==0) consume(Edge{a/b,a,b,'/'});
        if(b>a && b%a==0) consume(Edge{b/a,b,a,'/'});
    }
    void init() {
        free.insert(base.begin(),base.end());
        for(size_t i=0;i<goals.size();++i) goal_bit[goals[i]]=Mask(1)<<i;
        all=goals.size()==64?~Mask(0):(Mask(1)<<goals.size())-1;
        for(size_t i=0;i<base.size();++i) for(size_t j=0;j<=i;++j)
            combine(base[i],base[j],[&](Edge e){if(!free.count(e.out)) pairs.emplace(e.out,e);});
        vector<I> possible=base;
        possible.insert(possible.end(),goals.begin(),goals.end());
        for(I t:goals) {
            Mask bit=goal_bit[t];
            for(I x:possible) inverse(t,x,[&](I h,Edge){if(!free.count(h)&&h!=t) potential[h]|=bit;});
            if(!(t%2)) potential[t/2]|=bit;
            I r=I(sqrt((long double)t));
            for(I h=max<I>(1,r-1);h<=r+1;++h) if(h*h==t) potential[h]|=bit;
        }
        for(I t:goals) warm_users[t]|=goal_bit[t];
        for(auto it=ordered.rbegin();it!=ordered.rend();++it) {
            auto e=warm.at(*it); Mask m=warm_users[e.out];
            if(m && !free.count(e.out)) {warm_users[e.a]|=m; warm_users[e.b]|=m;}
        }
    }
    void close(State &s,unordered_set<I> &known,vector<I> &values) const {
        bool changed=true;
        while(changed) {
            changed=false;
            for(I t:goals) {
                Mask bit=goal_bit.at(t);
                if(s.covered&bit) continue;
                if(known.count(t)) {s.covered|=bit;changed=true;continue;}
                Edge e{};
                for(I x:values) {
                    inverse(t,x,[&](I y,Edge option){if(!e.out && known.count(y)) e=option;});
                    if(e.out) break;
                }
                if(!e.out) continue;
                known.insert(t);values.push_back(t);s.path.push_back(e);
                s.covered|=bit;changed=true;
            }
        }
    }
    vector<Edge> finish(const State &s,const unordered_set<I> &known) const {
        vector<Edge> answer=s.path;
        unordered_set<I> seen;
        auto visit=[&](auto &&self,I x)->void {
            if(known.count(x) || !seen.insert(x).second) return;
            auto e=warm.at(x); self(self,e.a); self(self,e.b); answer.push_back(e);
        };
        for(I t:goals) visit(visit,t);
        return answer;
    }
    vector<Edge> used(const vector<Edge>& path) const {
        unordered_set<I> needed(goals.begin(),goals.end());
        vector<Edge> result;
        for(auto it=path.rbegin();it!=path.rend();++it)
            if(needed.erase(it->out)) {result.push_back(*it); needed.insert(it->a);needed.insert(it->b);}
        reverse(result.begin(),result.end());
        return result;
    }
    double evaluate(State &s,const unordered_set<I>& known) {
        auto filled=used(finish(s,known));
        int paid=filled.size();
        if(paid<upper) {upper=paid;best=move(filled);}
        return 2.2*__builtin_popcountll(s.covered)-.65*paid-.35*s.path.size();
    }
    void search() {
        init();
        State initial; auto known=free;auto values=base;
        close(initial,known,values); evaluate(initial,known);
        vector<vector<State>> levels(depth+1);
        levels[0].push_back(initial);
        for(int spent=0;spent<depth;++spent) {
            auto &level=levels[spent];
            sort(level.begin(),level.end(),[](auto&a,auto&b){return a.rating>b.rating;});
            set<vector<I>> unique;
            int taken=0;
            for(auto &s:level) {
                auto signature=s.helpers; sort(signature.begin(),signature.end());
                if(!unique.insert(signature).second || s.covered==all) continue;
                if(taken++>=width) break;
                expand(s,spent,levels);
            }
        }
    }
    void expand(const State &s,int spent,vector<vector<State>>& levels) {
        auto known=free; auto values=base;
        for(auto e:s.path) if(known.insert(e.out).second) values.push_back(e.out);
        Graph extra;
        for(size_t i=base.size();i<values.size();++i) for(size_t j=0;j<=i;++j)
            combine(values[i],values[j],[&](Edge e){if(!known.count(e.out) && !pairs.count(e.out))
                extra.emplace(e.out,e);});
        auto lookup=[&](I x)->const Edge* {
            auto it=pairs.find(x);if(it!=pairs.end()) return &it->second;
            auto jt=extra.find(x); return jt==extra.end()?nullptr:&jt->second;
        };
        unordered_map<I,Mask> immediate;
        for(I t:goals) if(!(s.covered&goal_bit[t])) {
            for(I x:values) inverse(t,x,[&](I h,Edge){if(h!=t && !known.count(h)) immediate[h]|=goal_bit[t];});
            if(!(t%2) && t/2>0) immediate[t/2]|=goal_bit[t];
        }
        vector<pair<double,I>> wishes;
        vector<Action> options;
        auto consider=[&](I h,Mask maybe) {
            if(known.count(h) || !h) return;
            Mask live=0;
            auto hit=immediate.find(h); if(hit!=immediate.end()) live=hit->second;
            auto w=warm_users.find(h);
            int warm_count=w==warm_users.end()?0:__builtin_popcountll(w->second&~s.covered);
            int now=__builtin_popcountll(live), future=__builtin_popcountll(maybe&~s.covered);
            double rating=3.5*now+1.5*future+min(3,warm_count)*.44;
            if(!now && !future && !warm_count) return;
            if(auto e=lookup(h)) {options.push_back({rating,{*e}});return;}
            if(spent+2<=depth && (now || future>=2 || warm_count>=2)) wishes.emplace_back(rating,h);
        };
        for(auto entry:potential) consider(entry.first,entry.second);
        for(auto entry:immediate) if(!potential.count(entry.first)) consider(entry.first,entry.second);
        for(I h:ordered) if(!potential.count(h)&&!immediate.count(h)) consider(h,0);
        sort(wishes.begin(),wishes.end(),greater<pair<double,I>>());
        if(wishes.size()>90) wishes.resize(90);
        for(auto [rating,h]:wishes) {
            int plans=0;
            for(I x:values) {
                inverse(h,x,[&](I y,Edge last) {
                    if(plans>=3 || y==h) return;
                    if(auto first=lookup(y)) {
                        ++plans;
                        double bonus=warm_users.count(y)?.5:0;
                        options.push_back({rating-1.4+bonus,{*first,last}});
                    }
                });
                if(plans>=3) break;
            }
        }
        sort(options.begin(),options.end(),[](auto &a,auto &b){
            if(a.rating!=b.rating) return a.rating>b.rating;
            return a.path.back().out<b.path.back().out;});
        int examined=0;
        for(auto &action:options) {
            if(examined++>=max(22,width*3)) break;
            State next=s; auto k=known;auto v=values;
            for(auto e:action.path) if(k.insert(e.out).second) {
                next.path.push_back(e);v.push_back(e.out);
                if(!goal_bit.count(e.out)) next.helpers.push_back(e.out);
            }
            int amount=next.helpers.size();
            if(amount<=spent || amount>depth) continue;
            close(next,k,v);
            next.rating=evaluate(next,k)+action.rating*.1;
            if(next.covered!=all && amount<depth) levels[amount].push_back(move(next));
        }
    }
};
int main(int argc,char**argv) {
    if(argc!=3) return 2;
    string id; I limit; int ns,ng,ne,upper;
    while(cin>>id>>limit>>ns>>ng>>ne>>upper) {
        Solver s{};s.limit=limit;s.width=stoi(argv[1]);s.depth=stoi(argv[2]);s.upper=upper;
        if(ng>56 || ns<1) return 3;
        s.base.resize(ns);s.goals.resize(ng);
        for(auto &x:s.base) cin>>x;
        for(auto &x:s.goals) cin>>x;
        for(int i=0;i<ne;++i) {
            Edge e;cin>>e.out>>e.op>>e.a>>e.b;
            s.warm.emplace(e.out,e);s.ordered.push_back(e.out);
        }
        s.search();
        cout<<id<<" "<<s.best.size()<<"\n";
        for(auto e:s.best) cout<<e.out<<" "<<e.op<<" "<<e.a<<" "<<e.b<<"\n";
        cout<<flush;
    }
}
