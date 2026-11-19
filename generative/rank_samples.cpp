// Produce verified upper-bound teaching examples for a residual-cost heuristic.
// The input contains only stages of independent local constructions.
#define RUDOLPH_NO_MAIN
#include "rudolph.cpp"
int main(){
    ios::sync_with_stdio(false);cin.tie(nullptr);
    WIDTH=3;ALPHA=.18;DISTANCE_GUIDE=true;
    string pid;int stage,leaf_count,query_count;Int limit;
    Dict dictionary;
    while(cin>>pid>>stage>>limit>>leaf_count>>query_count){
        vector<Int> leaves(leaf_count);for(Int &v:leaves)cin>>v;
        Puzzle p;p.lim=limit;p.have.insert(leaves.begin(),leaves.end());
        dictionary.lim=limit;dictionary.known=&p.have;dictionary.build(leaves);
        for(int j=0;j<query_count;++j){
            Int value;int upper,teacher;cin>>value>>upper>>teacher;
            if(dictionary.h.get(value)>=0)continue;
            if(teacher){
                Search search(dictionary);search.run(value);
                if(search.end>=0){
                    p.pick(dictionary,search);
                    upper=min(upper,p.true_cost(dictionary,search,search.end,search.term));
                }
            }
            if(upper<1||upper>24)continue;
            cout<<pid<<','<<stage<<','<<upper;
            for(float x:dictionary.features(value))cout<<','<<x;
            cout<<'\n';
        }
    }
}
