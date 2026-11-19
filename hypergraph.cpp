// Rebuild target groups in a common arithmetic hypergraph. The cost of a
// derivation counts the union of its dependencies, including repeated operands.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <functional>
#include <iostream>
#include <map>
#include <numeric>
#include <queue>
#include <random>
#include <set>
#include <tuple>
#include <unordered_map>
#include <unordered_set>
#include <vector>

using namespace std;
using I=long long;
using U=uint64_t;
struct Eq {int dst,a,b; char op;};
struct Arithmetic {I dst,a,b;char op;};

template<class F> void forward(I a,I b,I cap,F f){
    if(a<=cap-b) f(a+b,'+',a,b);
    if(a>b) f(a-b,'-',a,b);
    if(b>a) f(b-a,'-',b,a);
    if(a<=cap/b) f(a*b,'*',a,b);
    if(a%b==0) f(a/b,'/',a,b);
    if(b%a==0 && a!=b) f(b/a,'/',b,a);
}
// All x for v=f(x,known). The operation and orientation are recovered later.
template<class F> void inverse(I v,I known,I cap,F f){
    if(v>known) f(v-known);
    if(v<=cap-known) f(v+known);
    if(known>v) f(known-v);
    if(v%known==0) f(v/known);
    if(v<=cap/known) f(v*known);
    if(known%v==0) f(known/v);
}

