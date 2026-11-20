// Find a minimum-cost arithmetic arborescence in a restricted graph where
// every transition uses one paid constant. Terminal subsets may share any prefix.
#include <algorithm>
#include <cstdint>
#include <iostream>
#include <limits>
#include <queue>
#include <unordered_map>
#include <unordered_set>
#include <vector>
using I = std::int64_t;
using namespace std;

struct Recipe { I value, left, right; char op; };
template<class F> void inverse(I t, I b, I cap, F emit) {
    if (t > b) emit(t-b, Recipe{t,t-b,b,'+'});
    if (b > t) emit(b-t, Recipe{t,b,b-t,'-'});
    if (t <= cap-b) emit(t+b, Recipe{t,t+b,b,'-'});
    if (t%b == 0) emit(t/b, Recipe{t,t/b,b,'*'});
    if (t <= cap/b) emit(t*b, Recipe{t,t*b,b,'/'});
    if (b%t == 0) emit(b/t, Recipe{t,b,b/t,'/'});
}
template<class F> void forward(I a, I b, I cap, F emit) {
    if (a < b) swap(a,b);
    if (a <= cap-b) emit(Recipe{a+b,a,b,'+'});
    if (a > b) emit(Recipe{a-b,a,b,'-'});
    if (a <= cap/b) emit(Recipe{a*b,a,b,'*'});
    if (a%b == 0) emit(Recipe{a/b,a,b,'/'});
}
struct Edge { int from, to, cost; Recipe recipe; };
struct Result {int price; vector<Recipe> patch;};
constexpr int INF = 1000000;

Result solve(I cap, const vector<I>& anchors, const vector<I>& generators,
             const vector<I>& goals, const unordered_map<I,int>& oldCost) {
    unordered_set<I> free(anchors.begin(),anchors.end());
    unordered_map<I,Recipe> first;
    for (int i=0; i<int(anchors.size()); ++i) for (int j=0; j<=i; ++j)
        forward(anchors[i],anchors[j],cap,[&](Recipe s){first.emplace(s.value,s);});
    unordered_set<I> core(goals.begin(),goals.end());
    for (auto e:oldCost) core.insert(e.first);
    unordered_map<I,int> support;
    for (int i=0; i<int(goals.size()); ++i) {
        unordered_set<I> near;
        for (I b: generators)
            inverse(goals[i],b,cap,[&](I v,Recipe){if (v!=goals[i]) near.insert(v);});
        core.insert(near.begin(),near.end());
        for (I x:near) for (I b:generators)
            inverse(x,b,cap,[&](I v,Recipe){if (v!=x) support[v] |= 1<<i;});
    }
    for (auto e:support)
        if ((e.second & (e.second-1)) || first.count(e.first)) core.insert(e.first);

    unordered_map<I,int> ids;
    vector<I> numbers{0}; // vertex zero represents the paid input dictionary
    auto id=[&](I x) {
        auto row=ids.emplace(x,int(numbers.size()));
        if (row.second) numbers.push_back(x);
        return row.first->second;
    };
    vector<Edge> edges;
    for (I t:core) {
        int dest=id(t);
        if (free.count(t)) continue;
        for (I b:generators) inverse(t,b,cap,[&](I v,Recipe r){
            if (v!=t && (core.count(v)||first.count(v)||free.count(v)))
                edges.push_back({id(v),dest,1,r});
        });
    }
    for (int v=1; v<int(numbers.size()); ++v) {
        I t=numbers[v];
        if (free.count(t)) edges.push_back({0,v,0,{}});
        else if (first.count(t)) edges.push_back({0,v,1,first.at(t)});
        else if (oldCost.count(t)) edges.push_back({0,v,oldCost.at(t),{}});
    }
    int n=int(numbers.size()), full=(1<<goals.size())-1;
    vector<vector<int>> entering(n);
    for (int i=0; i<int(edges.size()); ++i) entering[edges[i].to].push_back(i);
    vector<vector<int>> cost(full+1,vector<int>(n,INF)), choice(full+1,vector<int>(n,0));
    for (int i=0; i<int(goals.size()); ++i) cost[1<<i][ids.at(goals[i])]=0;
    using Item=pair<int,int>;
    for (int mask=1; mask<=full; ++mask) {
        for (int a=(mask-1)&mask; a; a=(a-1)&mask) {
            int b=mask^a;
            if (a>b) continue;
            for (int v=0; v<n; ++v) {
                int c=cost[a][v]+cost[b][v];
                if (c<cost[mask][v]) {cost[mask][v]=c;choice[mask][v]=-a;}
            }
        }
        priority_queue<Item,vector<Item>,greater<Item>> todo;
        for (int v=0; v<n; ++v) if (cost[mask][v]<INF) todo.push({cost[mask][v],v});
        while (!todo.empty()) {
            auto [dist,v]=todo.top();todo.pop();
            if (dist!=cost[mask][v]) continue;
            for (int index:entering[v]) {
                auto& e=edges[index];int c=dist+e.cost;
                if (c<cost[mask][e.from]) {
                    cost[mask][e.from]=c;choice[mask][e.from]=index+1;
                    todo.push({c,e.from});
                }
            }
        }
    }
    Result out{cost[full][0],{}};
    vector<pair<int,int>> stack{{full,0}};
    while (!stack.empty()) {
        auto [mask,v]=stack.back();stack.pop_back();
        int decision=choice[mask][v];
        if (decision<0) {
            int a=-decision;stack.push_back({a,v});stack.push_back({mask^a,v});
        } else if (decision>0) {
            auto& e=edges[decision-1];if(e.recipe.op) out.patch.push_back(e.recipe);
            stack.push_back({mask,e.to});
        }
    }
    return out;
}
int main() {
    ios::sync_with_stdio(false);cin.tie(nullptr);
    I cap;int na,nc,nt,no;
    while (cin>>cap>>na>>nc>>nt>>no) {
        if (nt<1 || nt>7) return 2;
        vector<I> anchors(na),generators(nc),targets(nt);
        for (I& x:anchors) cin>>x;
        for (I& x:generators) cin>>x;
        for (I& x:targets) cin>>x;
        unordered_map<I,int> old;
        for (int i=0;i<no;i++) {I v;int cost;cin>>v>>cost;old[v]=cost;}
        auto out=solve(cap,anchors,generators,targets,old);
        cout<<out.price<<' '<<out.patch.size()<<'\n';
        for (auto r:out.patch) cout<<r.value<<' '<<r.op<<' '<<r.left<<' '<<r.right<<'\n';
    }
}
