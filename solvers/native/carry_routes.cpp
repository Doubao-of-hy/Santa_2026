// Recode a private arithmetic cone by allowing its intermediate values to
// move up or down. Shortest paths can cross any number of former boundaries.
#include <algorithm>
#include <cstdint>
#include <iostream>
#include <queue>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

using Number = std::int64_t;
struct Step { Number out, left, right; char op; };

template<class F>
void operations(Number a, Number b, Number limit, F emit) {
    if (a<b) std::swap(a,b);
    if (a<=limit-b) emit(Step{a+b,a,b,'+'});
    if (a>b) emit(Step{a-b,a,b,'-'});
    if (a<=limit/b) emit(Step{a*b,a,b,'*'});
    if (a%b==0) emit(Step{a/b,a,b,'/'});
}

// Each transition produces the requested destination from the current
// accumulator and either a retained value or a one-operation side constant.
template<class F>
void transitions(Number x, Number y, Number limit, F offer) {
    if (x<y) offer(y-x,Step{y,x,y-x,'+'});
    if (x>y) offer(x-y,Step{y,x,x-y,'-'});
    if (x<=limit-y) offer(x+y,Step{y,x+y,x,'-'});
    if (y%x==0) offer(y/x,Step{y,x,y/x,'*'});
    if (x%y==0) offer(x/y,Step{y,x,x/y,'/'});
    if (x<=limit/y) offer(x*y,Step{y,x*y,x,'/'});
}

struct Origin {
    int previous=-1;
    Number side=0;
    Step edge{};
    Number second_side=0;
    Step inner{};
};
struct End {int price; Origin source;};
struct Candidate {Number value; int original_cost;};

