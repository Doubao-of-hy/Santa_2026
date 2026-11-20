// Grant an old arithmetic value, isolate several precursors that can then be
// discarded together, and build the granted value again from genuine inputs.
#define main value_exchange_entry
#include "value_exchange.cpp"
#undef main
#include <array>
#ifndef PIVOT_BAN_COUNT
#define PIVOT_BAN_COUNT 3
#endif
constexpr int banCount=PIVOT_BAN_COUNT;

struct PivotBridge : Search {
    struct Case { int pivot; array<int,banCount> banned; };
    int pivotCount=0,attempts=0,restored=0;
    void close(vector<U>& have,const vector<U>& allow){
        U change;
        do {change=0;for(auto e:base){
            U got=have[e.a]&have[e.b]&allow[e.v]&~have[e.v];
            change|=got;have[e.v]|=got;
        }}while(change);
    }
    U passed(const vector<U>& have,U live){
        for(int t:goalids)live&=have[t];return live;
    }
    vector<int> removable(int pivot){
        vector<int> out;
        for(auto& b:batches){
            auto have=b.reach;
            U baseline=passed(have,b.live);have[pivot]|=b.allowed[pivot];
            close(have,b.allowed);U bits=passed(have,b.live)&~baseline;
            while(bits){int k=__builtin_ctzll(bits);bits&=bits-1;out.push_back(b.banned[k]);}
        }
        return out;
    }
    vector<Case> screen(int pivot,vector<int>& can,int limit,int quota){
        // Original ancestors precede each other in the supplied topological
        // trace. Give close ancestors priority in bounded probes.
        stable_sort(can.begin(),can.end(),[&](int a,int b){return abs(a-pivot)<abs(b-pivot);});
        vector<array<int,banCount>> choices;choices.reserve(limit);
        array<int,banCount> current;
        auto choose=[&](auto&& self,int upper,int remaining)->void{
            if(!remaining){choices.push_back(current);return;}
            for(int i=remaining-1;i<upper&&int(choices.size())<limit;i++){
                current[remaining-1]=can[i];self(self,i,remaining-1);
            }
        };
        choose(choose,int(can.size()),banCount);
        vector<Case> out;
        for(int pos=0;pos<int(choices.size())&&int(out.size())<quota;pos+=64){
            int sz=min(64,int(choices.size())-pos);U live=sz==64?~U(0):(U(1)<<sz)-1;
            vector<U> have(n),allow(n,live);
            for(int i=0;i<sz;i++)for(int v:choices[pos+i])allow[v]^=U(1)<<i;
            for(int s:seedids)have[s]=live;
            have[pivot]=live;close(have,allow);U bits=passed(have,live);
            while(bits&&int(out.size())<quota){
                int k=__builtin_ctzll(bits);bits&=bits-1;out.push_back({pivot,choices[pos+k]});
            }
        }
        return out;
    }
    template<class Accept> void joins(I t,const vector<I>& anchors,Accept accept){
        for(I a:anchors)inverse(t,a,cap,accept);
        if(t%2==0)accept(t/2,Op{t,t/2,t/2,'+'});
        I r=(I)sqrt((long double)t);while(r+1<=t/(r+1))r++;while(r>t/r)r--;
        if(r*r==t)accept(r,Op{t,r,r,'*'});
    }
    void witnessBridge(const Case& trial,const vector<Op>& repair){
        unordered_map<I,int> id=lookup;vector<I> all=values;vector<Edge> add;
        auto symbol=[&](I v){
            auto [it,ins]=id.emplace(v,int(all.size()));if(ins)all.push_back(v);return it->second;
        };
        for(auto e:repair){int v=symbol(e.v),a=symbol(e.a),b=symbol(e.b);add.push_back({v,a,b,e.op});}
        vector<char> known(all.size()),enabled(all.size(),1);vector<Edge> recipe(all.size());
        vector<int> order;for(int s:seedids)known[s]=1;for(int ban:trial.banned)enabled[ban]=0;
        auto step=[&](const vector<Edge>& edges){
            for(auto e:edges)if(enabled[e.v]&&!known[e.v]&&known[e.a]&&known[e.b]){
                order.push_back(e.v);known[e.v]=1;recipe[e.v]=e;
            }
        };
        size_t prev;do{prev=order.size();step(add);step(base);}while(prev!=order.size());
        vector<char> need(all.size());
        for(int t:goalids){if(!known[t])throw runtime_error("pivot bridge has unreachable target");need[t]=1;}
        for(auto it=order.rbegin();it!=order.rend();it++)if(need[*it]){auto e=recipe[*it];need[e.a]=need[e.b]=1;}
        vector<Op> actual;
        for(int v:order)if(need[v]){auto e=recipe[v];actual.push_back({all[v],all[e.a],all[e.b],e.op});}
        record(move(actual));
    }
    void repair(const Case& trial){
        attempts++;I target=values[trial.pivot];
        vector<U> have(n),allow(n,1);
        unordered_set<I> banned;for(int v:trial.banned){allow[v]=0;banned.insert(values[v]);}
        for(int s:seedids)have[s]=1;
        close(have,allow);
        if(have[trial.pivot]){witnessBridge(trial,{});return;}
        vector<I> anchors;
        unordered_set<I> grounded;for(int i=0;i<n;i++)if(have[i]){anchors.push_back(values[i]);grounded.insert(values[i]);}
        // One-op forward table from the fully grounded old subgraph. All
        // operands remain usable after simultaneously banning the three nodes.
        unordered_map<I,Op> forward;forward.reserve(anchors.size()*anchors.size());
        for(int i=0;i<int(anchors.size());i++)for(int j=0;j<=i;j++)
            arithmetic(anchors[i],anchors[j],cap,[&](Op e){if(!banned.count(e.v)&&!grounded.count(e.v))forward.emplace(e.v,e);});
        auto direct=forward.find(target);
        if(direct!=forward.end()){restored++;witnessBridge(trial,{direct->second});return;}
        vector<pair<I,Op>> back;
        unordered_set<I> seen;
        joins(target,anchors,[&](I x,Op e){
            if(x!=target&&!banned.count(x)&&seen.insert(x).second)back.push_back({x,e});
        });
        for(auto& [x,e]:back){
            auto it=forward.find(x);if(it!=forward.end()){restored++;witnessBridge(trial,{it->second,e});return;}
        }
        // Fork construction: the two operands of the final instruction may
        // both be new, independently synthesized intermediates.
        for(auto& [h,first]:forward){
            bool found=false;
            inverse(target,h,cap,[&](I x,Op e){
                if(found||x==target)return;auto it=forward.find(x);if(it==forward.end())return;
                restored++;witnessBridge(trial,{first,it->second,e});found=true;
            });if(found)return;
        }
        // Chain construction: the upstream intermediate may be private to
        // the middle operation, with no existing recipient anywhere else.
        for(auto& [x,last]:back){
            bool found=false;
            joins(x,anchors,[&](I h,Op middle){
                if(found||h==target||h==x)return;auto it=forward.find(h);if(it==forward.end())return;
                restored++;witnessBridge(trial,{it->second,middle,last});found=true;
            });if(found)return;
        }
        if constexpr(banCount>=4){
            // Four instructions permit a fork, or a chain, one layer
            // earlier, as well as a fork with arms costing one and two ops.
            vector<I> one;one.reserve(forward.size());
            for(auto& kv:forward)one.push_back(kv.first);sort(one.begin(),one.end());
            if(one.empty())return;
            auto distance=[&](I x){
                auto it=lower_bound(one.begin(),one.end(),x);
                I delta=cap;
                if(it!=one.end())delta=min(delta,*it-x);
                if(it!=one.begin())delta=min(delta,x-*prev(it));
                return delta;
            };
            stable_sort(back.begin(),back.end(),[&](const auto& a,const auto& b){
                I da=distance(a.first),db=distance(b.first);
                if(da!=db)return da<db;return a.first<b.first;
            });
            if(back.size()>18)back.resize(18);
            for(const auto& [x,last]:back){
                bool found=false;
                for(I h:one){
                    inverse(x,h,cap,[&](I k,Op middle){
                        if(found||k==x||k==target||h==x||h==target)return;
                        auto it=forward.find(k);if(it==forward.end())return;
                        restored++;witnessBridge(trial,{forward.at(h),it->second,middle,last});found=true;
                    });if(found)return;
                }
                joins(x,anchors,[&](I m,Op middle){
                    if(found||m==x||m==target||banned.count(m))return;
                    joins(m,anchors,[&](I h,Op second){
                        if(found||h==m||h==x||h==target)return;
                        auto it=forward.find(h);if(it==forward.end())return;
                        restored++;witnessBridge(trial,{it->second,second,middle,last});found=true;
                    });
                });
                if(found)return;
            }
            vector<pair<int,I>> branches;branches.reserve(one.size());
            for(I h:one){
                int rank=0;if(target%h==0||h%target==0)rank+=120;
                I delta=abs(h-target);
                if(delta!=0)rank+=max(0,55-int(log2((double)delta)));
                rank+=max(0,35-int(log2((double)h)));
                branches.push_back({rank,h});
            }
            const size_t take=min<size_t>(50,branches.size());
            partial_sort(branches.begin(),branches.begin()+take,branches.end(),greater<pair<int,I>>());
            for(size_t j=0;j<take;j++){
                I h=branches[j].second;bool found=false;
                inverse(target,h,cap,[&](I x,Op last){
                    if(found||x==target||x==h||banned.count(x))return;
                    joins(x,anchors,[&](I k,Op middle){
                        if(found||k==target||k==x)return;
                        auto it=forward.find(k);if(it==forward.end())return;
                        restored++;witnessBridge(trial,{forward.at(h),it->second,middle,last});found=true;
                    });
                });if(found)return;
            }
        }
    }
    void runPivot(int maxCases,int trialLimit,int perPivot){
        populate(false);vector<vector<Case>> todo;
        for(int i=0;i<n;i++){
            if(find(seedids.begin(),seedids.end(),i)!=seedids.end())continue;
            auto can=removable(i);if(can.size()<banCount)continue;
            auto cases=screen(i,can,trialLimit,perPivot);
            if(!cases.empty()){pivotCount++;todo.push_back(move(cases));}
        }
        for(int j=0;j<perPivot&&attempts<maxCases;j++)for(auto& group:todo){
            if(j<int(group.size()))repair(group[j]);if(attempts>=maxCases)break;
        }
    }
};
#ifndef PIVOT_LIBRARY
int main(int argc,char**argv){
    ios::sync_with_stdio(false);cin.tie(nullptr);string id;int ns,nt,ng;
    while(cin>>id){
        PivotBridge s;cin>>s.cap>>ns>>nt>>ng;s.seeds.resize(ns);s.goals.resize(nt);
        for(I&v:s.seeds)cin>>v;for(I&v:s.goals)cin>>v;
        for(int i=0;i<ng;i++){Op e;cin>>e.v>>e.op>>e.a>>e.b;s.original.push_back(e);}
        s.runPivot(argc>1?stoi(argv[1]):50,argc>2?stoi(argv[2]):160,argc>3?stoi(argv[3]):4);
        cout<<id<<' '<<s.pivotCount<<' '<<s.attempts<<' '<<s.restored<<' '<<s.winners.size()<<'\n';
        for(auto&pg:s.winners){cout<<pg.size()<<'\n';for(auto&e:pg)cout<<e.v<<' '<<e.op<<' '<<e.a<<' '<<e.b<<'\n';}
    }
}
#endif
