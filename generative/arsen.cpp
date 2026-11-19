// SPDX-License-Identifier: Apache-2.0
// Original graph simplification and scheduling extension; conceptual sources in SOURCES.md.
// Local modification: optionally rank unresolved targets cheaply before the full-width search.
#define main historical_main
#include "recovered/solver.cpp"
#undef main

int reachable(Graph &g, vector<char> *out=nullptr) {
    vector<char> live(g.nodes.size()); int count=0;
    function<void(int)> visit=[&](int i) {
        if(live[i])return; live[i]=1;
        auto r=g.nodes[i]; if(r.op) {++count;visit(r.left);visit(r.right);}
    };
    for(int t:g.goals)visit(t);
    if(out)*out=move(live); return count;
}

// Enumerate legal, acyclic one-instruction alternatives on the graph's own values.
// Judge changes by total reachable graph size, not expression-tree cost.
void simplify(Graph &g) {
    int n=g.nodes.size(); vector<vector<Recipe>> options(n);
    for(int k=0;k<n;k++) if(g.nodes[k].op) {
        I v=g.nodes[k].value;
        auto put=[&](char op,int a,I b) {
            auto it=g.at.find(b);if(it==g.at.end()||it->second>=k)return;
            options[k].push_back({v,a,it->second,op,0});
        };
        for(int a=0;a<k;a++) {
            I x=g.nodes[a].value;
            if(v>x)put('+',a,v-x);
            if(x>v)put('-',a,x-v);
            if(v%x==0)put('*',a,v/x);
            if(x%v==0)put('/',a,x/v);
        }
    }
    int score=reachable(g);
    for(int pass=0;pass<4;pass++) {
        bool changed=false; vector<char> live;reachable(g,&live);
        for(int k=n-1;k>=0;k--) if(live[k]&&g.nodes[k].op) {
            Recipe old=g.nodes[k],best=old;
            for(auto alt:options[k]) {
                if(alt.left==old.left&&alt.right==old.right&&alt.op==old.op)continue;
                // Newly required ancestors can be useful, but cannot contain k.
                g.nodes[k]=alt; int s=reachable(g);
                if(s<score) {score=s;best=alt;changed=true;}
            }
            g.nodes[k]=best;
        }
        if(!changed)break;
    }
    // Refresh rebuilding costs after rewrites, with repeated operands counted once.
    for(auto &r:g.nodes)if(r.op)r.cost=min(1000,1+g.nodes[r.left].cost+(r.left==r.right?0:g.nodes[r.right].cost));
}

vector<array<int,4>> schedule_best(Graph &g,int trials) {
    auto best=allocate(g,g.goals,0); mt19937 rng(20261118);
    auto order=g.goals;
    for(int i=0;i<trials;i++) {
        if(i==0)order=g.goals;
        else if(i==1)reverse(order.begin(),order.end());
        else shuffle(order.begin(),order.end(),rng);
        auto p=allocate(g,order,1);
        if(p.size()<best.size())best=move(p);
    }
    return best;
}

pair<int,unique_ptr<Planner>> shortlist_target(Graph &graph, Dictionary &dictionary,
                                              const vector<I> &targets, int width,
                                              double alpha, int shortlist_size) {
    int direct = -1, direct_cost = 3;
    for (int index = 0; index < int(targets.size()); ++index) {
        I target = targets[index];
        if (graph.at.count(target))
            return {index, nullptr};
        int expression = dictionary.table.get(target);
        if (expression >= 0 && dictionary.items[expression].cost < direct_cost) {
            direct = index;
            direct_cost = dictionary.items[expression].cost;
        }
    }
    if (direct >= 0) {
        auto plan = make_unique<Planner>(dictionary, width, alpha);
        plan->search(targets[direct]);
        return {direct, move(plan)};
    }
    vector<pair<int,int>> ranked;
    for (int index = 0; index < int(targets.size()); ++index) {
        Planner coarse(dictionary, 1, alpha);
        coarse.search(targets[index]);
        ranked.emplace_back(coarse.best, index);
    }
    sort(ranked.begin(), ranked.end());
    ranked.resize(min(int(ranked.size()), shortlist_size));
    int winner = ranked.front().second;
    unique_ptr<Planner> best;
    for (auto [estimate, index] : ranked) {
        auto plan = make_unique<Planner>(dictionary, width, alpha);
        plan->search(targets[index]);
        if (!best || make_pair(plan->best, index) < make_pair(best->best, winner)) {
            winner = index;
            best = move(plan);
        }
    }
    return {winner, move(best)};
}

