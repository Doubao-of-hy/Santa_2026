// Recombine neutral descendants of the same original tape. Explore the
// shared arithmetic value space by maximizing feasible simultaneous deletions.
struct SubsetBreeder : Search {
    int remaining=0,bound=0;
    vector<Op> chosen;
    bool reachable(const vector<char>& allow){
        vector<char> have(n);for(int v:seedids)have[v]=1;bool changed;
        do {changed=false;for(auto e:base)if(!have[e.v]&&allow[e.v]&&have[e.a]&&have[e.b]){
            have[e.v]=1;changed=true;
        }}while(changed);
        for(int v:goalids)if(!have[v])return false;return true;
    }
    void consider(const vector<char>& allow){
        vector<int> banned;
        for(int v:optional)if(!allow[v])banned.push_back(v);
        auto tape=witness(nullptr,banned);
        if(!tape.empty()&&int(tape.size())<bound){bound=tape.size();chosen=move(tape);}
    }
    void branch(int index,const vector<int>& choices,int stillPaid,vector<char>& allow){
        // Every unexplored decision can save at most one operation.
        if(!remaining||stillPaid-int(choices.size())+index>=bound)return;
        if(index==int(choices.size())){consider(allow);return;}
        remaining--;int v=choices[index];allow[v]=0;
        if(reachable(allow))branch(index+1,choices,stillPaid-1,allow);
        allow[v]=1;branch(index+1,choices,stillPaid,allow);
    }
    Tape run(const vector<I>& start,const vector<I>& target,I limit,const Tape& a,const Tape& b,mt19937& rng){
        seeds=start;goals=target;cap=limit;bound=min(a.size(),b.size())+1;
        unordered_set<I> merged;for(const Tape* tape:{&a,&b})for(auto e:*tape)
            if(merged.insert(e.v).second)original.push_back(e);
        populate(false);vector<int> choices;
        for(auto& batch:batches){
            U bits=batch.live;for(int t:goalids)bits&=batch.reach[t];
            while(bits){int j=__builtin_ctzll(bits);bits&=bits-1;choices.push_back(batch.banned[j]);}
        }
        vector<char> allow(n,1);
        for(int attempt=0;attempt<5;attempt++){
            shuffle(choices.begin(),choices.end(),rng);
            fill(allow.begin(),allow.end(),1);
            for(int v:choices){allow[v]=0;if(!reachable(allow))allow[v]=1;}
            consider(allow);
        }
        fill(allow.begin(),allow.end(),1);
        remaining=190;
        branch(0,choices,original.size(),allow);
        return move(chosen);
    }
};
