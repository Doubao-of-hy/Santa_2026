// Batched backward construction. Both the residual and the quotient can be
// the next open branch; the other operand carries a reconstructible device ID.
typedef struct { uint lo, hi, op, a, b, terminal, cost, rank; } Wave;

inline uint log_bin(ulong value, uint digits) {
    uint msb=63u-(uint)clz(value);
    if(msb<digits) return (uint)value;
    uint leading=(uint)(value>>(msb-digits));
    return (msb-digits+1u)*(1u<<digits)+leading-(1u<<digits);
}

inline void extremum(__global uint *slots,uint key,ulong value,uint id,
                     __global const ulong *raw,uint maximum) {
    uint prev=slots[key];
    for(;;) {
        if(prev) {
            ulong other=raw[prev-1];
            if(maximum ? value<=other : value>=other) return;
        }
        uint replaced=atomic_cmpxchg(slots+key,prev,id+1u);
        if(replaced==prev) return;
        prev=replaced;
    }
}

__kernel void index_nearest(__global const ulong *raw,uint count,uint digits,uint offset,
                            __global uint *fine,__global uint *coarse) {
    uint id=offset+(uint)get_global_id(0);
    if(id>=count || !raw[id]) return;
    ulong value=raw[id];
    uint a=log_bin(value,digits)*2u,b=log_bin(value,8u)*2u;
    extremum(fine,a,value,id,raw,0u); extremum(fine,a+1u,value,id,raw,1u);
    extremum(coarse,b,value,id,raw,0u); extremum(coarse,b+1u,value,id,raw,1u);
}

__kernel void index_residue(__global const ulong *raw,uint count,uint digits,uint modulus,
                            uint offset,__global uint *bins) {
    uint id=offset+(uint)get_global_id(0);
    if(id>=count || !raw[id]) return;
    ulong value=raw[id];
    uint pos=2u*(log_bin(value,digits)*modulus+(uint)(value%modulus));
    extremum(bins,pos,value,id,raw,0u); extremum(bins,pos+1u,value,id,raw,1u);
}

inline uint nearest_raw(ulong goal,uint digits,__global const uint *fine,
                        __global const uint *coarse,__global const ulong *raw) {
    uint best=NO_VALUE;
    ulong gap=0xfffffffffffffffful;
    for(uint pass=0;pass<2 && gap>1ul;++pass) {
        uint bits=pass?8u:digits;
        __global const uint *bins=pass?coarse:fine;
        int key=(int)log_bin(goal,bits);
        int bound=(int)((65u-bits)*(1u<<bits));
        for(int j=max(0,key-2);j<=min(bound-1,key+2);++j) {
            for(uint side=0;side<2;++side) {
                uint ref=bins[2*j+side];
                if(!ref) continue;
                ulong v=raw[ref-1],d=v>goal?v-goal:goal-v;
                if(d<gap) {gap=d; best=ref-1;}
            }
        }
        if(best!=NO_VALUE) break;
    }
    return best;
}

inline void choice(ulong child, uint op, uint a, uint b, uint added, ulong parent,
                   __private Wave *open, __private Wave *closed,
                   __global const ulong *known, __global const uint *shorts, uint sm,
                   __global const ulong *raw, __global const uint *longs, uint lm,
                   uint n0, uint n1) {
    if (!child) return;
    uint id=pool_lookup(child, known, shorts, sm, raw, longs, lm);
    if (id!=NO_VALUE) {
        uint cost=added+operand_cost(id,n0,n1);
        if(cost<closed->cost) {
            Wave result={(uint)child,(uint)(child>>32),op,a,b,id,cost,cost*256u};
            *closed=result;
        }
    } else if(child<parent) {
        uint rank=added*256u+(64u-(uint)clz(child))*48u;
        if(rank<open->rank || (rank==open->rank && child<(((ulong)open->hi<<32)|open->lo))) {
            Wave result={(uint)child,(uint)(child>>32),op,a,b,NO_VALUE,added,rank};
            *open=result;
        }
    }
}

inline uint lower_short(ulong goal,__global const ulong *known,uint lo,uint hi) {
    while(lo<hi) {
        uint mid=lo+(hi-lo)/2u;
        if(known[mid]<goal) lo=mid+1u;
        else hi=mid;
    }
    return lo;
}

