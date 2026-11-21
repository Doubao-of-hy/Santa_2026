// SPDX-License-Identifier: Apache-2.0
// Select an acyclic multi-output circuit from all known arithmetic identities.
struct JointCircuit {
    struct Recipe {int out,a,b;char op;};
    vector<Int> values;
    unordered_map<Int,int> ids;
    vector<Recipe> recipes;
    map<tuple<int,int,int,char>,int> recipe_id;
    vector<int> targets, seeds;
    vector<vector<int>> initial;
    mt19937 rng;
    struct Solution {vector<int> pick; int size=INT_MAX;};

    int index(Int x) {
        auto [i,added]=ids.emplace(x,int(values.size()));
        if(added) values.push_back(x);
        return i->second;
    }
    void add(Edge e) {
        int out=index(e.out),a=index(e.a),b=index(e.b);
        if((e.op=='+' || e.op=='*') && a>b) swap(a,b);
        if(recipe_id.emplace(make_tuple(out,a,b,e.op),int(recipes.size())).second)
            recipes.push_back({out,a,b,e.op});
    }
    JointCircuit(const Puzzle &p,const map<Int,vector<Route>> &routes,
                 const Plan &previous,unsigned seed):rng(seed) {
        for(Int s:p.starts) seeds.push_back(index(s));
        for(Int t:p.targets) targets.push_back(index(t));
        Plan current;
        for(Int v:p.order) {
            auto [a,b]=p.args.at(v);
            current.push_back({v,a,b,p.defs.at(v).op});
            add(current.back());
        }
        for(auto &[t,options]:routes) for(auto &r:options) for(auto e:r.edges) add(e);
        for(auto e:previous) add(e);
        // Pair identities and their inverses can join two otherwise unrelated
        // goal plans, even when neither input plan originally used the edge.
        vector<Int> sorted=values;
        sort(sorted.begin(),sorted.end());
        for(size_t j=0;j<sorted.size();++j) {
            Int b=sorted[j];
            for(size_t i=0;i<=j;++i) {
                Int a=sorted[i];
                if(a<=p.limit-b && ids.count(a+b)) {
                    add({a+b,a,b,'+'}); add({b,a+b,a,'-'});
                    if(a!=b) add({a,a+b,b,'-'});
                }
                if(a>1 && a<=p.limit/b && ids.count(a*b)) {
                    add({a*b,a,b,'*'}); add({b,a*b,a,'/'});
                    if(a!=b) add({a,a*b,b,'/'});
                }
            }
        }
        remember(current);
        remember(previous);
    }
    void remember(const Plan &known) {
        vector<int> pick(values.size(),-1);
        vector<bool> reached(values.size());
        for(int v:seeds) reached[v]=true;
        for(auto e:known) {
            int out=ids.at(e.out),a=ids.at(e.a),b=ids.at(e.b);
            if((e.op=='+' || e.op=='*') && a>b) swap(a,b);
            if(!reached[a] || !reached[b]) return;
            reached[out]=true;
            pick[out]=recipe_id.at({out,a,b,e.op});
        }
        if(all_of(targets.begin(),targets.end(),[&](int v){return reached[v];}))
            initial.push_back(retained(pick,targets));
    }
    vector<int> retained(const vector<int> &pick,const vector<int> &keep) const {
        vector<int> active(values.size(),-1);
        auto visit=[&](auto &self,int v)->void {
            if(active[v]>=0 || pick[v]<0) return;
            active[v]=pick[v];auto e=recipes[pick[v]];
            self(self,e.a);self(self,e.b);
        };
        for(int t:keep) visit(visit,t);
        return active;
    }
    static int count(const vector<int> &pick) {
        return count_if(pick.begin(),pick.end(),[](int i){return i>=0;});
    }
    // With an already valid circuit available at zero incremental cost,
    // strictly positive edge prices guarantee an acyclic shortest derivation.
    vector<int> derive(const vector<int> &fixed,const vector<double> &weight,
                       const vector<int> &next) const {
        constexpr double inf=1e15;
        vector<double> distance(values.size(),inf);
        vector<int> pick=fixed;
        for(int v:seeds) distance[v]=0;
        for(size_t i=0;i<fixed.size();++i) if(fixed[i]>=0) distance[i]=0;
        bool changed=true;
        while(changed) {
            changed=false;
            for(size_t i=0;i<recipes.size();++i) {
                auto e=recipes[i];
                double cost=weight[e.out]+distance[e.a]+(e.a==e.b?0:distance[e.b]);
                if(cost+1e-8<distance[e.out]) {
                    distance[e.out]=cost;pick[e.out]=int(i);changed=true;
                }
            }
        }
        vector<int> active=fixed;
        auto visit=[&](auto &self,int v)->void {
            if(active[v]>=0 || pick[v]<0) return;
            active[v]=pick[v];auto e=recipes[pick[v]];
            self(self,e.a);self(self,e.b);
        };
        for(int t:next) {
            if(distance[t]>=inf) throw runtime_error("unreachable joint target");
            visit(visit,t);
        }
        return active;
    }
    Solution search(int effort) {
        vector<int> empty(values.size(),-1);
        vector<double> prices(values.size(),1.0);
        Solution best;
        best.pick=derive(empty,prices,targets);best.size=count(best.pick);
        for(auto &known:initial) {
            int cost=count(known);
            if(cost<best.size) best={known,cost};
        }
        vector<int> order=targets;
        for(int trial=0;trial<effort;++trial) {
            shuffle(order.begin(),order.end(),rng);
            vector<int> state;
            int cut=trial<2?int(order.size()):max(1,int(order.size())*(2+trial%4)/8);
            int prefix=int(order.size())-cut;
            vector<int> kept(order.begin(),order.begin()+prefix);
            state=retained(best.pick,kept);
            for(size_t i=0;i<prices.size();++i)
                prices[i]=(best.pick[i]>=0 && trial%3!=0?.76:1.0)+double(rng()%500)/2000;
            for(int i=prefix;i<int(order.size());++i) state=derive(state,prices,{order[i]});
            // Remove a whole target's private cone, then allow paths to use
            // values already supplied by all the other roots at zero cost.
            for(int i=0;i<int(order.size());++i) {
                vector<int> others=order;
                others.erase(others.begin()+i);
                auto rest=retained(state,others);
                auto candidate=derive(rest,prices,{order[i]});
                if(count(candidate)<=count(state)) state=move(candidate);
            }
            int size=count(state);
            if(size<best.size || (size==best.size && trial%2==0))
                best={move(state),size};
        }
        return best;
    }
    Plan export_plan(const Solution &solution) const {
        Plan result;
        vector<bool> visited(values.size());
        auto visit=[&](auto &self,int v)->void {
            if(visited[v] || solution.pick[v]<0) return;
            visited[v]=true;auto e=recipes[solution.pick[v]];
            self(self,e.a);self(self,e.b);
            result.push_back({values[v],values[e.a],values[e.b],e.op});
        };
        for(int t:targets) visit(visit,t);
        return result;
    }
};
