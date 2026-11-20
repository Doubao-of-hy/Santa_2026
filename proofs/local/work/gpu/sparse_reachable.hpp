// Sorted occupied 64-value blocks, with no allocation indexed by the puzzle domain.
struct SparseReachable {
    using Word=std::pair<Num,uint64_t>;
    std::vector<Word> blocks;
    auto where(Num block)const {
        return std::lower_bound(blocks.begin(),blocks.end(),block,[](const Word& entry,Num key){return entry.first<key;});
    }
    bool contains(Num v)const {
        Num block=v>>6;auto it=where(block);
        return it!=blocks.end()&&it->first==block&&(it->second&(uint64_t(1)<<(v&63)));
    }
    bool mark(Num v,bool on) {
        Num block=v>>6;uint64_t mask=uint64_t(1)<<(v&63);auto pos=where(block);
        if(pos==blocks.end()||pos->first!=block) {
            if(!on)return false;
            blocks.insert(pos,{block,mask});return true;
        }
        auto ix=pos-blocks.cbegin();auto& bits=blocks[ix].second;
        if(bool(bits&mask)==on)return false;
        bits^=mask;if(!bits)blocks.erase(blocks.begin()+ix);return true;
    }
};
