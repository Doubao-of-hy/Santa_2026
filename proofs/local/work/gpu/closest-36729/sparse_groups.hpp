// Sparse iteration over a dense, reversible set of one-operation neighbors.
// The node order and completed-branch exclusions match the original search.
struct SparseStar : Search {
    SparseReachable reach;
    bool audit_state=false;size_t peak_blocks=0;
    std::unordered_map<Num,Mask> initial_unary;
    std::vector<Num> undo;
    struct Bans {
        Set values;
        bool count(Num n) const { return values.count(n); }
        void insert(Num n) { values.insert(n); }
        void erase(Num n) { values.erase(n); }
    } bans;
    bool inverse_terminal = false;
    bool pair_bound = false;
    bool early_pair = false;
    Values multi;
    struct PairCover { Num a,b; Mask joint; };
    std::vector<PairCover> double_outputs;

    bool two_helpers_possible(Mask missing) const {
        int count=__builtin_popcountll(missing);
        if (count<4) return true;
        // Either one pair alone supplies two distinct outputs, or the two
        // unary support masks must cover at least count-1 distinct goals.
        for (auto p:double_outputs) {
            if ((missing & ~(current(p.a)|current(p.b)|p.joint))==0 &&
                !bans.count(p.a) && !bans.count(p.b)) return true;
        }
        Shortlists cache;
        for (Num x:multi) {
            Mask own=current(x)&missing;
            if (__builtin_popcountll(own)<count/2 || bans.count(x)) continue;
            if (last_possible(x,missing & ~own,bans,cache)) return true;
        }
        return false;
    }

    // With one helper left, every unsupported goal must either use it
    // with an indexed operand or pair it with the penultimate helper.
    // Earlier helpers are indexed by extend_index. The penultimate one
    // lives only in helpers.back() because it was chosen with two slots.
    bool finish_one(const Values& active, Mask seen, Mask supported, const Values& helpers) {
        Mask missing = all & ~supported;
        unsigned pivot = __builtin_ctzll(missing);
        for (Mask rest=missing & (missing-1); rest; rest &= rest-1) {
            unsigned j=__builtin_ctzll(rest);
            if (partners[j].size() < partners[pivot].size()) pivot=j;
        }
        Values possible=partners[pivot];
        if (!helpers.empty())
            inverse(goals[pivot],helpers.back(),[&](Num x){possible.push_back(x);});
        std::sort(possible.begin(),possible.end());
        possible.erase(std::unique(possible.begin(),possible.end()),possible.end());
        for (Num v:possible) {
            if (!reach.contains(v) || bans.count(v)) continue;
            ++last_candidates;
            Mask legal=current(v);
            if (!helpers.empty()) legal |= hits(v,helpers.back());
            if (missing & ~legal) continue;
            Values next=active;
            next.push_back(v);
            Mask reached=seen;
            close(next,reached,active.size());
            if (reached==all) { witness=std::move(next); return true; }
        }
        return false;
    }

