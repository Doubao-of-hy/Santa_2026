// Materialize and share a recovered product table with a circuit's original
// arithmetic paths. Other goals stay available at their original cost.
#include <bits/stdc++.h>
#include "integer_factors.hpp"
#define main hypergraph_entry
#include "hypergraph.cpp"
#undef main
namespace smallword{
#define main smooth_entry
#include "smooth_windows.cpp"
#undef main
}
struct Token {I t,a,b,k,r,d,e;};
struct Builder {
    Network net;
    vector<Token> tokens;
    vector<I> primaries;
    vector<I> values;
    vector<int> used;
    map<I,vector<Token>> lanes;
    unique_ptr<smallword::Search> cheap;
    unordered_map<I,int> cost;
    unordered_map<I,int> factor_cost;
    set<I> base_values, seeds;
    set<int> model_nodes;
    vector<U> groups;
    map<U,set<I>> group_roots,group_centers,group_bias;
    I cap;
    bool legal(__int128 v)const{return v>=1 && v<=cap;}
    void add(I v,char op,I a,I b){
        if(v==a||v==b)return;
        net.add(v,op,a,b);
        // A completed target can pay for a latent center by exact inversion.
        // Keep each legal orientation; the scheduler admits only acyclic paths.
        if(op=='+'){net.add(a,'-',v,b);net.add(b,'-',v,a);}
        else if(op=='-'){net.add(a,'+',v,b);net.add(b,'-',a,v);}
        else if(op=='*'){net.add(a,'/',v,b);net.add(b,'/',v,a);}
        else if(op=='/'){net.add(a,'*',v,b);net.add(b,'/',a,v);}
        model_nodes.insert(net.lookup.at(v));
    }
    int helper(I v){
        if(v<1 || v>cap)return 100;
        if(cost.count(v))return cost.at(v);
        auto w=cheap->cheap(v);
        if(w.cost<=2){
            smallword::Plan plan;unordered_set<int64_t> done;
            cheap->append(v,{},plan,done);
            for(auto e:plan)add(e.out,e.op,e.a,e.b);
            return cost[v]=w.cost;
        }
        if(base_values.count(v))return cost[v]=1;
        return cost[v]=100;
    }
    int coefficient(I v){
        auto it=factor_cost.find(v);if(it!=factor_cost.end())return it->second;
        int price=helper(v);
        if(v>=4 && v<=1000000000000LL){
            vector<tuple<int,I,I>> ways;
            for(auto factor:factors::divisors(v)){
                I a=factor,b=v/a;
                if(a<=1||a>b)continue;
                int ca=helper(a),cb=helper(b);
                if(ca>2||cb>2)continue;
                ways.emplace_back(1+ca+(a!=b?cb:0),a,b);
            }
            sort(ways.begin(),ways.end());if(ways.size()>4)ways.resize(4);
            for(auto [c,a,b]:ways){add(v,'*',a,b);price=min(price,c);}
        }
        return factor_cost[v]=price;
    }
    void hub(I x){
        if(helper(x)<=2)return;
        bool found=false;
        for(I a:values){
            if(a<1)continue;
            auto offer=[&](I b,char op,bool left){
                if(!legal(b)||b==x||helper(b)>2)return;
                add(x,op,left?b:a,left?a:b);found=true;
            };
            if(x>a)offer(x-a,'+',true);
            if(legal((__int128)x+a))offer(x+a,'-',true);
            if(a>x)offer(a-x,'-',false);
            if(x%a==0)offer(x/a,'*',true);
            if(legal((__int128)x*a))offer(x*a,'/',true);
            if(a%x==0)offer(a/x,'/',false);
            if(found)break;
        }
        if(found){cost[x]=3;return;}
        // A short radix recurrence guarantees that every recovered hub is
        // reachable from the official seeds, including entirely new hubs.
        if(x<=1)return;
        I radix=2;
        if(x>1024){
            for(I s:{31,32,64,17,16,8})if(helper(s)<=1){radix=s;break;}
        }
        I q=x/radix,r=x%radix;
        if(!q)return;
        if(helper(radix)>2 && radix==2){hub(1);add(2,'+',1,1);cost[2]=1;}
        hub(q);
        if(r)hub(r);
        if(q>1)add(q*radix,'*',q,radix);
        if(r)add(x,'+',q*radix,r);
        cost[x]=6;
    }
    bool shift(I out,I base,I delta){
        if(out!=base+delta||!legal(out))return false;
        if(!delta)return true;
        I bias=abs(delta);
        if(helper(bias)>2)return false;
        add(out,delta>0?'+':'-',base,bias);return true;
    }
    void lane(I t,I anchor,I m,I q,I c,const vector<I>& offsets){
        // q*t = m*(anchor+d)+e. The q side may temporarily exceed the official cap.
        __int128 final=(__int128)q*t;
        if(!legal(final) || coefficient(m)>4 || (q!=1 && coefficient(q)>4))return;
        for(I d:offsets){
            __int128 middle=(__int128)anchor+d,prod=middle*m,rem=(__int128)c-( __int128)m*d;
            if(!legal(middle)||!legal(prod)||rem< -cap||rem>cap)continue;
            I e=I(rem);
            if((d&&helper(abs(d))>2)||(e&&helper(abs(e))>2))continue;
            if(!shift(I(middle),anchor,d))continue;
            if(m!=1)add(I(prod),'*',I(middle),m);
            if(!shift(I(final),I(prod),e))continue;
            if(q!=1)add(t,'/',I(final),q);
        }
    }
    void stages(const Token& z,I center,const vector<Token>& peers){
        if(z.k<4||z.k>1000000000000LL)return;
        using Route=tuple<double,I,I,I,I,I>;
        vector<Route> routes;
        for(auto vf:factors::divisors(z.k)){
            I f=vf,g=z.k/f;
            if(f==1||g==1)continue;
            int cf=coefficient(f),cg=coefficient(g);if(cf>4||cg>4)continue;
            bool shared=false;
            for(auto other:peers)shared|=other.k==f;
            I u=llround((long double)z.r/g);
            for(I left:{u-1,u,u+1}){
                I v=z.r-g*left;if(v && helper(abs(v))>2)continue;
                I d=llround((long double)left/f);
                for(I first:{I(0),d,d-1,d+1}){
                    I second=left-f*first;
                    if((first&&helper(abs(first))>2)||(second&&helper(abs(second))>2))continue;
                    __int128 base=(__int128)center+first, prod=base*f, mid=prod+second, last=mid*g;
                    if(!legal(base)||!legal(prod)||!legal(mid)||!legal(last))continue;
                    double rank=cf+cg+2+(first?1+helper(abs(first)):0)
                                       +(second?1+helper(abs(second)):0)+(v?1+helper(abs(v)):0);
                    if(base_values.count(I(mid)))rank-=3;
                    if(base_values.count(I(base)))rank-=1;
                    if(shared)rank-=1.1;
                    for(auto other:peers)if(other.k==f && abs(other.t-I(mid))<=64)rank-=.9;
                    routes.emplace_back(rank,f,g,first,second,v);
                }
            }
        }
        sort(routes.begin(),routes.end());routes.erase(unique(routes.begin(),routes.end()),routes.end());
        if(routes.size()>12)routes.resize(12);
        for(auto [rank,f,g,d,e,v]:routes){
            I base=center+d,prod=base*f,mid=prod+e,last=mid*g;
            shift(base,center,d);add(prod,'*',base,f);shift(mid,prod,e);
            add(last,'*',mid,g);shift(z.t,last,v);
            for(auto other:peers)if(other.k==f && other.t!=mid && abs(other.t-mid)<=4096){
                shift(mid,other.t,mid-other.t);
                shift(other.t,mid,other.t-mid);
            }
        }
    }
    #include "factor_bridges.hpp"
    #include "matrix_groups.hpp"
    void model(){
        set<I> hubs(primaries.begin(),primaries.end());
        for(auto z:tokens){hubs.insert(z.a);hubs.insert(z.b);lanes[z.a*z.b].push_back(z);}
        vector<I> safe;unordered_set<I> known;
        for(int s:net.seeds){safe.push_back(net.value[s]);known.insert(net.value[s]);seeds.insert(net.value[s]);}
        I ceiling=max(I(2000000),*hubs.rbegin()*4);
        for(size_t i=0;i<net.base.size();++i)if(net.base[i]>=0)base_values.insert(net.value[i]);
        // First recipes are provided in chronological order; use their edges
        // instead of value IDs, which put all final goals near the front.
        for(auto e:net.edges){
            I x=net.value[e.dst],a=net.value[e.a],b=net.value[e.b];
            if(x<=ceiling&&known.count(a)&&known.count(b)&&known.insert(x).second)safe.push_back(x);
        }
        values=safe;
        stable_sort(values.begin(),values.end(),[&](I a,I b){
            return net.usage.at(net.lookup.at(a))>net.usage.at(net.lookup.at(b));});
        vector<int64_t> small(values.begin(),values.end());
        cheap=make_unique<smallword::Search>(cap,-1,0,0,0,move(small));
        for(I h:hubs)hub(h);
        factor_bridges(hubs);
        for(const auto& item:lanes){
            I c=item.first;const auto& z=item.second.front();
            for(const auto& entry:lanes){
                I other=entry.first;if(c==other)continue;
                const auto& p=entry.second.front();
                for(I common:{z.a,z.b})if(common==p.a||common==p.b){
                    I x=c/common,y=other/common,f=gcd(x,y),num=x/f,den=y/f;
                    if((num>1&&coefficient(num)>4)||(den>1&&coefficient(den)>4))continue;
                    I inner=other/den;
                    if(den!=1)add(inner,'/',other,den);
                    if(num!=1)add(c,'*',inner,num);
                    if(legal((__int128)other*num)){
                        if(num!=1)add(other*num,'*',other,num);
                        if(den!=1)add(c,'/',other*num,den);
                    }
                }
            }
        }
        map<I,U> hmask;
        map<int,int> target_position;
        for(size_t i=0;i<net.goals.size();++i)target_position[net.goals[i]]=i;
        U all=0;
        for(auto &entry:lanes){
            I center=entry.first;auto &rows=entry.second;U mask=0;
            for(auto z:rows){
                add(center,'*',z.a,z.b);
                U bit=U(1)<<target_position.at(net.lookup.at(z.t));mask|=bit;
                hmask[z.a]|=bit;hmask[z.b]|=bit;
                set<I> shifts{0,z.d,z.d-1,z.d+1};
                for(auto other:rows)if(other.k==1)shifts.insert(other.r);
                lane(z.t,center,z.k,1,z.r,vector<I>(shifts.begin(),shifts.end()));
                stages(z,center,rows);
                if(z.k>1 && helper(z.k)<=2 && legal((__int128)z.k*center)
                   && (!z.r||helper(abs(z.r))<=2)){
                    for(auto axis:{pair<I,I>{z.a,z.b},{z.b,z.a}}){
                        I partial=z.k*axis.first;
                        add(partial,'*',z.k,axis.first);add(center*z.k,'*',partial,axis.second);
                    }
                    shift(z.t,center*z.k,z.r);
                }
                for(auto from:rows)if(from.t!=z.t){
                    I g=gcd(z.k,from.k),m=z.k/g,q=from.k/g;
                    if(q>32 || m>1000000)continue;
                    __int128 c=(__int128)q*z.r-(__int128)m*from.r;
                    if(c< -cap||c>cap)continue;
                    I d=llround((long double)c/m);
                    lane(z.t,from.t,m,q,I(c),{0,d,d-1,d+1});
                }
            }
            groups.push_back(mask);all|=mask;
        }
        for(auto x:hmask)groups.push_back(x.second);
        groups.push_back(all);
        extend_groups(all);
        sort(groups.begin(),groups.end());groups.erase(unique(groups.begin(),groups.end()),groups.end());
        for(U group:groups){
            map<I,int> uses;
            for(auto z:tokens){
                U bit=U(1)<<target_position.at(net.lookup.at(z.t));
                if(!(group&bit))continue;
                group_roots[group].insert(z.a);group_roots[group].insert(z.b);
                group_centers[group].insert(z.a*z.b);
                for(I v:{z.k,abs(z.r),abs(z.d),abs(z.e),z.a*z.b+z.d})
                    if(v>1 && net.lookup.count(v))++uses[v];
            }
            for(auto [v,count]:uses)if(count>1)group_bias[group].insert(v);
        }
        const int n=net.value.size();net.outgoing.resize(n);
        for(size_t i=0;i<net.edges.size();++i){
            auto e=net.edges[i];net.outgoing[e.a].push_back(i);if(e.b!=e.a)net.outgoing[e.b].push_back(i);
        }
    }
    void solve(int attempts){
        int n=net.value.size(),words=(n+63)/64;
        vector<int> base(n,-1),order;
        for(int s:net.seeds)base[s]=-2;
        for(int g:net.goals)net.commit(g,net.base,base,order);
        vector<int> best=base;int incumbent=order.size();
        vector<pair<int,vector<int>>> candidates;
        int rep=0;
        for(int pass=0;pass<attempts;++pass){
            shuffle(groups.begin(),groups.end(),net.rng);
            for(U group:groups){
                ++rep;
                vector<int> assigned(n,-1),made,wanted;
                for(int s:net.seeds)assigned[s]=-2;
                for(size_t i=0;i<net.goals.size();++i){
                    int g=net.goals[i];
                    if(group&(U(1)<<i))wanted.push_back(g);
                    else net.commit(g,best,assigned,made);
                }
                if(pass%3==2&&wanted.size()>1){
                    vector<int> anchors=wanted;
                    shuffle(anchors.begin(),anchors.end(),net.rng);
                    int chosen=anchors[0],minimum=INT_MAX;
                    for(int g:anchors){
                        vector<int> trial=assigned,extra;
                        net.commit(g,best,trial,extra);
                        if(int(extra.size())<minimum){minimum=extra.size();chosen=g;}
                        if(pass%6==5)break;
                    }
                    net.commit(chosen,best,assigned,made);
                }
                vector<U> favored(words,0);
                for(int x:model_nodes)if(pass==0||net.rng()%4)
                    favored[x/64]|=U(1)<<(x%64);
                if(pass%6!=0){
                    vector<int> prepay;
                    auto include=[&](const set<I>& values){for(I v:values)
                        if(net.lookup.count(v))prepay.push_back(net.lookup.at(v));};
                    if(pass%6==1||pass%6==3)include(group_roots[group]);
                    if(pass%6==2||pass%6==4||pass%6==5)include(group_centers[group]);
                    if(pass%6>=3)include(group_bias[group]);
                    sort(prepay.begin(),prepay.end());prepay.erase(unique(prepay.begin(),prepay.end()),prepay.end());
                    while(!prepay.empty()&&net.augment(assigned,made,favored,rep,prepay)){}
                }
                while(net.augment(assigned,made,favored,rep,wanted)){}
                vector<int> active(n,-1),unique;
                for(int s:net.seeds)active[s]=-2;
                for(int g:net.goals)net.commit(g,assigned,active,unique);
                int len=unique.size();
                bool neutral=len==incumbent && pass>0 && net.rng()%3==0;
                if(len<incumbent||neutral){
                    best=active;incumbent=len;
                    if(!neutral){
                        vector<int> e;for(int x:unique)e.push_back(active[x]);
                        candidates.emplace_back(len,move(e));
                    }
                }
            }
        }
        sort(candidates.begin(),candidates.end());if(candidates.size()>5)candidates.resize(5);
        cout<<candidates.size()<<'\n';
        for(auto& c:candidates){
            cout<<c.first<<'\n';
            for(int i:c.second){auto e=net.edges[i];cout<<net.value[e.dst]<<' '<<e.op<<' '<<net.value[e.a]<<' '<<net.value[e.b]<<'\n';}
        }
    }
    void dump(){
        cout<<net.edges.size()<<' '<<groups.size()<<'\n';
        for(auto e:net.edges)cout<<net.value[e.dst]<<' '<<e.op<<' '<<net.value[e.a]<<' '<<net.value[e.b]<<'\n';
        for(U group:groups){
            cout<<__builtin_popcountll(group);
            for(size_t i=0;i<net.goals.size();++i)if(group&(U(1)<<i))cout<<' '<<net.value[net.goals[i]];
            cout<<'\n';
        }
    }
};
int main(int argc,char**argv){
    if(argc!=3)return 2;
    ios::sync_with_stdio(false);cin.tie(nullptr);
    Builder b;int ns,nt,n;
    if(!(cin>>b.cap>>ns>>nt>>n))return 0;
    b.net.cap=b.cap;b.net.rng.seed(stoul(argv[2]));
    for(int i=0;i<ns;++i){I x;cin>>x;b.net.seeds.push_back(b.net.node(x));}
    for(int i=0;i<nt;++i){I x;cin>>x;b.net.goals.push_back(b.net.node(x));}
    b.net.trace(true);
    int donors;cin>>donors;
    for(int i=0;i<donors;++i)b.net.trace(false);
    for(int i=0;i<n;++i){Token z;cin>>z.t>>z.a>>z.b>>z.k>>z.r>>z.d>>z.e;b.tokens.push_back(z);}
    int extras=0;if(cin>>extras)for(int i=0;i<extras;++i){I x;cin>>x;b.primaries.push_back(x);}
    if(n==0){cout<<"0\n";return 0;}
    b.model();if(stoi(argv[1])<0)b.dump();else b.solve(stoi(argv[1]));
}
