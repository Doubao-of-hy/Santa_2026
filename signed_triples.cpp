// Enumerate all three-term signed sums over a paid dictionary and its one-step
// neighbors. For each difference or sum inspect the less populated interval.
#define main offset_engine_main
#include "offset_closure.cpp"
#undef main
#include <array>

struct Term { I v; int sign; };
struct TripleSearch {
    I cap,target;
    int budget,max_answers;
    unordered_map<I,Step> atom;
    unordered_set<I> paid;
    vector<I> vals;
    vector<vector<Step>> answers;
    unsigned long long inspected=0;
    unordered_set<string> distinct;
    bool done() const {return int(answers.size())>=max_answers;}
    void emit(array<Term,3> terms) {
        for (int i=0;i<3 && !done();++i) {
            auto x=terms[i], y=terms[(i+1)%3], z=terms[(i+2)%3];
            I signed_mid=x.sign*x.v+y.sign*y.v, mid=abs(signed_mid);
            if (!mid || mid>cap || signed_mid+z.sign*z.v!=target) continue;
            Step joined{x.sign==y.sign?x.v+y.v:abs(x.v-y.v),x.v,y.v,'+'};
            if (x.sign!=y.sign) {joined.a=max(x.v,y.v);joined.b=min(x.v,y.v);joined.op='-';}
            Step last{target,mid,z.v,'+'};
            if ((signed_mid>0)!=(z.sign>0)) {
                last.a=max(mid,z.v);last.b=min(mid,z.v);last.op='-';
            }
            if (target==mid || target==z.v) continue;
            vector<Step> patch; unordered_set<I> known;
            auto buy=[&](I v) {
                if (paid.count(v)||known.count(v))return;
                auto s=atom.at(v);patch.push_back(s);known.insert(v);
            };
            buy(z.v);
            if (!paid.count(mid) && !known.count(mid)) {
                if (atom.count(mid)) buy(mid);
                else {buy(x.v);buy(y.v);patch.push_back(joined);known.insert(mid);}
            }
            patch.push_back(last);
            if (int(patch.size())>=budget) continue;
            string sig;
            for (auto s:patch) {sig+=to_string(s.v)+s.op+to_string(s.a)+","+to_string(s.b)+" ";}
            if (distinct.insert(sig).second) answers.push_back(std::move(patch));
        }
    }
    // For two numbers whose sum is d, u <= v <= largest.
    template<class F> void sums(I d,I largest,F cb) {
        I lo=max<I>(1,d-largest), hi=d/2;
        if (lo>hi)return;
        auto a=lower_bound(vals.begin(),vals.end(),lo), b=upper_bound(a,vals.end(),hi);
        auto c=lower_bound(vals.begin(),vals.end(),d-hi), e=upper_bound(c,vals.end(),d-lo);
        if (b-a<=e-c) {
            for (;a!=b && !done();++a) {++inspected;if(atom.count(d-*a))cb(*a,d-*a);}
        } else {
            for (;c!=e && !done();++c) {++inspected;if(atom.count(d-*c))cb(d-*c,*c);}
        }
    }
    // Enumerate small, small+d with a separate upper limit for each endpoint.
    template<class F> void diffs(I d,I max_small,I max_big,F cb) {
        I last=min(max_small,max_big-d);
        if (last<1)return;
        auto b=upper_bound(vals.begin(),vals.end(),last);
        auto c=lower_bound(vals.begin(),vals.end(),d+1),e=upper_bound(c,vals.end(),d+last);
        if (b-vals.begin()<=e-c) {
            for (auto a=vals.begin();a!=b && !done();++a) {
                ++inspected;if(atom.count(*a+d))cb(*a,*a+d);
            }
        } else {
            for (;c!=e && !done();++c) {++inspected;if(atom.count(*c-d))cb(*c-d,*c);}
        }
    }
    void run(const vector<I>& free) {
        for (I x:free) {paid.insert(x);atom.emplace(x,Step{x,0,0,0});}
        for (size_t i=0;i<free.size();++i) for (size_t j=0;j<=i;++j)
            forward(free[i],free[j],cap,[&](Step s){atom.emplace(s.v,s);});
        if (atom.count(target) && !paid.count(target) && budget>1) answers.push_back({atom.at(target)});
        for (const auto& e:atom) if (e.first!=target) vals.push_back(e.first);
        sort(vals.begin(),vals.end());
        // In every representation of a positive target, the largest term
        // with positive sign is at least target/3. Its companions' signs
        // distinguish these four disjoint numeric cases.
        vector<I> leads(lower_bound(vals.begin(),vals.end(),(target+2)/3),vals.end());
        sort(leads.begin(),leads.end(),[&](I a,I b){return abs(target-a)<abs(target-b);});
        for (I z:leads) {
            if (done())break;
            auto found=[&](I a,int sa,I b,int sb){
                if(a!=target && b!=target)emit({Term{z,1},Term{a,sa},Term{b,sb}});
            };
            if (z<target) {
                sums(target-z,z,[&](I a,I b){found(a,1,b,1);});
                if (z>=target-z)diffs(target-z,cap,z,[&](I a,I b){found(a,-1,b,1);});
            } else if (z>target) {
                sums(z-target,cap,[&](I a,I b){found(a,-1,b,-1);});
                diffs(z-target,z,cap,[&](I a,I b){found(a,1,b,-1);});
            }
        }
    }
};

int main(){
    ios::sync_with_stdio(false);cin.tie(nullptr);
    I cap,target;int n,budget,limit;
    while(cin>>cap>>target>>n>>budget>>limit){
        vector<I> free(n);for(I& x:free)cin>>x;
        TripleSearch search;search.cap=cap;search.target=target;search.budget=budget;
        search.max_answers=limit;search.run(free);
        cout<<search.answers.size()<<' '<<search.inspected<<'\n';
        for(const auto& plan:search.answers){
            cout<<plan.size()<<'\n';
            for(auto s:plan)cout<<s.v<<' '<<s.op<<' '<<s.a<<' '<<s.b<<'\n';
        }
    }
}
