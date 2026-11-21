// SPDX-License-Identifier: Apache-2.0
// Cumulative shared benefit is inspired by Voronenko and Püschel's MCM Hcub.
// For this calculator all +/-/*/exact-/ operations and intermediate bounds count.
#include <bits/stdc++.h>
namespace shared_core {
#include "virtual.cpp"
}

namespace creative {
using namespace std;
using shared_core::Edge;
using shared_core::Int;
using shared_core::LiveBank;
using shared_core::Plan;
using shared_core::Puzzle;
using shared_core::TargetSearch;
#include "creative_bilinear.hpp"

struct Route {
    Plan edges;
    vector<int> left, right;
    vector<uint64_t> closure;
    vector<Int> values;
    uint64_t fingerprint=0;

    explicit Route(Plan steps): edges(move(steps)) {
        unordered_map<Int,int> index;
        for(size_t i=0;i<edges.size();++i) {
            Edge e=edges[i];
            auto pos=[&](Int x){auto it=index.find(x); return it==index.end()?-1:it->second;};
            int a=pos(e.a), b=pos(e.b);
            left.push_back(a);right.push_back(b);
            uint64_t bits= i<63 ? uint64_t(1)<<i : 0;
            if(a>=0) bits|=closure[a];
            if(b>=0) bits|=closure[b];
            closure.push_back(bits);index[e.out]=i;
            values.push_back(e.out);
        }
        sort(values.begin(),values.end());
        for(Int x:values) fingerprint=(fingerprint^uint64_t(x))*0x9e3779b97f4a7c15ULL;
    }

    int charging(const unordered_set<Int> &paid) const {
        if(edges.empty()) return 0;
        if(edges.size()<64) {
            uint64_t required=uint64_t(1)<<(edges.size()-1);
            int total=0;
            while(required) {
                int i=63-__builtin_clzll(required);required^=uint64_t(1)<<i;
                if(paid.count(edges[i].out)) continue;
                ++total;
                if(left[i]>=0) required|=uint64_t(1)<<left[i];
                if(right[i]>=0) required|=uint64_t(1)<<right[i];
            }
            return total;
        }
        vector<bool> required(edges.size());required.back()=true;
        int total=0;
        for(int i=int(edges.size())-1;i>=0;--i) if(required[i] && !paid.count(edges[i].out)) {
            ++total;
            if(left[i]>=0) required[left[i]]=true;
            if(right[i]>=0) required[right[i]]=true;
        }
        return total;
    }

    Plan slice(int root,const unordered_set<Int> &paid) const {
        vector<bool> required(edges.size());required[root]=true;
        for(int i=root;i>=0;--i) if(required[i]) {
            if(paid.count(edges[i].out)) {required[i]=false;continue;}
            if(left[i]>=0) required[left[i]]=true;
            if(right[i]>=0) required[right[i]]=true;
        }
        Plan result;
        for(int i=0;i<=root;++i) if(required[i]) result.push_back(edges[i]);
        return result;
    }
};
#include "creative_joint.hpp"
struct Proposal {Int root;Plan plan; int support; double priority;};

class Planner {
    Puzzle &p;
    LiveBank bank;
    map<Int,vector<Route>> choices;
    unordered_set<Int> paid;
    mt19937 rng;
    const int budget,width,refresh;
    const double discount;
    int searches=0,scaffolds=0,epochs=0;
    int bilinear_mode;
    Bilinear products;
    int joint_effort;
    Plan best_joint;
    mt19937 joint_rng;

    void solve_joint() {
        JointCircuit circuit(p,choices,best_joint,joint_rng());
        auto solution=circuit.search(joint_effort);
        if(best_joint.empty() || solution.size<int(best_joint.size()))
            best_joint=circuit.export_plan(solution);
    }

    void store(Int target,Plan fragment) {
        Plan full=shared_core::unpaid_cone(target,fragment,p,paid);
        if(full.empty()) return;
        Route r(move(full));
        auto &old=choices[target];
        for(auto &s:old) if(s.fingerprint==r.fingerprint && s.values==r.values) return;
        old.push_back(move(r));
    }