struct Network {
    I cap;
    mt19937 rng;
    unordered_map<I,int> lookup;
    vector<I> value;
    vector<int> seeds,goals,base,usage;
    vector<Eq> edges;
    set<tuple<int,int,int,char>> unique;
    vector<vector<int>> outgoing;
    int node(I v){
        auto [it,ins]=lookup.emplace(v,(int)value.size());
        if(ins){value.push_back(v);base.push_back(-1);usage.push_back(0);}
        return it->second;
    }
    int add(I v,char op,I a,I b){
        if(v==a||v==b) return -1;
        if((op=='+'||op=='*')&&a>b) swap(a,b);
        int d=node(v),l=node(a),r=node(b);
        auto key=make_tuple(d,l,r,op);
        if(!unique.insert(key).second) return -1;
        edges.push_back({d,l,r,op});return (int)edges.size()-1;
    }
    void trace(bool primary){
        int n;cin>>n;
        for(int i=0;i<n;++i){
            I v,a,b;char op;cin>>v>>op>>a>>b;
            int e=add(v,op,a,b);
            if(e>=0 && primary) base[lookup.at(v)]=e;
            usage[lookup.at(a)]+=primary?3:1;
            if(a!=b) usage[lookup.at(b)]+=primary?3:1;
        }
    }
    // Meet two independently computed sides of the last arithmetic operation.
    // For an affine join, index admissible corrections by residue modulo the
    // multiplier, so corrections can greatly exceed the ordinary remainder.
    void meet(const vector<int>& outputs,const vector<int>& core,
              const unordered_map<I,vector<Arithmetic>>& ready,int original,int budget){
        struct Choice {I left,right,factor;char op;int merit;};
        unordered_map<I,int> atoms;
        for(int j=0;j<original;++j)atoms.emplace(value[j],j);
        for(const auto &kv:ready)atoms.emplace(kv.first,-1);
        auto strength=[&](I x,I goal){
            if(x==goal)return -10000;
            int i=atoms.at(x);
            if(i>=0)return 90+min(35,usage[i]);
            int best=-10000;
            for(const auto &e:ready.at(x)){
                if(e.a==goal||e.b==goal)continue;
                best=max(best,24+min(26,usage[lookup.at(e.a)])+min(26,usage[lookup.at(e.b)]));
            }
            return best;
        };
        auto ensure=[&](I x,I goal){
            if(atoms.at(x)>=0)return;
            for(auto e:ready.at(x))if(e.a!=goal&&e.b!=goal)add(e.dst,e.op,e.a,e.b);
        };
        vector<vector<Choice>> pools(outputs.size());
        auto propose=[&](int i,I a,I b,I f,char op){
            I d=value[outputs[i]];
            if(!atoms.count(a)||!atoms.count(b)||a==d||b==d||d==f)return;
            if(f==1 && atoms.at(a)>=0 && atoms.at(b)>=0)return;
            int quality=strength(a,d)+strength(b,d);
            if(quality<0)return;
            if(f>1)quality+=min(16,usage[lookup.at(f)])-30;
            if(f==1&&a==b)quality+=7;
            uint64_t hash=uint64_t(a)*11400714819323198485ull ^ (uint64_t(b)*1099511628211ull) ^ f;
            pools[i].push_back({a,b,f,op,quality+int(hash%31)});
        };
        for(size_t i=0;i<outputs.size();++i){
            I d=value[outputs[i]];
            for(const auto &[x,id]:atoms){
                if(x<d && x<=d-x) propose(i,x,d-x,1,'+');
                if(x<=cap-d)propose(i,d+x,x,1,'-');
                if(x>1 && d%x==0 && x<=d/x)propose(i,x,d/x,1,'*');
                if(x>1 && x<=cap/d)propose(i,d*x,x,1,'/');
            }
        }
        vector<pair<I,I>> columns;
        columns.reserve(atoms.size());
        for(int k:core){
            I f=value[k];if(f<3)continue;
            columns.clear();
            for(auto [x,id]:atoms)columns.emplace_back(x%f,x);
            sort(columns.begin(),columns.end());
            for(size_t i=0;i<outputs.size();++i){
                I d=value[outputs[i]];if(d==f)continue;
                for(int sign=0;sign<2;++sign){
                    I residue=sign?(f-d%f)%f:d%f;
                    auto lo=lower_bound(columns.begin(),columns.end(),make_pair(residue,I(0)));
                    auto hi=upper_bound(lo,columns.end(),make_pair(residue,cap));
                    int len=hi-lo;
                    // Sample the two ends (small corrections and small quotients)
                    // and the interior of a large congruence class.
                    int count=min(40,len);
                    for(int j=0;j<count;++j){
                        int p=(len<=40||j<10)?j:j<20?len-20+j:int((int64_t(j-19)*len)/21);
                        I b=lo[p].second;
                        if(sign){
                            if(b>cap-d)continue;
                            I q=(d+b)/f;
                            if(q>1)propose(i,q,b,f,'-');
                        }else if(b!=d){
                            I q=llabs(d-b)/f;
                            if(q>1)propose(i,q,b,f,d>b?'+':'r');
                        }
                    }
                }
            }
        }
        for(size_t i=0;i<outputs.size();++i){
            I d=value[outputs[i]]; auto &choices=pools[i];
            stable_sort(choices.begin(),choices.end(),[](const Choice&a,const Choice&b){return a.merit>b.merit;});
            set<tuple<I,I,I,char>> seen;map<pair<I,char>,int> groups;
            int kept=0;
            for(auto c:choices){
                if(!seen.emplace(c.left,c.right,c.factor,c.op).second)continue;
                if(++groups[{c.factor,c.op}]>max(4,budget/3))continue;
                ensure(c.left,d);ensure(c.right,d);
                I x=c.left;
                if(c.factor!=1){x*=c.factor;add(x,'*',c.left,c.factor);}
                if(c.op=='r')add(d,'-',c.right,x);
                else add(d,c.op,x,c.right);
                if(++kept>=budget)break;
            }
        }
    }
    // Shift internal values on both sides of the same instruction. An offset
    // introduced in one place can cancel several levels later. The target
    // values themselves are still required exactly in the assembled graph.
    void offsets(const vector<int>& core,int original,int count){
        vector<I> shifts;
        for(I x:{1,2,3,4,5,7,8,16})if(lookup.count(x))shifts.push_back(x);
        for(int i:core)if(value[i]<=100000 && find(shifts.begin(),shifts.end(),value[i])==shifts.end())
            shifts.push_back(value[i]);
        shifts.resize(min<int>(count,shifts.size()));
        vector<I> sorted(value.begin(),value.begin()+original);
        sort(sorted.begin(),sorted.end());
        vector<vector<I>> domain(original);
        for(int i=0;i<original;++i){
            I x=value[i];set<I> choices{x};
            for(I k:shifts){
                if(k<x){
                    choices.insert(x-k); add(x-k,'-',x,k);add(x,'+',x-k,k);
                }
                if(x<=cap-k){
                    choices.insert(x+k);add(x+k,'+',x,k);add(x,'-',x+k,k);
                }
                if(k>=2 && k<=16){
                    if(x<=cap/k){choices.insert(x*k);add(x*k,'*',x,k);add(x,'/',x*k,k);}
                    if(x%k==0){choices.insert(x/k);add(x/k,'/',x,k);add(x,'*',x/k,k);}
                }
            }
            auto center=lower_bound(sorted.begin(),sorted.end(),x)-sorted.begin();
            for(int j=max<long long>(0,center-2);j<min<long long>(original,center+3);++j)
                choices.insert(sorted[j]);
            domain[i].assign(choices.begin(),choices.end());
        }
        for(int i=0;i<original;++i)if(base[i]>=0){
            auto host=edges[base[i]];
            unordered_set<I> destinations(domain[i].begin(),domain[i].end());
            for(I a:domain[host.a])for(I b:domain[host.b]){
                forward(a,b,cap,[&](I v,char op,I l,I r){
                    auto found=lookup.find(v);
                    if(destinations.count(v)||(found!=lookup.end()&&found->second<original))
                        add(v,op,l,r);
                });
            }
        }
    }
    void enrich(int coreSize,int bridgeBudget,int perturb){
        int original=value.size();
        vector<int> primary;
        for(int i=0;i<original;++i) if(base[i]>=0) primary.push_back(i);
        for(int i=0;i<original;++i) for(int j=0;j<=i;++j)
            forward(value[i],value[j],cap,[&](I v,char op,I a,I b){
                if(lookup.count(v)) add(v,op,a,b);
            });
        vector<int> core(original); iota(core.begin(),core.end(),0);
        for(int s:seeds) usage[s]+=10000;
        stable_sort(core.begin(),core.end(),[&](int a,int b){return usage[a]>usage[b];});
        core.resize(min((int)core.size(),coreSize));
        unordered_map<I,vector<Arithmetic>> ready;
        for(int i=0;i<(int)core.size();++i) for(int j=0;j<=i;++j){
            forward(value[core[i]],value[core[j]],cap,[&](I v,char op,I a,I b){
                if(lookup.count(v)||v==a||v==b) return;
                auto &options=ready[v];
                if(options.size()<3) options.push_back({v,a,b,op});
            });
        }
        vector<int> outputs=goals;
        for(int i:primary) if(find(outputs.begin(),outputs.end(),i)==outputs.end()) outputs.push_back(i);
        for(int d:outputs){
            I out=value[d];
            vector<tuple<int,I,int>> options;
            for(int j=0;j<original;++j){
                inverse(out,value[j],cap,[&](I x){
                    if(x==out||value[j]==out) return;
                    auto found=ready.find(x);if(found==ready.end())return;
                    const auto &first=found->second.front();
                    int merit=min(50,usage[j])+min(32,usage[lookup.at(first.a)])
                              +min(32,usage[lookup.at(first.b)])+(rng()%9);
                    options.emplace_back(-merit,x,j);
                });
            }
            sort(options.begin(),options.end());
            int used=0;
            set<pair<I,int>> seen;
            for(auto [merit,x,j]:options){
                if(!seen.emplace(x,j).second)continue;
                for(auto e:ready.at(x)) add(e.dst,e.op,e.a,e.b);
                forward(x,value[j],cap,[&](I v,char op,I a,I b){if(v==out)add(v,op,a,b);});
                if(++used>=bridgeBudget) break;
            }
        }
        if(bridgeBudget>=20) meet(outputs,core,ready,original,bridgeBudget);
        if(perturb>0) offsets(core,original,perturb);
    }
    void support_model(int previous,int nativeCount){
        if(previous==(int)value.size())return;
        vector<int> core(nativeCount);
        iota(core.begin(),core.end(),0);
        stable_sort(core.begin(),core.end(),[&](int a,int b){return usage[a]>usage[b];});
        if(core.size()>86)core.resize(86);
        unordered_map<I,Arithmetic> one;
        for(int i=0;i<(int)core.size();++i)for(int j=0;j<=i;++j)
            forward(value[core[i]],value[core[j]],cap,[&](I v,char op,I a,I b){
                if(v==a||v==b)return;
                one.emplace(v,Arithmetic{v,a,b,op});
                auto it=lookup.find(v);if(it!=lookup.end()&&it->second>=previous)add(v,op,a,b);
            });
        int last=value.size();
        for(int i=previous;i<last;++i){
            I t=value[i];int found=0;
            for(int j:core){
                I b=value[j];if(b==t)continue;
                inverse(t,b,cap,[&](I a){
                    if(a==t||a<=0||found>=10)return;
                    auto it=one.find(a);
                    if(it==one.end() || it->second.a==t || it->second.b==t)return;
                    auto e=it->second;add(e.dst,e.op,e.a,e.b);
                    forward(a,b,cap,[&](I v,char op,I l,I r){if(v==t){add(v,op,l,r);++found;}});
                });
                if(found>=10)break;
            }
        }
    }
    void index_edges(){
        outgoing.resize(value.size());
        for(int i=0;i<(int)edges.size();++i){
            auto e=edges[i];outgoing[e.a].push_back(i);
            if(e.a!=e.b)outgoing[e.b].push_back(i);
        }
    }
    void commit(int x,const vector<int>& route,vector<int>& assigned,vector<int>& order){
        if(assigned[x]!=-1) return;
        int i=route[x];if(i<0) throw runtime_error("disconnected derivation");
        auto e=edges[i];
        commit(e.a,route,assigned,order);commit(e.b,route,assigned,order);
        assigned[x]=i;order.push_back(x);
    }
    // All dependencies in a settled label have one consistent chosen recipe.
    // Combining labels therefore charges each newly materialized value once.
    int augment(vector<int>& assigned,vector<int>& order,const vector<U>& favored,int trial,
                const vector<int>& wanted){
        const int n=value.size(),words=(n+63)/64;
        vector<U> storage(size_t(n)*words,0);
        vector<int> price(n,1<<28),route(n,-1),tie(n,0),discount(n);
        vector<char> closed(n,0),isgoal(n,0);
        using Item=tuple<int,int,int>;
        priority_queue<Item,vector<Item>,greater<Item>> todo;
        vector<int> pending;
        for(int x:wanted) if(assigned[x]==-1){pending.push_back(x);isgoal[x]=1;}
        int remaining=pending.size();
        if(!remaining)return 0;
        for(int i=0;i<n;++i) if(assigned[i]!=-1){
            todo.emplace(0,0,i);price[i]=0;
        }
        while(!todo.empty() && remaining){
            auto [c,t,x]=todo.top();todo.pop();
            if(closed[x]||c!=price[x]||t!=tie[x])continue;
            closed[x]=1;if(isgoal[x])--remaining;
            for(int ei:outgoing[x]){
                auto e=edges[ei];int d=e.dst;
                if(closed[d]||!closed[e.a]||!closed[e.b])continue;
                int best=price[d];
                if(max(price[e.a],price[e.b])+2>best)continue;
                U *a=&storage[size_t(e.a)*words], *b=&storage[size_t(e.b)*words];
                int cst=(favored[d/64]&(U(1)<<(d%64)))?2:4;
                for(int w=0;w<words && cst<=best;++w){
                    U bits=a[w]|b[w];
                    if(bits)cst+=4*__builtin_popcountll(bits)-2*__builtin_popcountll(bits&favored[w]);
                }
                if(cst>best)continue;
                int noise=(trial%3==0)?ei:int((uint32_t(ei)*2654435761u+uint32_t(trial)*764321u)%65521u);
                if(cst==best && noise>=tie[d])continue;
                U *out=&storage[size_t(d)*words];
                for(int w=0;w<words;++w)out[w]=a[w]|b[w];
                out[d/64]|=U(1)<<(d%64);
                price[d]=cst;tie[d]=noise;route[d]=ei;
                todo.emplace(cst,noise,d);
            }
        }
        vector<int> frequency(n);
        for(int g:pending){
            if(!closed[g])throw runtime_error("unreachable target");
            U *bits=&storage[size_t(g)*words];
            for(int w=0;w<words;++w) for(U z=bits[w];z;z&=z-1)
                ++frequency[w*64+__builtin_ctzll(z)];
        }
        int chosen=-1; double best=1e30;
        for(int g:pending){
            U *bits=&storage[size_t(g)*words];
            int count=0,overlap=0;
            for(int w=0;w<words;++w) for(U z=bits[w];z;z&=z-1){
                ++count;overlap+=min(4,frequency[w*64+__builtin_ctzll(z)]-1);
            }
            double priority=count-(trial%4)*0.15*overlap+(trial%2?(rng()%101)*0.004:0);
            if(priority<best){chosen=g;best=priority;}
        }
        commit(chosen,route,assigned,order);return 1;
    }
    void solve(int trials,int variants,int islands){
        int n=value.size(),words=(n+63)/64;
        vector<int> reference(n,-1),baseOrder;
        for(int s:seeds)reference[s]=-2;
        for(int g:goals)commit(g,base,reference,baseOrder);
        vector<vector<int>> closures(goals.size());
        for(size_t i=0;i<goals.size();++i){
            vector<int> kept(n,-1);for(int s:seeds)kept[s]=-2;
            commit(goals[i],base,kept,closures[i]);
        }
        using Result=pair<int,vector<int>>;
        vector<Result> best;
        set<vector<int>> signatures;
        vector<vector<int>> children(n);
        vector<char> target(n);
        for(int g:goals)target[g]=1;
        for(int x:baseOrder){auto e=edges[base[x]];children[e.a].push_back(x);
            if(e.a!=e.b)children[e.b].push_back(x);}
        vector<int> centers=baseOrder;
        shuffle(centers.begin(),centers.end(),rng);
        stable_sort(centers.begin(),centers.end(),[&](int a,int b){
            return min<int>(5,children[a].size())>min<int>(5,children[b].size());});
        for(int rep=0;rep<trials+islands;++rep){
            vector<int> indices(goals.size());iota(indices.begin(),indices.end(),0);
            shuffle(indices.begin(),indices.end(),rng);
            if(indices.empty())break;
            if(rep%4==2){
                int center=indices[0];set<int> neighborhood(closures[center].begin(),closures[center].end());
                stable_sort(indices.begin()+1,indices.end(),[&](int a,int b){
                    auto measure=[&](int j){int sum=0;for(int v:closures[j])sum+=neighborhood.count(v);return sum/sqrt(1.+closures[j].size());};
                    return measure(a)>measure(b);
                });
            }
            static const int widths[]={1,2,4,7,100,3,5,9,100,2};
            int release=min<int>(indices.size(),widths[rep%10]);
            vector<int> assigned(n,-1),order;
            for(int s:seeds)assigned[s]=-2;
            vector<int> wanted;
            if(rep<trials){
                wanted=goals;
                for(int i=release;i<(int)indices.size();++i)commit(goals[indices[i]],base,assigned,order);
            }else{
                if(centers.empty())break;
                int index=rep-trials;
                int center=centers[(index%3?index/3:rng()%centers.size())%centers.size()];
                int depth=(index/3)%4+1;
                vector<char> region(n,0),boundary(n,0),down(n,0);
                region[center]=1;
                vector<int> frontier{center};
                while(depth-- && !frontier.empty()){
                    vector<int> next;
                    for(int x:frontier)for(int y:children[x])if(!region[y]){
                        region[y]=1;next.push_back(y);
                    }
                    frontier.swap(next);
                }
                for(int x:baseOrder)if(region[x]){
                    bool exit=target[x];
                    for(int child:children[x])if(!region[child])exit=true;
                    if(exit){boundary[x]=1;wanted.push_back(x);}
                }
                if(wanted.empty()||wanted.size()>14)continue;
                // Traverse the retained graph from the targets, stopping at
                // each cut outlet. Retained descendants are not free operands.
                vector<char> retained(n,0);
                function<void(int)> keep=[&](int x){
                    if(retained[x]||boundary[x]||base[x]<0)return;
                    retained[x]=1;auto e=edges[base[x]];keep(e.a);keep(e.b);
                };
                for(int g:goals)keep(g);
                for(int x:baseOrder){
                    auto e=edges[base[x]];down[x]=boundary[x]||down[e.a]||down[e.b];
                    if(retained[x] && !down[x])commit(x,base,assigned,order);
                }
            }
            vector<U> favored(words);
            for(int v:baseOrder) if(rep%5 && usage[v]>=3 && rng()%100<unsigned(15+rep%4*15))
                favored[v/64]|=U(1)<<(v%64);
            if(rep%4==3 && !best.empty()) for(int ei:best[0].second){
                int v=edges[ei].dst;if(rng()%3==0)favored[v/64]|=U(1)<<(v%64);
            }
            while(order.size()<=baseOrder.size()+3 && augment(assigned,order,favored,rep,wanted)){}
            if(order.size()>baseOrder.size()+3)continue;
            for(int g:goals)commit(g,base,assigned,order);
            vector<int> materialized(n,-1),used;
            for(int s:seeds)materialized[s]=-2;
            for(int g:goals)commit(g,assigned,materialized,used);
            if(used.size()>baseOrder.size()+3)continue;
            vector<int> eqs;for(int x:used)eqs.push_back(assigned[x]);
            auto sign=eqs;sort(sign.begin(),sign.end());
            if(!signatures.insert(move(sign)).second)continue;
            best.emplace_back((int)eqs.size(),move(eqs));
            sort(best.begin(),best.end());if((int)best.size()>variants)best.pop_back();
        }
        cout<<best.size()<<'\n';
        for(auto &result:best){
            cout<<result.first<<'\n';
            for(int ei:result.second){auto e=edges[ei];cout<<value[e.dst]<<' '<<e.op<<' '<<value[e.a]<<' '<<value[e.b]<<'\n';}
        }
    }
};
int main(int argc,char** argv){
    if(argc!=6 && argc!=8)return 2;
    ios::sync_with_stdio(false);cin.tie(nullptr);
    Network net;
    int s,t,k;cin>>net.cap>>s>>t>>k;
    net.rng.seed(stoul(argv[argc-1]));
    for(int i=0;i<s;++i){I x;cin>>x;net.seeds.push_back(net.node(x));}
    for(int i=0;i<t;++i){I x;cin>>x;net.goals.push_back(net.node(x));}
    for(int i=0;i<k;++i)net.trace(i==0);
    int nativeCount=net.value.size();
    net.enrich(stoi(argv[2]),stoi(argv[3]),argc==8?stoi(argv[6]):0);
    int previous=net.value.size(),additional;
    if(cin>>additional){
        for(int j=0;j<additional;++j){
            I v,a,b;char op;cin>>v>>op>>a>>b;net.add(v,op,a,b);
        }
        net.support_model(previous,nativeCount);
    }
    net.index_edges();
    net.solve(stoi(argv[1]),stoi(argv[4]),argc==8?stoi(argv[5]):0);
}
