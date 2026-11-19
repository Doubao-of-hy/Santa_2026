// SPDX-License-Identifier: Apache-2.0
// Original implementation for Santa 2026. See SOURCES.md for conceptual attribution.
#include <bits/stdc++.h>
using namespace std;
using I = int64_t;
struct Recipe { I value; int left=-1, right=-1; char op=0; int cost=0; };
I calc(char op,I x,I y) {
    if(op=='+') return x+y;
    if(op=='-') return x-y;
    if(op=='/') { if(x%y) throw runtime_error("division"); return x/y; }
    return x*y;
}
struct Graph {
    I limit; vector<Recipe> nodes; unordered_map<I,int> at; vector<int> seeds, goals, palette;
    int add(I v,int a=-1,int b=-1,char op=0) {
        if(v<=0 || v>limit) throw runtime_error("range");
        auto it=at.find(v); if(it!=at.end()) return it->second;
        int n=nodes.size(); nodes.push_back({v,a,b,op,op?1+nodes[a].cost+nodes[b].cost:0});
        nodes.back().cost=min(nodes.back().cost,1000); at[v]=n; return n;
    }
    int make(char op,int a,int b) { return add(calc(op,nodes[a].value,nodes[b].value),a,b,op); }
    int binary(I v) {
        if(at.count(v)) return at[v];
        if(v==1) return make('/',seeds[0],seeds[0]);
        int h=binary(v/2), d=make('+',h,h);
        return v%2 ? make('+',d,binary(1)) : d;
    }
    int power(int k) {
        I v=I(1)<<k; if(at.count(v)) return at[v];
        if(k<2) return binary(v);
        int a=power(k/2), b=power(k-k/2); return make('*',a,b);
    }
    void initialize(int style) {
        palette.push_back(binary(1));
        vector<int> exps={1,2,3,4,5,6,7,8,10,12,16,20,24,32,40,48};
        if(style==1) exps={1,2,3,4,6,8,9,12,16,18,24,27,32,36,48,54};
        for(int k:exps) if((I(1)<<k)<=limit) palette.push_back(power(k));
        for(int v:{3,5,7,9,11,13,15,17,19,23,31}) if(v<=limit) palette.push_back(binary(v));
    }
};
// Generation-stamped open addressing, deterministic and cleared without reallocating.
struct Table {
    vector<I> keys; vector<int> vals; vector<unsigned> stamp; unsigned generation=1;
    size_t mask;
    Table(int bits):keys(size_t(1)<<bits),vals(keys.size()),stamp(keys.size()),mask(keys.size()-1){}
    size_t hash(I v) const {
        uint64_t z=v; z^=z>>30; z*=0xbf58476d1ce4e5b9ULL;
        z^=z>>27; z*=0x94d049bb133111ebULL; return (z^(z>>31))&mask;
    }
    int get(I v) const {
        size_t j=hash(v);
        while(stamp[j]==generation) { if(keys[j]==v) return vals[j]; j=(j+1)&mask; }
        return -1;
    }
    bool put(I v,int idx) {
        size_t j=hash(v);
        while(stamp[j]==generation) { if(keys[j]==v) return false; j=(j+1)&mask; }
        stamp[j]=generation; keys[j]=v; vals[j]=idx; return true;
    }
    void clear(){generation++;}
};
struct Dictionary {
    I limit; Table table; vector<Recipe> items; int free_count,one_count;
    array<vector<pair<I,int>>,3> ordered;
    Dictionary(I lim,int bits):limit(lim),table(bits){}
    void insert(I v,int a,int b,char op,int cost) {
        if(v<=0 || v>limit || items.size()>table.mask*0.75) return;
        if(table.put(v,items.size())) items.push_back({v,a,b,op,cost});
    }
    void pair_ops(int i,int j,int c) {
        I x=items[i].value,y=items[j].value;
        insert(x+y,i,j,'+',c);
        if(x>y) insert(x-y,i,j,'-',c); else if(y>x) insert(y-x,j,i,'-',c);
        if(x<=limit/y) insert(x*y,i,j,'*',c);
        if(x%y==0) insert(x/y,i,j,'/',c);
        if(y%x==0) insert(y/x,j,i,'/',c);
    }
    void build(Graph &g,vector<int> leaves) {
        table.clear(); items.clear(); for(auto &o:ordered)o.clear();
        for(int j:leaves) insert(g.nodes[j].value,j,-1,0,0);
        free_count=items.size();
        for(int i=0;i<free_count;i++) for(int j=0;j<=i;j++) pair_ops(i,j,1);
        one_count=items.size();
        for(int i=free_count;i<one_count;i++) for(int j=0;j<free_count;j++) pair_ops(i,j,2);
        for(int i=0;i<(int)items.size();i++) ordered[items[i].cost].push_back({items[i].value,i});
        for(auto &o:ordered) sort(o.begin(),o.end());
    }
    int realize(int i,Graph &g) {
        Recipe r=items[i]; auto it=g.at.find(r.value); if(it!=g.at.end())return it->second;
        int a=realize(r.left,g),b=realize(r.right,g); return g.make(r.op,a,b);
    }
};
struct Step { I residue; int cost,parent,factor,offset; char op; double priority; };
struct Planner {
    Dictionary &d; int width; double weight; vector<Step> states, pending;
    int best=10000,last=-1,terminal=-1; unordered_map<I,int> seen;
    Planner(Dictionary &dict,int w,double h):d(dict),width(w),weight(h){}
    void propose(int parent,I v,int factor,int offset,char op) {
        if(v<1 || v>d.limit)return;
        int c=states[parent].cost+(factor<0?0:1+d.items[factor].cost)+(offset<0?0:1+d.items[offset].cost);
        if(c>=best)return;
        int end=d.table.get(v);
        Step s{v,c,parent,factor,offset,op,c+weight*log2(double(v))};
        if(end>=0) {
            if(c+d.items[end].cost<best) {best=c+d.items[end].cost; last=states.size(); terminal=end; states.push_back(s);}
            return;
        }
        if(c+3>=best || v>=states[parent].residue)return;
        auto it=seen.find(v); if(it!=seen.end() && it->second<=c)return;
        if((int)pending.size()>=width && s.priority>=pending.back().priority)return;
        for(auto j=pending.begin();j!=pending.end();++j) if(j->residue==v) {
            if(j->cost<=c)return; pending.erase(j); break;
        }
        auto j=lower_bound(pending.begin(),pending.end(),s,[](const Step&a,const Step&b){return a.priority<b.priority;});
        pending.insert(j,s); if((int)pending.size()>width)pending.pop_back();
    }
    void expand(int p) {
        I t=states[p].residue;
        for(auto &o:d.ordered) {
            int k=lower_bound(o.begin(),o.end(),make_pair(t,-1))-o.begin();
            for(int j=max(0,k-3);j<min((int)o.size(),k+3);j++)
                propose(p,abs(t-o[j].first),-1,o[j].second,t>o[j].first?'+':'R');
        }
        for(int i=0;i<d.one_count;i++) {
            I a=d.items[i].value; if(a<=1)continue;
            I diff=abs(t-a);
            if(diff && d.table.get(diff)>=0) propose(p,diff,-1,i,t>a?'+':'R');
            if(t+a<=d.limit && d.table.get(t+a)>=0)propose(p,t+a,-1,i,'-');
            // A power-of-two cofactor after an additive correction is especially cheap.
            for(int mode=0;mode<2;mode++) {
                I v=mode?t+a:diff;
                if(!v || v>d.limit || (v&31))continue;
                int k=__builtin_ctzll(v);
                for(;k>=5;k--) {
                    int f=d.table.get(I(1)<<k);
                    if(f>=0) {propose(p,v>>k,f,i,mode?'-':(t>a?'+':'R'));break;}
                }
            }
            if(a>=t)continue;
            I q=t/a,r=t%a;
            if(!r) {propose(p,q,i,-1,'+');continue;}
            int rid=d.table.get(r);
            if(rid>=0)propose(p,q,i,rid,'+');
            if(a-r<=d.limit-t) {rid=d.table.get(a-r);if(rid>=0)propose(p,q+1,i,rid,'-');}
        }
    }
    void search(I target) {
        states.push_back({target,0,-1,-1,-1,'+',0});
        int idx=d.table.get(target);
        if(idx>=0) {best=d.items[idx].cost;last=0;terminal=idx;return;}
        vector<int> frontier={0};
        for(int depth=0;depth<18 && !frontier.empty();depth++) {
            pending.clear();
            for(int p:frontier) if(states[p].cost+3<best)expand(p);
            frontier.clear();
            for(auto s:pending) if(s.cost+3<best) {
                seen[s.residue]=s.cost;frontier.push_back(states.size());states.push_back(s);
            }
        }
    }
    int emit(Graph &g) {
        int value=d.realize(terminal,g);
        for(int p=last;states[p].parent>=0;p=states[p].parent) {
            auto s=states[p];
            if(s.factor>=0)value=g.make('*',value,d.realize(s.factor,g));
            if(s.offset>=0) {
                int offset=d.realize(s.offset,g);
                value=s.op=='R'?g.make('-',offset,value):g.make(s.op,value,offset);
            }
        }
        return value;
    }
};
vector<array<int,4>> allocate(Graph &g,vector<int> goals,int mode) {
    int n=g.nodes.size(); vector<bool> ready(n); for(int s:g.seeds)ready[s]=true;
    vector<int> schedule;
    function<void(int)> dfs=[&](int v){if(ready[v])return;ready[v]=true;auto r=g.nodes[v];dfs(r.left);dfs(r.right);schedule.push_back(v);};
    for(int t:goals)dfs(t);
    vector<vector<int>> uses(n);
    for(int i=(int)schedule.size()-1;i>=0;i--) {auto r=g.nodes[schedule[i]];uses[r.left].push_back(i);if(r.right!=r.left)uses[r.right].push_back(i);}
    vector<int> bank(48,-1),location(n,-1); vector<bool> seed(n);
    for(int i=0;i<(int)g.seeds.size();i++){bank[i]=g.seeds[i];location[g.seeds[i]]=i;seed[g.seeds[i]]=true;}
    vector<array<int,4>> out; int now=0;
    function<int(int,uint64_t)> ensure=[&](int v,uint64_t lock)->int {
        if(location[v]>=0)return location[v];
        auto r=g.nodes[v];
        int a=ensure(r.left,lock),b=ensure(r.right,lock|(1ULL<<a));
        int dest=-1; double highest=-1;
        for(int k=0;k<48;k++) {
            if((lock>>k)&1)continue;
            int old=bank[k];if(old<0){dest=k;break;}if(seed[old])continue;
            double dist=uses[old].empty()?1e12:1+max(0,uses[old].back()-now);
            double expense=mode?pow(1.+min(20,g.nodes[old].cost),1.5):1.;
            double priority=dist/expense;
            if(priority>highest){highest=priority;dest=k;}
        }
        if(dest<0)throw runtime_error("register pressure");
        if(bank[dest]>=0)location[bank[dest]]=-1;
        bank[dest]=v;location[v]=dest;out.push_back({r.op,a,b,dest});return dest;
    };
    for(int v:schedule) {
        auto r=g.nodes[v];uses[r.left].pop_back();if(r.right!=r.left)uses[r.right].pop_back();
        ensure(v,0);now++;
    }
    return out;
}
int main(int argc,char**argv) {
    int width=argc>1?stoi(argv[1]):4, leaves_max=argc>2?stoi(argv[2]):72;
    double alpha=argc>3?stod(argv[3]):.18;int style=argc>4?stoi(argv[4]):0;
    int ordering=argc>5?stoi(argv[5]):0;
    string id; I lim;int ns,nt;
    while(cin>>id>>lim>>ns>>nt) {
        Graph g;g.limit=lim;
        for(int i=0;i<ns;i++){I v;cin>>v;g.seeds.push_back(g.add(v));}
        vector<I> targets(nt);for(I &v:targets)cin>>v;
        if(ordering==1)reverse(targets.begin(),targets.end());
        if(ordering>=2){mt19937 rng(ordering);shuffle(targets.begin(),targets.end(),rng);}
        g.initialize(style); Dictionary dict(lim,leaves_max>96?23:22);
        for(I t:targets) {
            if(!g.at.count(t)) {
                vector<int> leaves; unordered_set<int> added;
                auto add=[&](int v){if(added.insert(v).second)leaves.push_back(v);};
                for(int s:g.seeds)add(s);for(int p:g.palette)add(p);
                for(auto j=g.goals.rbegin();j!=g.goals.rend() && (int)leaves.size()<leaves_max*3/4;j++)add(*j);
                for(int j=g.nodes.size()-1;j>=0 && (int)leaves.size()<leaves_max;j--)add(j);
                dict.build(g,leaves);Planner planner(dict,width,alpha);planner.search(t);
                int idx=planner.last<0?g.binary(t):planner.emit(g);
                if(g.nodes[idx].value!=t)throw runtime_error("reconstruction");
            }
            g.goals.push_back(g.at[t]);
        }
        auto best=allocate(g,g.goals,0);
        for(int mode=1;mode<=2;mode++) {
            vector<int> goals=g.goals;if(mode==2)reverse(goals.begin(),goals.end());
            auto v=allocate(g,goals,1);if(v.size()<best.size())best=v;
        }
        cout<<id<<" [";
        for(int i=0;i<(int)best.size();i++){if(i)cout<<',';auto r=best[i];cout<<"[\""<<char(r[0])<<"\","<<r[1]<<','<<r[2]<<','<<r[3]<<']';}
        cout<<"]"<<endl;
    }
}
