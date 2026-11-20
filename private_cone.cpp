// Bounded arithmetic-pattern enumeration for one private dependency cone.
// No returned candidate (or lack of one) establishes full-puzzle optimality.
#include <algorithm>
#include <cmath>
#include <iostream>
#include <sstream>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>
using namespace std;
using I=long long;
struct E {I v,a,b;char op;};
using Plan=vector<E>;
template<class F> void ops(I x,I y,I M,F f){
 if(x<=M-y)f(E{x+y,x,y,'+'});
 if(x>y)f(E{x-y,x,y,'-'});
 if(y>x)f(E{y-x,y,x,'-'});
 if(x<=M/y)f(E{x*y,x,y,'*'});
 if(x%y==0)f(E{x/y,x,y,'/'});
 if(y%x==0)f(E{y/x,y,x,'/'});
}
template<class F> void invert(I x,I t,I M,F f) {
 if(x<t)f(t-x,'+',0);
 if(x<=M-t)f(x+t,'-',1);
 if(x>t)f(x-t,'-',0);
 if(t%x==0)f(t/x,'*',0);
 if(x<=M/t)f(t*x,'/',1);
 if(x%t==0)f(x/t,'/',0);
}
class Planner {
 I M;
 vector<I> roots,ones;
 unordered_set<I> seed;
 unordered_map<I,E> one;
 bool c(I v) const{return seed.count(v);}
public:
 Planner(vector<I> r,I M):M(M),roots(move(r)),seed(roots.begin(),roots.end()) {
  sort(roots.begin(),roots.end());roots.erase(unique(roots.begin(),roots.end()),roots.end());
  one.reserve(15000);
  for(size_t a=0;a<roots.size();++a)for(size_t b=0;b<=a;++b)
    ops(roots[a],roots[b],M,[&](E e){
      if(!c(e.v) && one.emplace(e.v,e).second)ones.push_back(e.v);
    });
 }
 template<class F> void direct(I t,F f) const{
  if(c(t)){f(Plan{});return;}
  if(auto l=one.find(t);l!=one.end())f(Plan{l->second});
  for(I x:roots){
    invert(x,t,M,[&](I y,char op,bool inv){
      if(y>=1 && y!=t)
        if(auto l=one.find(y);l!=one.end())
          f(Plan{l->second,E{t,inv?y:x,inv?x:y,op}});
    });
  }
  // Allow the first helper to be used twice.
  if(t>1 && t%2==0){
   if(auto l=one.find(t/2);l!=one.end())f(Plan{l->second,E{t,t/2,t/2,'+'}});
  }
  I a=sqrt((long double)t);
  while((__int128)a*a<t)++a;
  if(a>1 && (__int128)a*a==t){
   if(auto l=one.find(a);l!=one.end())f(Plan{l->second,E{t,a,a,'*'}});
  }
 }
 template<class F> void pair_join(I t,F f) const{
  for(I x:ones) {
    invert(x,t,M,[&](I y,char op,bool inv){
      if(y<x || x==t || y==t)return;
      if(auto l=one.find(y);l!=one.end()){
        Plan plan={one.at(x)}; if(y!=x)plan.push_back(l->second);
        plan.push_back(E{t,inv?y:x,inv?x:y,op});f(move(plan));
      }
    });
  }
 }
 vector<Plan> solve(I t,int cap) const{
  vector<Plan> out;
  auto add=[&](Plan p){if(p.size()<size_t(cap)&&out.size()<32)out.push_back(move(p));};
  direct(t,add);
  if(!out.empty())return out;
  pair_join(t,add);
  if(!out.empty() || cap<4)return out;
  // One exact three-instruction chain: root combined with a two-step helper.
  for(I x:roots){
    if(out.size()>=24)break;
    invert(x,t,M,[&](I y,char op,bool inv){
      if(y<1||y==t)return;
      direct(y,[&](Plan p){
        if(any_of(p.begin(),p.end(),[&](const E&e){return e.v==t;}))return;
        p.push_back(E{t,inv?y:x,inv?x:y,op});add(move(p));
      });
    });
  }
  if(!out.empty())return out;
  for(I x:ones){
    if(out.size()>=24)break;
    invert(x,t,M,[&](I y,char op,bool inv){
      if(y<1||y==t||y==x)return;
      invert(x,y,M,[&](I z,char sym,bool reverse){
          if(!(c(z) || z==x))return;
          add(Plan{one.at(x),E{y,reverse?z:x,reverse?x:z,sym},E{t,inv?y:x,inv?x:y,op}});
      });
    });
  }
  if(!out.empty())return out;
  if(t%2==0)direct(t/2,[&](Plan p){
    if(any_of(p.begin(),p.end(),[&](const E&e){return e.v==t;}))return;
    p.push_back(E{t,t/2,t/2,'+'});add(move(p));
  });
  I q=sqrt((long double)t);
  while((__int128)q*q<t)++q;
  if(q>1 && (__int128)q*q==t)direct(q,[&](Plan p){
    if(any_of(p.begin(),p.end(),[&](const E&e){return e.v==t;}))return;
    p.push_back(E{t,q,q,'*'});add(move(p));
  });
  if(!out.empty() || cap<5)return out;
  // Four-op meet-in-the-middle: a two-op chunk and a one-op atom.
  // Probe inverses of each known one-step atom rather than materializing
  // the two-step closure. Each chunk is independent of the final result.
  for(I x:ones){
    if(out.size()>=16)break;
    invert(x,t,M,[&](I y,char op,bool inv){
      if(y<1 || y==x || y==t)return;
      direct(y,[&](Plan p){
        if(any_of(p.begin(),p.end(),[&](const E&e){return e.v==t;}))return;
        if(none_of(p.begin(),p.end(),[&](const E&e){return e.v==x;}))p.insert(p.begin(),one.at(x));
        p.push_back(E{t,inv?y:x,inv?x:y,op});add(move(p));
      });
    });
  }
  if(!out.empty())return out;
  // Third-step pair-join chunk plus live root.
  for(I x:roots){
    if(out.size()>=16)break;
    invert(x,t,M,[&](I y,char op,bool inv){
      if(y<1 || y==t)return;
      pair_join(y,[&](Plan p){
        if(any_of(p.begin(),p.end(),[&](const E&e){return e.v==t;}))return;
        p.push_back(E{t,inv?y:x,inv?x:y,op});add(move(p));
      });
    });
  }
  return out;
 }
};
int main() {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    constexpr I maximum = 1000000000000000000LL;
    string line;
    int number = 0;
    auto bad = [&](const char* detail) {
        cerr << "query line " << number << ": " << detail << '\n';
        return 2;
    };
    while (getline(cin, line)) {
        ++number;
        istringstream input(line);
        int index, root_count, budget;
        I limit, target;
        if (!(input >> index >> limit >> root_count >> budget) ||
            index < 0 || limit < 1 || limit > maximum ||
            root_count < 1 || root_count > 64 || budget < 1 || budget > 4096)
            return bad("invalid index, value limit, root count, or budget");
        vector<I> roots(root_count);
        for (I& root : roots)
            if (!(input >> root) || root < 1 || root > limit)
                return bad("missing or out-of-range root");
        if (!(input >> target) || target < 1 || target > limit)
            return bad("missing or out-of-range target");
        input >> ws;
        if (!input.eof()) return bad("unexpected trailing fields");
        unordered_set<I> unique(roots.begin(), roots.end());
        if (int(unique.size()) != root_count || unique.count(target))
            return bad("duplicate root or target supplied as a root");
        auto plans = Planner(move(roots), limit).solve(target, budget);
        cout << index << ' ' << plans.size() << '\n';
        for (const auto& plan : plans) {
            cout << plan.size() << '\n';
            for (const auto& edge : plan)
                cout << edge.v << ' ' << edge.op << ' ' << edge.a << ' ' << edge.b << '\n';
        }
    }
    if (!cin.eof()) {
        cerr << "input stream failed\n";
        return 2;
    }
}
