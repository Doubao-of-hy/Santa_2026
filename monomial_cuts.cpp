// Jointly rebuild the exits of multiplicative regions using normalized ratios.
// The second argument sets the number of new integers. Zero is the control.
#define main cut_set_driver
#include "generative/cut_set.cpp"
#undef main
#include <unordered_map>
#include <tuple>
#include <string>
using Int = long long;
struct NumericStep { Int v, a, b; char op; };

template<class F> void equations(Int a, Int b, Int cap, F emit) {
    if (a > b) swap(a,b);
    if (a <= cap-b) emit(a+b,'+',a,b);
    if (a < b) emit(b-a,'-',b,a);
    if (a <= cap/b) emit(a*b,'*',a,b);
    if (b%a == 0) emit(b/a,'/',b,a);
}

int main(int argc,char** argv) {
    if (argc < 3) return 2;
    int trials=stoi(argv[1]), width=stoi(argv[2]);
    int visits=argc>3 && stoi(argv[3])>0 ? stoi(argv[3]) : 100;
    string name; Int cap; int ns,nt,nr;
    if (!(cin>>name>>cap>>ns>>nt>>nr)) return 2;
    vector<Int> seeds(ns),targets(nt),values;
    unordered_map<Int,int> ids;
    auto append=[&](Int x) {
        if (ids.emplace(x,int(values.size())).second) values.push_back(x);
    };
    for (auto& x:seeds) { cin>>x; append(x); }
    for (auto& x:targets) cin>>x;
    vector<NumericStep> old(nr);
    for (auto& e:old) { cin>>e.v>>e.op>>e.a>>e.b; append(e.v); }
    if (!cin) return 3;
    int core=values.size();
    vector<int> kind(core),isTarget(core),isSeed(core);
    vector<vector<int>> children(core);
    for (Int x:targets) isTarget.at(ids.at(x))=1;
    for (Int x:seeds) isSeed.at(ids.at(x))=1;
    for (int i=0;i<nr;i++) {
        auto e=old[i]; int v=ids.at(e.v),a=ids.at(e.a),b=ids.at(e.b);
        kind[v]=e.op=='*'||e.op=='/';
        children[a].push_back(v);
        if (a!=b) children[b].push_back(v);
    }
    unordered_map<Int,int> votes;
    auto vote=[&](Int h,int count) {
        if (width>0 && h>1 && !ids.count(h)) votes[h]+=count;
    };
    map<pair<Int,Int>,vector<Int>> scales;
    map<vector<int>,double> cuts;
    auto offer=[&](vector<int> group,double score) {
        sort(group.begin(),group.end());
        group.erase(unique(group.begin(),group.end()),group.end());
        if (group.empty() || group.size()>7) return;
        for (int x:group) if (isSeed[x]) return;
        auto [it,ok]=cuts.emplace(group,score);
        if (!ok) it->second=max(it->second,score);
    };
    for (int i=0;i<core;i++) for (int j=0;j<i;j++) {
        Int a=values[i],b=values[j],g=gcd(a,b);
        if (g<2) continue;
        Int u=a/g,v=b/g;
        int weight=1+2*(kind[i]+kind[j])+2*(isTarget[i]+isTarget[j]);
        vote(g,weight); vote(u,weight); vote(v,weight);
        if (u<=cap/b && u>1 && v>1 && (kind[i]||isTarget[i]) && (kind[j]||isTarget[j]))
            vote(u*b,weight/2+1);
        if (u>1 && v>1 && (kind[i]||isTarget[i]) && (kind[j]||isTarget[j]))
            scales[minmax(u,v)].push_back(g);
        if (!isSeed[i]&&!isSeed[j] && (kind[i]||kind[j])) {
            int existing=ids.count(u)+ids.count(v)+ids.count(g);
            if (u>1 && v>1 && g>=3)
                offer({i,j},30+4*existing+2*(isTarget[i]+isTarget[j])+2*(kind[i]+kind[j]));
        }
    }
    for (const auto& [ratio,gs]:scales) {
        if (gs.size()<2) continue;
        int weight=12+min(80,6*int(gs.size()));
        vote(ratio.first,weight); vote(ratio.second,weight);
        vector<int> exits;
        for (auto g:gs) {
            vote(g,weight);
            int a=ids.at(g*ratio.first),b=ids.at(g*ratio.second);
            offer({a,b},60+min(10,int(gs.size())));
            if (!isSeed[a]&&!isSeed[b]) { exits.push_back(a); exits.push_back(b); }
        }
        if (exits.size()<=6) offer(exits,75);
    }
    // Trace connected product/division subgraphs downward to their consumers.
    // An addition or subtraction can be an exit at which rescaling cancels.
    for (int i=0;i<core;i++) if (kind[i]) {
        vector<int> frontier{i},finished;
        for (int layer=0;layer<4 && !frontier.empty();layer++) {
            vector<int> next;
            for (int x:frontier) {
                if (isTarget[x]||children[x].empty()) finished.push_back(x);
                for (int y:children[x]) {
                    if (kind[y]) next.push_back(y); else finished.push_back(y);
                }
            }
            sort(next.begin(),next.end()); next.erase(unique(next.begin(),next.end()),next.end());
            sort(finished.begin(),finished.end()); finished.erase(unique(finished.begin(),finished.end()),finished.end());
            vector<int> rim=finished; rim.insert(rim.end(),next.begin(),next.end());
            if (!rim.empty() && rim.size()<=7)
                offer(rim,62+3*min(3,int(rim.size()))+layer);
            if (rim.size()>10) break;
            frontier=move(next);
        }
    }
    if (width>0) {
        unordered_set<Int> reachable;
        for (int i=0;i<core;i++) for (int j=0;j<=i;j++)
            equations(values[i],values[j],cap,[&](Int x,char,Int,Int){if (votes.count(x)) reachable.insert(x);});
        vector<pair<double,Int>> ranked;
        for (auto [x,v]:votes) ranked.emplace_back(v*(reachable.count(x)?2.5:1.),x);
        sort(ranked.rbegin(),ranked.rend());
        for (int i=0;i<min(width,int(ranked.size()));i++) append(ranked[i].second);
    }
    Solver s(values.size(),41993); s.maxVisits=visits;
    for (auto v:seeds) { int x=ids.at(v);s.isSeed[x]=true;s.seeds.push_back(x); }
    for (auto v:targets) s.targets.push_back(ids.at(v));
    vector<NumericStep> bank;
    auto add=[&](Int v,char op,Int a,Int b) {
        s.add(ids.at(v),ids.at(a),ids.at(b));bank.push_back({v,a,b,op});
    };
    for (auto e:old) { s.base[ids.at(e.v)]=bank.size(); add(e.v,e.op,e.a,e.b); }
    for (size_t i=0;i<values.size();i++) for (size_t j=0;j<=i;j++)
        equations(values[i],values[j],cap,[&](Int x,char op,Int a,Int b) {
            if (x!=a && x!=b && ids.count(x) && !s.isSeed[ids.at(x)]) add(x,op,a,b);
        });
    vector<pair<double,vector<int>>> rankedCuts;
    for (const auto& [g,score]:cuts) rankedCuts.emplace_back(score+(s.rng()%1000)/1000.,g);
    sort(rankedCuts.rbegin(),rankedCuts.rend());
    auto live=s.trace(s.base);
    int tested=0,nontrivial=0;
    for (const auto& entry:rankedCuts) {
        const auto& holes=entry.second;
        // Elites can change the active graph. Only test existing cut values.
        vector<unsigned char> present(values.size());
        for (int e:live) present[s.edges[e].dst]=1;
        if (any_of(holes.begin(),holes.end(),[&](int h){return !present[h];})) continue;
        s.visits=0;
        if (s.test(holes,live)) live=s.elites.back();
        ++tested;
        if (s.visits>0 && ++nontrivial>=trials) break;
        if (tested>=trials*12) break;
    }
    cout<<name<<" "<<values.size()-core<<" "<<tested<<" "<<nontrivial<<" "<<s.elites.size()<<"\n";
    for (auto& list:s.elites) {
        cout<<list.size()<<"\n";
        for (int id:list) { auto e=bank[id]; cout<<e.v<<" "<<e.op<<" "<<e.a<<" "<<e.b<<"\n"; }
    }
}