    void toggle(Num value) {reach.mark(value,!reach.contains(value));}
    void mark(Num value,bool on) {if(reach.mark(value,on))undo.push_back(value);}
    Mask goal_mask(Num x) const {if(!dense_goals.empty())return dense_goals[x];auto it=goal_bit.find(x);return it==goal_bit.end()?0:it->second;}
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
    void saturate(Values& active, Mask& seen, std::size_t start) {
        for (std::size_t i=start; i<active.size(); ++i) {
            Mask next=0;
            for (std::size_t j=0; j<=i; ++j) {
                auto a=active[i], b=active[j];
                auto emit=[&](Num x) {
                    mark(x,true);
                    if (x!=a && x!=b) next |= goal_mask(x);
                };
                operations(a,b,emit);
            }
            next &= ~seen;
            while (next) {
                unsigned j=__builtin_ctzll(next);
                active.push_back(goals[j]);seen |= Mask(1)<<j;next &= next-1;
            }
        }
        for (Num v:active) mark(v,false);
    }
    #include "three.inc"
    #include "groups.inc"
    bool visit_frontier(const Values& active, Mask seen, Mask supported, Values& helpers, unsigned remaining) {
        if(audit_state && remaining) audit_node(active,helpers,remaining);
        if(reach.blocks.size()>peak_blocks)peak_blocks=reach.blocks.size();
        if (seen==all) { witness=active; return true; }
        if (!remaining) return false;
        if (nodes==max_nodes) { interrupted=true; return false; }
        ++nodes;
        if (enable_star && remaining==3 && !three_possible(all&~supported,helpers)) return false;
        if (pair_bound && remaining==2 && (!early_pair || helpers.empty()) &&
            !two_helpers_possible(all & ~supported)) return false;
        // Do not shortcut a level that carries a partition. Each partition
        // index is assigned before feasibility filtering in the original order.
        bool partitioned = (helpers.empty() && shards>1) ||
            (helpers.size()==1 && shards_two>1) || (helpers.size()==2 && shards_three>1);
        if (inverse_terminal && remaining==1 && supported!=all && !partitioned)
            return finish_one(active,seen,supported,helpers);
        Set group_rejected;
        if (enable_star && remaining==4 && !partitioned) group_filter(active,helpers,all&~supported,group_rejected);
        if (!group_rejected.empty()) {
            for(Num v:group_rejected)bans.insert(v);
        }
        Values excluded;
        Shortlists cache;
        unsigned index=0;
        // Child recursion mutates and restores blocks. Iterate a compact, immutable level snapshot.
        const auto snapshot=reach.blocks;
        for(auto [block,word]:snapshot) {
                for(auto bits=word;bits;bits&=bits-1) {
                    Num v=block*64+__builtin_ctzll(bits);
                    if (bans.count(v)) continue;
                    if (elsewhere(helpers.size(),index)) {
                        bans.insert(v); excluded.push_back(v); continue;
                    }
                    Mask sup=supported | (remaining==1 && !inverse_terminal ? support(v,helpers) : current(v));
                    if (inverse_terminal && remaining==1 && !helpers.empty())
                        sup |= hits(v,helpers.back());
                    if (remaining==2 && !last_possible(v, all & ~sup, bans, cache)) continue;
                    if (remaining==1) {
                        ++last_candidates;
                        if (sup!=all) continue;
                        if (inverse_terminal) {
                            Values next=active; next.push_back(v);
                            Mask reached=seen; close(next,reached,active.size());
                            if (reached==all) { witness=std::move(next); return true; }
                            continue;
                        }
                    }
                    auto saved=undo.size();
                    std::vector<Edit> edits;
                    if (remaining>2) extend_index(v,edits);
                    auto previous_multi=multi.size();
                    if (pair_bound) for (auto edit:edits)
                        if (edit.before && !(edit.before & (edit.before-1))) multi.push_back(edit.value);
                    bool found=false;
                    if (early_pair && remaining==3 && !two_helpers_possible(all & ~sup)) {
                        // The two remaining helpers cannot cover the unresolved
                        // target equations even with all target values free.
                        // Building the next reachable frontier is unnecessary.
                        if (nodes==max_nodes) interrupted=true;
                        else ++nodes;
                    } else {
                        Values next=active; next.push_back(v);
                        Mask covered=seen; saturate(next,covered,active.size());
                        helpers.push_back(v);
                        found=visit_frontier(next,covered,sup,helpers,remaining-1);
                        helpers.pop_back();
                    }
                    undo_index(edits); multi.resize(previous_multi);
                    if (found || interrupted) return found;
                    while (undo.size()>saved) { toggle(undo.back()); undo.pop_back(); }
                    bans.insert(v); excluded.push_back(v);
                }
        }
        for (Num v:excluded) bans.erase(v);
        for (Num v:group_rejected)bans.erase(v);
        return false;
    }
    bool run_frontier(unsigned budget) {
        // Sparse ordered reachability also permits dense unary lookups.
        if(audit_state)initial_unary=unary;
        if (pair_bound) {
            for (auto [v,m]:unary) if (m & (m-1)) multi.push_back(v);
            for (const auto& [v,other]:exceptional)
                for (Num x:other) if (v<x) double_outputs.push_back({v,x,hits(v,x)});
        }
        Values active;
        Mask seen=0;
        for (Num x:seeds) if (std::find(active.begin(),active.end(),x)==active.end()) {
            active.push_back(x); seen |= goal_mask(x);
        }
        saturate(active,seen,0); undo.clear();
        Values helpers;
        return visit_frontier(active,seen,initial_supported,helpers,budget);
    }
};
