"""Specialize the established pair-bound traversal for a sparse reversible one-step frontier."""
from hashlib import sha256
from pathlib import Path
import json
H=Path(__file__).resolve().parent;R=H.parents[1];up=R/'exact_frontier.hpp';text=up.read_text()
def swap(old,new):
    global text
    assert text.count(old)==1,old
    text=text.replace(old,new)
swap('struct IncrementalSearch : DenseSearch {','struct SparseFrontier : Search {')
swap('    std::vector<uint64_t> words, occupied;','    SparseReachable reach;\n    bool audit_state=false;size_t peak_blocks=0;\n    std::unordered_map<Num,Mask> initial_unary;')
swap('        std::vector<uint8_t> bits;\n        bool count(Num n) const { return bits[n]; }\n        void insert(Num n) { bits[n]=1; }\n        void erase(Num n) { bits[n]=0; }',
     '        Set values;\n        bool count(Num n) const { return values.count(n); }\n        void insert(Num n) { values.insert(n); }\n        void erase(Num n) { values.erase(n); }')
swap('!(words[v>>6] & (uint64_t(1)<<(v&63)))','!reach.contains(v)')
begin=text.index('    void toggle(Num value) {');end=text.index('    void saturate(',begin)
text=text[:begin]+'''    void toggle(Num value) {reach.mark(value,!reach.contains(value));}
    void mark(Num value,bool on) {if(reach.mark(value,on))undo.push_back(value);}
    Mask goal_mask(Num x) const {auto it=goal_bit.find(x);return it==goal_bit.end()?0:it->second;}
    void audit_node(const Values& active,const Values& helpers,unsigned remaining) const {
        Set expected;
        for(size_t i=0;i<active.size();i++)for(size_t j=0;j<=i;j++)operations(active[i],active[j],[&](Num v){expected.insert(v);});
        for(Num v:active)expected.erase(v);
        Set actual;
        for(auto [k,word]:reach.blocks)for(;word;word&=word-1)actual.insert(k*64+__builtin_ctzll(word));
        if(actual!=expected)throw std::runtime_error("sparse frontier mismatch");
        auto expected_unary=initial_unary;
        for(size_t i=0;i<helpers.size();++i){
            if(remaining==1 && i+1==helpers.size())break;
            for(unsigned j=0;j<goals.size();++j)inverse(goals[j],helpers[i],[&](Num x){expected_unary[x]|=Mask(1)<<j;});
        }
        if(unary!=expected_unary)throw std::runtime_error("sparse inverse index mismatch");
        Set multi_seen(multi.begin(),multi.end());
        if(pair_bound) for(auto [v,m]:expected_unary)if(bool(m&(m-1))!=bool(multi_seen.count(v)))throw std::runtime_error("multi-support mismatch");
    }
'''+text[end:]
swap('if (x!=a && x!=b) next |= dense_goals[x];','if (x!=a && x!=b) next |= goal_mask(x);')
old=text[text.index('                if (a+b<=limit) emit(a+b);'):text.index('            }\n            next &= ~seen;')]
swap(old,'                operations(a,b,emit);\n')
swap('        if (seen==all) { witness=active; return true; }','        if(audit_state && remaining) audit_node(active,helpers,remaining);\n        if(reach.blocks.size()>peak_blocks)peak_blocks=reach.blocks.size();\n        if (seen==all) { witness=active; return true; }')
begin=text.index('        for (std::size_t page=0;');end=text.index('                    if (bans.count(v))',begin)
text=text[:begin]+'''        // Child recursion mutates and restores blocks. Iterate a compact, immutable level snapshot.
        const auto snapshot=reach.blocks;
        for(auto [block,word]:snapshot) {
                for(auto bits=word;bits;bits&=bits-1) {
                    Num v=block*64+__builtin_ctzll(bits);
'''+text[end:]
swap('                }\n            }\n        }\n        for (Num v:excluded)', '                }\n        }\n        for (Num v:excluded)')
begin=text.index('        if (limit>4000000)');end=text.index('        if (pair_bound) {',begin)
text=text[:begin]+'''        if(!dense_unary.empty() || !dense_goals.empty())throw std::runtime_error("requires sparse domain");
        if(audit_state)initial_unary=unary;
'''+text[end:]
swap('seen |= dense_goals[x];','seen |= goal_mask(x);')
dest=H/'sparse_frontier.hpp';dest.write_text(text)
files=[up,R/'exact_helpers.cpp',H/'sparse_reachable.hpp',H/'sparse_frontier_driver.cpp',dest,Path(__file__)]
(H/'sparse-frontier-source.json').write_text(json.dumps({p.relative_to(R).as_posix():sha256(p.read_bytes()).hexdigest()for p in files},indent=2)+'\n')
