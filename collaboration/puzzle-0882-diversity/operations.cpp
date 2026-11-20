#define main diversity_entry_point
#include "bundle_exact.cpp"
#undef main
#include <random>
#include <stdexcept>

// Independently evaluate the legal forward arithmetic using 64-bit arithmetic.
// The actual bound is 93524, so even a product of two operands fits int64.
template<class F> void forward(Num a, Num b, Num limit, F record) {
    auto keep=[&](Num v){if(v>=1&&v<=limit&&v!=a&&v!=b)record(v);};
    keep(a+b); keep(a*b); keep(a-b); keep(b-a);
    if(a%b==0)keep(a/b);
    if(b%a==0)keep(b/a);
}
int main(){
    Search s;
    unsigned nseed,ngoal,ndonor;
    std::cin>>s.lim>>nseed>>ngoal>>ndonor;
    s.seeds=s.read(nseed);s.goals=s.read(ngoal);s.read(ndonor,&s.donors);s.prepare();
    const Mask all=(Mask(1)<<s.vals.size())-1;
    unsigned long long tests=0,reachtests=0,closures=0;
    auto mark=[&](Num a,Num b){Mask out=0; forward(a,b,s.lim,[&](Num v){out|=s.bits[v];});return out;};
    for(Num y=1;y<=s.lim;++y){
        auto square=mark(y,y);
        for(size_t i=0;i<s.vals.size();++i){
            auto direct=square|mark(y,s.vals[i]);
            if(direct!=s.cover(y,all,Mask(1)<<i)) throw std::runtime_error("cover mismatch");
            ++tests;
        }
    }
    std::mt19937 rng(150882);
    for(unsigned j=0;j<120;++j){
        Mask known=s.seeds; s.must=s.goals; s.path.clear();
        for(size_t i=nseed+ngoal;i<s.vals.size();++i)if(rng()%2)s.must|=Mask(1)<<i;
        for(size_t i=nseed;i<s.vals.size();++i)if(((Mask(1)<<i)&s.must)&&rng()%4==0)known|=Mask(1)<<i;
        while(s.path.size()<j%4){
            Num y=1+rng()%s.lim;
            if(!s.bits[y]&&std::find(s.path.begin(),s.path.end(),y)==s.path.end())s.path.push_back(y);
        }
        auto known_values=[&](Mask m){
            Values numbers=s.path;
            for(size_t i=0;i<s.vals.size();++i)if((Mask(1)<<i)&m)numbers.push_back(s.vals[i]);
            return numbers;
        };
        if(j<16){
            auto numbers=known_values(known);std::vector<char> direct(s.lim+1,0);
            for(Num a:numbers)for(Num b:numbers) forward(a,b,s.lim,[&](Num v){direct[v]=1;});
            for(Num a:numbers)direct[a]=0;
            for(Num y=1;y<=s.lim;++y){
                if(bool(direct[y])!=s.reachable(y,known))throw std::runtime_error("reachability mismatch");
                ++reachtests;
            }
        }
        auto want=known;
        for(;;){
            auto ns=known_values(want);Mask newmask=want;
            for(Num a:ns)for(Num b:ns)newmask|=s.must&mark(a,b);
            if(newmask==want)break;
            want=newmask;
        }
        if(want!=s.close(known,s.path))throw std::runtime_error("closure mismatch");
        ++closures;
    }
    std::cout<<tests<<" "<<reachtests<<" "<<closures<<"\n";
}
