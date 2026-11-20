#include <algorithm>
#include <cstdint>
#include <iostream>
#include <unordered_map>
#include <unordered_set>
#include <vector>
using namespace std;
using I=int64_t;
struct Edge {I v,a,b;char op;};
using Path=vector<Edge>;
template<class F> void forward(I a,I b,I cap,F f){
    if(a<b)swap(a,b);
    if(a<=cap-b)f(Edge{a+b,a,b,'+'});
    if(a>b)f(Edge{a-b,a,b,'-'});
    if(a<=cap/b)f(Edge{a*b,a,b,'*'});
    if(a%b==0)f(Edge{a/b,a,b,'/'});
}
template<class F> void inverse(I x,I t,I cap,F f){
    if(t>x)f(t-x,Edge{t,t-x,x,'+'});
    if(x>t)f(x-t,Edge{t,x,x-t,'-'});
    if(t<=cap-x)f(t+x,Edge{t,t+x,x,'-'});
    if(t%x==0)f(t/x,Edge{t,t/x,x,'*'});
    if(t<=cap/x)f(t*x,Edge{t,t*x,x,'/'});
    if(x%t==0)f(x/t,Edge{t,x,x/t,'/'});
}
struct Peel {I q,k,r;int rank;bool plus;};
struct Solver{
    I cap;vector<I> free,table,radix,digits;
    unordered_set<I> known;
    unordered_map<I,Edge> one;
    unordered_map<I,Path> cache;
    Solver(I maximum,const vector<I>& base):cap(maximum),free(base),known(base.begin(),base.end()){
        one.reserve(base.size()*base.size()*2+128);
        for(int i=0;i<base.size();++i)for(int j=0;j<=i;++j)
            forward(base[i],base[j],cap,[&](Edge e){if(!known.count(e.v))one.emplace(e.v,e);});
        table=base;for(auto kv:one)table.push_back(kv.first);sort(table.begin(),table.end());
        for(I x:base)if(x>=2&&x<=1000000000)radix.push_back(x);
        digits=base;
        for(I x:table)if(!known.count(x)&&x<=512)digits.push_back(x);
        sort(digits.begin(),digits.end());sort(radix.begin(),radix.end());
    }
    bool contains(const Path& p,I x)const{
        return known.count(x)||any_of(p.begin(),p.end(),[&](Edge e){return e.v==x;});
    }
    bool ready(I x)const{return known.count(x)||one.count(x);}
    void append(Path& p,I x)const{if(!contains(p,x))p.push_back(one.at(x));}
    void consider(Path& best,Path p)const{
        if(!p.empty()&&(best.empty()||p.size()<best.size()))best=move(p);
    }
    Path join(I n,bool whole){
        if(known.count(n))return {};
        if(one.count(n))return {one.at(n)};
        if(!whole&&cache.count(n))return cache.at(n);
        Path best;
        auto scan=[&](const vector<I>& options){
            for(I a:options){
                inverse(a,n,cap,[&](I b,Edge e){
                    if(b==n||a==n||!ready(b))return;
                    Path p;append(p,a);append(p,b);p.push_back(e);consider(best,move(p));
                });
                if(!best.empty())break;
            }
        };
        scan(free);
        if(best.empty()&&whole)scan(table);
        if(!whole)cache[n]=best;
        return best;
    }
    vector<Peel> peels(I t,int budget){
        vector<Peel> choices;
        for(I k:radix){
            if(k>t)break;
            for(I r:digits){
                I minus=t>r?t-r:0,plus=t<=cap-r?t+r:0;
                for(auto pair:{make_pair(minus,true),make_pair(plus,false)}){
                    I mid=pair.first;if(!mid||mid%k)continue;
                    I q=mid/k;if(q<=1||q>=t||mid==r||q==r)continue;
                    int rank=(known.count(q)?0:one.count(q)?140:280)+(known.count(r)?0:46)+64-__builtin_clzll(q)+(r>t/8?4:0);
                    choices.push_back({q,k,r,rank,pair.second});
                }
            }
        }
        sort(choices.begin(),choices.end(),[](auto a,auto b){
            if(a.rank!=b.rank)return a.rank<b.rank;
            if(a.q!=b.q)return a.q<b.q;
            if(a.r!=b.r)return a.r<b.r;
            return a.k<b.k;
        });
        unordered_set<I> seen;
        vector<Peel> distinct;
        for(auto x:choices)if(seen.insert(x.q).second){
            distinct.push_back(x);if(distinct.size()==budget)break;
        }
        return distinct;
    }
    void finish(Path& best,Path p,const Peel& m,I t){
        I mid=m.q*m.k;
        append(p,m.r);
        if(!contains(p,mid))p.push_back({mid,m.q,m.k,'*'});
        if(!contains(p,t))p.push_back({t,mid,m.r,m.plus?'+':'-'});
        consider(best,move(p));
    }
    Path solve(I t,int mode){
        Path best=join(t,true);
        if(!mode||(!best.empty()&&best.size()<=2))return best;
        auto opts=peels(t,96);
        for(auto m:opts){
            auto q=join(m.q,false);
            if(known.count(m.q)||!q.empty())finish(best,q,m,t);
        }
        if(!best.empty()&&best.size()<=3)return best;
        for(int i=0;i<min<int>(24,opts.size());++i){
            auto m=opts[i];auto q=join(m.q,true);
            if(known.count(m.q)||!q.empty())finish(best,q,m,t);
        }
        if(!best.empty()&&best.size()<=4)return best;
        for(int i=0;i<min<int>(16,opts.size());++i){
            auto m=opts[i];Path prefix;
            for(auto v:peels(m.q,48)){
                auto q=join(v.q,false);
                if(known.count(v.q)||!q.empty())finish(prefix,q,v,m.q);
            }
            if(!prefix.empty())finish(best,prefix,m,t);
        }
        return best;
    }
};
int main(){
    ios::sync_with_stdio(false);cin.tie(nullptr);
    I cap;int n,m,mode;
    while(cin>>cap>>n>>m>>mode){
        vector<I> a(n),goals(m);for(I& x:a)cin>>x;for(I& x:goals)cin>>x;
        Path path;unordered_set<I> known(a.begin(),a.end());bool ok=true;
        for(I t:goals){
            if(known.count(t))continue;
            Solver solver(cap,a);auto p=solver.solve(t,mode);
            if(p.empty()){ok=false;break;}
            for(auto x:p)if(known.insert(x.v).second){path.push_back(x);a.push_back(x.v);}
        }
        cout<<(ok?(int)path.size():-1)<<'\n';
        if(ok)for(auto e:path)cout<<e.v<<' '<<e.op<<' '<<e.a<<' '<<e.b<<'\n';
    }
}
