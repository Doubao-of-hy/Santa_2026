// Enumerate connected, two-input arithmetic SLPs through four instructions.
// Slots 0, 1, 2 are x, y, 1. Instruction i writes slot i+3.
#include <algorithm>
#include <array>
#include <cstdint>
#include <iostream>
#include <limits>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace {
using U32 = std::uint32_t;
using U64 = std::uint64_t;
constexpr U32 modulus = 1000000007;
constexpr unsigned max_depth = 4;
constexpr unsigned per_depth = 8;
constexpr char symbols[] = "+-*/";
constexpr std::array<std::pair<U64,U64>,16> samples{{
    {2,3},{3,2},{2,4},{4,2},{3,6},{6,3},{9,4},{4,9},
    {2,2},{1,1},{2,1},{1,2},{8,12},{12,8},{5,7},{7,5}
}};
using Samples = std::array<U64,samples.size()>;
struct Signature { U32 a,b; };
struct Operation { std::uint8_t op=0,left=0,right=0; };
using Tape = std::array<Operation,max_depth>;

U64 key(Signature s) { return (U64(s.a)<<32)|s.b; }
U32 multiply(U32 x,U32 y) { return U64(x)*y%modulus; }
U32 invert(U32 a) {
    U32 result=1;
    for (U32 n=modulus-2;n;n>>=1,a=multiply(a,a))
        if (n&1) result=multiply(result,a);
    return result;
}
U32 field(unsigned op,U32 l,U32 r,U32 inverse_right) {
    if (op==0) return l+r>=modulus?l+r-modulus:l+r;
    if (op==1) return l>=r?l-r:l+modulus-r;
    return op==2?multiply(l,r):multiply(l,inverse_right);
}
U64 positive(unsigned op,U64 l,U64 r) {
    if (!l || !r) return 0; // invalid ancestors propagate; all genuine values are positive.
    if (op==0) return l+r;
    if (op==1) return l>r?l-r:0;
    if (op==2) return l*r;
    return l%r==0?l/r:0;
}
unsigned popcount(U64 x) {
    unsigned n=0;
    for (;x;x&=x-1) ++n;
    return n;
}
struct Node {
    Signature signature{},inverse{};
    unsigned dependencies=0,inputs=0;
    Samples examples{};
};
struct Candidate {
    Tape tape{};
    // 16 positive/integer test cases, 3 source-input flags, 4 operation flags,
    // repeated multiplication, shared intermediate, and last-operation index.
    U64 profile=0;
    U64 lex=0;
};
struct Group {
    std::unordered_map<U64,Candidate> representatives;
};
struct Target { Signature signature; std::array<Group,max_depth> groups; };

class Library {
    std::unordered_map<U64,std::size_t> positions;
    std::vector<Target> targets;
    std::array<Node,3+max_depth> slots{};
    Tape tape{};

