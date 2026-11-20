// Close a set of mandatory outputs over retained anchors. Helpers can take any
// legal value. The first helper layer is exhaustive; subsequent layers use a beam.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <unordered_map>
#include <unordered_set>
#include <vector>
using namespace std;
using I=long long;
using Mask=uint64_t;
struct Step {I v,a,b; char op;};

template<class F> void forward(I a,I b,I cap,F f) {
    if(a<=cap-b) f(Step{a+b,a,b,'+'});
    if(a>b && a-b<=cap) f(Step{a-b,a,b,'-'});
    if(b>a && b-a<=cap) f(Step{b-a,b,a,'-'});
    if(a<=cap/b) f(Step{a*b,a,b,'*'});
    if(a%b==0 && a/b<=cap) f(Step{a/b,a,b,'/'});
    if(a!=b && b%a==0 && b/a<=cap) f(Step{b/a,b,a,'/'});
}
template<class F> void inverse(I t,I x,I cap,F f) {
    if(t>x) f(t-x,Step{t,t-x,x,'+'});
    if(x>t) f(x-t,Step{t,x,x-t,'-'});
    if(t<=cap-x) f(t+x,Step{t,t+x,x,'-'});
    if(t%x==0) f(t/x,Step{t,t/x,x,'*'});
    if(t<=cap/x) f(t*x,Step{t,t*x,x,'/'});
    if(x%t==0) f(x/t,Step{t,x,x/t,'/'});
}

struct Rule {Mask goal,deps; Step step;};
struct State {Mask painted; vector<Step> helpers;};
struct Move {int rank; Step s;};
struct Partial {int gain;Mask painted;vector<Step> helpers;};
struct Solver {
    I cap;
    int width,upper,depth;
    vector<I> anchors,goals,hints;
    unordered_map<I,Mask> mask;
    unordered_set<I> retained,preferred;
    vector<Rule> fixed;
    unordered_map<I,vector<Rule>> with;
    vector<Step> rootMoves,rootBridges,answer;
    unordered_map<I,Step> initial;
    Mask full=0,start=0,required=~Mask(0);
    int cert=-1;
    bool solved=false;
    bool partial=false;
    vector<pair<Mask,int>> weights;
    vector<Partial> alternatives;
    unordered_map<Mask,int> eliminated;

