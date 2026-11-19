// Enumerate small independent shifts of two previously inferred factors.
#include <algorithm>
#include <cmath>
#include <iostream>
#include <map>
#include <set>
#include <tuple>
#include <vector>
using namespace std;
using I=long long;
struct Factor {I a,u,b,v,c;};
struct Match {double quality=-1e20, evidence=0; Factor f{}; I k=0,r=0,d=0,e=0;};
double bits(I n){return log2(1.+2*double(abs(n)));}
int main(){
    ios::sync_with_stdio(false);cin.tie(nullptr);
    I limit; int nh,nt,ns;
    while(cin>>limit>>nh>>nt>>ns){
        vector<I> hubs(nh),goals(nt),seeds(ns);
        for(auto &x:hubs)cin>>x;
        for(auto &x:goals)cin>>x;
        for(auto &x:seeds)cin>>x;
        set<I> delta{0};
        for(int z=1;z<=16;++z){delta.insert(-z);delta.insert(z);}
        for(I z:seeds)if(z<=128){delta.insert(-z);delta.insert(z);}
        for(I z:{24,32,48,64}){delta.insert(-z);delta.insert(z);}
        map<I,Factor> all;
        for(int i=0;i<nh;++i)for(int j=i;j<nh;++j)
            for(I u:delta)for(I v:delta){
                if(!u&&!v)continue;
                I a=hubs[i],b=hubs[j],x=a+u,y=b+v;
                if(x<16||y<16||x>limit/y)continue;
                I c=x*y;
                if(c<32768)continue;
                auto it=all.find(c);
                if(it==all.end()||bits(u)+bits(v)<bits(it->second.u)+bits(it->second.v))
                    all[c]={a,u,b,v,c};
            }
        vector<Factor> fs;for(auto &it:all)fs.push_back(it.second);
        const double trials=log2(1.+fs.size());
        for(I t:goals){
            Match best;
            for(auto [a,u,b,v,c]:fs){
                if(c>t+t/2)break;
                I k=t/c;k+=t%c>=(c+1)/2;
                if(k<1||k>100000000)continue;
                I r=t-k*c;
                I d=(abs(r)+k/2)/k;if(r<0)d=-d;I e=r-k*d;
                if(abs(r)>256&&(abs(d)>64||abs(e)>64))continue;
                double mass=min(bits(r),bits(d)+bits(e));
                double evidence=log2(double(c))-mass-trials;
                if(evidence<3.0)continue;
                double quality=evidence-.52*(bits(u)+bits(v))-.24*log2(1.+k)-.7*(u!=0&&v!=0);
                if(quality>best.quality)best={quality,evidence,{a,u,b,v,c},k,r,d,e};
            }
            auto f=best.f;
            cout<<t<<' '<<f.a<<' '<<f.u<<' '<<f.b<<' '<<f.v<<' '<<best.k<<' '
                <<best.r<<' '<<best.d<<' '<<best.e<<' '<<best.quality<<' '<<best.evidence<<'\n';
        }
    }
}
