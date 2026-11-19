// Rank arithmetic identities linking four different targets through a common
// difference. A local, scale-matched null provides an independent comparison.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>
#include <random>
#include <set>
#include <string>
#include <tuple>
#include <vector>
using namespace std;
using I=int64_t;
struct Rule {I x,a,b,c,k,error; int divide;};
struct Fit {I absolute=numeric_limits<I>::max(); double priority; Rule rule;};

int main(int argc,char** argv){
    int keep=argc>1?stoi(argv[1]):7;
    bool probe=argc>2&&string(argv[2])=="probe";
    string id;I cap;int ns,nt;
    while(cin>>id>>cap>>ns>>nt){
        vector<I> seeds(ns),targets(nt);
        for(I& x:seeds)cin>>x;for(I& x:targets)cin>>x;
        sort(targets.begin(),targets.end());targets.erase(unique(targets.begin(),targets.end()),targets.end());
        nt=targets.size();
        vector<I> scale{1,2,3,4,5,6,7,8,9,10,11,12,13,16,20,24,25,32,48,64};
        for(I s:seeds)if(s<=128)scale.push_back(s);
        sort(scale.begin(),scale.end());scale.erase(unique(scale.begin(),scale.end()),scale.end());
        mt19937_64 rng(stoul(id.substr(id.find_last_of('_')+1))+700413);
        for(I original:targets){
            vector<I> queries{original};
            if(probe&&original>1000){
                for(int j=0;j<3;++j){
                    double shift=(.011+.073*generate_canonical<double,48>(rng))*(j%2?-1.:1.);
                    I x=llround(original*(1+shift));if(x>cap)x=llround(original*(1-abs(shift)));
                    queries.push_back(max<I>(1,x));
                }
            }
            // Preserve every label's anchor set when evaluating the null.
            for(size_t variant=0;variant<queries.size();++variant){
                I x=queries[variant],best_raw=numeric_limits<I>::max();
                I separation=max<I>(64,min<I>(8192,I(sqrt(double(x))*.07)));
                vector<Fit> best;
                auto offer=[&](I a,I b,I c,I k,bool divide,I predicted){
                    if(predicted<1||predicted>cap)return;
                    I residual=x-predicted,err=abs(residual);
                    best_raw=min(best_raw,err);
                    double cost=(k==1?1.:2.)+.18*log2(1.+double(err));
                    if(err==0)cost-=1.0;
                    if(k!=1 && find(seeds.begin(),seeds.end(),k)==seeds.end())cost+=.4;
                    if(best.size()==size_t(keep)&&cost>=best.back().priority)return;
                    auto eq=Rule{x,a,b,c,k,residual,int(divide)};
                    for(auto &f:best)if(f.rule.a==a&&f.rule.b==b&&f.rule.c==c&&f.rule.k==k&&f.rule.divide==divide)return;
                    best.push_back({err,cost,eq});
                    stable_sort(best.begin(),best.end(),[](auto& u,auto& v){return u.priority<v.priority;});
                    if(int(best.size())>keep)best.pop_back();
                };
                for(I a:targets)if(a!=original && abs(x-a)>separation){
                    I delta=abs(x-a);
                    for(size_t bi=0;bi<targets.size();++bi)for(size_t ci=0;ci<bi;++ci){
                        I b=targets[bi],c=targets[ci];
                        if(b==original||c==original||a==b||a==c || min({abs(x-b),abs(x-c),abs(a-b),abs(a-c),b-c})<=separation)continue;
                        I gap=b-c;
                        auto nearest=[&](I required,I available,bool divide){
                            I q=required/available;
                            auto it=lower_bound(scale.begin(),scale.end(),q);
                            for(int offset=-1;offset<=1;++offset){
                                int ix=int(it-scale.begin())+offset;if(ix<0||ix>=int(scale.size()))continue;
                                I k=scale[ix],part;
                                if(divide){
                                    if(k==1||gap%k)continue;
                                    part=gap/k;
                                }else{
                                    if(gap>cap/k)continue;
                                    part=gap*k;
                                }
                                if(x>a&&a>cap-part)continue;
                                I predicted=x>a?a+part:a-part;
                                // The sign can be reconstructed from x-error versus a.
                                offer(a,b,c,k,divide,predicted);
                            }
                        };
                        nearest(delta,gap,false);nearest(gap,delta,true);
                    }
                }
                if(probe){
                    cout<<id<<' '<<original<<' '<<variant<<' '<<best_raw<<' '<<separation<<'\n';
                }else if(!variant){
                    for(auto &f:best){
                        auto q=f.rule;
                        cout<<id<<' '<<q.x<<' '<<q.a<<' '<<q.b<<' '<<q.c<<' '<<q.k<<' '<<q.error<<' '<<q.divide<<'\n';
                    }
                }
            }
        }
    }
}
