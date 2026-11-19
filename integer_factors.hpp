#pragma once
#include <algorithm>
#include <cstdint>
#include <numeric>
#include <vector>

namespace factors {
using U=std::uint64_t;
inline U mult(U a,U b,U n) {
    return static_cast<U>(static_cast<__uint128_t>(a)*b%n);
}
inline U power(U a,U b,U n) {
    U result=1;
    while(b) {
        if(b&1) result=mult(result,a,n);
        a=mult(a,a,n); b>>=1;
    }
    return result;
}
inline bool prime(U n) {
    if(n<2) return false;
    for(U p:{2,3,5,7,11,13,17,19,23,29,31,37})
        if(n%p==0) return n==p;
    U d=n-1;int s=0;
    while(!(d&1)) {d>>=1;++s;}
    for(U a:{2,325,9375,28178,450775,9780504,1795265022}) {
        if(a%n==0) continue;
        U x=power(a%n,d,n);
        if(x==1 || x==n-1) continue;
        bool passes=false;
        for(int i=1;i<s;++i) {
            x=mult(x,x,n);
            if(x==n-1) {passes=true;break;}
        }
        if(!passes) return false;
    }
    return true;
}
inline U random_word(U &s) {
    U z=(s+=0x9e3779b97f4a7c15ULL);
    z=(z^(z>>30))*0xbf58476d1ce4e5b9ULL;
    z=(z^(z>>27))*0x94d049bb133111ebULL;
    return z^(z>>31);
}
inline U split(U n) {
    for(U p:{2,3,5,7,11,13,17,19,23,29,31,37}) if(n%p==0) return p;
    U state=n;
    for(;;) {
        U c=1+random_word(state)%(n-1), y=1+random_word(state)%(n-1),g=1,x=0,ys=0;
        auto step=[&](U v){return (mult(v,v,n)+c)%n;};
        for(U r=1;g==1 && r<=(1u<<19);r*=2) {
            x=y;
            for(U i=0;i<r;++i) y=step(y);
            for(U k=0;k<r && g==1;k+=96) {
                ys=y;U product=1;
                for(U i=0;i<std::min<U>(96,r-k);++i) {
                    y=step(y);product=mult(product,x>y?x-y:y-x,n);
                }
                g=std::gcd(product,n);
            }
        }
        if(g==n) {
            do {ys=step(ys);g=std::gcd(x>ys?x-ys:ys-x,n);} while(g==1);
        }
        if(g>1 && g<n) return g;
    }
}
inline void factor(U n,std::vector<U>& out) {
    if(n<=1) return;
    if(prime(n)) {out.push_back(n);return;}
    U d=split(n);factor(d,out);factor(n/d,out);
}
inline std::vector<U> divisors(U n) {
    std::vector<U> primes,values{1};
    factor(n,primes);std::sort(primes.begin(),primes.end());
    for(std::size_t i=0;i<primes.size();) {
        U p=primes[i],scale=1;auto original=values.size();
        do {
            scale*=p;
            for(std::size_t j=0;j<original;++j) values.push_back(values[j]*scale);
            ++i;
        } while(i<primes.size() && primes[i]==p);
    }
    return values;
}
}
