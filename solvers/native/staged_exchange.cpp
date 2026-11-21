// A two-integer replacement in which only the downstream integer need have
// arithmetic uses in a current program. Three old deletions pay for both.
#define main original_value_exchange_main
#include "value_exchange.cpp"
#undef main
#include <array>

struct Tip {int merit,id;vector<U> gift,ordinary;};
struct Chain {int merit,ti;I h;vector<int> removable;vector<Edge> middle;};
struct Staged : Search {
    int gifted=0,tested=0,lanes=0;
    unordered_map<I,vector<Edge>> book;
    vector<Edge> calculate(I h,I x,const vector<Edge>& mid,const Extra& tip){
        vector<Edge> more=book.at(h); // h is n; x is n+1.
        for(auto e:tip.birth){e.v=n+1;more.push_back(e);}
        more.insert(more.end(),mid.begin(),mid.end());
        for(auto e:tip.use){if(e.a==n)e.a++;if(e.b==n)e.b++;more.push_back(e);}
        auto pos=idx.find(h);if(pos!=idx.end())more.insert(more.end(),extras[pos->second].use.begin(),extras[pos->second].use.end());
        arithmetic(h,x,cap,[&](Op e){
            auto it=lookup.find(e.v);if(it!=lookup.end())more.push_back({it->second,e.a==h?n:n+1,e.b==h?n:n+1,e.op});
        });
        return more;
    }
    vector<Op> materialize(const vector<Edge>& add,const vector<int>& bans,I h,I x){
        vector<char> reach(n+2),allow(n+2,1);vector<Edge> choices(n+2);
        vector<int> seq;
        for(int b:bans)allow[b]=0;for(int s:seedids)reach[s]=1;
        auto apply=[&](const vector<Edge>& bank){for(auto e:bank)if(!reach[e.v]&&allow[e.v]&&reach[e.a]&&reach[e.b]){
            seq.push_back(e.v);choices[e.v]=e;reach[e.v]=1;
        }};
        size_t prev;do{prev=seq.size();apply(add);apply(base);}while(prev!=seq.size());
        vector<char> marked(n+2);
        for(int g:goalids){if(!reach[g])return {};marked[g]=1;}
        for(auto i=seq.rbegin();i!=seq.rend();i++)if(marked[*i]){auto e=choices[*i];marked[e.a]=marked[e.b]=1;}
        auto val=[&](int a){return a<n?values[a]:(a==n?h:x);};
        vector<Op> result;for(int v:seq)if(marked[v]){auto e=choices[v];result.push_back({val(v),val(e.a),val(e.b),e.op});}
        return result;
    }
    void assess(const Chain& c,const Tip& t,int tripleLimit){
        auto& tip=extras[t.id];vector<Edge> added=calculate(c.h,tip.value,c.middle,tip);
        assessEdges(added,c.removable,c.h,tip.value,tripleLimit);
    }
    void assessEdges(const vector<Edge>& added,const vector<int>& xs,I h,I x,int tripleLimit){
        vector<array<int,3>> combos;
        for(int k=2;k<(int)xs.size()&&int(combos.size())<tripleLimit;k++)
            for(int j=1;j<k&&int(combos.size())<tripleLimit;j++)
                for(int i=0;i<j&&int(combos.size())<tripleLimit;i++)
                    combos.push_back({xs[i],xs[j],xs[k]});
        for(int offset=0;offset<(int)combos.size();offset+=64){
            int sz=min(64,int(combos.size())-offset);lanes+=sz;
            U live=sz==64?~U(0):((U(1)<<sz)-1);
            vector<U> have(n+2),allow(n+2,live);
            for(int s:seedids)have[s]=live;
            for(int i=0;i<sz;i++)for(int v:combos[offset+i])allow[v]^=U(1)<<i;
            U changed;
            auto step=[&](const vector<Edge>& bank){
                for(const auto&e:bank){
                    U bits=allow[e.v]&have[e.a]&have[e.b]&~have[e.v];
                    changed|=bits;have[e.v]|=bits;
                }
            };
            do{changed=0;step(base);step(added);}while(changed);
            U solved=live;for(int g:goalids)solved&=have[g];
            int hits=0;
            while(solved&&hits<2){
                int bit=__builtin_ctzll(solved);solved&=solved-1;hits++;
                auto b=combos[offset+bit];vector<int> bans{b[0],b[1],b[2]};
                auto pg=materialize(added,bans,h,x);
                if(pg.empty())throw runtime_error("inconsistent bit-sliced triple witness");
                for(int old:xs)if(find(bans.begin(),bans.end(),old)==bans.end()){
                    bans.push_back(old);auto trial=materialize(added,bans,h,x);
                    if(trial.empty())bans.pop_back();else pg=move(trial);
                }
                record(move(pg));
            }
            if(hits)break;
        }
    }
    void staged(int tipLimit,int chainLimit,int triples){
        populate();vector<Tip> tips;vector<U> free;
        int unused=0;for(auto& b:batches)free.push_back(helped(b,nullptr,unused));
        for(int i=0;i<(int)extras.size();i++){
            const Extra &c=extras[i];Tip t{0,i,{},{}};
            int np=0,novel=0;
            for(int j=0;j<(int)batches.size();j++){
                U upper=helped(batches[j],&c,unused,true);
                t.gift.push_back(upper);
                if(__builtin_popcountll(upper)==0){t.ordinary.push_back(0);continue;}
                U rooted=c.birth.empty()?free[j]:helped(batches[j],&c,unused);
                t.ordinary.push_back(rooted);np+=__builtin_popcountll(upper);
                novel+=__builtin_popcountll(upper&~rooted);
            }
            if(np<3||!novel)continue;
            t.merit=75*novel+16*np+int(min<size_t>(c.use.size(),40));tips.push_back(move(t));
        }
        gifted=tips.size();
        sort(tips.begin(),tips.end(),[&](const Tip&a,const Tip&b){return a.merit!=b.merit?a.merit>b.merit:extras[a.id].value<extras[b.id].value;});
        if(tips.size()>size_t(tipLimit))tips.resize(tipLimit);
        // Build only the one-operation precursors relevant to these free-tip
        // upper bounds. A private precursor need never appear in an old recipe.
        vector<unordered_map<I,vector<Edge>>> mid(tips.size());
        for(int i=0;i<(int)tips.size();i++){
            I x=extras[tips[i].id].value;
            auto put=[&](I h,Op e,int ci){
                if(h==x||lookup.count(h))return;
                book.try_emplace(h);
                mid[i][h].push_back({n+1,e.a==h?n:ci,e.b==h?n:ci,e.op});
            };
            for(int c=0;c<n;c++)inverse(x,values[c],cap,[&](I h,Op e){put(h,e,c);});
            if(x%2==0)put(x/2,{x,x/2,x/2,'+'},n);
            I r=(I)sqrt((long double)x);while(r+1<=x/(r+1))r++;while(r>x/r)r--;
            if(r*r==x)put(r,{x,r,r,'*'},n);
        }
        if(book.empty())return;
        for(int a=0;a<n;a++)for(int b=0;b<=a;b++)arithmetic(values[a],values[b],cap,[&](Op e){
            auto it=book.find(e.v);if(it!=book.end())it->second.push_back({n,lookup.at(e.a),lookup.at(e.b),e.op});
        });
        vector<Chain> chains;
        for(int i=0;i<(int)tips.size();i++)for(auto &piece:mid[i]){
            I h=piece.first;auto& births=book[h];if(births.empty())continue;
            Chain c{0,i,h,{},piece.second};int novel=0;
            for(int j=0;j<(int)batches.size();j++){
                const auto &batch=batches[j];U funded=0,access=0;
                for(auto e:births)funded|=batch.reach[e.a]&batch.reach[e.b];
                for(auto e:piece.second){
                    int old=e.a==n?e.b:e.a;access|=old==n?batch.live:batch.reach[old];
                }
                U elig=tips[i].gift[j]&access&funded;
                novel+=__builtin_popcountll(elig&~tips[i].ordinary[j]);
                while(elig){int k=__builtin_ctzll(elig);elig&=elig-1;c.removable.push_back(batch.banned[k]);}
            }
            if(c.removable.size()<3||!novel)continue;
            c.merit=100*novel+20*int(c.removable.size())+int(min<size_t>(births.size(),30));
            chains.push_back(move(c));
        }
        stable_sort(chains.begin(),chains.end(),[](const Chain&a,const Chain&b){return a.merit!=b.merit?a.merit>b.merit:a.h<b.h;});
        unordered_map<int,int> perTip;
        for(auto& c:chains){
            if(perTip[c.ti]>=max(3,chainLimit/8))continue;
            perTip[c.ti]++;tested++;assess(c,tips[c.ti],triples);
            if(tested>=chainLimit)break;
        }
    }
};
#ifndef STAGED_LIBRARY
int main(int argc,char**argv){
    ios::sync_with_stdio(false);cin.tie(nullptr);string name;int ns,nt,ng;
    while(cin>>name){
        Staged s;cin>>s.cap>>ns>>nt>>ng;s.seeds.resize(ns);s.goals.resize(nt);
        for(I&v:s.seeds)cin>>v;for(I&v:s.goals)cin>>v;
        for(int i=0;i<ng;i++){Op e;cin>>e.v>>e.op>>e.a>>e.b;s.original.push_back(e);}
        s.staged(argc>1?stoi(argv[1]):70,argc>2?stoi(argv[2]):45,argc>3?stoi(argv[3]):100);
        cout<<name<<' '<<s.gifted<<' '<<s.tested<<' '<<s.lanes<<' '<<s.winners.size()<<'\n';
        for(auto&pg:s.winners){cout<<pg.size()<<'\n';for(auto&e:pg)cout<<e.v<<' '<<e.op<<' '<<e.a<<' '<<e.b<<'\n';}
    }
}
#endif
