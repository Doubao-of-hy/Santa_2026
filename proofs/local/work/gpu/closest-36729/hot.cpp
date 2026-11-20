#define main legacy_exact_main
#include "../../../exact_helpers.cpp"
#undef main
#include "../sparse_reachable.hpp"
#include "hot_dense.hpp"


template<class S>
int solve(Num limit,const std::string& mode,int argc,char** argv) {
    S s;
    s.limit=limit; if(const char* width=std::getenv("SANTA_GROUP_WIDTH"))s.group_width=std::max(2,std::atoi(width));
    s.inverse_terminal=true;
    s.pair_bound=true;
    s.early_pair=true;
    s.enable_star=mode=="star";
    s.shard=std::stoul(argv[2]);s.shards=std::stoul(argv[3]);
    s.shard_two=std::stoul(argv[4]);s.shards_two=std::stoul(argv[5]);
    s.shard_three=std::stoul(argv[6]);s.shards_three=std::stoul(argv[7]);
    if (!s.shards || s.shard>=s.shards || !s.shards_two || s.shard_two>=s.shards_two || !s.shards_three || s.shard_three>=s.shards_three) return 2;
    unsigned n,m,h;
    if (!(std::cin>>n>>m>>h>>s.max_nodes) || !n || m>64 || h>4096 ||
        (s.shards_two>1 && h<4) || (s.shards_three>1 && h<5)) return 2;
    s.seeds.resize(n);s.goals.resize(m);
    for (Num& v:s.seeds) if (!(std::cin>>v) || v<1 || v>limit) return 2;
    for (Num& v:s.goals) if (!(std::cin>>v) || v<1 || v>limit) return 2;
    std::sort(s.goals.begin(),s.goals.end());
    s.goals.erase(std::unique(s.goals.begin(),s.goals.end()),s.goals.end());
    s.prepare();
    if (limit>4'000'000 && limit<=20'000'000) {
        s.dense_unary.assign(limit+1,0);s.dense_goals.assign(limit+1,0);
        for (const auto& [v,bits]:s.unary) s.dense_unary[v]=bits;
        for (const auto& [v,bits]:s.goal_bit) s.dense_goals[v]=bits;
    }
    if (s.enable_star) {s.prepare_stars();s.prepare_hot();}
    bool found=s.run_frontier(h);
    std::cout<<(found?"FOUND":s.interrupted?"UNKNOWN":"UNSAT")<<" "<<s.nodes<<" "<<s.last_candidates
             <<" "<<s.tested_stars<<" "<<s.rejected_stars<<" "<<s.grouped_calls<<" "<<s.grouped_rejections<<" "<<s.removed_next<<"\n";
    if (found) {for (Num v:s.witness) std::cout<<v<<" ";std::cout<<"\n";}
    return 0;
}

int main(int argc,char** argv) {
    Num cap;
    if (argc!=8 || !(std::cin>>cap) || cap<1 || cap>1'000'000'000'000'000'000LL) return 2;
    std::string mode=argv[1];
    if (mode!="star" && mode!="plain") return 2;
    if(cap>2'000'000 || mode!="star")return 2; return solve<DenseStar>(cap,mode,argc,argv);
}
