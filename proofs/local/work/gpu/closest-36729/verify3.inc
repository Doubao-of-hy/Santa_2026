    bool verify_tail=false;
    Values candidates_with_two;
    struct Joint {Num a,b;Mask support;};
    std::vector<Joint> joints;
    std::uint64_t verify_tests=0,verify_rejections=0;
    struct Network {Mask targets; unsigned anchors;};
    std::vector<Network> networks;
    std::unordered_map<Num,std::vector<unsigned>> price_groups,starts_group;

    void prepare_networks() {
        for(const auto& item:unary) {
            Num x=item.first;
            if (!(item.second&(item.second-1)) || goal_bit.count(x))continue;
            std::vector<unsigned> label(goals.size());
            for(unsigned j=0;j<goals.size();++j)label[j]=j;
            auto find=[&](unsigned v) {while(label[v]!=v)v=label[v];return v;};
            for(unsigned j=0;j<goals.size();++j) {
                for(Mask m=hits(x,goals[j]);m;m&=m-1) {
                    unsigned k=__builtin_ctzll(m);
                    label[find(k)]=find(j);
                }
            }
            Mask initial=hits(x,x);
            for(Num seed:seeds)initial|=hits(x,seed);
            std::vector<Mask> component(goals.size());
            for(unsigned j=0;j<goals.size();++j)component[find(j)]|=Mask(1)<<j;
            for(Mask c:component) {
                if (!(c&(c-1)) || (c&initial))continue;
                unsigned id=networks.size();networks.push_back({c,0});price_groups[x].push_back(id);
                Set extra;
                for(Mask m=c;m;m&=m-1) {
                    unsigned k=__builtin_ctzll(m);
                    inverse(goals[k],x,[&](Num v){if(!goal_bit.count(v))extra.insert(v);});
                }
                for(Num v:extra)starts_group[v].push_back(id);
            }
        }
    }
    void ground_with(Num v,bool add) {
        auto it=starts_group.find(v);
        if(it!=starts_group.end())for(unsigned j:it->second) {
            if(add)++networks[j].anchors;
            else {if(!networks[j].anchors)throw std::logic_error("ground count");--networks[j].anchors;}
        }
    }
    unsigned rooted_units(Num v,Mask missing) const {
        unsigned result=__builtin_popcountll(current(v)&missing);
        auto it=price_groups.find(v);
        if(it!=price_groups.end())for(unsigned j:it->second) {
            const auto& net=networks[j];
            // Every component fully contained in the still-unsupported goals
            // must enter from outside unless an actual prefix helper grounds it.
            if(!net.anchors && !(net.targets&~missing)) --result;
        }
        return result;
    }

    // This verifier independently reasons about a possible SET of three helpers.
    // It does not edit any inverse tables to run a nested pair subproblem.
    bool can_finish_three(const Values& active,Mask seen,Mask missing,const Set& banned) {
        const unsigned m=__builtin_popcountll(missing);
        if (m<7) return true;
        ++verify_tests;
        auto allowed=[&](Num v) {return !banned.count(v) && !goal_bit.count(v);};
        auto unary_for=[&](Num v,Num extra){return current(v)|hits(v,extra);};
        std::array<Values,65> buckets;
        unsigned maximum=1;
        const unsigned primary=(m-1)/3;
        for (Num v:candidates_with_two) {
            if (!allowed(v))continue;
            unsigned n=rooted_units(v,missing);
            if (n>=2) {buckets[n].push_back(v);maximum=std::max(maximum,n);}
        }
        auto rooted=[&](Num a,Num b,Num c) {
            Values free=active;
            for (Num v:{a,b,c}) if (v && std::find(free.begin(),free.end(),v)==free.end()) free.push_back(v);
            Mask actual=seen;
            close(free,actual,active.size());
            return actual==all;
        };
        // Check every possible last helper after fixing an unordered pair.
        auto complete=[&](Num a,Num b,Mask need) {
            // A third helper may be necessary solely to start a cycle of
            // target equations. Returning true here preserves that possibility.
            if (!need) return true;
            auto test=[&](Num c) {
                if (!allowed(c) || c==a || c==b) return false;
                return !(need&~(current(c)|hits(c,a)|hits(c,b))) && rooted(a,b,c);
            };
            unsigned count=__builtin_popcountll(need);
            if (count>=4) {
                for (Num fixed:{a,b}) {
                    auto it=exceptional.find(fixed);
                    if (it!=exceptional.end())for (Num c:it->second)if(test(c))return true;
                }
                // The two ordinary remaining pair edges contribute at most
                // two targets beyond c's unary goal mask.
                for (unsigned w=count-2;w<=maximum;++w) for (Num c:buckets[w]) {
                    if ((unsigned)__builtin_popcountll(current(c)&need)>=count-2 && test(c))return true;
                }
                return false;
            }
            unsigned pivot=__builtin_ctzll(need);
            for (Mask rest=need&(need-1);rest;rest&=rest-1) {
                unsigned k=__builtin_ctzll(rest);
                if (partners[k].size()<partners[pivot].size()) pivot=k;
            }
            for (Num c:partners[pivot]) if(test(c))return true;
            bool ok=false;
            inverse(goals[pivot],a,[&](Num c){if(!ok && test(c))ok=true;});
            inverse(goals[pivot],b,[&](Num c){if(!ok && test(c))ok=true;});
            return ok;
        };
        for (const auto& edge:joints) {
            if (__builtin_popcountll(edge.support&missing)<2 || !allowed(edge.a) || !allowed(edge.b)) continue;
            if (complete(edge.a,edge.b,missing&~(current(edge.a)|current(edge.b)|edge.support))) return true;
        }
        // Remaining cases: each of ab,bc,ac produces at most one missing goal.
        // At least one helper has ceil((m-3)/3) ordinary unary supports.
        for (unsigned weight=primary;weight<=maximum;++weight) for (Num a:buckets[weight]) {
            const Mask after=missing&~current(a);
            unsigned n=__builtin_popcountll(after);
            if (n<4) return true;
            // With a granted free, only the bc edge is still unaccounted for.
            // Any double-output bc was already checked as an exceptional pair.
            const unsigned secondary=n/2;
            auto attempt=[&](Num b) {
                if (b==a || !allowed(b))return false;
                Mask cover=unary_for(b,a)&after;
                return (unsigned)__builtin_popcountll(cover)>=secondary && complete(a,b,after&~cover);
            };
            // If b gains no new unary output from a, it is already on the
            // multi-unary list. Otherwise b is an inverse image of (goal,a).
            for (unsigned w=secondary;w<=maximum;++w) for (Num b:buckets[w]) if(attempt(b))return true;
            bool ok=false;
            for (Mask rest=after;rest && !ok;rest&=rest-1) {
                unsigned j=__builtin_ctzll(rest);
                inverse(goals[j],a,[&](Num b){if(!ok && attempt(b))ok=true;});
            }
            if (ok)return true;
        }
        ++verify_rejections;
        return false;
    }
