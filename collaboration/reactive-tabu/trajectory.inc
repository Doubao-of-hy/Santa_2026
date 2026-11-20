    // Local extension to Wang Jakie's incremental solver. Value and recipe identify a move.
    using Move = std::tuple<Value, char, Value, Value>;
    static Move move_for(Value v, Recipe r) {
        if ((r.op=='+' || r.op=='*') && r.a>r.b) std::swap(r.a,r.b);
        return {v,r.op,r.a,r.b};
    }
    static uint64_t hash_move(const Move& key) {
        auto [v,op,a,b] = key;
        auto mix=[](uint64_t x) {
            x^=x>>30; x*=UINT64_C(0xbf58476d1ce4e5b9);
            x^=x>>27; x*=UINT64_C(0x94d049bb133111eb);
            return x^(x>>31);
        };
        return mix(v)^mix(uint64_t(op)*31+a)^mix(uint64_t(b)+UINT64_C(15485863));
    }
    Tape improve(const std::vector<Tape>& tapes) {
        Tape best=tapes.front();
        Graph champion=graph_from(best), current=champion;
        const bool reactive=max_neighbors!=0;
        std::map<Move,int> prohibited;
        std::unordered_map<uint64_t,int> visits;
        int tenure=4,stalled=0,blocked=0,accepted=0,revisited=0,proposals=0;
        for (int step=0;proposals<rounds;++step) {
            if(stalled>=12) {current=champion;prohibited.clear();stalled=0;}
            for(auto it=prohibited.begin();it!=prohibited.end();)
                if(it->second<=step) it=prohibited.erase(it); else ++it;
            size_t chosen_length=std::numeric_limits<size_t>::max();
            int chosen_edits=-1;
            Graph chosen;
            uint64_t chosen_hash=0;
            for(int j=0;j<3 && proposals<rounds;++j,++proposals) {
                Graph candidate=current;
                std::shuffle(targets.begin(),targets.end(),rng);
                const size_t cap=best.size()+(stalled>=5?3:2);
                perturb(candidate,cap,3+rng()%8);
                rotate(candidate,cap);
                Tape program;
                if(!compile(candidate,program)||program.size()>cap)continue;
                knockout(candidate,program);
                const bool aspiration=program.size()<best.size();
                if(aspiration){best=program;champion=candidate;}
                int edits=0;bool tabu=false;uint64_t hash=0;
                for(const auto& [v,r]:candidate){
                    if(!r.op)continue;
                    Move key=move_for(v,r);hash^=hash_move(key);
                    auto old=current.find(v);
                    if(old!=current.end() && move_for(v,old->second)==key)continue;
                    ++edits;
                    if(reactive && prohibited.count(key))tabu=true;
                }
                // Count lost recipes as well as replacements so a pure deletion can advance.
                for(const auto& [v,r]:current)
                    if(r.op && candidate.find(v)==candidate.end())++edits;
                if(tabu && !aspiration){++blocked;continue;}
                if(edits && (program.size()<chosen_length ||
                   (program.size()==chosen_length && edits>chosen_edits))) {
                    chosen_length=program.size();chosen_edits=edits;
                    chosen=std::move(candidate);chosen_hash=hash;
                }
            }
            ++stalled;
            if(chosen_edits<0)continue;
            if(chosen_length<best.size()+1)stalled=std::min(stalled,5);
            if(reactive) {
                auto visit=visits.find(chosen_hash);
                if(visit!=visits.end() && step-visit->second<=8) {
                    ++revisited;tenure=std::min(12,tenure+2);
                } else if(step%5==0)tenure=std::max(3,tenure-1);
                visits[chosen_hash]=step;
                for(const auto& [v,r]:current){
                    if(!r.op)continue;
                    auto now=chosen.find(v);
                    auto key=move_for(v,r);
                    if(now==chosen.end() || move_for(v,now->second)!=key)
                        prohibited[key]=step+1+tenure;
                }
            }
            current=std::move(chosen);++accepted;
        }
        std::cerr<<proposals<<" "<<accepted<<" "<<blocked<<" "<<revisited<<"\n";
        return best;
    }
