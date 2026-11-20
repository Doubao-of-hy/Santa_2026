    struct IndexedUpdate {unsigned value;unsigned goal;};
    struct Component {Mask members;unsigned present;};
    std::vector<std::vector<IndexedUpdate>> possible_edits;
    std::vector<unsigned char> initialized;
    std::vector<std::vector<unsigned>> value_components,rooted_by;
    std::vector<Component> components;
    Values anchor_stack;

    void prepare_hot() {
        if(limit>2'000'000)throw std::runtime_error("hot mode requires a bounded dense domain");
        possible_edits.resize(limit+1);initialized.resize(limit+1);
        value_components.resize(limit+1);rooted_by.resize(limit+1);
        for(const auto& item:goal_links) {
            Num v=item.first;
            if(goal_bit.count(v))continue;
            auto& edges=item.second;
            Mask reachable=hits(v,v),pending=0;
            for(Num s:seeds)reachable|=hits(v,s);
            for(unsigned i=0;i<edges.size();++i)if(edges[i])pending|=Mask(1)<<i;
            while(pending) {
                Mask component=pending&-pending,visit=component;
                while(visit) {
                    unsigned j=__builtin_ctzll(visit);visit&=visit-1;
                    Mask fresh=edges[j]&~component;
                    visit|=fresh;component|=fresh;
                }
                pending&=~component;
                if(component&reachable || !(component&(component-1)))continue;
                unsigned id=components.size();components.push_back({component,0});value_components[v].push_back(id);
                Set anchor;
                for(Mask bits=component;bits;bits&=bits-1) {
                    unsigned j=__builtin_ctzll(bits);
                    inverse(goals[j],v,[&](Num y){if(!goal_bit.count(y))anchor.insert(y);});
                }
                for(Num y:anchor)rooted_by[y].push_back(id);
            }
        }
    }
    unsigned fast_weight(Num v,Mask subset,Mask missing)const {
        unsigned weight=__builtin_popcountll(subset);
        for(unsigned id:value_components[v]) {
            auto c=components[id];
            if(!c.present && (c.members&missing)==c.members)--weight;
        }
        return weight;
    }
    // These overrides maintain the same inverse masks/partner lists as the
    // frozen traversal. The rooted component counter also follows artificial
    // candidates temporarily granted in the group and star tests.
    void extend_index(Num v,std::vector<Edit>& edits) {
        auto& updates=possible_edits[v];
        if(!initialized[v]) {
            initialized[v]=1;
            for(unsigned j=0;j<goals.size();++j)
                inverse(goals[j],v,[&](Num x){updates.push_back({static_cast<unsigned>(x),j});});
        }
        for(const auto& u:updates) {
            Mask bit=Mask(1)<<u.goal,old=dense_unary[u.value];
            if(!(old&bit)) {
                edits.push_back({u.value,u.goal,old});
                partners[u.goal].push_back(u.value);
                dense_unary[u.value]=old|bit;
            }
        }
        anchor_stack.push_back(v);
        for(auto id:rooted_by[v])++components[id].present;
    }
    void undo_index(const std::vector<Edit>& edits) {
        Search::undo_index(edits);
        Num v=anchor_stack.back();anchor_stack.pop_back();
        for(auto id:rooted_by[v])--components[id].present;
    }
