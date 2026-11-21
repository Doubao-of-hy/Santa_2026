// Find exact target decompositions d*q +/- a*b. Invert a in the residue ring
// to query every compatible b class without enumerating the full product grid.
class Bilinear {
    using Wide=__int128;
    struct Fraction {int a;Int common,mod,inverse;};
    struct Column {int scale;vector<pair<Int,int>> entries;vector<Fraction> factors;};
    struct Hit {int d,a,b,q,sign;Int quotient;double score;};
    LiveBank &bank;
    vector<Column> columns;
    int precursors,recursive;
    static Int inverse(Int value,Int modulus) {
        Int a=value%modulus,b=modulus;
        Wide x=1,y=0;
        while(b) {Int k=a/b,r=a%b; a=b;b=r;Wide next=x-k*y;x=y;y=next;}
        Int result=Int(x%modulus);
        return result<0?result+modulus:result;
    }
    int cost(int id) const {return bank.nodes[id].cost;}

public:
    long long matches=0, sealed=0;
    Bilinear(LiveBank &bank,int precursors,int recursive):
        bank(bank),precursors(precursors),recursive(recursive) {}

    void rebuild(int epoch) {
        columns.clear();
        vector<int> operands;
        for(int i:bank.zero) operands.push_back(i);
        for(int i:bank.one) if(cost(i)==1) operands.push_back(i);
        vector<int> bias=operands;
        size_t step=max<size_t>(1,(bank.nodes.size()+65000-1)/65000);
        for(size_t j=epoch%step;j<bank.nodes.size();j+=step)
            if(cost(j)==2) bias.push_back(j);
        // Favor a range of distinct scale sizes, including non-binary scales.
        vector<pair<double,int>> scales;
        for(int i:operands) {
            Int d=bank.nodes[i].v;
            if(d<96 || d>(Int(1)<<42)) continue;
            double bits=log2(double(d));
            bool dyadic=(d&(d-1))==0;
            double priority=cost(i)*4+.09*abs(bits-17)-(dyadic?1:0);
            priority+=double((uint64_t(d)*0xbf58476d1ce4e5b9ULL+epoch*17)>>56)/256;
            scales.emplace_back(priority,i);
        }
        sort(scales.begin(),scales.end());
        map<pair<int,bool>,int> bucket;
        vector<int> factors;
        for(int i:bank.zero) if(bank.nodes[i].v>=2) factors.push_back(i);
        vector<int> affordable;
        for(int i:bank.one) if(cost(i)==1 && bank.nodes[i].v>2) affordable.push_back(i);
        if(!affordable.empty()) {
            size_t stride=max<size_t>(1,affordable.size()/max(1,precursors));
            for(size_t i=epoch%stride;i<affordable.size() && factors.size()<bank.zero.size()+precursors;i+=stride)
                factors.push_back(affordable[i]);
        }
        for(auto [priority,i]:scales) {
            Int d=bank.nodes[i].v;
            auto band=make_pair(int(log2(double(d)))/3,(d&(d-1))==0);
            if(bucket[band]>=2) continue;
            ++bucket[band];
            Column col{i,{},{}};
            col.entries.reserve(bias.size());
            for(int j:bias) col.entries.emplace_back(bank.nodes[j].v%d,j);
            sort(col.entries.begin(),col.entries.end(),[&](auto a,auto b){
                if(a.first!=b.first) return a.first<b.first;
                return bank.nodes[a.second].v<bank.nodes[b.second].v;});
            for(int a:factors) {
                Int x=bank.nodes[a].v,g=std::gcd(x,d),m=d/g;
                if(g>4 || m<=1 || x>bank.limit/2) continue;
                col.factors.push_back({a,g,m,inverse(x/g,m)});
            }
            columns.push_back(move(col));
            if(columns.size()>=14) break;
        }
    }
    vector<Plan> search(Int t,int ceiling) {
        vector<Hit> immediate, waiting;
        auto retain=[](vector<Hit> &list,Hit hit,size_t count) {
            if(list.size()>=count && hit.score>=list.back().score) return;
            for(auto old:list) if(old.quotient==hit.quotient && old.d==hit.d && old.a==hit.a
                                 && old.b==hit.b && old.sign==hit.sign) return;
            auto at=upper_bound(list.begin(),list.end(),hit.score,[](double n,const Hit &h){return n<h.score;});
            list.insert(at,hit);if(list.size()>count) list.pop_back();
        };
        for(const auto &col:columns) {
            Int d=bank.nodes[col.scale].v;
            for(auto f:col.factors) {
                if(t%f.common) continue;
                Int a=bank.nodes[f.a].v;
                if(a>=bank.limit) continue;
                Int residue=Int((Wide(t/f.common%f.mod)*f.inverse)%f.mod);
                for(int neg=0;neg<2;++neg) {
                    Int r=neg?(f.mod-residue)%f.mod:residue;
                    for(int lift=0;lift<f.common;++lift,r+=f.mod) {
                        auto lo=lower_bound(col.entries.begin(),col.entries.end(),r,
                            [](auto it,Int key){return it.first<key;});
                        auto hi=upper_bound(lo,col.entries.end(),r,
                            [](Int key,auto it){return key<it.first;});
                        int n=int(hi-lo);
                        auto test=[&](int k) {
                            int bi=lo[k].second;
                            Int b=bank.nodes[bi].v;
                            if(b<2 || b>bank.limit/a) return;
                            Int prod=a*b;
                            if(neg && prod>bank.limit-t) return;
                            Int rhs=neg?t+prod:abs(t-prod);
                            if(!rhs) return;
                            Int q=rhs/d;
                            if(q<1 || q==t) return;
                            int qi=bank.index.get(q);
                            int base=3+cost(col.scale)+cost(f.a)+(f.a==bi?0:cost(bi));
                            if(base>=ceiling+1) return;
                            int sign=neg?-1:(prod<t?1:0);
                            Hit h{col.scale,f.a,bi,qi,sign,q,0};
                            if(qi>=0) {
                                h.score=base+cost(qi);
                                if(h.score<=ceiling+2) {++matches;retain(immediate,h,8);}
                            } else if(recursive && base+3<ceiling+1) {
                                h.score=base+.215*log2(double(q));
                                retain(waiting,h,recursive);
                            }
                        };
                        if(n<=30) for(int k=0;k<n;++k) test(k);
                        else {
                            for(int k=0;k<5;++k) test(k);
                            int center=lower_bound(lo,hi,t/a,[&](auto item,Int x){
                                return bank.nodes[item.second].v<x;})-lo;
                            for(int k=max(0,center-7);k<min(n,center+7);++k) test(k);
                            for(int k=1;k<=6;++k) test(k*n/7);
                        }
                    }
                }
            }
        }
        auto assemble=[&](const Hit &h,Plan plan) {
            unordered_set<Int> seen;
            for(auto e:plan) seen.insert(e.out);
            for(int i:{h.d,h.a,h.b}) bank.materialize(i,plan,seen);
            auto emit=[&](char op,Int a,Int b) {
                Int out=shared_core::apply(op,a,b);
                if(out<1 || out>bank.limit) throw runtime_error("invalid bilinear intermediate");
                if(seen.insert(out).second) plan.push_back({out,a,b,op});
                return out;
            };
            Int d=bank.nodes[h.d].v, a=bank.nodes[h.a].v, b=bank.nodes[h.b].v;
            Int x=emit('*',d,h.quotient),y=emit('*',a,b);
            Int out=h.sign==0?emit('-',y,x):emit(h.sign==1?'+':'-',x,y);
            if(out!=t) throw runtime_error("invalid bilinear residue");
            return plan;
        };
        vector<Plan> alternatives;
        for(auto h:immediate) {
            Plan q;unordered_set<Int> seen;
            bank.materialize(h.q,q,seen);alternatives.push_back(assemble(h,move(q)));
        }
        for(auto h:waiting) {
            TargetSearch tail(bank,2,max(4,ceiling-2),.18);
            auto plan=tail.run(h.quotient,5);
            if(tail.best_node>=0) {
                auto result=assemble(h,move(plan));
                if(int(result.size())<=ceiling+2) {++sealed;alternatives.push_back(move(result));}
            }
        }
        return alternatives;
    }
};
