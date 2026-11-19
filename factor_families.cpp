// Fit a sparse collection of reusable divisors to neighboring target integers.
// Shared primes need not form a square or a complete multiplication table.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <map>
#include <numeric>
#include <set>
#include <unordered_map>
#include <unordered_set>
#include <vector>
using namespace std;
using I=int64_t;using U=uint64_t;
struct Fit{I a=0,b=0,k=0,r=0,d=0,e=0;double score=0;};
struct Pattern{I c;U mask;vector<Fit> fits;double cost;};
struct Learner{
    vector<I> ts,seeds;I cap;vector<int> primes;
    int radius=96;
    unordered_map<I,U> support;
    unordered_map<I,pair<I,I>> split;
    unordered_map<I,double> cached;
    unordered_set<I> initial;
    void divisor(I x,I y,int row){
        I val=x*y;if(val<384||val>cap/2)return;
        support[val]|=U(1)<<row;
        if(x>y)swap(x,y);
        auto old=split.find(val);
        if(old==split.end()||x>old->second.first)split[val]={x,y};
    }
    void sieve(int row){
        I t=ts[row],lo=max(I(2),t-radius),hi=min(cap,t+radius);
        if(lo>hi)return;
        int size=int(hi-lo+1);vector<I> rem(size);vector<vector<I>> atoms(size);
        for(int i=0;i<size;++i)rem[i]=lo+i;
        for(int p:primes){
            for(int j=int((p-lo%p)%p);j<size;j+=p)while(rem[j]%p==0){
                rem[j]/=p;atoms[j].push_back(p);
            }
        }
        for(int i=0;i<size;++i){
            auto& factors=atoms[i];
            if(rem[i]>1)factors.push_back(rem[i]);
            I n=lo+i;
            vector<I> divisors{1};
            for(size_t j=0;j<factors.size();){
                I q=factors[j],mul=1;int e=0;
                do{++e;++j;}while(j<factors.size()&&factors[j]==q);
                int old=divisors.size();
                for(int k=1;k<=e;++k){
                    mul*=q;
                    for(int u=0;u<old;++u)divisors.push_back(divisors[u]*mul);
                }
            }
            for(I v:divisors){
                if(v<384||v>=n||v>1000000000000LL)continue;
                // Group exact common divisors from independent noisy members.
                support[v]|=U(1)<<row;
            }
            // A balanced pair of small factors yields cheap latent bases and
            // naturally shares e.g. p*q with another center containing p*r.
            for(size_t a=0;a<factors.size();++a){
                I x=factors[a];if(x<11||x>1000000)continue;
                for(size_t b=a+1;b<factors.size();++b){
                    I y=factors[b];if(y<11||y>1000000)continue;
                    divisor(x,y,row);
                }
            }
        }
    }
    double complexity(I v){
        if(v<=1)return 0;
        if(initial.count(v))return .2;
        auto before=cached.find(v);if(before!=cached.end())return before->second;
        I z=v;double estimate=0;
        for(int p:primes){
            if(p>127||z==1)break;
            int e=0;while(z%p==0){z/=p;++e;}
            if(e)estimate+=.55+.52*log2(1.+e)+.1*log2(double(p));
        }
        if(z>1)estimate+=.5+.13*log2(double(z));
        return cached[v]=min(estimate,.45+.16*log2(double(v)));
    }
    Fit fit(I t,I c){
        I k=t/c+(t%c>=(c+1)/2);
        if(!k||k>1000000000000LL)return {};
        I r=t-k*c;
        I d=(r<0?-1:1)*(I(abs(r)/k)+(abs(r)%k>=(k+1)/2)),e=r-d*k;
        if(abs(r)>3072&&(abs(d)>2048||abs(e)>1024))return {};
        double mass=min(2.*abs(r)+1.,(2.*abs(d)+1.)*(2.*abs(e)+1.));
        double info=log2(double(c)/mass);
        if(info<5.5)return {};
        double adjust=r==0?0:min(1.+complexity(abs(r)),
           (d?1.+complexity(abs(d)):0)+(e?1.+complexity(abs(e)):0));
        double price=(k>1?1.+complexity(k):0)+adjust;
        double gain=1.0+.195*log2(double(t))-price;
        if(gain<=0)return {};
        double score=gain+.20*min(info,18.);
        auto [a,b]=split.count(c)?split[c]:make_pair(I(1),c);
        return {a,b,k,r,d,e,score};
    }
    void run(){
        for(int p=2;p<=4093;++p){
            bool yes=true;for(int q:primes){if(q*q>p)break;if(p%q==0){yes=false;break;}}
            if(yes)primes.push_back(p);
        }
        for(I a:seeds)for(I b:seeds){
            initial.insert(a);initial.insert(a+b);initial.insert(abs(a-b));initial.insert(a*b);
            if(a%b==0)initial.insert(a/b);
        }
        for(size_t i=0;i<ts.size();++i)sieve(i);
        vector<Pattern> patterns;
        for(auto [v,mask]:support){
            if(__builtin_popcountll(mask)<2)continue;
            vector<Fit> hits;int n=0;double largest=0;
            for(I t:ts){auto h=fit(t,v);n+=h.score>0;largest=max(largest,h.score);hits.push_back(h);}
            if(n<2 || largest<3)continue;
            auto [a,b]=split.count(v)?split[v]:make_pair(I(1),v);
            double cost=min(complexity(v)+3,complexity(a)+complexity(b)+3.5);
            patterns.push_back({v,mask,move(hits),cost});
        }
        vector<Fit> selected(ts.size());
        set<I> hubs;double total=0;
        for(int iteration=0;iteration<12;++iteration){
            int best=-1;double largest=2.;
            for(int i=0;i<(int)patterns.size();++i){
                auto&p=patterns[i];double gain=-p.cost;int improved=0;
                for(size_t j=0;j<ts.size();++j){
                    if(p.fits[j].score>selected[j].score){
                        gain+=p.fits[j].score-selected[j].score;++improved;
                    }
                }
                if(improved>=2 && gain>largest){largest=gain;best=i;}
            }
            if(best<0)break;
            total+=largest;auto& p=patterns[best];
            for(size_t j=0;j<ts.size();++j)if(p.fits[j].score>selected[j].score)selected[j]=p.fits[j];
        }
        int count=0;
        for(auto z:selected)if(z.score>0){++count;hubs.insert(z.a);hubs.insert(z.b);}
        if(count<4){cout<<"0 0 0\n";return;}
        cout<<hubs.size()<<' '<<count<<' '<<total<<'\n';for(I x:hubs)cout<<x<<' ';cout<<'\n';
        for(size_t i=0;i<ts.size();++i){auto z=selected[i];if(z.score>0)cout<<ts[i]<<' '<<z.a<<' '<<z.b<<' '<<z.k<<' '<<z.r<<' '<<z.d<<' '<<z.e<<' '<<z.score<<'\n';}
    }
};
int main(int argc,char** argv){
    ios::sync_with_stdio(false);cin.tie(nullptr);
    string id;I cap;int n;
    while(cin>>id>>cap>>n){
        Learner l;l.cap=cap;l.radius=argc>1?stoi(argv[1]):96;
        l.ts.resize(n);for(I&v:l.ts)cin>>v;
        l.seeds={1,2,3,4,5,7,8,9,11,13,16,17,19,23,25,29,31};
        cout<<id<<' ';l.run();
    }
}
