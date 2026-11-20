// Construct a whole program forward. Every new helper is computed directly
// from the current state. Backward goal distances guide beam selection only.
#define main exact_search_driver
#include "exact_helpers.cpp"
#undef main
#include <random>
#include <tuple>
#include <numeric>

using Packed=uint64_t;
Packed mix64(Packed x) {
    x+=0x9e3779b97f4a7c15ULL;
    x=(x^(x>>30))*0xbf58476d1ce4e5b9ULL;
    x=(x^(x>>27))*0x94d049bb133111ebULL;
    return x^(x>>31);
}
struct Beam : Search {
    struct State {
        Values active;
        Mask seen,support;
        Packed proximity,key,owned;
    };
    struct Candidate {
        int parent;
        Num value;
        Mask support,immediate;
        Packed proximity,key;
        double score;
    };
    int width,variant;
    uint64_t iterations=0;
    bool lookahead=false;
    bool warm=false;
    bool separate_goals=false;
    Values old_values;
    std::vector<Packed> old_parents,goal_nodes;
    std::unordered_map<Num,Packed> old_index;
    Packed old_targets=0;
    Packed old_node(Num x) const {
        auto it=old_index.find(x);return it==old_index.end()?0:it->second;
    }
    Packed remaining_nodes(Packed owned) const {
        Packed due=old_targets&~owned,needed=0;
        while(due) {
            unsigned j=63-__builtin_clzll(due);Packed bit=Packed(1)<<j;
            needed|=bit;due=(due^bit)|(old_parents[j]&~owned&~needed);
        }
        return needed;
    }
    Packed original_goals(Mask r) const {
        Packed result=0;while(r){unsigned j=__builtin_ctzll(r);result|=goal_nodes[j];r&=r-1;}
        return result;
    }
    std::mt19937 gen;
    std::vector<Packed> proximity;
    std::unordered_map<Num,Packed> sparse_proximity;
    std::vector<unsigned> tag;
    std::vector<Mask> actual;
    unsigned stamp=0;
    bool dense() const {return !dense_goals.empty();}
    Mask goal(Num x) const {
        if(dense())return dense_goals[x];
        auto it=goal_bit.find(x);return it==goal_bit.end()?0:it->second;
    }
    Packed nearest(Num x) const {
        if(dense())return proximity[x];
        auto it=sparse_proximity.find(x);return it==sparse_proximity.end()?0:it->second;
    }
    // Four bits per goal. Distances 1, 2, 3 receive scores 3, 2, 1.
    void reverse_index() {
        if(dense())proximity.assign(limit+1,0);
        Values anchors=seeds;
        if (variant%3!=0) anchors.insert(anchors.end(),goals.begin(),goals.end());
        if (variant%3==2) for (Num a:seeds) for(Num b:seeds)
            operations(a,b,[&](Num x){if(x<=32)anchors.push_back(x);});
        std::sort(anchors.begin(),anchors.end());anchors.erase(std::unique(anchors.begin(),anchors.end()),anchors.end());
        std::vector<unsigned char> dist(dense()?limit+1:0,0);
        for(unsigned j=0;j<goals.size();j++) {
            Values frontier{goals[j]},touched{goals[j]};
            std::unordered_map<Num,int> distances;
            if(dense())dist[goals[j]]=4;else distances[goals[j]]=4;
            for (int d=1;d<=3;d++) {
                Values following;
                for(Num t:frontier) for(Num b:anchors) if(b!=t) inverse(t,b,[&](Num v){
                    if(dense()){
                        if(!dist[v]) {dist[v]=4-d;following.push_back(v);}
                    }else if(distances.emplace(v,4-d).second) following.push_back(v);
                });
                touched.insert(touched.end(),following.begin(),following.end());frontier=std::move(following);
            }
            if(dense())for(Num x:touched) {proximity[x]|=Packed(dist[x])<<(4*j);dist[x]=0;}
            else for(auto [x,merit]:distances) sparse_proximity[x]|=Packed(merit)<<(4*j);
        }
    }
    Packed merge(Packed left,Packed right) const {
        // Each nibble is in [0,4]. A high guard bit isolates borrows.
        constexpr Packed guards=0x8888888888888888ULL;
        Packed greater=(((left|guards)-right)&guards)>>3;
        Packed select=greater*15;
        return (left&select)|(right&~select);
    }
    static int utility(Packed close) {
        return __builtin_popcountll(close&0x1111111111111111ULL)+
               2*__builtin_popcountll(close&0x2222222222222222ULL)+
               4*__builtin_popcountll(close&0x4444444444444444ULL);
    }
    bool solve(int budget) {
        if(budget<0)return false;
        prepare();reverse_index();
        if(dense()){tag.assign(limit+1,0);actual.assign(limit+1,0);}
        Values start=seeds;Mask have=0;
        for(Num v:seeds)have|=goal(v);
        close(start,have,0);
        Packed proximity0=0;for(Num v:start)proximity0=merge(proximity0,nearest(v));
        Packed initial_owned=warm?original_goals(have):0;
        const int allowance=budget+__builtin_popcountll(all&~have)+int(start.size()-seeds.size());
        std::vector<State> beam{{start,have,initial_supported,proximity0,0,initial_owned}};
        if(have==all){witness=start;return true;}
        for (int d=0;d<budget;d++) {
            std::vector<Candidate> candidates;
            for (int id=0;id<int(beam.size());id++) {
                auto& s=beam[id];++stamp;Values options;
                std::unordered_map<Num,Mask> sparse_actual;
                for(size_t i=0;i<s.active.size();i++) {
                    Num a=s.active[i];
                    for(size_t j=0;j<=i;j++) operations(a,s.active[j],[&](Num x){
                        if(goal(x))return;
                        if(dense()){
                            if(tag[x]==stamp)return;
                            tag[x]=stamp;actual[x]=0;
                        }else if(!sparse_actual.emplace(x,0).second)return;
                        options.push_back(x);
                    });
                }
                for(Num v:s.active)if(dense())tag[v]=0;else sparse_actual.erase(v);
                std::unordered_map<Num,Mask> latent;
                for(unsigned j=0;j<goals.size();j++) {
                    Mask bit=Mask(1)<<j;
                    if(s.seen&bit)continue;
                    Num t=goals[j];
                    auto add=[&](Num x){
                        if(lookahead)latent[x]|=bit;
                        if(dense()){if(tag[x]==stamp)actual[x]|=bit;}
                        else {auto it=sparse_actual.find(x);if(it!=sparse_actual.end())it->second|=bit;}
                    };
                    for(Num b:s.active) inverse(t,b,add);
                    if(t%2==0)add(t/2);
                    Num root=isqrt(t);
                    if(root*root==t)add(root);
                }
                size_t begin=candidates.size();
                Mask reachable_next=0;
                int untouched=warm?__builtin_popcountll(remaining_nodes(s.owned)):0;
                for(Num v:options) {
                    Mask fresh=0;
                    if(dense()){if(tag[v]!=stamp)continue;fresh=actual[v];}
                    else {auto it=sparse_actual.find(v);if(it==sparse_actual.end())continue;fresh=it->second;}
                    ++iterations;
                    Mask immediate=s.seen|fresh;
                    reachable_next|=fresh;
                    Mask support=s.support|current(v)|fresh;
                    Packed near=merge(s.proximity,nearest(v));
                    Packed hash=s.key^mix64(v);
                    double score=__builtin_popcountll(immediate)*(variant%2?12.:18.)
                               +__builtin_popcountll(support)*(variant%2?8.:4.)
                               +utility(near)*(variant%2?1.2:1.8)
                               +__builtin_popcountll(current(v)&~s.seen)*.4
                               +((gen()>>8)*(1./16777216.))*(variant%2?8.:4.);
                    if(warm){
                        Packed bought=old_node(v)|original_goals(fresh);
                        int still=bought?__builtin_popcountll(remaining_nodes(s.owned|bought)):untouched;
                        score-=3.5*(still+__builtin_popcountll(immediate));
                    }
                    if(d+1==budget && !fresh && !warm)continue;
                    candidates.push_back({id,v,support,immediate,near,hash,score});
                }
                // Reserve most of the beam for independently reached prefixes.
                size_t keep=std::max(10,int(std::sqrt(width)));
                if(lookahead && d+2<=budget) {
                    size_t assess=3*keep;
                    if(candidates.size()>begin+assess){
                        std::nth_element(candidates.begin()+begin,candidates.begin()+begin+assess,candidates.end(),
                            [](const auto& a,const auto& b){return a.score>b.score;});
                        candidates.resize(begin+assess);
                    }
                    // For a prospective first helper v, evaluate actual
                    // two-helper routes to the missing targets. Both operands
                    // of the intermediate step must already be available.
                    for(size_t ix=begin;ix<candidates.size();ix++) {
                        auto& cand=candidates[ix];Num v=cand.value;
                        Mask additional=0;int jointly=0;
                        auto measure=[&](Mask mask){
                            mask &= ~s.seen;
                            additional|=mask;jointly=std::max(jointly,__builtin_popcountll(mask));
                        };
                        auto test=[&](Num z){
                            auto it=latent.find(z);
                            if(it!=latent.end())measure(it->second);
                        };
                        for(Num b:s.active)operations(v,b,test);
                        operations(v,v,test);
                        for(unsigned j=0;j<goals.size();j++)if(!(s.seen&(Mask(1)<<j))){
                            inverse(goals[j],v,[&](Num z){
                                if(z!=v && (dense()?tag[z]==stamp:sparse_actual.count(z)>0)) {
                                    Mask already=dense()?actual[z]:sparse_actual.at(z);
                                    measure(already|(Mask(1)<<j));
                                }
                            });
                        }
                        cand.score+=3.1*__builtin_popcountll(additional&~reachable_next)
                                   +.55*__builtin_popcountll(additional)+2.7*std::max(0,jointly-1);
                    }
                }
                if(candidates.size()>begin+keep){
                    std::nth_element(candidates.begin()+begin,candidates.begin()+begin+keep,candidates.end(),
                        [](const auto& a,const auto& b){return a.score>b.score;});
                    candidates.resize(begin+keep);
                }
            }
            std::sort(candidates.begin(),candidates.end(),[](const auto& a,const auto& b){return a.score>b.score;});
            if(separate_goals && candidates.size()>size_t(width) && !goals.empty()){
                // Keep the best overall partial programs, then reserve slots
                // for prefixes which are unusually close to each single goal.
                // Overlap between lists is removed by the usual set hash below.
                size_t global=std::max(1,width/3),quota=std::max(1,width/(2*int(goals.size())));
                std::vector<Candidate> focus(candidates.begin(),candidates.begin()+global);
                std::vector<size_t> order(candidates.size());
                for(unsigned j=0;j<goals.size();j++){
                    std::iota(order.begin(),order.end(),0);Mask bit=Mask(1)<<j;
                    auto priority=[&](const Candidate& c){
                        return c.score+((c.immediate&bit)?19.:0.)+((c.support&bit)?7.:0.)
                             +4.*((c.proximity>>(4*j))&15);
                    };
                    std::partial_sort(order.begin(),order.begin()+quota,order.end(),[&](size_t a,size_t b){
                        double av=priority(candidates[a]),bv=priority(candidates[b]);
                        return av!=bv?av>bv:a<b;
                    });
                    for(size_t k=0;k<quota;k++)focus.push_back(candidates[order[k]]);
                }
                focus.insert(focus.end(),candidates.begin(),candidates.end());candidates.swap(focus);
            }
            std::vector<State> next;std::unordered_set<Packed> unique;
            for(const auto& c:candidates) {
                if(!unique.insert(c.key).second)continue;
                const auto& prev=beam[c.parent];
                Values values=prev.active;values.push_back(c.value);
                Mask seen=prev.seen;close(values,seen,prev.active.size());
                if(seen==all){witness=std::move(values);return true;}
                Packed owned=0;
                if(warm) {
                    owned=prev.owned|old_node(c.value)|original_goals(seen^prev.seen);
                    Packed due=remaining_nodes(owned);
                    if(int(values.size()-seeds.size())+__builtin_popcountll(due)<=allowance){
                        for(;due;due&=due-1)values.push_back(old_values[__builtin_ctzll(due)]);
                        witness=std::move(values);return true;
                    }
                }
                if(d+1<budget) next.push_back({std::move(values),seen,c.support,c.proximity,c.key,owned});
                if(next.size()>=size_t(width))break;
            }
            if(next.empty())break;
            beam=std::move(next);
        }
        return false;
    }
};
int main(int argc,char**argv) {
    if(argc<4 || argc>7)return 2;
    Beam b;b.width=std::stoi(argv[1]);b.variant=std::stoi(argv[2]);b.gen.seed(std::stoul(argv[3]));
    for(int j=4;j<argc;j++){
        if(std::string(argv[j])=="--lookahead")b.lookahead=true;
        else if(std::string(argv[j])=="--warm")b.warm=true;
        else if(std::string(argv[j])=="--separate-goals")b.separate_goals=true;
        else return 2;
    }
    int ns,nt,budget;std::cin>>b.limit>>ns>>nt>>budget;
    if(!std::cin || b.limit<1 || b.limit>1000000000000000000LL || nt>16 || ns<1 || b.width<1)return 2;
    for(int i=0;i<ns+nt;i++){Num v;std::cin>>v;(i<ns?b.seeds:b.goals).push_back(v);}
    if(b.warm){
        int n;std::cin>>n;if(!std::cin||n<0||n>64)return 2;
        std::unordered_set<Num> stable(b.seeds.begin(),b.seeds.end());
        for(int i=0;i<n;i++){
            Num v,x,y;char op;std::cin>>v>>op>>x>>y;
            if(!std::cin||!stable.count(x)||!stable.count(y)||stable.count(v))return 2;
            bool ok=(op=='+' && x<=b.limit-y && x+y==v)||(op=='-' && x-y==v)
                    ||(op=='*' && x<=b.limit/y && x*y==v)||(op=='/' && x%y==0 && x/y==v);
            if(!ok||v<1||v>b.limit)return 2;
            b.old_parents.push_back(b.old_node(x)|b.old_node(y));b.old_values.push_back(v);
            b.old_index[v]=Packed(1)<<i;stable.insert(v);
        }
        for(Num v:b.goals){if(!stable.count(v))return 2;auto m=b.old_node(v);b.goal_nodes.push_back(m);b.old_targets|=m;}
    }
    bool ok=b.solve(budget);
    std::cout<<(ok?"FOUND":"NO_WITNESS")<<" "<<b.iterations<<"\n";
    if(ok){for(Num x:b.witness)std::cout<<x<<" ";std::cout<<"\n";}
}
