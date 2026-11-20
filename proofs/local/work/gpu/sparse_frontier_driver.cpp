#define main legacy_exact_main
#include "../../exact_helpers.cpp"
#undef main
#include "sparse_reachable.hpp"
#include "sparse_frontier.hpp"

int main(int argc,char**argv){
    if(argc!=8)return 2;
    std::string mode=argv[1];SparseFrontier s;
    if(mode!="generic"&&mode!="sparse"&&mode!="pair"&&mode!="audit")return 2;
    s.inverse_terminal=mode=="pair"||mode=="audit";s.pair_bound=s.inverse_terminal;s.early_pair=s.pair_bound;s.audit_state=mode=="audit";
    s.shard=std::stoul(argv[2]);s.shards=std::stoul(argv[3]);s.shard_two=std::stoul(argv[4]);s.shards_two=std::stoul(argv[5]);s.shard_three=std::stoul(argv[6]);s.shards_three=std::stoul(argv[7]);
    if(!s.shards||!s.shards_two||!s.shards_three||s.shard>=s.shards||s.shard_two>=s.shards_two||s.shard_three>=s.shards_three)return 2;
    unsigned ns,nt,h;if(!(std::cin>>s.limit>>ns>>nt>>h>>s.max_nodes)||s.limit<=4000000||s.limit>1000000000000000000LL||ns<1||nt>64)return 2;
    if((s.shards_two>1&&h<4)||(s.shards_three>1&&h<5))return 2;
    s.seeds.resize(ns);s.goals.resize(nt);for(Num&x:s.seeds)std::cin>>x;for(Num&x:s.goals)std::cin>>x;
    std::sort(s.goals.begin(),s.goals.end());s.goals.erase(std::unique(s.goals.begin(),s.goals.end()),s.goals.end());s.prepare();
    bool found=mode=="generic"?s.run(h):s.run_frontier(h);
    std::cout<<(found?"FOUND":s.interrupted?"UNKNOWN":"UNSAT")<<" "<<s.nodes<<" "<<s.last_candidates<<" "<<s.peak_blocks<<"\n";
    if(found){for(Num v:s.witness)std::cout<<v<<" ";std::cout<<"\n";}
}