    void refresh_routes() {
        ++epochs;
        if(bilinear_mode) products.rebuild(epochs);
        for(Int t:p.targets) if(!paid.count(t)) {
            auto &routes=choices[t];
            // Compact old cones after new helpers have been paid for.
            vector<Route> trimmed;
            unordered_set<uint64_t> seen;
            for(auto &r:routes) {
                Route new_route(r.slice(int(r.edges.size())-1,paid));
                if(!new_route.edges.empty() && seen.insert(new_route.fingerprint).second)
                    trimmed.push_back(move(new_route));
            }
            stable_sort(trimmed.begin(),trimmed.end(),[](const Route &a,const Route &b){
                return a.edges.size()<b.edges.size();});
            if(trimmed.size()>12) trimmed.erase(trimmed.begin()+12,trimmed.end());
            routes.swap(trimmed);
            int ceiling=routes.empty()?42:min(42,int(routes.front().edges.size())+4);
            TargetSearch finder(bank,width,ceiling,epochs%3==0?.23:.18,5);
            ++searches;
            auto best=finder.run(t);
            if(!best.empty() || p.defs.count(t)) store(t,move(best));
            for(auto [cost,node,last]:finder.finishes) if(node!=finder.best_node)
                store(t,finder.reconstruct(t,node,last));
            if(bilinear_mode) for(auto alternative:products.search(t,min(ceiling,max(6,finder.upper+1))))
                store(t,move(alternative));
            if(routes.empty()) {
                // Only the fallback graph is copied; it is still seed-derived.
                Puzzle backup=p;
                backup.binary(t);
                auto raw=shared_core::unpaid_cone(t,{},backup,paid);
                routes.emplace_back(move(raw));
            }
        }
    }

    Proposal choose() {
        map<Int,int> cheapest;
        unordered_map<Int,int> supports;
        map<Int,Plan> cones;
        for(auto &[t,routes]:choices) if(!paid.count(t)) {
            int best=INT_MAX;
            for(auto &r:routes) best=min(best,r.charging(paid));
            cheapest[t]=best;
            unordered_set<Int> touched;
            for(auto &r:routes) {
                if(r.charging(paid)>best+2) continue;
                for(size_t i=0;i<r.edges.size();++i) {
                    Int v=r.edges[i].out;
                    if(paid.count(v)) continue;
                    touched.insert(v);
                    if(i+1<r.edges.size() && r.edges.size()<64 && __builtin_popcountll(r.closure[i])>8)
                        continue;
                    Plan cone=r.slice(i,paid);
                    if(!cones.count(v) || cone.size()<cones[v].size()) cones[v]=move(cone);
                }
            }
            for(auto v:touched) ++supports[v];
        }
        vector<Proposal> shortlist;
        for(auto &[v,cone]:cones) {
            bool target=cheapest.count(v)>0;
            if(!target && supports[v]<2) continue;
            double proxy=supports[v]+(target?3.0:0.0)-.15*cone.size();
            shortlist.push_back({v,move(cone),supports[v],proxy});
        }
        stable_sort(shortlist.begin(),shortlist.end(),[](auto &a,auto &b){return a.priority>b.priority;});
        Proposal winner{}; double merit=-1e30;
        for(size_t j=0;j<shortlist.size();++j) {
            auto &q=shortlist[j];
            bool target=cheapest.count(q.root)>0;
            if(j>=72 && !target) continue;
            vector<Int> novel;
            for(auto e:q.plan) if(paid.insert(e.out).second) novel.push_back(e.out);
            double gain=0;int helped=0;
            for(auto [t,price]:cheapest) {
                int after=price;
                for(auto &r:choices[t]) after=min(after,r.charging(paid));
                if(price>after) {++helped;gain+=price-after;}
            }
            for(auto v:novel) paid.erase(v);
            if(novel.empty() || (!target && (helped<2 || gain<=novel.size()))) continue;
            double unit=double(novel.size());
            // Favor clusters which eliminate repeated work from several actual root routes.
            // Closing one target also gives the next search a new large operand.
            double value=(gain-unit)/pow(unit,.55) + (target ? discount-.20*unit : 0.0);
            if(value>merit) {merit=value;winner=q;}
        }
        if(winner.plan.empty()) throw runtime_error("no live finite construction");
        if(!cheapest.count(winner.root)) ++scaffolds;
        return winner;
    }

    vector<Int> leaves() {
        map<Int,double> rate;
        for(auto v:p.starts) rate[v]=1e6;
        for(auto v:p.palette) rate[v]+=paid.count(v)?15:4;
        for(size_t i=0;i<p.order.size();++i) {
            Int v=p.order[i];
            if(paid.count(v)) rate[v]+=3+3.0*i/p.order.size();
            rate[v]+=min(8.0,1.5*log2(1.0+p.uses[v]));
        }
        for(auto &[t,routes]:choices) if(!paid.count(t)) {
            unordered_set<Int> seen;
            for(auto &r:routes) for(auto e:r.edges) {
                if(paid.count(e.a)) seen.insert(e.a);
                if(paid.count(e.b)) seen.insert(e.b);
            }
            for(auto v:seen) rate[v]+=1.2;
        }
        vector<pair<double,Int>> ranks;
        for(auto [v,s]:rate) ranks.emplace_back(-s-double(rng()%1000)/5000,v);
        sort(ranks.begin(),ranks.end());
        vector<Int> out;
        for(auto [s,v]:ranks) if(int(out.size())<budget) out.push_back(v); else break;
        return out;
    }

public:
    Planner(Puzzle &p,int budget,int width,int refresh,double discount,unsigned seed,int bilinear,int joint):
      p(p),bank(p.limit,1800000),rng(seed),budget(budget),width(width),refresh(refresh),discount(discount),
      bilinear_mode(bilinear),products(bank,110,bilinear>1?3:0),joint_effort(joint),joint_rng(seed+103) {}

