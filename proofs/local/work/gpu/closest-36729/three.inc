    bool enable_star = false;
    std::uint64_t tested_stars = 0, rejected_stars = 0;
    std::unordered_map<Num,std::vector<Mask>> goal_links;

    void prepare_stars() {
        for (unsigned i=0;i<goals.size();++i) {
            for (unsigned j=i+1;j<goals.size();++j) {
                inverse(goals[i],goals[j],[&](Num v) {
                    if (v==goals[i] || v==goals[j]) return;
                    auto& links=goal_links[v];
                    if (links.empty()) links.resize(goals.size());
                    links[i]|=Mask(1)<<j;
                    links[j]|=Mask(1)<<i;
                });
            }
        }
    }

    // Count at most the targets whose FIRST production can use x together
    // with an already paid helper, a seed, itself, or another target.
    unsigned rooted_weight(Num x, Mask subset, Mask missing, const Values& prefix) const {
        unsigned weight=__builtin_popcountll(subset);
        auto it=goal_links.find(x);
        if (weight<2 || it==goal_links.end()) return weight;
        const auto& links=it->second;
        Mask todo=subset, roots=hits(x,x);
        for (Num seed:seeds) roots|=hits(seed,x);
        for (Num previous:prefix) roots|=hits(previous,x);
        while (todo) {
            Mask wave=todo&-todo, component=wave, adjacent=0;
            while (wave) {
                unsigned j=__builtin_ctzll(wave);
                wave&=wave-1;
                adjacent|=links[j];
                Mask fresh=links[j]&subset&~component;
                component|=fresh;wave|=fresh;
            }
            // Singletons retain their full weight as a conservative shortcut.
            // A linked component with no root cannot produce its first member.
            if ((component&(component-1)) && !(roots&component) && !(adjacent&~missing)) --weight;
            todo&=~component;
        }
        return weight;
    }

    // Once x and y are fixed, each still unsupported target has to use z.
    // Its other operand is an indexed seed/target/prefix value, x, y, or z.
    bool exceptional_triple(Num x,Num y,Mask left,unsigned max_unary) const {
        if (!left) return true;
        auto covers=[&](Num z) {
            return z!=x && z!=y && !bans.count(z) &&
                   !(left&~(current(z)|hits(x,z)|hits(y,z)));
        };
        // If neither remaining edge has two outputs, at most two extra
        // targets can be covered beyond the best unary candidate.
        if (__builtin_popcountll(left)>max_unary+2) {
            for (Num fixed:{x,y}) {
                auto it=exceptional.find(fixed);
                if (it!=exceptional.end()) for (Num z:it->second) if (covers(z)) return true;
            }
            return false;
        }
        unsigned pivot=__builtin_ctzll(left);
        for (Mask rest=left&(left-1);rest;rest&=rest-1) {
            unsigned j=__builtin_ctzll(rest);
            if (partners[j].size()<partners[pivot].size()) pivot=j;
        }
        for (Num z:partners[pivot]) if (covers(z)) return true;
        bool found=false;
        for (Num fixed:{x,y}) inverse(goals[pivot],fixed,[&](Num z){if (covers(z)) found=true;});
        return found;
    }

    bool three_possible(Mask missing,const Values& prefix) {
        unsigned count=__builtin_popcountll(missing);
        if (count<7) return true;
        ++tested_stars;
        unsigned threshold=(count-3+2)/3;
        unsigned max_unary=1;
        Values pivots;
        for (Num x:multi) {
            if (bans.count(x)) continue;
            Mask subset=current(x)&missing;
            unsigned count_x=__builtin_popcountll(subset);
            max_unary=std::max(max_unary,count_x);
            if (count_x>=threshold && rooted_weight(x,subset,missing,prefix)>=threshold)
                pivots.push_back(x);
        }
        // A pair that supplies two of the missing targets is on this
        // precomputed inverse list. Its third operand may be any legal integer.
        for (const auto& p:double_outputs) {
            Mask useful=p.joint&missing;
            if (!(useful&(useful-1)) || bans.count(p.a) || bans.count(p.b)) continue;
            if (exceptional_triple(p.a,p.b,missing&~(current(p.a)|current(p.b)|p.joint),max_unary)) return true;
        }
        // Otherwise the three helper/helper edges produce at most three
        // first targets. Pigeonhole forces one of these rooted unary pivots.
        for (Num x:pivots) {
            Mask left=missing&~current(x);
            if (!left) return true;
            std::vector<Edit> edits;
            extend_index(x,edits);
            const auto old_multi=multi.size();
            for (const auto& e:edits)
                if (e.before && !(e.before&(e.before-1))) multi.push_back(e.value);
            bool okay=two_helpers_possible(left);
            undo_index(edits);
            multi.resize(old_multi);
            if (okay) return true;
        }
        ++rejected_stars;
        return false;
    }
