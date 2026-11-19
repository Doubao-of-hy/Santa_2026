// Sieve an entire neighborhood around an arithmetic goal. Reconstruct smooth
// products and their small offsets using the values retained outside the cut.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>
#include <map>
#include <set>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>
using namespace std;
using I=int64_t;
struct Edge {I out,a,b; char op;};
using Plan=vector<Edge>;
struct Word {int cost=90; Edge edge{0,0,0,'?'};};

template<class F> void pairs(I a,I b,I cap,F accept){
    if(a<=cap-b) accept(Edge{a+b,a,b,'+'});
    if(a>b) accept(Edge{a-b,a,b,'-'});
    if(b>a) accept(Edge{b-a,b,a,'-'});
    if(a<=cap/b) accept(Edge{a*b,a,b,'*'});
    if(a%b==0) accept(Edge{a/b,a,b,'/'});
    if(b%a==0 && a!=b) accept(Edge{b/a,b,a,'/'});
}
struct Candidate {I v,rem;int offset;double rank;};
struct Search {
    I cap,goal;int budget,radius,centers;
    vector<I> atoms;
    unordered_set<I> paid;
    unordered_map<I,Edge> one;
    unordered_map<I,Word> two;
    vector<Plan> best;
    vector<pair<int,int>> ranges;
    unordered_map<I,Word> books;
    Search(I cap,I goal,int budget,int radius,int centers,vector<I> atoms)
        :cap(cap),goal(goal),budget(budget),radius(radius),centers(centers),atoms(move(atoms)){
        paid.insert(this->atoms.begin(),this->atoms.end());
        one.reserve(this->atoms.size()*this->atoms.size()*2);
        for(size_t i=0;i<this->atoms.size();++i)for(size_t j=0;j<=i;++j)
            pairs(this->atoms[i],this->atoms[j],cap,[&](Edge e){
                if(!paid.count(e.out))one.emplace(e.out,e);
            });
    }
    Word basic(I v){
        if(paid.count(v))return {0,{}};
        auto it=one.find(v);if(it!=one.end())return {1,it->second};
        return {};
    }
    Word cheap(I v){
        auto simple=basic(v);if(simple.cost<=1)return simple;
        auto prev=two.find(v);if(prev!=two.end())return prev->second;
        Word word;
        for(I a:atoms){
            auto try_word=[&](I x,char op,bool left){
                if(x<=0||x==goal||!one.count(x))return false;
                word={2,{v,left?x:a,left?a:x,op}};return true;
            };
            if((v>a && try_word(v-a,'+',true))
               ||(v<=cap-a && try_word(v+a,'-',true))
               ||(a>v && try_word(a-v,'-',false))
               ||(v%a==0 && try_word(v/a,'*',true))
               ||(v<=cap/a && try_word(v*a,'/',true))
               ||(a%v==0 && try_word(a/v,'/',false)))break;
        }
        two.emplace(v,word);return word;
    }
    void append(I v,const unordered_map<I,Word>& expressions,Plan& plan,unordered_set<I>& done){
        if(paid.count(v)||!done.insert(v).second)return;
        auto it=expressions.find(v);
        Word w=it==expressions.end()?cheap(v):it->second;
        if(w.cost>=80)throw runtime_error("missing witness");
        auto e=w.edge;append(e.a,expressions,plan,done);append(e.b,expressions,plan,done);
        plan.push_back(e);
    }
    void consider(I v,int offset,const unordered_map<I,Word>& expressions){
        unordered_set<I> done;Plan plan;
        append(v,expressions,plan,done);
        if(offset){
            I r=abs(offset);append(r,expressions,plan,done);
            plan.push_back({goal,v,r,offset>0?'-':'+'});
        }
        if(plan.empty()||(int)plan.size()>=budget)return;
        vector<I> signature;for(auto e:plan)signature.push_back(e.out);
        sort(signature.begin(),signature.end());
        for(auto &alternative:best){
            vector<I> other;for(auto e:alternative)other.push_back(e.out);
            sort(other.begin(),other.end());if(other==signature)return;
        }
        best.push_back(move(plan));
        stable_sort(best.begin(),best.end(),[](const Plan&a,const Plan&b){return a.size()<b.size();});
        if(best.size()>3)best.pop_back();
    }
    void product(I v,I rem,vector<pair<int,int>> pf,int offset){
        vector<I> divisors{1};
        for(auto [p,k]:pf){
            size_t available=divisors.size();I mul=1;
            for(int j=0;j<k;++j){mul*=p;for(size_t i=0;i<available;++i)divisors.push_back(divisors[i]*mul);}
        }
        if(rem>1){
            size_t available=divisors.size();for(size_t i=0;i<available;++i)divisors.push_back(divisors[i]*rem);
        }
        sort(divisors.begin(),divisors.end());
        unordered_map<I,Word> costs;
        costs.reserve(divisors.size()*2);
        for(size_t i=1;i<divisors.size();++i){
            I x=divisors[i];
            Word best_word=basic(x);
            if(best_word.cost>1 && (x<=65536 || x==rem || x==v))best_word=cheap(x);
            if(best_word.cost>1){
                for(size_t j=1;j<i;++j){
                    I a=divisors[j];if(a>x/a)break;
                    if(x%a)continue;
                    I b=x/a;
                    auto wb=costs.find(b);if(wb==costs.end())continue;
                    auto wa=costs.find(a);if(wa==costs.end())continue;
                    int sum=1+wa->second.cost+(a==b?0:wb->second.cost);
                    if(sum<best_word.cost)best_word={sum,{x,a,b,'*'}};
                    if(sum<=1)break;
                }
            }
            if(best_word.cost<budget)costs[x]=best_word;
        }
        if(costs.count(v))consider(v,offset,costs);
    }
    void run(const vector<int>& primes){
        I lo=max(I(2),goal-radius),hi=min(cap,goal+radius);
        if(lo>hi)return;
        int n=int(hi-lo+1);
        vector<I> remainder(n);vector<vector<pair<int,int>>> factors(n);
        for(int i=0;i<n;++i)remainder[i]=lo+i;
        for(int p:primes){
            int j=(p-lo%p)%p;
            for(;j<n;j+=p){
                int e=0;while(remainder[j]%p==0){remainder[j]/=p;++e;}
                factors[j].emplace_back(p,e);
            }
        }
        vector<Candidate> ranked;
        for(int i=0;i<n;++i){
            I v=lo+i,rem=remainder[i];int offset=int(v-goal);
            int r=abs(offset);Word rw=r?cheap(r):Word{0,{}};
            if(rw.cost+int(r!=0)>=budget-1)continue;
            auto easy=basic(v);
            if(easy.cost<=1){consider(v,offset,{});continue;}
            if(factors[i].empty())continue;
            Word last=rem==1?Word{0,{}}:basic(rem);
            if(last.cost>=3 && rem<=10000000)last=cheap(rem);
            if(last.cost>=3)continue;
            double rank=1.9*rw.cost+last.cost+.12*factors[i].size()+.04*log2(double(1+r));
            if(r==0)rank-=25;
            ranked.push_back({v,rem,offset,rank});
        }
        sort(ranked.begin(),ranked.end(),[](const auto&a,const auto&b){return a.rank<b.rank;});
        if((int)ranked.size()>centers)ranked.resize(centers);
        for(auto c:ranked)product(c.v,c.rem,factors[c.v-lo],c.offset);
        // Multiplicative cofactors discovered by the sieve have no obligation to
        // end in a known small prime. Try the unshifted value's exact two-step path.
        if(cheap(goal).cost<budget)consider(goal,0,{});
    }
};
int main(int argc,char**argv){
    if(argc!=4)return 2;
    ios::sync_with_stdio(false);cin.tie(nullptr);
    int radius=stoi(argv[1]),bound=stoi(argv[2]),centers=stoi(argv[3]);
    vector<int> primes;
    for(int p=2;p<=bound;++p){
        bool prime=true;for(int q:primes){if(q*q>p)break;if(p%q==0){prime=false;break;}}
        if(prime)primes.push_back(p);
    }
    I cap,goal;int budget,count;
    while(cin>>cap>>goal>>budget>>count){
        vector<I> atoms(count);for(I &x:atoms)cin>>x;
        Search s(cap,goal,budget,radius,centers,move(atoms));s.run(primes);
        cout<<goal<<' '<<s.best.size()<<'\n';
        for(const auto&plan:s.best){
            cout<<plan.size()<<'\n';
            for(auto e:plan)cout<<e.out<<' '<<e.op<<' '<<e.a<<' '<<e.b<<'\n';
        }
    }
    return 0;
}
