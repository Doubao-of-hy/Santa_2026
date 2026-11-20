// Enumerate primitive three-target linear identities directly from official
// targets. A second distinct relation on the same triple, or a shared target
// pair across two triples, identifies a candidate for joint reconstruction.
#include <algorithm>
#include <array>
#include <cstdint>
#include <iostream>
#include <map>
#include <numeric>
#include <set>
#include <string>
#include <unordered_set>
#include <vector>
using namespace std;
using I=int64_t;
struct Point{I value;int id,k;};
struct Rule{int x,y,z,a,b,c;I error;};
int main(int argc,char** argv){
    const bool writeRules=argc==2 && string(argv[1])=="rules";
    ios::sync_with_stdio(false);cin.tie(nullptr);
    string tag,id;I cap;int ns,nt;
    const vector<int> coeff={1,2,3,4,5,6,8};
    while(cin>>tag>>id>>cap>>ns>>nt){
        unordered_set<I> errs={0,1,-1};I radius=1;
        for(int i=0;i<ns;i++){I s;cin>>s;errs.insert(s);errs.insert(-s);radius=max(radius,s);}
        vector<I> t(nt);for(I& x:t)cin>>x;
        t.erase(remove_if(t.begin(),t.end(),[](I x){return x<4096;}),t.end());
        sort(t.begin(),t.end());int n=t.size();
        vector<Point> pool;
        for(int i=0;i<n;i++)for(int k:coeff)if(t[i]<=cap/k)pool.push_back({k*t[i],i,k});
        sort(pool.begin(),pool.end(),[](auto a,auto b){return a.value<b.value;});
        vector<vector<char>> trivial(n,vector<char>(n));
        for(size_t i=0;i<pool.size();i++)for(size_t j=i+1;j<pool.size() && pool[j].value-pool[i].value<=radius;j++){
            if(pool[i].id!=pool[j].id && errs.count(pool[j].value-pool[i].value)){
                int a=pool[i].id,b=pool[j].id;trivial[a][b]=trivial[b][a]=1;
            }
        }
        map<array<int,3>,vector<Rule>> groups;int raw=0,unscaled=0;
        for(int x=0;x<n;x++)for(int y=x+1;y<n;y++)for(int a:coeff){
            if(t[x]>cap/a)continue;
            I ax=t[x]*a;
            for(int b:coeff){
                if(t[y]>(cap-ax)/b)continue;
                I sum=ax+t[y]*b;
                auto it=lower_bound(pool.begin(),pool.end(),sum-radius,[](auto p,I s){return p.value<s;});
                for(;it!=pool.end() && it->value<=sum+radius;it++){
                    int z=it->id,c=it->k;I e=sum-it->value;
                    if(z==x || z==y || !errs.count(e) || gcd(gcd(a,b),c)>1)continue;
                    ++raw;
                    if(a==1 && b==1 && c==1){++unscaled;continue;}
                    if(trivial[x][y]||trivial[x][z]||trivial[y][z])continue;
                    array<int,3> nodes={x,y,z};sort(nodes.begin(),nodes.end());
                    groups[nodes].push_back({x,y,z,a,b,c,e});
                }
            }
        }
        map<pair<int,int>,int> pairs;int rank2=0,exact=0,joint=0;
        for(auto& [nodes,rules]:groups){
            for(int a=0;a<3;a++)for(int b=a+1;b<3;b++)pairs[{nodes[a],nodes[b]}]++;
            if(rules.size()>1)++rank2;
            if(any_of(rules.begin(),rules.end(),[](auto r){return r.error==0;}))++exact;
        }
        for(auto& [p,size]:pairs)if(size>=2)++joint;
        cout<<tag<<' '<<id<<' '<<n<<' '<<raw<<' '<<unscaled<<' '<<groups.size()<<' '<<exact<<' '<<rank2<<' '<<joint<<'\n';
        if(writeRules){
            for(auto& [nodes,rules]:groups)for(auto r:rules)
                cout<<"R "<<id<<' '<<t[r.x]<<' '<<t[r.y]<<' '<<t[r.z]<<' '<<r.a<<' '<<r.b<<' '<<r.c<<' '<<r.error<<'\n';
        }
    }
}
