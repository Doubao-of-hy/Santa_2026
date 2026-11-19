// Rebuild neighboring targets whose original traces reuse the same helpers as
// a recovered cell. Both modeled and previously unmodeled outputs may move.
void extend_groups(U modeled){
    const int count=net.goals.size();
    if(count<2 || count>=64)return;
    vector<set<int>> ancestry(count);
    map<int,int> coverage;
    for(int i=0;i<count;++i){
        vector<int> stack{net.goals[i]};
        while(!stack.empty()){
            int x=stack.back();stack.pop_back();
            if(net.base[x]<0||!ancestry[i].insert(x).second)continue;
            auto e=net.edges[net.base[x]];stack.push_back(e.a);stack.push_back(e.b);
        }
        for(int v:ancestry[i])++coverage[v];
    }
    auto current=groups;
    map<U,double> offers;
    for(U group:current){
        int n=__builtin_popcountll(group);
        if(n<1 || n>count/2)continue;
        map<int,int> members;
        for(int i=0;i<count;++i)if(group&(U(1)<<i))for(int v:ancestry[i])++members[v];
        vector<pair<double,int>> peers;
        for(int i=0;i<count;++i)if(!(group&(U(1)<<i))){
            double gain=0;
            for(int v:ancestry[i]){
                auto it=members.find(v);
                if(it==members.end()||coverage[v]<=1)continue;
                int outside=coverage[v]-it->second;
                // Once the last other user moves, the intermediate can
                // disappear. Ubiquitous initial constants have low weight.
                if(outside==1)gain+=2.5/(1+.06*coverage[v]);
                else if(outside<=3)gain+=.6/(outside*(1+.1*coverage[v]));
            }
            if(gain>0)peers.emplace_back(gain,i);
        }
        sort(peers.rbegin(),peers.rend());U more=group;double total=0;
        for(size_t j=0;j<min<size_t>(3,peers.size());++j){
            auto [score,i]=peers[j];more|=U(1)<<i;total+=score;
            double rating=total/(.8+n+j)*((modeled&(U(1)<<i))?1.:1.4);
            offers[more]=max(offers[more],rating);
        }
    }
    vector<pair<double,U>> ranked;for(auto [g,s]:offers)ranked.emplace_back(s,g);
    sort(ranked.rbegin(),ranked.rend());
    for(int i=0;i<min<int>(18,ranked.size());++i)groups.push_back(ranked[i].second);
    groups.push_back((U(1)<<count)-1);
}
