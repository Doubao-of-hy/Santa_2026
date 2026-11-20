// Schedule by selecting an arithmetic recipe when its inputs are resident.
// Each possible eviction gets a bit lane; prohibit reconstructing dropped
// values and ensure all still-unseen goals remain derivable after that eviction.
#define main value_exchange_entry
#include "value_exchange.cpp"
#undef main
struct LiveBank : Search {
    vector<vector<Edge>> recipes;
    vector<int> warm,mayBan;vector<I> primary;
    int slots,tries=0,longest=0,peakProgress=0;mt19937 rng;
    struct Ready {int id;Edge recipe;int score;};
    U droppable(const vector<char>& done,const vector<int>& live,int added){
        int z=live.size();U all=z==64?~U(0):(U(1)<<z)-1;
        vector<U> have(n);for(int j=0;j<z;j++)have[live[j]]=all&~(U(1)<<j);have[added]=all;
        U changed;
        do{changed=0;for(auto& e:base){
            if(done[e.v]||e.v==added)continue;
            U got=have[e.a]&have[e.b]&~have[e.v];have[e.v]|=got;changed|=got;
        }}while(changed);
        U out=all;for(int t:goalids)if(!done[t]&&t!=added)out&=have[t];
        return out;
    }
    vector<Op> attempt(int round,const vector<int>& banned){
        vector<char> done(n),available(n);vector<int> live=seedids;vector<Op> tape;
        for(int s:seedids)done[s]=available[s]=1;
        for(int v:banned)done[v]=1;
        int jitter=18+(round%7)*10;
        vector<int> guide=warm;
        for(int i=0;i<n;i++)guide[i]+=int(rng()%jitter)-jitter/2;
        for(int t=0;t<n;t++){
            bool solved=true;int hit=0;for(int g:goalids){solved&=done[g];hit+=done[g];}
            peakProgress=max(peakProgress,hit);if(solved)return tape;
            vector<int> uses(n),mandatory(n);vector<Ready> options;
            for(int v=0;v<n;v++)if(!done[v]){
                Edge pick{};int found=0;int left=-1,right=-1;
                for(auto e:recipes[v]){
                    if((done[e.a]&&!available[e.a])||(done[e.b]&&!available[e.b]))continue;
                    uses[e.a]++;if(e.b!=e.a)uses[e.b]++;
                    if(left==-1){left=e.a;right=e.b;}else{
                        if(left!=e.a&&left!=e.b)left=-2;if(right!=e.a&&right!=e.b)right=-2;
                    }
                    if(available[e.a]&&available[e.b]){found++;if(int(rng()%found)==0)pick=e;}
                }
                if(left>=0)mandatory[left]++;
                if(right>=0&&right!=left)mandatory[right]++;
                if(found)options.push_back({v,pick,0});
            }
            vector<int> kept;
            for(int v:live){if(uses[v])kept.push_back(v);else available[v]=0;}
            live=move(kept);
            if(options.empty())return {};
            int earliest=n*3;for(auto& o:options)earliest=min(earliest,guide[o.id]);
            for(auto& o:options){
                int a=o.recipe.a,b=o.recipe.b;
                int freed=(uses[a]<=1)+(a!=b&&uses[b]<=1);
                int late=(mandatory[a]<=1)+(a!=b&&mandatory[b]<=1);
                int weight=round%4==0?13:round%4==1?3:7;
                o.score=-min(140,guide[o.id]-earliest)*weight+35*freed+10*late+int(rng()%75);
            }
            sort(options.begin(),options.end(),[](auto& a,auto& b){return a.score>b.score;});
            int chosen=-1,evict=-1,score=-100000,checked=0;
            for(int k=0;k<int(options.size());k++){
                auto &o=options[k];
                if(int(live.size())<slots){chosen=k;break;}
                U valid=droppable(done,live,o.id);
                if(!valid)continue;
                int flexibility=__builtin_popcountll(valid);
                int priority=o.score+min(flexibility,8)*13;
                if(priority>score){
                    score=priority;chosen=k;int best=-100000;
                    while(valid){int j=__builtin_ctzll(valid);valid&=valid-1;int v=live[j];
                        int penalty=min(65,uses[v])*2+min(20,mandatory[v])*14;
                        int worth=int(rng()%45)-penalty;
                        if(worth>best){best=worth;evict=j;}
                    }
                }
                if(++checked>=4)break;
            }
            if(chosen<0)return {};
            auto e=options[chosen].recipe;int v=e.v;
            tape.push_back({values[v],values[e.a],values[e.b],e.op});
            if(evict>=0){available[live[evict]]=0;live.erase(live.begin()+evict);}
            live.push_back(v);available[v]=done[v]=1;
            longest=max(longest,int(tape.size()));
        }
        for(int g:goalids)if(!done[g])return {};return tape;
    }
    vector<Op> solve(int rounds,unsigned seed,int target=0){
        rng.seed(seed);populate(false);recipes.resize(n);for(auto e:base)recipes[e.v].push_back(e);
        warm.resize(n);for(int i=0;i<n;i++)warm[i]=i;
        unordered_set<I> preferred(primary.begin(),primary.end());
        if(target)for(auto& batch:batches){
            U valid=batch.live;for(int g:goalids)valid&=batch.reach[g];
            while(valid){int j=__builtin_ctzll(valid);valid&=valid-1;int v=batch.banned[j];
                if(preferred.count(values[v]))mayBan.push_back(v);
            }
        }
        vector<Op> best;
        for(int k=0;k<rounds;k++){
            vector<int> deleted;
            if(target&&!mayBan.empty()&&k%5){
                shuffle(mayBan.begin(),mayBan.end(),rng);int count=min<int>(mayBan.size(),1+k%3);
                deleted.assign(mayBan.begin(),mayBan.begin()+count);
            }
            tries++;auto tape=attempt(k,deleted);if(tape.empty())continue;
            if(!target)return tape;
            unordered_set<I> used(goals.begin(),goals.end());
            vector<Op> trimmed;
            for(auto it=tape.rbegin();it!=tape.rend();it++)if(used.count(it->v)){
                used.insert(it->a);used.insert(it->b);trimmed.push_back(*it);
            }
            if(int(trimmed.size())>=target||(!best.empty()&&trimmed.size()>=best.size()))continue;
            reverse(trimmed.begin(),trimmed.end());best=move(trimmed);
        }
        return best;
    }
};
int main(int argc,char**argv){
    ios::sync_with_stdio(false);cin.tie(nullptr);string id;int ns,nt,nop;
    while(cin>>id){
        LiveBank s;cin>>s.cap>>s.slots>>ns>>nt>>nop;s.seeds.resize(ns);s.goals.resize(nt);
        for(auto&v:s.seeds)cin>>v;for(auto&v:s.goals)cin>>v;
        for(int i=0;i<nop;i++){Op e;cin>>e.v>>e.op>>e.a>>e.b;s.original.push_back(e);}
        unsigned seed=argc>2?stoul(argv[2]):31793;for(char c:id)seed=seed*137+unsigned(c);
        int target=argc>3?stoi(argv[3]):0;
        if(target){int cnt;cin>>cnt;s.primary.resize(cnt);for(auto&v:s.primary)cin>>v;}
        auto tape=s.solve(argc>1?stoi(argv[1]):160,seed,target);
        cout<<s.tries<<' '<<s.longest<<' '<<s.peakProgress<<' '<<tape.size()<<'\n';
        for(auto e:tape)cout<<e.v<<' '<<e.op<<' '<<e.a<<' '<<e.b<<'\n';
    }
}
