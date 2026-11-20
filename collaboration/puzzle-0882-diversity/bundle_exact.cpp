// Enumerate a required subset of an independent donor union; allow unrestricted
// extra integer operands. The final arbitrary helper is found by inverting a
// necessary target equation and checked in the physically reachable frontier.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <map>
#include <set>
#include <unordered_map>
#include <unordered_set>
#include <vector>
using Num=std::int64_t;
using Mask=std::uint64_t;
using Values=std::vector<Num>;
using Set=std::unordered_set<Num>;
using U=std::uint64_t;

struct Search {
    Num lim;
    unsigned allowance,desired,part,parts,oldcap;
    U per,seen=0,owned=0,done=0,unknown=0,visits=0,total_visits=0;
    Mask seeds=0,goals=0,old=0,must=0,base=0,unsupported=0,winning=0;
    Values vals,donors,path,answer;
    std::unordered_map<Num,unsigned> id;
    std::vector<Mask> bits,self,anchors;
    std::vector<Values> partners;
    Mask pairs[64][64]={};
    std::map<Mask,Values> root_offers;
    bool limited=false,found=false;

    template<class F> void ops(Num a,Num b,F fn)const {
        auto lo=std::min(a,b),hi=std::max(a,b);
        auto add=[&](Num y){if(y>0&&y<=lim&&y!=a&&y!=b)fn(y);};
        if(lo<=lim-hi)add(lo+hi);if(lo<=lim/hi)add(lo*hi);
        add(hi-lo);if(hi%lo==0)add(hi/lo);
    }
    template<class F> void inverse(Num t,Num a,F fn)const {
        if(a==t)return;
        auto add=[&](Num y){if(y>0&&y<=lim&&y!=t)fn(y);};
        add(t-a);add(a-t);if(t<=lim-a)add(t+a);
        if(t<=lim/a)add(t*a);if(t%a==0)add(t/a);if(a%t==0)add(a/t);
    }
    template<class F> void bits_each(Mask m,F fn)const {
        while(m){auto j=__builtin_ctzll(m);m&=m-1;fn(j);}
    }
    Mask read(unsigned n,Values* buf=nullptr) {
        Mask m=0;
        while(n--){Num x;std::cin>>x;if(x<1||x>lim)throw 1;
            if(!id.count(x)){if(vals.size()>=63)throw 1;id[x]=vals.size();vals.push_back(x);}
            m|=Mask(1)<<id[x];if(buf)buf->push_back(x);}
        return m;
    }
    void prepare() {
        unsigned n=vals.size();
        if(lim>2000000)throw 2;
        bits.assign(lim+1,0);self.assign(lim+1,0);anchors.assign((lim+1)*n,0);partners.resize(n);
        for(unsigned i=0;i<n;++i)bits[vals[i]]=Mask(1)<<i;
        for(unsigned j=0;j<n;++j){
            Num t=vals[j];Set candidates;
            if(t%2==0){self[t/2]|=Mask(1)<<j;candidates.insert(t/2);}
            Num r=std::sqrt((long double)t);
            if(r*r==t&&r!=t){self[r]|=Mask(1)<<j;candidates.insert(r);}
            for(unsigned i=0;i<n;++i)inverse(t,vals[i],[&](Num y){
                anchors[y*n+j]|=Mask(1)<<i;candidates.insert(y);});
            partners[j]=Values(candidates.begin(),candidates.end());
            std::sort(partners[j].begin(),partners[j].end());
        }
        for(unsigned i=0;i<n;++i)for(unsigned j=0;j<=i;++j){
            ops(vals[i],vals[j],[&](Num y){pairs[i][j]|=bits[y];});pairs[j][i]=pairs[i][j];}
    }
    Mask hits(Num x,Num y)const {
        Mask m=0;ops(x,y,[&](Num z){m|=bits[z];});return m;
    }
    Mask raw(Mask m)const {
        Mask result=0;
        bits_each(m,[&](unsigned i){bits_each(m&((Mask(1)<<(i+1))-1),[&](unsigned j){result|=pairs[i][j];});});
        return result;
    }
    Mask cover(Num x,Mask wanted,Mask allowed)const {
        Mask result=self[x]&wanted;
        const auto* row=&anchors[x*vals.size()];
        bits_each(wanted&~result,[&](unsigned j){if(row[j]&allowed)result|=Mask(1)<<j;});
        return result;
    }
    Mask close(Mask known,const Values& aux)const {
        Mask extra=0;
        for(unsigned i=0;i<aux.size();++i)for(unsigned j=0;j<=i;++j)extra|=hits(aux[i],aux[j]);
        for(;;) {
            Mask supply=raw(known)|extra;
            for(Num v:aux)supply|=cover(v,must&~(known|supply),known);
            Mask fresh=must&supply&~known;
            if(!fresh)return known;
            known|=fresh;
        }
    }
    const Values& offers(Mask known) {
        auto [it,inserted]=root_offers.try_emplace(known);
        if(inserted){
            Set options;
            bits_each(known,[&](unsigned i){bits_each(known&((Mask(1)<<(i+1))-1),[&](unsigned j){
                ops(vals[i],vals[j],[&](Num v){if(!(bits[v]&known))options.insert(v);});});});
            it->second=Values(options.begin(),options.end());std::sort(it->second.begin(),it->second.end());
        }
        return it->second;
    }
    Values options(Mask known,const Values& aux) {
        const auto& initial=offers(known);
        if(aux.empty())return initial;
        Set values(initial.begin(),initial.end());
        auto add=[&](Num v){if(!(bits[v]&known))values.insert(v);};
        for(unsigned k=0;k<aux.size();++k){
            bits_each(known,[&](unsigned i){ops(aux[k],vals[i],add);});
            for(unsigned j=0;j<=k;++j)ops(aux[k],aux[j],add);
        }
        for(Num v:aux)values.erase(v);
        auto res=Values(values.begin(),values.end());std::sort(res.begin(),res.end());return res;
    }
    bool reachable(Num v,Mask known)const {
        auto selectable=[&](Num y){return bool(bits[y]&known)||std::find(path.begin(),path.end(),y)!=path.end();};
        if(selectable(v))return false;
        if(v%2==0&&selectable(v/2))return true;
        auto r=(Num)std::sqrt((long double)v);if(r*r==v&&r!=v&&selectable(r))return true;
        if(v==1 && (known || !path.empty()))return true;
        bool yes=false;
        bits_each(known,[&](unsigned i){if(!yes)inverse(v,vals[i],[&](Num y){if(selectable(y))yes=true;});});
        for(Num x:path)inverse(v,x,[&](Num y){if(selectable(y))yes=true;});
        return yes;
    }
    bool visit(Mask known,Mask missing,unsigned left) {
        if(++visits>per){limited=true;return false;}
        if(!(must&~known)){answer=path;return true;}
        if(!left)return false;
        Values ys;
        if(left==1&&missing){
            unsigned pivot=__builtin_ctzll(missing);
            bits_each(missing,[&](unsigned j){if(partners[j].size()<partners[pivot].size())pivot=j;});
            ys=partners[pivot];
            for(Num x:path)inverse(vals[pivot],x,[&](Num y){ys.push_back(y);});
            std::sort(ys.begin(),ys.end());ys.erase(std::unique(ys.begin(),ys.end()),ys.end());
        }else ys=options(known,path);
        for(Num y:ys){
            if(bits[y]&must)continue;
            Mask provided=cover(y,missing,base);
            for(Num x:path)provided|=hits(x,y);
            Mask rest=missing&~provided;
            if(left==1&&(rest || (missing&&!reachable(y,known))))continue;
            path.push_back(y);
            Mask next=close(known,path);
            if(visit(next,rest,left-1))return true;
            path.pop_back();
            if(limited)return false;
        }
        return false;
    }
    void subsets(unsigned at,unsigned need,Mask selected) {
        if(found||donors.size()-at<need)return;
        if(need){
            for(unsigned i=at;i+need<=donors.size()&&!found;++i)subsets(i+1,need-1,selected|bits[donors[i]]);
            return;
        }
        ++seen;
        if((seen-1)%parts!=part || (unsigned)__builtin_popcountll(selected&old)>oldcap)return;
        ++owned;must=goals|selected;base=seeds|must;unsupported=must&~(seeds|raw(base));
        visits=0;limited=false;path.clear();
        if(visit(close(seeds,path),unsupported,allowance)){found=true;winning=selected;}
        if(limited)++unknown;else if(!found)++done;
        total_visits+=visits;
    }
};
int main(){
    try {Search s;unsigned ns,ng,nd,no;
        if(!(std::cin>>s.lim>>s.allowance>>s.desired>>s.part>>s.parts>>s.oldcap>>s.per>>ns>>ng>>nd>>no))return 2;
        s.seeds=s.read(ns);s.goals=s.read(ng);s.read(nd,&s.donors);s.old=s.read(no);
        s.prepare();s.subsets(0,s.desired,0);
        std::cout<<(s.found?"FOUND":s.unknown?"UNKNOWN":"UNSAT_REGION")<<" "<<s.seen<<" "<<s.owned<<" "<<s.done<<" "<<s.unknown<<" "<<s.total_visits<<"\n";
        if(s.found){s.bits_each(s.winning,[&](unsigned i){std::cout<<s.vals[i]<<" ";});for(Num v:s.answer)std::cout<<v<<" ";std::cout<<"\n";}
    }catch(int){return 2;}
}