    int count(Mask m) const {return __builtin_popcountll(m);}
    bool complete(Mask m)const{return (m&required)==required;}
    Mask bit(I v) const {auto it=mask.find(v);return it==mask.end()?0:it->second;}
    void scan(const vector<Rule>& rules,Mask& have,vector<Step>* out)const {
        for(const auto &r:rules) if(!(r.goal&have) && !(r.deps&~have)){
            have|=r.goal;if(out)out->push_back(r.step);
        }
    }
    Mask close(Mask have,const vector<Step>& helpers,vector<Step>* out=nullptr) const {
        Mask before;
        do {
            before=have;scan(fixed,have,out);
            for(size_t i=0;i<helpers.size();i++){
                auto it=with.find(helpers[i].v);
                if(it!=with.end())scan(it->second,have,out);
                for(size_t j=0;j<i;j++)forward(helpers[i].v,helpers[j].v,cap,[&](Step e){
                    Mask m=bit(e.v);if(m && !(m&have)){have|=m;if(out)out->push_back(e);}
                });
            }
        } while(have!=before && have!=full);
        return have;
    }
    void populate(){
        vector<I> core=anchors;core.insert(core.end(),goals.begin(),goals.end());
        retained.insert(anchors.begin(),anchors.end());
        preferred.insert(hints.begin(),hints.end());
        for(size_t i=0;i<goals.size();i++){mask[goals[i]]=Mask(1)<<i;full|=Mask(1)<<i;}
        if(required==~Mask(0))required=full;
        for(I t:goals){
            Mask dst=bit(t);
            for(I x:core)if(x!=t) inverse(t,x,cap,[&](I v,Step e){
                if(v==t || e.a==t || e.b==t)return;
                if(retained.count(v) || mask.count(v)){
                    if(v>=x || e.op=='-' || e.op=='/')fixed.push_back({dst,bit(x)|bit(v),e});
                }else if(v<=cap) with[v].push_back({dst,bit(x),e});
            });
            auto twice=[&](I v,char op){
                if(v<=0 || v==t)return;Rule rule{dst,0,{t,v,v,op}};
                if(retained.count(v)||mask.count(v)){rule.deps=bit(v);fixed.push_back(rule);}
                else with[v].push_back(rule);
            };
            if(t%2==0)twice(t/2,'+');
            I v=(I)sqrt((long double)t);
            while((v+1)<=t/(v+1))v++;while(v>t/v)v--;
            if(v*v==t)twice(v,'*');
        }
        start=close(0,{});
        auto known=anchors;for(I v:goals)if(bit(v)&start)known.push_back(v);
        initial.reserve(known.size()*known.size());
        for(size_t i=0;i<known.size();i++)for(size_t j=0;j<=i;j++)forward(known[i],known[j],cap,[&](Step e){
            if(mask.count(e.v)||retained.count(e.v))return;
            if(!initial.emplace(e.v,e).second)return;
            if(with.count(e.v))rootMoves.push_back(e);
            else if(e.v<=4096||preferred.count(e.v))rootBridges.push_back(e);
        });
        sort(rootBridges.begin(),rootBridges.end(),[&](Step a,Step b){
            bool pa=preferred.count(a.v),pb=preferred.count(b.v);
            return pa!=pb?pa>pb:a.v<b.v;
        });
        if(rootBridges.size()>size_t(width*3))rootBridges.resize(width*3);
    }
    int displaced(Mask painted) {
        auto it=eliminated.find(painted);if(it!=eliminated.end())return it->second;
        int n=0;for(auto [owners,freq]:weights)if(!(owners&~painted))n+=freq;
        eliminated[painted]=n;return n;
    }
    void consider(Mask painted,const vector<Step>& helpers){
        if(!partial||!painted)return;
        int gain=displaced(painted)-int(helpers.size());
        if(gain<=0 || (alternatives.size()==4 && gain<alternatives.back().gain))return;
        for(auto &e:alternatives)if(e.painted==painted){
            if(gain>e.gain){e.gain=gain;e.helpers=helpers;}
            else return;
            sort(alternatives.begin(),alternatives.end(),[](const Partial&a,const Partial&b){return a.gain>b.gain;});
            return;
        }
        alternatives.push_back({gain,painted,helpers});
        sort(alternatives.begin(),alternatives.end(),[](const Partial&a,const Partial&b){return a.gain>b.gain;});
        if(alternatives.size()>4)alternatives.pop_back();
    }
    vector<Step> emit(Mask wanted,const vector<Step>& helpers) const {
        vector<Step> result;
        vector<Step> used;
        Mask have=close(0,{},&result);
        for(Step s:helpers){result.push_back(s);used.push_back(s);have=close(have,used,&result);}
        if((have&wanted)!=wanted)throw runtime_error("missing output after replay");
        return result;
    }
    void seal(const vector<Step>& helpers){
        solved=true;answer=emit(required,helpers);
    }
    void moves(const State&s,int level,vector<pair<long long,State>>& next) {
        vector<Step> supplied=rootMoves;
        if(level+1<depth)supplied.insert(supplied.end(),rootBridges.begin(),rootBridges.end());
        unordered_set<I> hidden,seen;
        vector<I> fixedValues=anchors,extra;
        for(I t:goals)if(bit(t)&s.painted){
            if(bit(t)&start)fixedValues.push_back(t);else extra.push_back(t);
        }
        for(const auto &h:s.helpers){extra.push_back(h.v);hidden.insert(h.v);}
        unordered_set<I> pairWithChosen;
        for(I t:goals)if(!(bit(t)&s.painted))for(auto h:s.helpers)
            inverse(t,h.v,cap,[&](I v,Step){pairWithChosen.insert(v);});
        for(I v:pairWithChosen){auto it=initial.find(v);if(it!=initial.end())supplied.push_back(it->second);}
        for(size_t i=0;i<extra.size();i++){
            auto receive=[&](Step e){
                if(!initial.count(e.v) && !retained.count(e.v) && !bit(e.v) &&
                   (with.count(e.v)||pairWithChosen.count(e.v)||preferred.count(e.v)))supplied.push_back(e);
            };
            for(I x:fixedValues)forward(extra[i],x,cap,receive);
            for(size_t j=0;j<=i;j++)forward(extra[i],extra[j],cap,receive);
        }
        vector<Move> options;
        auto path=s.helpers;
        for(Step e:supplied){
            if(hidden.count(e.v)||!seen.insert(e.v).second)continue;
            Mask gained=0,potential=0;
            auto it=with.find(e.v);
            if(it!=with.end())for(auto &r:it->second)if(!(r.goal&s.painted)){
                potential|=r.goal;if(!(r.deps&~s.painted))gained|=r.goal;
            }
            if(pairWithChosen.count(e.v))for(const auto& h:s.helpers)
                forward(e.v,h.v,cap,[&](Step r){gained|=bit(r.v)&~s.painted;});
            if(gained){
                path.push_back(e);
                Mask total=close(s.painted,path);
                consider(total,path);
                if(complete(total)){seal(path);return;}
                path.pop_back();
                int marginal=partial?displaced(total)*185:0;
                options.push_back({int(1000*count(total)+300*count(total&required)+marginal+21*count(potential)+(preferred.count(e.v)?26:0)),e});
            }else if(level+1<depth && (potential||preferred.count(e.v)||e.v<=4096)){
                options.push_back({int(1000*count(s.painted)+10*count(potential)+(preferred.count(e.v)?80:0)),e});
            }
        }
        if(level+1>=depth)return;
        // Reserve a few places for intermediate values that have yet to open
        // a goal. These can feed another helper before either produces an output.
        sort(options.begin(),options.end(),[](const Move&a,const Move&b){
            return a.rank!=b.rank?a.rank>b.rank:a.s.v<b.s.v;
        });
        int n=0;
        for(auto m:options){
            path.push_back(m.s);
            Mask painted=close(s.painted,path);
            long long rank=100000LL*count(painted)+m.rank+(partial?20000LL*displaced(painted):0);
            next.emplace_back(rank,State{painted,path});
            path.pop_back();if(++n>=width)break;
        }
    }
    void run(){
        populate();cert=0;
        consider(start,{});
        if(complete(start)){seal({});return;}
        depth=min(depth,upper-1);if(depth<=0)return;
        vector<State> current{{start,{}}};
        for(int level=0;level<depth && !current.empty();level++){
            vector<pair<long long,State>> expanded;
            for(const State& s:current){moves(s,level,expanded);if(solved){if(!level)cert=1;return;}}
            if(!level)cert=1;
            sort(expanded.begin(),expanded.end(),[](const auto& a,const auto& b){return a.first>b.first;});
            current.clear();
            unordered_set<uint64_t> seen;
            for(auto &candidate:expanded){
                uint64_t sig=0;
                for(auto e:candidate.second.helpers){
                    uint64_t x=e.v+0x9e3779b97f4a7c15ULL;
                    x=(x^(x>>30))*0xbf58476d1ce4e5b9ULL;
                    x=(x^(x>>27))*0x94d049bb133111ebULL;sig^=x^(x>>31);
                }
                if(!seen.insert(sig).second)continue;
                current.push_back(move(candidate.second));
                if(int(current.size())>=width)break;
            }
        }
    }
};

