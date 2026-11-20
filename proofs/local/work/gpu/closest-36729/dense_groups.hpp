// Sparse iteration over a dense, reversible set of one-operation neighbors.
// The node order and completed-branch exclusions match the original search.
struct DenseStar : DenseSearch {
    std::vector<uint64_t> words, occupied;
    std::vector<Num> undo;
    struct Bans {
        std::vector<uint8_t> bits;
        bool count(Num n) const { return bits[n]; }
        void insert(Num n) { bits[n]=1; }
        void erase(Num n) { bits[n]=0; }
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
            if (!(words[v>>6] & (uint64_t(1)<<(v&63))) || bans.count(v)) continue;
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

    void toggle(Num value) {
        auto index = value >> 6;
        words[index] ^= uint64_t(1) << (value & 63);
        auto& word = occupied[index >> 6];
        auto bit = uint64_t(1) << (index & 63);
        if (words[index]) word |= bit;
        else word &= ~bit;
    }
    void mark(Num value, bool on) {
        if (bool((words[value >> 6] >> (value & 63)) & 1) != on) {
            toggle(value);
            undo.push_back(value);
        }
    }
    void saturate(Values& active, Mask& seen, std::size_t start) {
        for (std::size_t i=start; i<active.size(); ++i) {
            Mask next=0;
            for (std::size_t j=0; j<=i; ++j) {
                auto a=active[i], b=active[j];
                auto emit=[&](Num x) {
                    mark(x,true);
                    if (x!=a && x!=b) next |= dense_goals[x];
                };
                if (a+b<=limit) emit(a+b);
                if (a*b<=limit) emit(a*b); // this engine is limited to four million
                if (a<b) std::swap(a,b);
                if (a>b) emit(a-b);
                if (a%b==0) emit(a/b);
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
        for (std::size_t page=0; page<occupied.size(); ++page) {
            for (auto blocks=occupied[page]; blocks; blocks &= blocks-1) {
                auto block=(page<<6)+__builtin_ctzll(blocks);
                for (auto bits=words[block]; bits; bits &= bits-1) {
                    Num v=(block<<6)+__builtin_ctzll(bits);
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
        }
        for (Num v:excluded) bans.erase(v);
        for (Num v:group_rejected)bans.erase(v);
        return false;
    }
    bool run_frontier(unsigned budget) {
        if (limit>4000000) return run(budget);
        words.assign((limit>>6)+1,0);
        occupied.assign((words.size()+63)>>6,0);
        bans.bits.assign(limit+1,0);
        if (pair_bound) {
            for (auto [v,m]:unary) if (m & (m-1)) multi.push_back(v);
            for (const auto& [v,other]:exceptional)
                for (Num x:other) if (v<x) double_outputs.push_back({v,x,hits(v,x)});
        }
        Values active;
        Mask seen=0;
        for (Num x:seeds) if (std::find(active.begin(),active.end(),x)==active.end()) {
            active.push_back(x); seen |= dense_goals[x];
        }
        saturate(active,seen,0); undo.clear();
        Values helpers;
        return visit_frontier(active,seen,initial_supported,helpers,budget);
    }
};