    void solve(const vector<Int>& anchors) {
        p.setup();
        if(!anchors.empty()) {
            auto base=p.starts;
            base.insert(base.end(),p.palette.begin(),p.palette.end());
            shared_core::LiveBank scout(p.limit,175000);
            scout.extend(base);
            int remaining=19;
            for(Int a:anchors) {
                if(p.defs.count(a) || a<2 || a>p.limit) continue;
                TargetSearch finder(scout,6,min(23,remaining+4),.22,3);
                Plan plan=finder.run(a);
                if(plan.empty()) continue;
                unordered_set<Int> charged(p.starts.begin(),p.starts.end());
                charged.insert(p.order.begin(),p.order.end());
                auto cone=shared_core::unpaid_cone(a,plan,p,charged);
                if(cone.empty() || int(cone.size())>min(remaining,12)) continue;
                shared_core::commit(p,cone);
                p.palette.push_back(a);
                vector<Int> growth;
                for(auto e:cone) growth.push_back(e.out);
                scout.extend(growth);
                remaining-=cone.size();
                if(remaining<=2) break;
            }
            cerr<<" anchors-budget="<<(19-remaining);
        }
        paid.insert(p.starts.begin(),p.starts.end());
        int bit=0;
        for(Int v:p.order) {
            auto [a,b]=p.args.at(v);
            uint64_t mask=bank.scaffold[a]|bank.scaffold[b];
            if(bit<64) mask|=uint64_t(1)<<bit++;
            bank.scaffold[v]=mask;
        }
        bank.extend(leaves());
        int last=0;
        vector<Int> added;
        while(any_of(p.targets.begin(),p.targets.end(),[&](Int t){return !paid.count(t);})) {
            if(epochs==0 || int(added.size())>=refresh || last>=4) {
                if(int(bank.zero.size()+added.size())>budget+12) {
                    bank.reset();bank.extend(leaves());
                } else if(!added.empty()) bank.extend(added);
                refresh_routes();
                if(joint_effort) solve_joint();
                added.clear();last=0;
            }
            auto chosen=choose();
            shared_core::commit(p,chosen.plan);
            for(auto e:chosen.plan) if(paid.insert(e.out).second) {
                added.push_back(e.out);bank.paid_mask|=bank.scaffold[e.out];
            }
            ++last;
        }
        if(joint_effort) {
            solve_joint();
            Puzzle candidate(p.limit,p.width);
            candidate.starts=p.starts;candidate.targets=p.targets;
            for(Int v:p.starts) candidate.defs[v]={v};
            shared_core::commit(candidate,best_joint);
            unordered_set<Int> visited(p.starts.begin(),p.starts.end());
            auto visit=[&](auto &self,Int v)->void {
                if(!visited.insert(v).second) return;
                auto [a,b]=p.args.at(v);
                self(self,a);self(self,b);
            };
            size_t initial=visited.size();
            for(Int t:p.targets) visit(visit,t);
            cerr<<" joint="<<best_joint.size()<<" greedy="<<visited.size()-initial;
            if(candidate.order.size()<=visited.size()-initial) p=move(candidate);
        }
        cerr<<" epochs="<<epochs<<" searches="<<searches<<" shared-blocks="<<scaffolds;
        if(bilinear_mode) cerr<<" bilinear-hits="<<products.matches<<" sealed="<<products.sealed;
    }
};
}

int main(int argc,char **argv) {
    using namespace std;
    using creative::Int;
    if(argc<6 || argc>8) return 2;
    int leaves=stoi(argv[1]),width=stoi(argv[2]),refresh=stoi(argv[3]),seed=stoi(argv[5]);
    double target_credit=stod(argv[4]);
    shared_core::join_mode=65;
    shared_core::TARGET_LEAVES=true;
    string id;Int limit;int ns,nt;
    while(cin>>id>>limit>>ns>>nt) {
        shared_core::Puzzle p(limit,width);
        p.starts.resize(ns);p.targets.resize(nt);
        for(auto &v:p.starts) cin>>v;
        for(auto &v:p.targets) cin>>v;
        int n;
        if(!(cin>>n) || n<0 || n>64) throw runtime_error("invalid anchor count");
        vector<Int> anchors(n);
        for(Int &v:anchors)
            if(!(cin>>v) || v<1 || v>limit) throw runtime_error("invalid anchor");
        cerr<<id;
        creative::Planner(p,leaves,width,refresh,target_credit,seed^uint32_t(hash<string>{}(id)),
                          argc>6?stoi(argv[6]):0,argc>7?stoi(argv[7]):0).solve(anchors);
        cerr<<"\n";
        cout<<id<<' '<<p.order.size()<<'\n';
        for(Int v:p.order) {auto [a,b]=p.args.at(v);cout<<v<<' '<<p.defs.at(v).op<<' '<<a<<' '<<b<<'\n';}
    }
}
