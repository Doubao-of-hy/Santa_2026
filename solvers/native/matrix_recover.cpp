// Recover a noisy unlabelled multiplication table from its diagonal entries
// or triangles. For xy, xz, yz, the ratio (xy)(xz)/(yz) equals x squared.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <map>
#include <set>
#include <tuple>
#include <vector>
using namespace std;
using I=int64_t;
struct Hit {double value=0;I a=0,b=0,k=0,r=0,d=0,e=0;};
struct Model {vector<I> hub;vector<Hit> hits;double score;int direct;};
struct Recover {
    vector<I> targets,observed;
    set<vector<I>> initial;
    I cap;
    bool wide=false;
    I noise(I x)const{return min(I(4096),max(wide?I(1024):I(6),x/50));}
    static I rounded(I a,I b){return a/b+(a%b>=(b+1)/2);}
    void add(vector<I> parts){
        sort(parts.begin(),parts.end());
        parts.erase(unique(parts.begin(),parts.end()),parts.end());
        if(parts.empty()||parts.front()<8 || parts.back()>parts.front()*60)return;
        initial.insert(move(parts));
    }
    double weight(I t,I a,I b,Hit *out=nullptr)const{
        if(a>cap/b)return 0;
        I center=a*b, k=rounded(t,center);
        if(k<1 || k>1000000000)return 0;
        I r=t-k*center;
        I d=(r<0?-1:1)*rounded(abs(r),k),e=r-k*d;
        I rad=noise(min(a,b));
        double direct=double(abs(r))/rad;
        // Corrections may be applied before and after the final multiplication.
        // Large integer k then amplifies the inner, still-small correction.
        double split=max(double(abs(d))/rad,double(abs(e))/rad);
        double fit=min(direct,split);
        if(fit>1.25)return 0;
        double uncertainty=min(double(rad)*(1+k),double(rad)*(2*rad+1));
        if(wide){
            double directMass=2*double(abs(r))+1;
            double splitMass=(2*double(abs(d))+1)*(2*double(abs(e))+1);
            uncertainty=min(uncertainty,min(directMass,splitMass)*(1+log2(1.+abs(r))*.2));
        }
        double information=log2(double(center)/(2*uncertainty+1));
        if(information<3.5)return 0;
        double score=min(13.,information)*(.78+.22/(1+fit));
        if(k==1)score+=2;
        if(k<=16)score+=.7;
        if(r==0)score+=1;
        if(out)*out={score,a,b,k,r,d,e};
        return score;
    }
    Model fit(vector<I> h){
        sort(h.begin(),h.end());h.erase(unique(h.begin(),h.end()),h.end());
        vector<Hit> hits(targets.size());
        for(size_t i=0;i<h.size();++i)for(size_t j=i;j<h.size();++j){
            I a=h[i],b=h[j];if(a>cap/b)continue;
            for(size_t q=0;q<targets.size();++q){
                Hit trial;
                if(weight(targets[q],a,b,&trial)>hits[q].value)hits[q]=trial;
            }
        }
        double score=-(wide?21.:11.)*h.size();
        int direct=0;set<pair<I,I>> pairs;
        for(auto z:hits)if(z.value>0){
            score+=z.value;direct+=z.k==1;
            if(z.k<=8)pairs.emplace(z.a,z.b);
        }
        score+=min<int>(12,pairs.size())*2;
        return {move(h),move(hits),score,direct};
    }
    void candidates(){
        for(I t:targets){
            if(t<4096)continue;
            I x=I(sqrtl(t));
            if(!observed.empty()&&t-observed.back()<noise(x)/2)continue;
            if(observed.size()<22)observed.push_back(t);
        }
        for(size_t i=0;i<observed.size();++i){
            I u=observed[i];
            for(int k=1;k<=60;++k){
                I x=llround(sqrtl((long double)u/k));
                if(x<10||abs(u-k*x*x)>k*noise(x))continue;
                add({x});
                for(I t:observed){
                    I estimate=rounded(t,x);
                    int step=(wide && x<=2048)?min<I>(3,1024/x+1):0;
                    for(I y=max(I(10),estimate-step);y<=estimate+step;++y){
                        if(y>60*x||y*60<x)continue;
                        if(abs(t-x*y)<=noise(min(x,y)))add({x,y});
                    }
                }
            }
            for(size_t j=i+1;j<observed.size();++j)for(size_t l=0;l<observed.size();++l){
                if(l==i||l==j)continue;
                I v=observed[j],w=observed[l];
                I x=llround(sqrtl((long double)u*v/w));
                if(x<10||x>1000000000)continue;
                I y=rounded(u,x),z=rounded(v,x);
                if(min(y,z)<10 || max({x,y,z})>60*min({x,y,z}))continue;
                if(abs(u-x*y)<=noise(min(x,y)) && abs(v-x*z)<=noise(min(x,z)) &&
                   abs(w-y*z)<=noise(min(y,z)))add({x,y,z});
            }
        }
    }
    Model expand(Model best){
        for(int epoch=0;epoch<5 && best.hub.size()<9;++epoch){
            set<I> options;
            for(I x:best.hub)for(I t:targets){
                for(int k: {1,2,3,4,5,7,8,9,11,13,16}){
                    I estimate=rounded(t,x*k);
                    int drift=(wide && x<=2048)?min<I>(3,1024/x+1):0;
                    for(I y=max(I(10),estimate-drift);y<=estimate+drift;++y){
                    if(y<10||y>60*best.hub.front()||y*60<best.hub.back())continue;
                    if(abs(t-k*x*y)>k*noise(min(x,y)))continue;
                    bool alias=false;
                    for(I old:best.hub)if(y%old==0 || old%y==0){alias=true;break;}
                    if(!alias)options.insert(y);
                    }
                }
            }
            vector<I> prev=best.hub;
            Model next=best;
            for(I y:options){
                vector<I> h=prev;h.push_back(y);
                Model proposed=fit(move(h));
                if(proposed.score>next.score)next=move(proposed);
            }
            if(next.score<best.score+4)break;
            best=move(next);
        }
        return best;
    }
    void run(){
        candidates();
        vector<Model> queue;
        for(auto h:initial){
            auto m=fit(h);
            if(m.direct || m.score>18)queue.push_back(move(m));
        }
        sort(queue.begin(),queue.end(),[](auto&a,auto&b){return a.score>b.score;});
        if(queue.size()>12)queue.resize(12);
        Model best{{},{},-1e30,0};
        for(auto&m:queue){
            auto improved=expand(move(m));
            if(improved.score>best.score)best=move(improved);
        }
        int covered=count_if(best.hits.begin(),best.hits.end(),[](Hit h){return h.value>0;});
        if(best.hub.size()<2||covered<4||best.direct<2||best.score<30){cout<<"0 0 0\n";return;}
        cout<<best.hub.size()<<' '<<covered<<' '<<best.score<<'\n';
        for(I x:best.hub)cout<<x<<' ';cout<<'\n';
        for(size_t i=0;i<best.hits.size();++i){
            Hit h=best.hits[i];if(h.value>0)cout<<targets[i]<<' '<<h.a<<' '<<h.b<<' '<<h.k<<' '<<h.r<<' '<<h.d<<' '<<h.e<<' '<<h.value<<'\n';
        }
    }
};
int main(int argc,char**argv){
    ios::sync_with_stdio(false);cin.tie(nullptr);
    string id;I cap;int n;
    while(cin>>id>>cap>>n){
        Recover r;r.wide=argc>1;r.cap=cap;r.targets.resize(n);
        for(I&x:r.targets)cin>>x;
        cout<<id<<' ';r.run();
    }
}
