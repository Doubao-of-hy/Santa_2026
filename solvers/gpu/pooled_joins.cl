// Each bit marks a cut in which all leaves of this particular recipe survive.
// The arithmetic dictionary is shared across cuts and all their inverse goals.
inline void keep_join(uint q, uint cost, uint a, uint b, uint op, uint capacity,
                      __global uint *counts, __global uint *answers) {
    uint bucket=q*6+cost;
    if (counts[bucket]>=capacity) return;
    uint slot=atomic_inc(&counts[bucket]);
    if (slot>=capacity) return;
    size_t pos=((size_t)bucket*capacity+slot)*3;
    answers[pos]=a; answers[pos+1]=b; answers[pos+2]=op;
}

inline void extend_mask(ulong x, ulong y, ulong cap, uint reach, uint mask,
                        __global const ulong *values, __global const uint *slots,
                        volatile __global uint *output) {
    if (!reach) return;
    ulong hi=max(x,y),lo=min(x,y);
    ulong out[4]={hi<=cap-lo ? hi+lo:0, hi-lo, hi<=cap/lo ? hi*lo:0,
                  hi%lo==0 ? hi/lo:0};
    for (uint k=0;k<4;k++) if (out[k]) {
        uint pos=lookup(out[k],values,slots,mask);
        if (pos && (output[pos-1]&reach)!=reach) atomic_or(&output[pos-1],reach);
    }
}

__kernel void allowable(__global const ulong *values,__global const uint *slots,
                        __global const uint *anchors, __global const uint *previous,
                        __global uint *next,uint mask,uint n0,uint count,ulong cap) {
    size_t idx=get_global_id(0);
    uint which=(uint)(idx/(n0+1)), base=(uint)(idx%(n0+1));
    if(which>=count)return;
    uint other=base<n0?base:which;
    uint reach=previous[which] & (base<n0?anchors[base]:previous[which]);
    extend_mask(values[which],values[other],cap,reach,mask,values,slots,next);
}

inline uint local_cost(uint vertex,uint n0,uint n1,uint bit,uint alternate,
                       __global const uint *zero,__global const uint *one) {
    if(!alternate)return (vertex>=n0)+(vertex>=n1);
    if(vertex<n0 && (zero[vertex]&bit))return 0;
    return (vertex<n1 && (one[vertex]&bit))?1:2;
}
inline ulong partner_value(ulong x,ulong t,ulong cap,uint op) {
    switch(op) {
        case 0:return t>x?t-x:0;
        case 1:return x>t?x-t:0;
        case 2:return t<=cap-x?t+x:0;
        case 3:return t%x==0?t/x:0;
        case 4:return x%t==0?x/t:0;
        default:return x<=cap/t?x*t:0;
    }
}
__kernel void pooled_join(__global const ulong *values, __global const uint *slots,
                          __global const uint *allowed, __global const uint *zero,
                          __global const uint *one,uint alternate, __global const ulong *queries,
                          __global const uint *bits, uint mask, uint n0, uint n1,
                          uint total, ulong cap, uint capacity,
                          __global uint *counts, __global uint *answers, uint track,
                          __global const uint *budgets, volatile __global uint *demand) {
    uint a=get_global_id(0),q=get_global_id(1);
    if (a>=total || !(allowed[a]&bits[q])) return;
    ulong x=values[a],t=queries[q];
    uint cost=local_cost(a,n0,n1,bits[q],alternate,zero,one);
    if (x==t) {keep_join(q,cost,a,a,6,capacity,counts,answers);return;}
    for (uint op=0;op<6;op++) {
        ulong y=partner_value(x,t,cap,op);
        if(!y || y==t) continue;
        // Look up only one operand order for commutative roots.
        uint out=lookup(y,values,slots,mask);
        if(!out || !(allowed[out-1]&bits[q])) continue;
        uint b=out-1;
        if ((op==0 || op==3) && x>y && b<total) continue;
        uint other=local_cost(b,n0,n1,bits[q],alternate,zero,one);
        uint total_cost=cost+1+(a!=b)*other;
        if(track) {
            if(cost && total_cost-cost<=budgets[q])atomic_or(demand+a,bits[q]);
            if(a!=b && other && total_cost-other<=budgets[q])atomic_or(demand+b,bits[q]);
        }
        keep_join(q,total_cost,a,b,op,capacity,counts,answers);
    }
}

// Every valid witness using a selected shared input is returned, even if a
// query's ordinary result bucket filled before that input was visited.
__kernel void focused_joins(__global const ulong *values,__global const uint *slots,
                            __global const uint *allowed,__global const ulong *targets,
                            __global const uint *bits,__global const uint *focus,
                            uint width,uint mask,ulong cap,__global uint *results) {
    uint i=get_global_id(0),q=get_global_id(1);
    if(i>=width)return;
    uint a=focus[i], bit=bits[q];
    if(!(allowed[a]&bit))return;
    ulong t=targets[q],x=values[a];
    if(x==t)return;
    for(uint op=0;op<6;op++) {
        ulong y=partner_value(x,t,cap,op);
        if(!y || y==t)continue;
        uint b=lookup(y,values,slots,mask);
        if(b && (allowed[b-1]&bit))results[((size_t)q*width+i)*6+op]=b;
    }
}