__kernel void backward_wave(__global const ulong *known, __global const uint *shorts, uint sm,
                    __global const ulong *raw, __global const uint *longs, uint lm,
                    uint n0, uint n1, uint total, ulong limit,
                    __global const ulong *parents, uint nparents,
                    __global const uint *scales, uint nscales, uint stride,
                    uint digits, __global const uint *fine, __global const uint *coarse,
                    uint mod0,uint mb0,__global const uint *res0,uint mod1,uint mb1,
                    __global const uint *res1,
                    __global Wave *out) {
    uint gid=get_global_id(0), p=gid/stride, column=gid%stride;
    Wave o={0,0,0,0,0,NO_VALUE,255,0xffffffffu}, c=o;
    if(column<nscales) {
    ulong t=parents[p]; uint i=scales[column];
    ulong m=known[i];
    uint cm=operand_cost(i,n0,n1);
    #define OFFER(x,op,a,b,cost) choice(x,op,a,b,cost,t,&o,&c,known,shorts,sm,raw,longs,lm,n0,n1)
    if(!column) OFFER(t,0u,NO_VALUE,NO_VALUE,0u);
    if(digits && !column) {
        uint nidx=nearest_raw(t,digits,fine,coarse,raw);
        if(nidx!=NO_VALUE) {
            ulong a=raw[nidx];
            if(a!=t) OFFER(t>a?t-a:a-t,t>a?1u:2u,nidx|RAW_FLAG,NO_VALUE,4u);
        }
    }
    if(t>m) OFFER(t-m,1u,i,NO_VALUE,cm+1);
    if(m>t) OFFER(m-t,2u,i,NO_VALUE,cm+1);
    if(m<=limit-t) OFFER(m+t,3u,i,NO_VALUE,cm+1);
    if(m>1 && m<t) {
        ulong q=t/m;
        int hops=i<n0?9:3;
        for(int k=0;k<hops;++k) {
            int delta=(k==0?0:(k&1?(1<<((k-1)/2)):-(1<<((k-2)/2))));
            if(delta<0 && q<=(ulong)(-delta)) continue;
            ulong approx=delta>=0?q+(uint)delta:q-(uint)(-delta);
            if(approx<1 || approx>limit/m) continue;
            ulong product=approx*m;
            if(product==t) {OFFER(approx,4u,i,NO_VALUE,cm+1);continue;}
            ulong residual=product<t?t-product:product-t;
            uint r=pool_lookup(residual,known,shorts,sm,raw,longs,lm);
            if(r!=NO_VALUE) OFFER(approx,product<t?5u:6u,i,r,cm+2+operand_cost(r,n0,n1));
            uint qi=pool_lookup(approx,known,shorts,sm,raw,longs,lm);
            if(qi!=NO_VALUE) OFFER(residual,product<t?8u:9u,i,qi,cm+2+operand_cost(qi,n0,n1));
        }
        if(digits && q>1024) {
            uint near_id=nearest_raw(q,digits,fine,coarse,raw);
            if(near_id!=NO_VALUE) {
                ulong approx=raw[near_id];
                if(approx<=limit/m) {
                    ulong product=approx*m;
                    uint qi=near_id|RAW_FLAG;
                    if(product!=t) {
                        ulong residual=product<t?t-product:product-t;
                        OFFER(residual,product<t?8u:9u,i,qi,cm+5u);
                    } else OFFER(approx,4u,i,NO_VALUE,cm+1);
                }
            }
        }
        if(digits && q>64 && i<n0) {
            for(uint tier=0;tier<3;++tier) {
                uint lo=tier==0?0u:tier==1?n0:n1, hi=tier==0?n0:tier==1?n1:total;
                int at=(int)lower_short(q,known,lo,hi);
                for(int x=max((int)lo,at-2);x<min((int)hi,at+2);++x) {
                    ulong a=known[x];
                    if(a>limit/m) continue;
                    ulong product=m*a;
                    if(product!=t) OFFER(product<t?t-product:product-t,
                        product<t?8u:9u,i,(uint)x,cm+tier+2u);
                }
            }
        }
        if(m==mod0 || m==mod1) {
            uint mb=m==mod0?mb0:mb1;
            __global const uint *index=m==mod0?res0:res1;
            int bound=(int)((65u-mb)*(1u<<mb));
            for(int center=0;center<2;++center) {
                ulong approximate=center==0?t:q;
                int bin=(int)log_bin(approximate,mb);
                for(int x=max(0,bin-2);x<=min(bound-1,bin+2);++x) {
                    for(uint neg=0;neg<2;++neg) {
                        uint residue=(uint)(t%m);
                        if(neg && residue) residue=(uint)m-residue;
                        uint pos=2u*((uint)x*(uint)m+residue);
                        for(uint side=0;side<2;++side) {
                            uint id=index[pos+side];
                            if(!id) continue;
                            ulong a=raw[id-1];
                            if(neg) {
                                if(a<=limit-t) OFFER((t+a)/m,6u,i,(id-1u)|RAW_FLAG,cm+5u);
                            } else if(t!=a) {
                                OFFER(t>a?(t-a)/m:(a-t)/m,t>a?5u:7u,i,(id-1u)|RAW_FLAG,cm+5u);
                            }
                        }
                    }
                }
            }
        }
    }
    if(m>1 && t<=limit/m) OFFER(t*m,10u,i,NO_VALUE,cm+1);
    if(m>t && !(m%t)) OFFER(m/t,11u,i,NO_VALUE,cm+1);
    }
    __local Wave opens[128];
    __local Wave closes[128];
    uint lane=get_local_id(0);
    opens[lane]=o;
    closes[lane]=c;
    barrier(CLK_LOCAL_MEM_FENCE);
    if(!(lane&15u)) {
        for(uint k=1;k<16;++k) {
            Wave alt=opens[lane+k];
            if(alt.rank<o.rank || (alt.rank==o.rank &&
               (((ulong)alt.hi<<32)|alt.lo)<(((ulong)o.hi<<32)|o.lo))) o=alt;
            alt=closes[lane+k];
            if(alt.cost<c.cost) c=alt;
        }
        out[(gid/16u)*2u]=o;
        out[(gid/16u)*2u+1u]=c;
    }
}

