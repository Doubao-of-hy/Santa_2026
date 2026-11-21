// Reconstruct a target from already funded values and one-operation expressions.
// The streaming request and witness format is shared with smooth_search.py.
// Arguments: search breadth, mode, secondary breadth, optional number of witnesses.
// Mode 1 uses puzzle values as moduli in c*d +/- (a +/- b).
// Mode 2 factors shifted targets. Mode 3 solves a*q +/- b*r with two funded scales.
// Mode 4 tests nearby products. Mode 5 tests three signed terms near a target.
// A prime >=11 selects arbitrary modular buckets for two compound expressions.
#include <algorithm>
#include <cstdint>
#include <iostream>
#include <map>
#include <numeric>
#include <random>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include "../../generative/atakan_v15/santa_factor64.h"
using namespace std;
using I=int64_t;
struct Step{I v,a,b;char op;};
struct Part{int a,b;char op;int cost;};
struct Atom{I v;Step step;int residue;};
struct Search{
    I cap,t;int budget,m,freeN;
    const vector<int>& inv;
    vector<Atom> atoms;
    unordered_map<I,int> ids;
    vector<int> start,slots;
    vector<Step> best;
    int keep=0;
    map<pair<int,uint64_t>,vector<Step>> alternatives;
    mt19937_64 rng;
    Search(I cap,I t,int cost,int mod,const vector<I>& constants,const vector<int>& inv):
        cap(cap),t(t),budget(cost),m(mod),inv(inv),rng(uint64_t(t)^uint64_t(mod)*57863){
        for(I x:constants) if(ids.emplace(x,int(atoms.size())).second)atoms.push_back({x,{},int(x%m)});
        freeN=int(atoms.size());
        ids.reserve(size_t(freeN)*freeN*2);
        auto add=[&](I x,char op,I a,I b){
            if(x<=0||x>cap||ids.count(x))return;
            ids[x]=int(atoms.size());atoms.push_back({x,{x,a,b,op},int(x%m)});
        };
        for(int i=0;i<freeN;++i)for(int j=0;j<=i;++j){
            I a=atoms[i].v,b=atoms[j].v;if(a<b)swap(a,b);
            if(a<=cap-b)add(a+b,'+',a,b);
            if(a>b)add(a-b,'-',a,b);
            if(a<=cap/b)add(a*b,'*',a,b);
            if(a%b==0)add(a/b,'/',a,b);
        }
        start.assign(m+1,0);for(auto a:atoms)++start[1+a.residue];
        for(int j=1;j<=m;j++)start[j]+=start[j-1];
        auto current=start;slots.resize(atoms.size());
        for(int i=0;i<int(atoms.size());i++)slots[current[atoms[i].residue]++]=i;
    }
    int mod(int x)const{return x>=m?x-m:(x<0?x+m:x);}
    template<class F> bool bucket(int r,F process)const {
        for(int j=start[r];j<start[r+1];j++)if(process(slots[j]))return true;
        return false;
    }
    Part single(int i)const{return {i,-1,' ',i>=freeN};}
    template<class F> bool walk(int r,bool cheap,F emit)const{
        if(bucket(r,[&](int i){return emit(atoms[i].v,single(i));}))return true;
        int stop=cheap?freeN:int(atoms.size());
        for(int i=0;i<stop;i++){
            I x=atoms[i].v;int s=atoms[i].residue;
            auto add=[&](int j,I value,char op,bool swapOrder=false){
                int a=i,b=j;if(swapOrder)swap(a,b);
                int c=1+int(i>=freeN)+int(j>=freeN&&i!=j);
                return emit(value,Part{a,b,op,c});
            };
            if(bucket(mod(r-s),[&](int j){
                I y=atoms[j].v;
                return j>=i && x<=cap-y && add(j,x+y,'+');
            }))return true;
            if(bucket(mod(s-r),[&](int j){
                I y=atoms[j].v;
                return x>y&&add(j,x-y,'-');
            }))return true;
            if(cheap&&bucket(mod(s+r),[&](int j){
                I y=atoms[j].v;
                return j>=freeN && y>x && add(j,y-x,'-',true);
            }))return true;
            if(s && bucket(int(int64_t(r)*inv[s]%m),[&](int j){
                I y=atoms[j].v;
                return j>=i && x<=cap/y && x>1 && y>1 && add(j,x*y,'*');
            }))return true;
            if(!s && !r && x>1)for(int j=i;j<int(atoms.size());++j){
                I y=atoms[j].v;
                if(y>1 && x<=cap/y && add(j,x*y,'*'))return true;
            }
            // For division, x is the denominator. Non-unit quotients only.
            if(bucket(int(int64_t(r)*s%m),[&](int j){
                I y=atoms[j].v;
                return x>1 && y>x && y%x==0 && add(j,y/x,'/',true);
            }))return true;
        }
        return false;
    }
    using Graph=unordered_map<I,Step>;
    void put_part(Graph& dag,I v,Part p)const{
        auto give=[&](int i){if(i>=freeN){auto e=atoms[i].step;dag.emplace(e.v,e);}};
        auto direct=ids.find(v);
        if(direct!=ids.end()){give(direct->second);return;}
        give(p.a);if(p.b>=0)give(p.b);
        if(p.b>=0)dag.emplace(v,Step{v,atoms[p.a].v,atoms[p.b].v,p.op});
    }
    void finish(const Graph& dag){
        vector<Step> graph;unordered_set<I> paid;
        auto visit=[&](auto&& self,I v)->void{
            if(!paid.insert(v).second)return;
            auto it=dag.find(v);if(it==dag.end())return;
            Step e=it->second;self(self,e.a);self(self,e.b);graph.push_back(e);
        };
        visit(visit,t);
        if(keep){
            if(graph.empty()||int(graph.size())>=budget)return;
            uint64_t hash=0;
            for(auto e:graph){
                uint64_t a=e.a,b=e.b;
                if((e.op=='+'||e.op=='*')&&a>b)swap(a,b);
                uint64_t key=uint64_t(e.v)*11400714819323198485ULL
                    ^a*7689490771071ULL^b*9531784911989ULL^uint64_t(e.op);
                key^=key>>30;key*=0xbf58476d1ce4e5b9ULL;key^=key>>27;
                hash^=key;
            }
            pair<int,uint64_t> key={int(graph.size()),hash};
            if(int(alternatives.size())<keep || key<alternatives.rbegin()->first){
                alternatives.emplace(key,move(graph));
                if(int(alternatives.size())>keep)alternatives.erase(prev(alternatives.end()));
            }
            return;
        }
        if(!graph.empty()&&int(graph.size())<budget){budget=int(graph.size());best=move(graph);}
    }
    void propose(I lv,Part left,I rv,Part right,char op){
        Graph dag;
        put_part(dag,lv,left);put_part(dag,rv,right);
        dag.emplace(t,Step{t,lv,rv,op});finish(dag);
    }
    Part two_terms(I q)const{
        Part result={-1,-1,' ',10};
        for(int i=0;i<int(atoms.size());i++){
            I x=atoms[i].v;
            auto find=[&](I y,char op,bool reverse){
                auto it=ids.find(y);if(it==ids.end())return;
                int j=it->second,c=1+(i>=freeN)+(j>=freeN&&i!=j);
                if(c<result.cost)result={reverse?j:i,reverse?i:j,op,c};
            };
            if(x<q)find(q-x,'+',false);
            if(x>q)find(x-q,'-',false);
            if(q<=cap-x)find(q+x,'-',true);
            if(x>1 && q%x==0)find(q/x,'*',false);
            if(q<=cap/x)find(q*x,'/',true);
            if(x>q && x%q==0)find(x/q,'/',false);
            if((i+1==freeN && result.cost<=2) || result.cost==1)break;
        }
        return result;
    }
    void offset_factors(int rounds,int quotientLimit){
        struct Option{I p,q;int factor,offset,op,rank;};
        vector<Option> pending;
        vector<int> offsets;
        for(int i=0;i<int(atoms.size());i++)offsets.push_back(i);
        // Free offsets always come first, then low-magnitude derived offsets.
        if(int(offsets.size())>freeN)stable_sort(offsets.begin()+freeN,offsets.end(),
            [&](int a,int b){return atoms[a].v<atoms[b].v;});
        if(int(offsets.size())>rounds)offsets.resize(rounds);
        for(int offset:offsets){
            I r=atoms[offset].v;
            auto scan=[&](I p,int op){
                if(p<4||p>cap||ids.count(p))return;
                auto divs=small_factor::divisors(p,600);
                for(I f:divs){
                    if(f==1||f==p)continue;
                    auto fi=ids.find(f);if(fi==ids.end())continue;
                    I q=p/f;auto qi=ids.find(q);
                    if(qi!=ids.end()){
                        if(f>q)continue;
                        Part product={fi->second,qi->second,'*',1+(fi->second>=freeN)+(qi->second>=freeN&&f!=q)};
                        if(op==2)propose(r,single(offset),p,product,'-');
                        else propose(p,product,r,single(offset),op==0?'+':'-');
                    }else if(quotientLimit && offset<freeN){
                        int bits=64-__builtin_clzll(q);
                        int cost=2+(fi->second>=freeN)+(offset>=freeN);
                        if(cost+1>=budget)continue;
                        // A pair of one-step values has a better chance of
                        // producing the smaller quotient, especially via sums.
                        int rank=bits+6*(fi->second>=freeN)+2*(q>t);
                        pending.push_back({p,q,fi->second,offset,op,rank});
                    }
                }
            };
            if(t>r)scan(t-r,0);
            if(t<=cap-r)scan(t+r,1);
            if(r>t)scan(r-t,2);
            if(budget<=3)return;
        }
        stable_sort(pending.begin(),pending.end(),[](auto& a,auto& b){return a.rank<b.rank;});
        unordered_map<I,Part> cache;
        for(auto x:pending){
            auto it=cache.find(x.q);
            if(it==cache.end()){
                if(int(cache.size())>=quotientLimit)continue;
                it=cache.emplace(x.q,two_terms(x.q)).first;
            }
            if(it->second.a<0)continue;
            I r=atoms[x.offset].v,f=atoms[x.factor].v;
            Graph dag;
            put_part(dag,x.q,it->second);put_part(dag,f,single(x.factor));put_part(dag,r,single(x.offset));
            dag.emplace(x.p,Step{x.p,f,x.q,'*'});
            if(x.op==2)dag.emplace(t,Step{t,r,x.p,'-'});
            else dag.emplace(t,Step{t,x.p,r,x.op==0?'+':'-'});
            finish(dag);
            if(budget<=3)return;
        }
    }
    static I coprime_inverse(I a,I m){
        I x=1,y=0,n=m;
        while(n){
            I q=a/n;
            I next=a%n;a=n;n=next;
            I v=x-q*y;x=y;y=v;
        }
        return x<0?x+m:x;
    }
    // With two selected scales, a and b, the admissible coefficients satisfy
    // an exact congruence. Coefficients need only one operation from a paid
    // value. This also covers composite scales with non-coprime gcd(a,b).
    void diophantine(int rounds,int sample){
        struct Query{int a,b;I residue;};
        map<I,vector<Query>> groups;
        vector<int> scales;
        for(int i=0;i<freeN;i++)if(atoms[i].v>1 && atoms[i].v<=cap/2)scales.push_back(i);
        if(int(scales.size())>rounds)scales.resize(rounds);
        for(int i:scales){
            I a=atoms[i].v;
            if(t%a || t/a<=1)continue;
            I q=t/a;auto found=ids.find(q);
            Part p=found==ids.end()?two_terms(q):single(found->second);
            if(p.a>=0)propose(q,p,a,single(i),'*');
        }
        if(budget<=3)return;
        int n=int(atoms.size());
        vector<int> sorted(n);iota(sorted.begin(),sorted.end(),0);
        sort(sorted.begin(),sorted.end(),[&](int i,int j){return atoms[i].v<atoms[j].v;});
        auto trial=[&](int i,int j,int k){
            I a=atoms[i].v,b=atoms[j].v,q=atoms[k].v;
            if(q>cap/a)return;
            I p=a*q;
            auto partner=[&](I s,char op,bool reverse){
                if(s<=0||s>cap||s%b)return;
                auto it=ids.find(s/b);if(it==ids.end())return;
                int l=it->second;
                Part left={i,k,'*',1+(k>=freeN)},right={j,l,'*',1+(l>=freeN)};
                if(reverse)propose(s,right,p,left,op);else propose(p,left,s,right,op);
            };
            if(t>p)partner(t-p,'+',false);
            if(p>t)partner(p-t,'-',false);
            if(t<=cap-p)partner(t+p,'-',true);
        };
        for(size_t z=0;z<scales.size();z++)for(size_t w=z+1;w<scales.size();w++){
            int i=scales[z],j=scales[w];
            // A large a keeps the integer range available for q small.
            if(atoms[i].v<atoms[j].v)swap(i,j);
            I a=atoms[i].v,b=atoms[j].v,g=gcd(a,b);
            if(t%g)continue;
            I m=b/g,bound=cap/a;
            I residue=m==1?0:I(small_factor::mul((t/g)%m,coprime_inverse((a/g)%m,m),m));
            auto add=[&](I r){
                if(r>bound)return;
                if((bound-r)/m<=192){
                    for(I q=r?r:m;q<=bound;q+=m){
                        auto hit=ids.find(q);if(hit!=ids.end())trial(i,j,hit->second);
                    }
                }else groups[m].push_back({i,j,r});
            };
            add(residue);
            if(residue && residue!=m-residue)add(m-residue);
            if(budget<=3)return;
        }
        for(auto& [m,requests]:groups){
            // Index only residues actually requested by a pair of scales.
            unordered_map<I,vector<int>> buckets;
            for(auto u:requests)buckets.try_emplace(u.residue);
            for(int k:sorted){
                auto it=buckets.find(atoms[k].v%m);
                if(it!=buckets.end())it->second.push_back(k);
            }
            for(auto u:requests){
                I bound=cap/atoms[u.a].v;
                const auto& candidates=buckets.find(u.residue)->second;
                int end=int(upper_bound(candidates.begin(),candidates.end(),bound,
                    [&](I v,int k){return v<atoms[k].v;})-candidates.begin());
                if(end<=2*sample){for(int k=0;k<end;k++)trial(u.a,u.b,candidates[k]);}
                else{
                    for(int k=0;k<sample;k++)trial(u.a,u.b,candidates[k]);
                    for(int k=0;k<sample;k++)
                        trial(u.a,u.b,candidates[sample+int(uint64_t(k)*(end-sample)/sample)]);
                }
                if(budget<=3)return;
            }
        }
    }
    void near_products(int rounds,int neighbors){
        int n=int(atoms.size());
        vector<int> sorted(n);iota(sorted.begin(),sorted.end(),0);
        sort(sorted.begin(),sorted.end(),[&](int i,int j){return atoms[i].v<atoms[j].v;});
        unordered_map<I,Part> products;
        products.reserve(2*n);
        for(int pos=0;pos<n;pos++){
            int i=sorted[pos];I a=atoms[i].v;
            if(a<2)continue;
            if(a>cap/a)break;
            auto center=lower_bound(sorted.begin()+pos,sorted.end(),t/a,
                [&](int k,I v){return atoms[k].v<v;});
            int start=max(pos,int(center-sorted.begin())-neighbors);
            int stop=min(n,int(center-sorted.begin())+neighbors+1);
            for(int jpos=start;jpos<stop;jpos++){
                int j=sorted[jpos];I b=atoms[j].v;
                if(b>cap/a)break;
                I p=a*b;
                if(p==t)continue;
                Part f={i,j,'*',1+(i>=freeN)+(j>=freeN&&i!=j)};
                if(auto one=ids.find(p);one!=ids.end())f=single(one->second);
                auto [it,fresh]=products.emplace(p,f);
                if(!fresh && f.cost<it->second.cost)it->second=f;
            }
        }
        vector<vector<I>> ranked(4);
        for(auto [p,f]:products)ranked[f.cost].push_back(p);
        auto distance=[&](I p){return p>t?p-t:t-p;};
        auto closer=[&](I a,I b){return distance(a)<distance(b);};
        for(auto& zone:ranked){
            if(int(zone.size())>rounds){
                nth_element(zone.begin(),zone.begin()+rounds,zone.end(),closer);zone.resize(rounds);
            }
            sort(zone.begin(),zone.end(),closer);
            for(I p:zone){
                I r=distance(p);Part prod=products.find(p)->second;
                auto offer=[&](Part remainder){propose(p,prod,r,remainder,p<t?'+':'-');};
                auto direct=ids.find(r);
                if(direct!=ids.end()){offer(single(direct->second));continue;}
                if(prod.cost+2>=budget)continue;
                for(I a:small_factor::divisors(r,300)){
                    I b=r/a;if(a<2 || a>b)continue;
                    auto ai=ids.find(a),bi=ids.find(b);
                    if(ai!=ids.end()&&bi!=ids.end())
                        offer({ai->second,bi->second,'*',1+(ai->second>=freeN)+(bi->second>=freeN&&a!=b)});
                }
                auto try_atom=[&](int i){
                    I x=atoms[i].v;
                    auto partner=[&](I y,char op,bool reverse){
                        auto hit=ids.find(y);if(hit==ids.end())return;
                        int j=hit->second;
                        offer({reverse?j:i,reverse?i:j,op,1+(i>=freeN)+(j>=freeN&&i!=j)});
                    };
                    if(x<r)partner(r-x,'+',false);
                    if(x>r)partner(x-r,'-',false);
                    if(r<=cap-x)partner(x+r,'-',true);
                    if(r<=cap/x)partner(r*x,'/',true);
                };
                for(int i=0;i<freeN;i++)try_atom(i);
                int upto=min(n,120+20*neighbors);
                for(int j=0;j<upto;j++)if(sorted[j]>=freeN)try_atom(sorted[j]);
                if(budget<=3)return;
            }
        }
    }
    void near_sums(int full,int neighbors){
        int n=int(atoms.size());
        vector<pair<I,int>> sorted;sorted.reserve(n);
        for(int i=0;i<n;i++)sorted.emplace_back(atoms[i].v,i);
        sort(sorted.begin(),sorted.end());
        for(int i=0;i<n;i++){
            I a=atoms[i].v;
            auto split=[&](I u,char outer,bool reverse){
                if(u<=0||u>cap||ids.count(u))return;
                auto offer=[&](Part p){
                    if(reverse)propose(u,p,a,single(i),outer);
                    else propose(a,single(i),u,p,outer);
                };
                if(i<full){
                    Part p=two_terms(u);
                    if(p.a>=0)offer(p);
                    return;
                }
                auto inspect=[&](int k){
                    I b=atoms[k].v;
                    auto check=[&](I c,char op,bool invert){
                        auto hit=ids.find(c);if(hit==ids.end())return;
                        int j=hit->second;
                        offer({invert?j:k,invert?k:j,op,1+(j>=freeN)+(k>=freeN&&k!=j)});
                    };
                    if(b<u)check(u-b,'+',false);
                    if(b>u)check(b-u,'-',false);
                    if(u<=cap-b)check(u+b,'-',true);
                };
                for(I center:{u,(u+1)/2}){
                    int ix=int(lower_bound(sorted.begin(),sorted.end(),make_pair(center,-1))-sorted.begin());
                    for(int j=max(0,ix-neighbors);j<min(n,ix+neighbors+1);j++)inspect(sorted[j].second);
                }
            };
            if(a<t)split(t-a,'+',false);
            if(a>t)split(a-t,'-',false);
            if(a<=cap-t)split(a+t,'-',true);
            if(budget<=3)return;
        }
    }
    // For a selected scale c, scan pairs of atoms whose sum or difference has
    // residue +/- target modulo c. The remaining term must equal c*d exactly.
    // Using a scale from the actual puzzle also works for composite moduli.
    void cofactors(int rounds,int bucketLimit){
        if(budget<=3)return;
        int n=int(atoms.size()),size=1;
        while(size<2*n)size*=2;
        vector<I> keys(size,-1);
        vector<int> heads(size,-1),links(n);
        vector<I> residues(n);
        auto slot=[&](I key){
            uint64_t h=uint64_t(key);
            h=(h^(h>>30))*0xbf58476d1ce4e5b9ULL;
            h=(h^(h>>27))*0x94d049bb133111ebULL;
            int j=int((h^(h>>31))&(size-1));
            while(keys[j]!=-1 && keys[j]!=key)j=(j+1)&(size-1);
            return j;
        };
        vector<int> scales;
        for(int i=0;i<n;++i){
            I v=atoms[i].v;
            if(v<64 || v>cap/4)continue;
            if(i>=freeN && __builtin_popcountll(v)>3 && __builtin_ctzll(v)<12)continue;
            scales.push_back(i);
        }
        auto rank=[&](int i){
            I v=atoms[i].v;
            int bits=64-__builtin_clzll(v);
            return 45*(i<freeN)+min(9,__builtin_ctzll(v))+
                3*(bits>=12&&bits<=52)-abs(bits-26)/3;
        };
        stable_sort(scales.begin(),scales.end(),[&](int i,int j){return rank(i)>rank(j);});
        if(int(scales.size())>rounds)scales.resize(rounds);
        for(int scale:scales){
            I c=atoms[scale].v, tr=t%c;
            fill(keys.begin(),keys.end(),-1);
            for(int i=n-1;i>=0;--i){
                I r=atoms[i].v%c;residues[i]=r;
                int h=slot(r);
                links[i]=keys[h]<0?-1:heads[h];heads[h]=i;keys[h]=r;
            }
            auto addmod=[&](I a,I b){return a>=c-b?a-(c-b):a+b;};
            auto submod=[&](I a,I b){return a<b?a+(c-b):a-b;};
            for(int i=0;i<n;++i){
                I a=atoms[i].v,s=residues[i];
                auto inspect=[&](I targetResidue,bool sum){
                    I wanted=sum?submod(targetResidue,s):submod(s,targetResidue);
                    int h=slot(wanted);
                    if(keys[h]<0)return;
                    int count=0;
                    for(int j=heads[h];j>=0 && count++<bucketLimit;j=links[j]){
                        I b=atoms[j].v;
                        if(sum?(i>j || a>cap-b):(a<=b))continue;
                        I rem=sum?a+b:a-b;
                        if(!rem)continue;
                        Part ab={i,j,sum?'+':'-',1+(i>=freeN)+(j>=freeN&&i!=j)};
                        auto attach=[&](I prod,char op,bool reverse){
                            if(prod<=0||prod>cap||prod%c)return;
                            auto d=ids.find(prod/c);if(d==ids.end())return;
                            int k=d->second;
                            Part mul={scale,k,'*',1+(scale>=freeN)+(k>=freeN&&k!=scale)};
                            if(reverse)propose(rem,ab,prod,mul,op);
                            else propose(prod,mul,rem,ab,op);
                        };
                        if(t>rem)attach(t-rem,'+',false);
                        if(rem>t)attach(rem-t,'-',true);
                        if(t<=cap-rem)attach(t+rem,'-',false);
                    }
                };
                inspect(tr,true);inspect(tr,false);
                if(tr && tr!=c-tr){inspect(c-tr,true);inspect(c-tr,false);}
                if(budget<=3)return;
            }
        }
    }
    void run(int rounds,int salt){
        auto self=ids.find(t);
        if(self!=ids.end()){
            if(self->second>=freeN)best={atoms[self->second].step};
            return;
        }
        for(int i=0;i<int(atoms.size());i++){
            I v=atoms[i].v;
            auto direct=[&](I w,char op,bool reverse){
                auto it=ids.find(w);if(it==ids.end())return;
                if(reverse)propose(w,single(it->second),v,single(i),op);
                else propose(v,single(i),w,single(it->second),op);
            };
            if(t>v)direct(t-v,'+',false);
            if(t+v<=cap)direct(t+v,'-',true);
            if(v>t)direct(v-t,'-',false);
            if(t%v==0)direct(t/v,'*',false);
        }
        if(budget<=3 || rounds==0)return;
        if(m==1){cofactors(rounds,salt);return;}
        if(m==2){offset_factors(rounds,salt);return;}
        if(m==3){diophantine(rounds,salt);return;}
        if(m==4){near_products(rounds,salt);return;}
        if(m==5){near_sums(rounds,salt);return;}
        unordered_map<I,Part> table;
        table.reserve(min<size_t>(600000,size_t(4.)*atoms.size()*atoms.size()/m+10000));
        int tr=int(t%m);vector<int> rs;unordered_set<int> used;
        auto queue=[&](int x){if(used.insert(x).second)rs.push_back(x);};
        queue(tr);queue(0);queue(tr/2);rng.seed(uint64_t(t)*681067+salt);
        for(int j=0;int(rs.size())<rounds;j++){
            if(j%4==0)queue(atoms[rng()%freeN].residue);
            else if(j%4==1)queue(mod(tr-atoms[rng()%freeN].residue));
            else queue(int(rng()%m));
        }
        for(int r:rs){
            table.clear();
            walk(r,false,[&](I value,Part p){
                if(p.cost+1>=budget)return false;
                auto [it,added]=table.emplace(value,p);
                if(!added&&it->second.cost>p.cost)it->second=p;
                return false;
            });
            auto check=[&](int residue,int kind){
                walk(residue,budget<=7,[&](I v,Part p){
                    I w=kind==0?t-v:(kind==1?t+v:v-t);
                    if(w<1||w>cap)return false;
                    auto it=table.find(w);
                    if(it!=table.end()){
                        if(kind==2)propose(v,p,w,it->second,'-');
                        else propose(w,it->second,v,p,kind==0?'+':'-');
                    }
                    return budget<=3;
                });
            };
            check(mod(tr-r),0);if(budget<=3)return;
            check(mod(r-tr),1);if(budget<=3)return;
            check(mod(tr+r),2);if(budget<=3)return;
        }
    }
};
int main(int argc,char**argv){
    if(argc!=4 && argc!=5)return 2;
    ios::sync_with_stdio(false);cin.tie(nullptr);
    int rounds=stoi(argv[1]),mod=stoi(argv[2]),salt=stoi(argv[3]);
    if((mod<1||mod>5) && (mod<11||mod>1000003||rounds>mod))return 2;
    if(rounds<0 || (mod<=5 && salt<1))return 2;
    if(mod>5)for(int d=2;int64_t(d)*d<=mod;d++)if(mod%d==0)return 2;
    vector<int> inv(max(2,mod));inv[1]=1;
    for(int v=2;v<mod;v++)inv[v]=mod-int(int64_t(mod/v)*inv[mod%v]%mod);
    I cap,t;int budget,k;
    while(cin>>cap>>t>>budget>>k){
        vector<I> inputs(k);for(auto&v:inputs)cin>>v;
        Search s(cap,t,budget,mod,inputs,inv);
        if(argc==5)s.keep=stoi(argv[4]);
        s.run(rounds,salt);
        cout<<t<<' '<<(s.alternatives.size()+!s.best.empty())<<'\n';
        auto report=[&](const vector<Step>& g){
            cout<<g.size()<<'\n';
            for(auto e:g)cout<<e.v<<' '<<e.op<<' '<<e.a<<' '<<e.b<<'\n';
        };
        if(!s.best.empty())report(s.best);
        for(auto& choice:s.alternatives)report(choice.second);
    }
}
