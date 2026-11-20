#include <algorithm>
#include <cstdint>
#include <iostream>
#include <limits>
#include <map>
#include <set>
#include <tuple>
#include <vector>
using I = int64_t;
using Wide = __int128;
struct Guess { I x,y,z,w,c; int a,b; I fit; };
int main(){
    std::ios::sync_with_stdio(false);std::cin.tie(nullptr);
    int ns,nt,nh,radius; I cap; std::string id;
    while(std::cin>>id>>cap>>radius>>ns>>nt>>nh){
        std::vector<I> seeds(ns),train(nt),held(nh);
        for(auto&x:seeds)std::cin>>x;for(auto&x:train)std::cin>>x;for(auto&x:held)std::cin>>x;
        std::sort(train.begin(),train.end());std::sort(held.begin(),held.end());
        std::map<I,Guess> forecasts;std::set<I> first_order; long long chains=0;
        auto add_simple=[&](Wide v){ if(v>4096&&v<=cap)first_order.insert(static_cast<I>(v)); };
        std::vector<I> old=train;old.insert(old.end(),seeds.begin(),seeds.end());
        std::vector<I> errors{0,1,-1};for(I d:seeds){errors.push_back(d);errors.push_back(-d);}
        auto build_simple=[&](){for(I x:old)for(I y:old){
            add_simple(Wide(x)*y);if(x%y==0)add_simple(x/y);
            for(int a=-3;a<=3;++a)for(int b=-3;b<=3;++b){
                if(!a&&!b)continue;
                for(I e:errors)add_simple(Wide(a)*x+Wide(b)*y+e);
            }
        }};
        for(int a=-3;a<=3;a++)for(int b=-3;b<=3;b++){
            if(!a||!b)continue;
            for(I x:train)for(I y:train){
                if(x==y)continue;
                for(I z:train){
                    if(z==x||z==y)continue;
                    Wide c=Wide(z)-Wide(a)*y-Wide(b)*x;
                    Wide expected=Wide(a)*z+Wide(b)*y+c;
                    if(c< -Wide(cap)||c>cap||expected<4097-radius||expected>Wide(cap)+radius)continue;
                    I e=static_cast<I>(expected);
                    auto it=std::lower_bound(train.begin(),train.end(),e-radius);
                    for(;it!=train.end()&&*it<=e+radius;++it){
                        I w=*it;if(w==x||w==y||w==z)continue;++chains;
                        Guess g{x,y,z,w,static_cast<I>(c),a,b,std::abs(w-e)};
                        auto keep=[&](Wide v){
                            if(v<=4096||v>cap||std::binary_search(train.begin(),train.end(),static_cast<I>(v)))return;
                            auto k=static_cast<I>(v);auto pos=forecasts.find(k);
                            if(pos==forecasts.end() || std::tie(g.fit,g.a,g.b,g.x,g.y,g.z)<std::tie(pos->second.fit,pos->second.a,pos->second.b,pos->second.x,pos->second.y,pos->second.z))forecasts[k]=g;
                        };
                        keep(Wide(a)*w+Wide(b)*z+c);
                        Wide previous=Wide(y)-Wide(a)*x-c;
                        if(previous%b==0)keep(previous/b);
                    }
                }
            }
        }
        int exact=0,near=0,extra=0;std::vector<std::tuple<I,I,Guess>> rows;
        bool built=false;
        for(I t:held){
            auto lo=forecasts.lower_bound(t-radius);auto best=forecasts.end();
            for(;lo!=forecasts.end()&&lo->first<=t+radius;++lo){
                if(best==forecasts.end()||std::abs(lo->first-t)<std::abs(best->first-t))best=lo;
            }
            if(best==forecasts.end())continue;
            if(!built){build_simple();built=true;}
            exact+=(best->first==t);++near;
            auto s=first_order.lower_bound(t-radius);
            if(s==first_order.end()||*s>t+radius){++extra;rows.emplace_back(t,best->first,best->second);}
        }
        std::cout<<id<<' '<<chains<<' '<<forecasts.size()<<' '<<exact<<' '<<near<<' '<<extra<<'\n';
        for(auto [t,p,g]:rows)
            std::cout<<t<<' '<<p<<' '<<g.a<<' '<<g.b<<' '<<g.c<<' '<<g.x<<' '<<g.y<<' '<<g.z<<' '<<g.w<<' '<<g.fit<<'\n';
    }
}