// Test every speculative point on the prior beam against each newly available
// numeric helper. A witness can be reused without rebuilding either dictionary.
__kernel void bridge_demands(__global const ulong *known,__global const uint *shorts,uint sm,
                             __global const ulong *raw,__global const uint *longs,uint lm,
                             uint n0,uint n1,ulong limit,
                             __global const ulong *residuals,uint nr,
                             __global const ulong *helpers,uint nh,__global uint2 *out) {
    uint i=get_global_id(0),s=i/nh,j=i%nh;
    if(s>=nr) return;
    ulong t=residuals[s],h=helpers[j];
    uint cost=255u,op=0,operand=NO_VALUE;
    if(t==h) cost=0;
    #define BRIDGE(proposed,operation) { \
       uint other=pool_lookup(proposed,known,shorts,sm,raw,longs,lm); \
       if(other!=NO_VALUE) {uint c=operand_cost(other,n0,n1)+1u; \
       if(c<cost) {cost=c;op=operation;operand=other;}} \
    }
    if(t>h) BRIDGE(t-h,1u);
    if(h>t) BRIDGE(h-t,2u);
    if(t<=limit-h) BRIDGE(t+h,3u);
    if(h>1ul && !(t%h)) BRIDGE(t/h,4u);
    if(h>1ul && t<=limit/h) BRIDGE(t*h,10u);
    if(h>t && !(h%t)) BRIDGE(h/t,11u);
    out[i]=(uint2)(cost|(op<<8u),operand);
}

// Enumerate the entire two-operation scale class. At a product boundary
// inspect its neighbours in the zero- and one-operation classes, then price
// the signed remainder with the independent three-operation dictionary.
__kernel void sweep_wave(__global const ulong *known,__global const uint *shorts,uint sm,
                         __global const ulong *raw,__global const uint *longs,uint lm,
                         uint n0,uint n1,uint total,ulong limit,
                         __global const ulong *parents,uint step,uint columns,
                         uint padded,__global Wave *output) {
    uint lane=get_local_id(0), gid=get_global_id(0), pos=gid%padded;
    Wave best={0,0,0,0,0,NO_VALUE,255,0xffffffffu};
    if(pos<columns) {
        uint index=n1+pos*step;
        ulong m=known[index], t=parents[gid/padded];
        #define SWEEP(child,code,a,b,charge) { \
            ulong v_=(child); \
            if(v_) { \
                uint witness=pool_lookup(v_,known,shorts,sm,raw,longs,lm); \
                if(witness!=NO_VALUE) { \
                    uint cost=(charge)+operand_cost(witness,n0,n1); \
                    if(cost<best.cost) { \
                        Wave alt={(uint)v_,(uint)(v_>>32),(code),(a),(b),witness,cost,cost*256u}; \
                        best=alt; \
                    } \
                } \
            } \
        }
        if(t>m) SWEEP(t-m,1u,index,NO_VALUE,3u)
        if(t<m) SWEEP(m-t,2u,index,NO_VALUE,3u)
        if(t<=limit-m) SWEEP(t+m,3u,index,NO_VALUE,3u)
        if(m>1 && t>=m) {
            ulong q=t/m;
            if(!(t%m)) SWEEP(q,4u,index,NO_VALUE,3u)
            if(q>1 && best.cost>4u) {
                for(uint tier=0;tier<2;++tier) {
                    uint lo=tier?n0:0, hi=tier?n1:n0;
                    int middle=(int)lower_short(q,known,lo,hi);
                    for(int k=max((int)lo,middle-1);k<min((int)hi,middle+2);++k) {
                        ulong b=known[k];
                        if(b<=1 || b>limit/m) continue;
                        ulong product=m*b;
                        if(product!=t) SWEEP(product<t?t-product:product-t,
                            product<t?8u:9u,index,(uint)k,4u+tier)
                    }
                }
            }
        }
        if(m>1 && t<=limit/m) SWEEP(t*m,10u,index,NO_VALUE,3u)
        if(m>t && !(m%t)) SWEEP(m/t,11u,index,NO_VALUE,3u)
        #undef SWEEP
    }
    __local Wave local_best[128];
    local_best[lane]=best;
    barrier(CLK_LOCAL_MEM_FENCE);
    if(!(lane&63u)) {
        for(uint k=1;k<64;++k) {
            Wave alt=local_best[lane+k];
            if(alt.cost<best.cost) best=alt;
        }
        output[gid/64]=best;
    }
}
