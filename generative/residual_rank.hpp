// Puzzle-level held-out training exports shallow regression trees. Each tree
// is a stump with up to two additional splits. No training runtime is needed.
#include <fstream>
struct ResidualRank {
    struct Tree {int feature[3]; float threshold[3]; float leaf[4];};
    double initial=0,weight=0;
    std::vector<Tree> trees;
    void load(const char* path,double strength){
        std::ifstream in(path);int count;
        if(!(in>>initial>>count)||count<1||count>256)throw std::runtime_error("invalid cost model");
        trees.resize(count);
        for(auto &t:trees){
            for(int j=0;j<3;++j)if(!(in>>t.feature[j]>>t.threshold[j]) || t.feature[j]<0 || t.feature[j]>=15)
                throw std::runtime_error("invalid cost-model split");
            for(float &leaf:t.leaf)if(!(in>>leaf))throw std::runtime_error("missing cost-model leaf");
        }
        weight=strength;
    }
    double predict(const std::array<float,15>& x)const{
        double sum=initial;
        for(auto &t:trees){
            int high=x[t.feature[0]]>t.threshold[0];
            int side=1+high;
            sum+=t.leaf[2*high+(x[t.feature[side]]>t.threshold[side])];
        }
        return sum;
    }
};
static ResidualRank residual_model;