int main(int argc,char**argv){
    ios::sync_with_stdio(false);cin.tie(nullptr);
    string name;int ns,ng,nh;
    while(cin>>name){
        Solver s;s.partial=argc>1;cin>>s.cap>>ns>>ng>>nh>>s.upper>>s.width>>s.depth;
        if(ng<1||ng>63||s.cap<1||s.cap>1000000000000000000LL)return 2;
        s.anchors.resize(ns);s.goals.resize(ng);s.hints.resize(nh);
        for(auto&v:s.anchors)cin>>v;for(auto&v:s.goals)cin>>v;for(auto&v:s.hints)cin>>v;
        if(s.partial){int n;cin>>n;while(n--){Mask mask;int weight;cin>>mask>>weight;s.weights.emplace_back(mask,weight);}}
        s.run();
        if(s.partial){
            cout<<name<<' '<<s.cert<<' '<<s.solved<<' '<<s.alternatives.size()<<'\n';
            for(const auto& alt:s.alternatives){
                auto pg=s.emit(alt.painted,alt.helpers);cout<<pg.size()<<' '<<alt.gain<<' '<<alt.painted<<'\n';
                for(auto e:pg)cout<<e.v<<' '<<e.op<<' '<<e.a<<' '<<e.b<<'\n';
            }
        }else{
            cout<<name<<' '<<s.cert<<' '<<s.solved<<' '<<s.answer.size()<<'\n';
            for(auto e:s.answer)cout<<e.v<<' '<<e.op<<' '<<e.a<<' '<<e.b<<'\n';
        }
    }
    return 0;
}