void solve(Number limit, Number goal, int budget, const std::vector<Number>& paid,
           const std::vector<Candidate>& states, bool split_entry, int deep_samples, bool ties) {
    const Step free_value{0,0,0,'?'};
    std::unordered_map<Number,Step> book;
    book.reserve(paid.size()*paid.size()*2+1);
    for (Number a:paid) book.emplace(a,free_value);
    for (std::size_t i=0;i<paid.size();++i)
        for (std::size_t j=0;j<=i;++j)
            operations(paid[i],paid[j],limit,[&](Step e){book.emplace(e.out,e);});
    std::vector<Number> probes;
    if (deep_samples>0 && budget>=4) {
        std::vector<Number> source;
        for (const auto& entry:book) if(entry.second.out) source.push_back(entry.first);
        std::sort(source.begin(),source.end());
        if (!source.empty()) {
            auto middle=std::lower_bound(source.begin(),source.end(),goal);
            int center=int(middle-source.begin());
            for (int k=0;k<deep_samples;++k) {
                if (std::size_t(k)<source.size()) probes.push_back(source[k]);
                int j=center+k-deep_samples/2;
                if (j>=0 && j<int(source.size())) probes.push_back(source[j]);
                probes.push_back(source[std::size_t(k)*source.size()/deep_samples]);
            }
        }
        std::sort(probes.begin(),probes.end());
        probes.erase(std::unique(probes.begin(),probes.end()),probes.end());
    }
    const int infinity=budget+1;
    std::vector<int> cost(states.size(),infinity);
    std::vector<Origin> history(states.size());
    using Item=std::pair<int,int>;
    std::priority_queue<Item,std::vector<Item>,std::greater<Item>> queue;
    int terminal=-1;
    for (int i=0;i<int(states.size());++i) {
        const Number v=states[i].value;
        const int old=states[i].original_cost;
        if (v==goal) terminal=i;
        if (v!=goal && old>=0 && old<infinity) cost[i]=old;
        auto it=book.find(v);
        if (it!=book.end()) {
            int direct=it->second.out?1:0;
            if (direct<=cost[i]) {
                cost[i]=direct;
                history[i]={-1,0,it->second};
            }
        }
        if (cost[i]>1 && budget>=2) {
            // A displaced accumulator may be two instructions from any
            // already-paid pair, even when its first operation is off-spine.
            for (Number anchor:paid) {
                bool reached=false;
                transitions(anchor,v,limit,[&](Number side,Step e) {
                    if (reached || side==v) return;
                    auto other=book.find(side);
                    if (other==book.end() || !other->second.out) return;
                    cost[i]=2;history[i]={-1,side,e};reached=true;
                });
                if (reached) break;
            }
        }
        if (split_entry && (v==goal || old>=(ties?3:4)) && cost[i]>2 && budget>=3) {
            // Meet two independent branches of the surrounding dictionary.
            // Both operands may be newly created, including a repeated square.
            for (const auto& entry:book) {
                Number x=entry.first;
                if (x==v || !entry.second.out) continue;
                bool reached=false;
                transitions(x,v,limit,[&](Number y,Step e) {
                    if (reached || y==v) return;
                    auto other=book.find(y);
                    if (other==book.end()) return;
                    int extra=int(y!=x && other->second.out!=0);
                    cost[i]=2+extra;
                    history[i]={-1,x,e,extra?y:0};reached=true;
                });
                if (reached) break;
            }
        }
        if (v==goal && cost[i]>=4 && budget>=4) {
            // Attach two independent one-operation side expressions at
            // different depths. The innermost accumulator can use *any*
            // retained register value, even one far from the previous path.
            bool reached=false;
            for (Number x:probes) {
                if (x==v) continue;
                transitions(x,v,limit,[&](Number y,Step outer) {
                    if (reached || y==v || y==x) return;
                    for (Number a:paid) {
                        if (a==y) continue;
                        transitions(a,y,limit,[&](Number z,Step inner) {
                            if (reached || z==v || z==y) return;
                            auto entry=book.find(z);
                            if (entry==book.end()) return;
                            bool extra=entry->second.out && x!=z;
                            cost[i]=3+int(extra);
                            history[i]={-1,x,outer,extra?z:0,inner};
                            reached=true;
                        });
                        if (reached) break;
                    }
                });
                if (reached) break;
            }
        }
        if (cost[i]<infinity) queue.emplace(cost[i],i);
    }
    if (terminal<0) throw std::runtime_error("missing terminal");
    std::vector<End> endings;
    if(cost[terminal]<infinity) endings.push_back({cost[terminal],history[terminal]});
    std::uint64_t expanded=0;
    while (!queue.empty()) {
        auto [price,i]=queue.top();queue.pop();
        if (i==terminal || cost[i]!=price || price+1>budget) continue;
        for (int j=0;j<int(states.size());++j) {
            if (j==i || (j!=terminal && cost[j]<=price+1)) continue;
            ++expanded;
            transitions(states[i].value,states[j].value,limit,[&](Number side,Step e){
                if (side==e.out) return;
                auto it=book.find(side);
                if (it==book.end() && side!=states[i].value) return;
                const bool make=side!=states[i].value && it->second.out!=0;
                int next=price+1+make;
                if (next>budget) return;
                Origin choice{i,make?side:0,e};
                if (j==terminal) {endings.push_back({next,choice});return;}
                if (next<cost[j]) {
                    cost[j]=next;history[j]=choice;queue.emplace(next,j);
                }
            });
        }
    }
    std::stable_sort(endings.begin(),endings.end(),[](auto& a,auto& b){return a.price<b.price;});
    const std::size_t retained=ties?28:10;
    if (endings.size()>retained) endings.resize(retained);
    std::cout<<expanded<<' '<<endings.size()<<'\n';
    for (const auto& end:endings) {
        std::vector<Step> reverse;
        Origin here=end.source;
        while (true) {
            if (here.edge.out) reverse.push_back(here.edge);
            if (here.inner.out) reverse.push_back(here.inner);
            if (here.second_side) reverse.push_back(book.at(here.second_side));
            if (here.side) reverse.push_back(book.at(here.side));
            if (here.previous<0) break;
            here=history[here.previous];
        }
        std::cout<<reverse.size()<<'\n';
        for (auto it=reverse.rbegin();it!=reverse.rend();++it)
            std::cout<<it->out<<' '<<it->op<<' '<<it->left<<' '<<it->right<<'\n';
    }
}

int main(int argc,char** argv) {
    std::ios::sync_with_stdio(false);std::cin.tie(nullptr);
    const bool split=argc>1 && std::string(argv[1])=="--split";
    const int deep=argc>2?std::stoi(argv[2]):0;
    const bool ties=argc>3 && std::string(argv[3])=="--ties";
    if (deep<0 || deep>100000) return 2;
    Number limit,goal;int budget,n,m;
    while (std::cin>>limit>>goal>>budget>>n>>m) {
        std::vector<Number> paid(n);
        std::vector<Candidate> states(m);
        for (auto& v:paid) std::cin>>v;
        for (auto& v:states) std::cin>>v.value>>v.original_cost;
        solve(limit,goal,budget,paid,states,split,deep,ties);
    }
}
