// Optimize the order of a fixed arithmetic DAG without changing its recipes.
#include <algorithm>
#include <chrono>
#include <cmath>
#include <iostream>
#include <numeric>
#include <random>
#include <vector>
using namespace std;

struct Layout {
    int n,seeds,cap;
    vector<int> a,b,hint,last,delta,live;
    vector<vector<int>> users;
    mt19937_64 rng;

    double objective(const vector<int>& order,int& maximum) {
        fill(last.begin(),last.end(),-1);
        for(int time=0;time<n;++time){int v=order[time];last[a[v]]=last[b[v]]=time;}
        fill(delta.begin(),delta.end(),0);int usage=0;
        for(int i=n;i<n+seeds;++i)if(last[i]>=0){++usage;--delta[last[i]];}
        maximum=usage;double value=0;
        for(int i=0;i<n;++i){
            usage+=delta[i];int needed=usage+1;live[i]=needed;
            maximum=max(maximum,needed);int excess=max(0,needed-cap);
            // Give the search an incentive to reduce the area of the peak
            // before it can eliminate the peak itself.
            value+=excess*excess+0.025*max(0,needed-cap+3);
            if(last[order[i]]>i){++usage;--delta[last[order[i]]];}
        }
        return value+2.5*max(0,maximum-cap)*max(0,maximum-cap);
    }
    vector<int> start(int kind){
        vector<int> out;vector<char> done(n+seeds,1);
        fill(done.begin(),done.begin()+n,0);
        for(int j=0;j<n;j++){
            int best=-1;double score=1e30;
            for(int i=0;i<n;i++)if(!done[i]&&done[a[i]]&&done[b[i]]){
                double s=kind==0?i:hint[i];
                if(kind>=2)s+=double(rng()%18000)/1000.;
                if(s<score){best=i;score=s;}
            }
            if(best<0)throw logic_error("cyclic");
            done[best]=1;out.push_back(best);
        }
        return out;
    }
    vector<int> search(double seconds,int& bestPeak,long long& attempts){
        auto t0=chrono::steady_clock::now();auto elapsed=[&](){return chrono::duration<double>(chrono::steady_clock::now()-t0).count();};
        vector<int> best;double bestScore=1e90;bestPeak=n;attempts=0;
        for(int restart=0;elapsed()<seconds;++restart){
            vector<int> cur=restart>2&&restart%3!=0?best:start(restart%4);
            vector<int> ix(n+seeds,-1);for(int i=0;i<n;i++)ix[cur[i]]=i;
            int mx;double score=objective(cur,mx);
            for(int step=0;step<18000;++step){
                if(score<bestScore){bestScore=score;best=cur;bestPeak=mx;}
                if(mx<=cap)return cur;
                if(step%256==0 && elapsed()>=seconds)break;
                ++attempts;int before=rng()%n;
                double frac=step/18000.;double heat=(restart%3==0?8.0:2.8)*exp(-4.5*frac)+.035;
                if(rng()%4==0){
                    int after=rng()%n;
                    if(before==after)continue;
                    const bool advance=before>after;
                    int left=min(before,after),right=max(before,after);
                    vector<char> chosen(n,0);
                    vector<int> todo{cur[before]};chosen[cur[before]]=1;
                    while(!todo.empty()){
                        int x=todo.back();todo.pop_back();
                        auto select=[&](int y){if(y<n && !chosen[y] && ix[y]>=left && ix[y]<=right){chosen[y]=1;todo.push_back(y);}};
                        if(advance){select(a[x]);select(b[x]);}else for(int y:users[x])select(y);
                    }
                    auto next=cur;
                    auto middle=stable_partition(next.begin()+left,next.begin()+right+1,[&](int node){return bool(chosen[node])==advance;});
                    if(middle==next.begin()+left || middle==next.begin()+right+1 || next==cur)continue;
                    int nm;double candidate=objective(next,nm);
                    if(candidate<=score || generate_canonical<double,36>(rng)<exp((score-candidate)/heat)){
                        cur.swap(next);score=candidate;mx=nm;
                        for(int i=left;i<=right;i++)ix[cur[i]]=i;
                    }
                    continue;
                }
                int v=cur[before],lo=max(ix[a[v]],ix[b[v]])+1,hi=n-1;
                for(int u:users[v])hi=min(hi,ix[u]-1);
                if(hi<=lo)continue;
                int after=lo+rng()%(hi-lo+1);
                if(rng()%3==0){int shift=(rng()%3+1)*(rng()%2?1:-1);after=clamp(before+shift,lo,hi);}
                if(before==after)continue;
                if(before<after)rotate(cur.begin()+before,cur.begin()+before+1,cur.begin()+after+1);
                else rotate(cur.begin()+after,cur.begin()+before,cur.begin()+before+1);
                int nm;double candidate=objective(cur,nm);
                if(candidate<=score || generate_canonical<double,36>(rng)<exp((score-candidate)/heat)){
                    score=candidate;mx=nm;
                    for(int i=min(before,after);i<=max(before,after);i++)ix[cur[i]]=i;
                }else{
                    if(before<after)rotate(cur.begin()+before,cur.begin()+after,cur.begin()+after+1);
                    else rotate(cur.begin()+after,cur.begin()+after+1,cur.begin()+before+1);
                }
            }
        }
        return best;
    }
};

int main(){
    ios::sync_with_stdio(false);double seconds;unsigned long long seed;Layout q;
    while(cin>>q.n>>q.seeds>>q.cap>>seconds>>seed){
        int n=q.n;q.a.resize(n);q.b.resize(n);q.hint.resize(n);q.last.resize(n+q.seeds);q.delta.resize(n);q.live.resize(n);q.users.assign(n+q.seeds,{});q.rng.seed(seed);
        for(int i=0;i<n;i++){
            cin>>q.a[i]>>q.b[i]>>q.hint[i];q.users[q.a[i]].push_back(i);
            if(q.a[i]!=q.b[i])q.users[q.b[i]].push_back(i);
        }
        int peak;long long attempts;auto order=q.search(seconds,peak,attempts);
        int checked;q.objective(order,checked);cout<<checked<<' '<<attempts<<'\n';
        for(int i:order)cout<<i<<' ';cout<<'\n';
    }
}
