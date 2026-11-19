// Recover latent factors or outputs as (earlier factor + shift) * word + tail.
// The second factor and the tail can each be a one-instruction combination
// of the seeds, an already-used register value, and the recovered factors.
void factor_bridges(const set<I>& latent){
    struct Word{double price;I a,b;char op;};
    struct Offer{double price;I a,u,x,y,v,tail;};
    unordered_map<I,Word> words;
    vector<I> palette=values;
    auto reuse=[&](I v){
        auto it=net.lookup.find(v);
        return it==net.lookup.end()?0:net.usage[it->second];
    };
    stable_sort(palette.begin(),palette.end(),[&](I a,I b){
        return 3*min(12,reuse(a))-(a>1000000)>3*min(12,reuse(b))-(b>1000000);
    });
    if(palette.size()>62)palette.resize(62);
    for(I v:latent)if(v>1)palette.push_back(v);
    for(I v:seeds)palette.push_back(v);
    sort(palette.begin(),palette.end());palette.erase(unique(palette.begin(),palette.end()),palette.end());
    for(I v:base_values)words[v]={seeds.count(v)?0.:max(.3,2.2-.13*min(12,reuse(v))),0,0,0};
    for(I v:palette)if(!words.count(v))words[v]={seeds.count(v)?0.:2.3,0,0,0};
    for(size_t i=0;i<palette.size();++i)for(size_t j=0;j<=i;++j){
        I a=palette[i],b=palette[j];double w=1.+words[a].price+(a!=b?words[b].price:0);
        forward(a,b,cap,[&](I v,char op,I l,I r){
            if(v==a||v==b)return;
            auto it=words.find(v);
            if(it==words.end() || (it->second.op && it->second.price>w))words[v]={w,l,r,op};
        });
    }
    set<I> offsets{0};
    for(I v:palette)if(v<=128){offsets.insert(v);offsets.insert(-v);}
    for(I n=1;n<=12;++n)if(words.count(n)){offsets.insert(n);offsets.insert(-n);}
    auto offer_word=[&](I v,I out){
        if(v==0)return true;
        auto w=words.at(v);
        if(w.op){
            if(w.a==out||w.b==out)return false;
            add(v,w.op,w.a,w.b);
        }
        return true;
    };
    set<I> objects(latent.begin(),latent.end());
    for(auto z:tokens){objects.insert(z.t);objects.insert(z.a*z.b);}
    for(I out:objects){
        if(out<4096)continue;
        vector<Offer> all;
        for(I a:latent){
            if(a<32||a>=out)continue;
            for(I u:offsets){
                I x=a+u;if(x<16||x>=out||!words.count(abs(u))&&u)continue;
                I q=out/x;
                // Rounding to a nearby factor is sufficient when the final
                // correction is small relative to the shifted latent factor.
                for(I y=max(I(2),q-1);y<=q+2;++y){
                    if((__int128)y*x>cap||!words.count(y)||y==out)continue;
                    I v=y*x,tail=out-v;
                    if(abs(tail)>65536||(tail&&!words.count(abs(tail))))continue;
                    auto w=words.at(y);
                    if(w.op&&(w.a==out||w.b==out||w.a==v||w.b==v))continue;
                    double rank=w.price+1.+(u?1.+words.at(abs(u)).price:0.)
                                +(tail?1.+words.at(abs(tail)).price:0.);
                    if(!base_values.count(a))rank+=1.3;
                    if(base_values.count(x))rank-=1.5;
                    if(base_values.count(v))rank-=1.;
                    all.push_back({rank,a,u,x,y,v,tail});
                }
            }
        }
        sort(all.begin(),all.end(),[](auto e,auto f){return tie(e.price,e.a,e.u,e.y)<tie(f.price,f.a,f.u,f.y);});
        set<pair<I,I>> used;
        for(auto [rank,a,u,x,y,v,tail]:all){
            if(used.size()>=8)break;
            if(!used.emplace(min(x,y),max(x,y)).second)continue;
            if(!offer_word(y,out)||!offer_word(abs(u),out)||!offer_word(abs(tail),out))continue;
            if(u)add(x,u>0?'+':'-',a,abs(u));
            add(v,'*',x,y);
            if(tail)add(out,tail>0?'+':'-',v,abs(tail));
        }
    }
}
