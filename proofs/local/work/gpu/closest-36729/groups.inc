    unsigned group_width=8;
    std::uint64_t grouped_calls=0,grouped_rejections=0,removed_next=0;

    void group_filter(const Values& active,const Values& prefix,Mask missing,Set& rejected) {
        if(__builtin_popcountll(missing)<10)return;
        Set options;
        for(std::size_t i=0;i<active.size();++i)for(std::size_t j=0;j<=i;++j)
            operations(active[i],active[j],[&](Num v){options.insert(v);});
        for(Num v:active)options.erase(v);
        std::vector<std::pair<Mask,Num>> ordered;
        for(Num v:options)if(!bans.count(v))ordered.push_back({current(v)&missing,v});
        std::sort(ordered.begin(),ordered.end());
        Values relaxed=prefix;
        for(std::size_t lo=0;lo<ordered.size();lo+=group_width) {
            auto hi=std::min(ordered.size(),lo+group_width);
            if(hi-lo<2)continue;
            Mask paid=0;
            for(auto j=lo;j<hi;++j)paid|=ordered[j].first;
            if(__builtin_popcountll(missing&~paid)<7)continue;
            ++grouped_calls;
            const auto saved=multi.size();
            std::vector<std::vector<Edit>> journal(hi-lo);
            for(auto j=lo;j<hi;++j) {
                Num v=ordered[j].second;
                auto& edits=journal[j-lo];
                extend_index(v,edits);
                for(const auto& e:edits)if(e.before && !(e.before&(e.before-1)))multi.push_back(e.value);
                relaxed.push_back(v);
            }
            bool impossible=!three_possible(missing&~paid,relaxed);
            for(auto i=journal.rbegin();i!=journal.rend();++i)undo_index(*i);
            multi.resize(saved);relaxed.resize(prefix.size());
            if(impossible) {
                ++grouped_rejections;
                for(auto j=lo;j<hi;++j)rejected.insert(ordered[j].second);
                removed_next+=hi-lo;
            }
        }
    }