int main(int argc,char**argv) {
    int width=argc>1?stoi(argv[1]):6, leafmax=argc>2?stoi(argv[2]):96;
    double alpha=argc>3?stod(argv[3]):.18;
    int style=argc>4?stoi(argv[4]):0, ordering=argc>5?stoi(argv[5]):0;
    int trials=argc>6?stoi(argv[6]):32;
    bool trace_mode=argc>7&&stoi(argv[7]);
    string id;I lim;int ns,nt;
    while(cin>>id>>lim>>ns>>nt) {
        Graph g;g.limit=lim;
        for(int i=0;i<ns;i++){I v;cin>>v;g.seeds.push_back(g.add(v));}
        vector<I> targets(nt);for(I &v:targets)cin>>v;
        if(trace_mode) {
            int count;cin>>count;vector<int> bank(48,-1);
            for(int i=0;i<ns;i++)bank[i]=g.seeds[i];
            for(int i=0;i<count;i++) {
                char op;int a,b,d;cin>>op>>a>>b>>d;
                bank[d]=g.make(op,bank[a],bank[b]);
            }
            for(I t:targets)g.goals.push_back(g.at.at(t));
        } else {
            if(ordering==1)reverse(targets.begin(),targets.end());
            if(ordering>=2&&ordering<100){mt19937 rng(ordering);shuffle(targets.begin(),targets.end(),rng);}
            g.initialize(style);Dictionary dict(lim,leafmax>96?23:22);
            while(!targets.empty()) {
                vector<int> leaves;unordered_set<int> added;
                auto add=[&](int i){if(added.insert(i).second)leaves.push_back(i);};
                for(int s:g.seeds)add(s);for(int p:g.palette)add(p);
                for(auto j=g.goals.rbegin();j!=g.goals.rend()&&(int)leaves.size()<leafmax*3/4;j++)add(*j);
                for(int j=g.nodes.size()-1;j>=0&&(int)leaves.size()<leafmax;j--)add(j);
                dict.build(g,leaves);
                int chosen=0; unique_ptr<Planner> best;
                int upto=ordering>=100?targets.size():1;
                if (ordering > 100) {
                    auto result = shortlist_target(g, dict, targets, width, alpha, ordering - 100);
                    chosen = result.first;
                    best = move(result.second);
                } else {
                    int bestcost=1000000;
                    for(int i=0;i<upto;i++) {
                        if(g.at.count(targets[i])) {chosen=i;best.reset();break;}
                        auto p=make_unique<Planner>(dict,width,alpha);p->search(targets[i]);
                        int cost=p->best;
                        // Prefer shorter estimates, stable deterministic ties in target order.
                        if(cost<bestcost){bestcost=cost;chosen=i;best=move(p);}
                    }
                }
                I t=targets[chosen];
                if(!g.at.count(t)) {
                    int idx=best&&best->last>=0?best->emit(g):g.binary(t);
                    if(g.nodes[idx].value!=t)throw runtime_error("reconstruction");
                }
                g.goals.push_back(g.at.at(t));targets.erase(targets.begin()+chosen);
            }
        }
        auto best=schedule_best(g,trials);simplify(g);auto alt=schedule_best(g,trials);
        if(alt.size()<best.size())best=move(alt);
        cout<<id<<" [";
        for(int i=0;i<(int)best.size();i++){if(i)cout<<',';auto r=best[i];cout<<"[\""<<char(r[0])<<"\","<<r[1]<<','<<r[2]<<','<<r[3]<<']';}
        cout<<"]"<<endl;
    }
}