    static void invert_signature(Node& n) {
        n.inverse={invert(n.signature.a),invert(n.signature.b)};
    }
    static void examples(Node& n,unsigned op,const Node& l,const Node& r) {
        // max sample = 12, so a depth-four value is at most 12^16 < 2^64.
        for (std::size_t j=0;j<samples.size();++j)
            n.examples[j]=positive(op,l.examples[j],r.examples[j]);
    }
    void retain(Group& group,const Node& n,unsigned length) {
        U64 mask=0,ops=0,lex=0;
        bool square=false,shared=false;
        unsigned used=0;
        for (unsigned j=0;j<samples.size();++j)
            if (n.examples[j]) mask|=U64(1)<<j;
        for (unsigned j=0;j<length;++j) {
            const auto& step=tape[j];
            ops|=1u<<step.op;
            square|=step.op==2 && step.left==step.right;
            for (unsigned slot:{unsigned(step.left),unsigned(step.right)}) {
                if (slot<3) continue;
                unsigned bit=1u<<(slot-3);
                shared|=(used&bit)!=0;
                used|=bit;
            }
            lex=(lex<<8)|(step.op<<6)|(step.left<<3)|step.right;
        }
        U64 profile=mask|(U64(n.inputs)<<16)|(ops<<19)|(U64(square)<<23)|
                    (U64(shared)<<24)|(U64(tape[length-1].op)<<25);
        auto it=group.representatives.find(profile);
        if (it==group.representatives.end()) {
            group.representatives.emplace(profile,Candidate{tape,profile,lex});
        } else if (lex<it->second.lex) {
            it->second={tape,profile,lex};
        }
    }
    void enumerate(unsigned depth) {
        const unsigned out=3+depth, required=(1u<<(depth+1))-1;
        for (unsigned op=0;op<4;++op) for (unsigned l=0;l<out;++l) {
            // Both argument orders are distinct for subtraction and division.
            unsigned first=(op==0 || op==2)?l:0;
            for (unsigned r=first;r<out;++r) {
                const Node& left=slots[l];const Node& right=slots[r];
                if (op==3 && (!right.signature.a || !right.signature.b)) continue;
                unsigned deps=left.dependencies|right.dependencies|(1u<<depth);
                bool descend=depth+1<max_depth;
                if (!descend && deps!=required) continue;
                Node& node=slots[out];
                node.signature={field(op,left.signature.a,right.signature.a,right.inverse.a),
                                field(op,left.signature.b,right.signature.b,right.inverse.b)};
                auto hit=positions.end();
                if (deps==required) hit=positions.find(key(node.signature));
                if (!descend && hit==positions.end()) continue;
                node.dependencies=deps;node.inputs=left.inputs|right.inputs;
                examples(node,op,left,right);
                tape[depth]={std::uint8_t(op),std::uint8_t(l),std::uint8_t(r)};
                if (hit!=positions.end()) retain(targets[hit->second].groups[depth],node,depth+1);
                if (descend) {
                    invert_signature(node);
                    enumerate(depth+1);
                }
            }
        }
    }
    static int separation(U64 a,U64 b) {
        U64 difference=a^b;
        return 5*int(popcount(difference&0xffff))+
               30*int((difference>>18)&1)+ // uses constant 1
               8*int(popcount((difference>>16)&3))+
               11*int(popcount((difference>>19)&15))+
               22*int((difference>>23)&1)+20*int((difference>>24)&1)+
               7*int((a>>25)!=(b>>25));
    }
    static std::vector<Candidate> shortlist(const Group& g) {
        std::vector<Candidate> pool;
        for (const auto& entry:g.representatives) pool.push_back(entry.second);
        std::vector<Candidate> kept;
        while (!pool.empty() && kept.size()<per_depth) {
            auto rank=[&](const Candidate& c) {
                int distance=0;
                if (!kept.empty()) {
                    distance=10000;
                    for (const Candidate& other:kept)
                        distance=std::min(distance,separation(c.profile,other.profile));
                }
                int cases=int(popcount(c.profile&0xffff));
                int uses_one=int((c.profile>>18)&1);
                return std::make_pair(distance*1000+cases*10-uses_one,
                                      std::numeric_limits<U64>::max()-c.lex);
            };
            auto best=std::max_element(pool.begin(),pool.end(),
                       [&](const Candidate& a,const Candidate& b){return rank(a)<rank(b);});
            kept.push_back(*best);
            *best=pool.back();pool.pop_back();
        }
        return kept;
    }
public:
    void request(Signature s) {
        if (positions.emplace(key(s),targets.size()).second) targets.push_back({s,{}});
    }
    void run() {
        if (targets.empty()) return;
        slots[0].signature={173,1009};slots[1].signature={617,379};slots[2].signature={1,1};
        for (unsigned i=0;i<3;++i) {
            slots[i].inputs=1u<<i;
            invert_signature(slots[i]);
            for (unsigned j=0;j<samples.size();++j)
                slots[i].examples[j]=i==0?samples[j].first:i==1?samples[j].second:1;
        }
        enumerate(0);
        for (const Target& target:targets) for (unsigned d=0;d<max_depth;++d) {
            for (const Candidate& c:shortlist(target.groups[d])) {
                std::cout<<target.signature.a<<' '<<target.signature.b;
                for (unsigned i=0;i<=d;++i) {
                    const auto& step=c.tape[i];
                    std::cout<<' '<<symbols[step.op]<<' '<<unsigned(step.left)<<' '<<unsigned(step.right);
                }
                std::cout<<'\n';
            }
        }
    }
};
}

int main() {
    std::ios::sync_with_stdio(false);std::cin.tie(nullptr);
    Library library;
    std::int64_t a,b;
    auto normalized=[](std::int64_t x){x%=modulus;if (x<0) x+=modulus;return U32(x);};
    while (std::cin>>a) {
        if (!(std::cin>>b)) { std::cerr<<"Incomplete signature\n";return 2; }
        library.request({normalized(a),normalized(b)});
    }
    if (!std::cin.eof()) { std::cerr<<"Invalid signature\n";return 2; }
    library.run();
}
