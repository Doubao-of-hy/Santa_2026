// Positive integer arithmetic with a per-puzzle bound of at most 10^18.
// Table slots store one-based identifiers so only 32-bit atomics are needed.

#define ADD 1u
#define SUB 2u
#define MUL 3u
#define DIV 4u

inline uint hash_value(ulong value, uint mask) {
    uint hash = (uint)value ^ ((uint)(value >> 32) * 0x9e3779b1u);
    hash ^= hash >> 16;
    hash *= 0x85ebca6bu;
    hash ^= hash >> 13;
    hash *= 0xc2b2ae35u;
    return (hash ^ (hash >> 16)) & mask;
}

__kernel void insert_table(__global const ulong *values,
                           uint count, uint mask,
                           volatile __global uint *slots) {
    uint id = (uint)get_global_id(0);
    if (id >= count)
        return;
    uint place = hash_value(values[id], mask);
    while (atomic_cmpxchg(&slots[place], 0u, id + 1u) != 0u)
        place = (place + 1u) & mask;
}

inline uint lookup(ulong value, __global const ulong *values,
                   __global const uint *slots, uint mask) {
    uint place = hash_value(value, mask);
    while (1) {
        uint id = slots[place];
        if (id == 0u || values[id - 1u] == value)
            return id;
        place = (place + 1u) & mask;
    }
}

inline void record_match(uint cost, uint capacity,
                         uint code, uint left, uint right,
                         uint root, uint reverse, uint other,
                         volatile __global uint *counts, __global uint *records) {
    // Avoid counter traffic once a cost bucket is already saturated.
    if (counts[cost] >= capacity)
        return;
    uint slot = atomic_inc(&counts[cost]);
    if (slot < capacity) {
        size_t position = ((size_t)cost * capacity + slot) * 6u;
        records[position + 0u] = code;
        records[position + 1u] = left;
        records[position + 2u] = right;
        records[position + 3u] = root;
        records[position + 4u] = reverse;
        records[position + 5u] = other;
    }
}

inline void probe(ulong complement, uint root, uint reverse,
                  uint code, uint left, uint right, uint subtree_cost,
                  uint n0, uint n1, uint budget, uint capacity,
                  __global const ulong *values, __global const uint *slots, uint mask,
                  volatile __global uint *counts, __global uint *records) {
    uint id = lookup(complement, values, slots, mask);
    if (id != 0u) {
        uint other = id - 1u;
        uint other_cost = other < n0 ? 0u : other < n1 ? 1u : 2u;
        uint cost = subtree_cost + other_cost + 1u;
        if (cost <= budget)
            record_match(cost, capacity, code, left, right, root, reverse, other, counts, records);
    }
}

inline void match(ulong intermediate,
                  uint code, uint left, uint right, uint subtree_cost,
                  ulong target, ulong limit,
                  uint n0, uint n1, uint budget, uint capacity,
                  __global const ulong *values, __global const uint *slots, uint mask,
                  volatile __global uint *counts, __global uint *records) {
    if (intermediate == 0ul || intermediate > limit)
        return;
    if (intermediate == target) {
        if (subtree_cost <= budget)
            record_match(subtree_cost, capacity, code, left, right, 0u, 0u, 0u, counts, records);
        return;
    }
    if (subtree_cost >= budget)
        return;
    if (intermediate < target)
        probe(target - intermediate, ADD, 0u, code, left, right, subtree_cost,
              n0, n1, budget, capacity, values, slots, mask, counts, records);
    else
        probe(intermediate - target, SUB, 0u, code, left, right, subtree_cost,
              n0, n1, budget, capacity, values, slots, mask, counts, records);
    if (target <= limit - intermediate)
        probe(target + intermediate, SUB, 1u, code, left, right, subtree_cost,
              n0, n1, budget, capacity, values, slots, mask, counts, records);
    if (intermediate > 1ul && intermediate < target && target % intermediate == 0ul)
        probe(target / intermediate, MUL, 0u, code, left, right, subtree_cost,
              n0, n1, budget, capacity, values, slots, mask, counts, records);
    if (intermediate > 1ul && intermediate <= limit / target)
        probe(target * intermediate, DIV, 1u, code, left, right, subtree_cost,
              n0, n1, budget, capacity, values, slots, mask, counts, records);
    if (target > 1ul && intermediate > target && intermediate % target == 0ul)
        probe(intermediate / target, DIV, 0u, code, left, right, subtree_cost,
              n0, n1, budget, capacity, values, slots, mask, counts, records);
}

inline void match_pair(uint i, uint j,
                       ulong target, ulong limit, uint n0, uint n1, uint budget, uint capacity,
                       __global const ulong *values, __global const uint *slots, uint mask,
                       volatile __global uint *counts, __global uint *records) {
    ulong a = values[i], b = values[j];
    if (a < b) {
        ulong swap_value = a;
        a = b;
        b = swap_value;
        uint swap_index = i;
        i = j;
        j = swap_index;
    }
    match(a + b, ADD, i, j, 3u, target, limit,
          n0, n1, budget, capacity, values, slots, mask, counts, records);
    if (a > b)
        match(a - b, SUB, i, j, 3u, target, limit,
              n0, n1, budget, capacity, values, slots, mask, counts, records);
    if (b > 1ul && a <= limit / b)
        match(a * b, MUL, i, j, 3u, target, limit,
              n0, n1, budget, capacity, values, slots, mask, counts, records);
    if (b > 1ul && a > b && a % b == 0ul)
        match(a / b, DIV, i, j, 3u, target, limit,
              n0, n1, budget, capacity, values, slots, mask, counts, records);
}

__kernel void join_two(__global const ulong *values, __global const uint *slots,
                       uint n0, uint n1, uint total, uint mask,
                       ulong target, ulong limit, uint budget, uint capacity,
                       volatile __global uint *counts, __global uint *records) {
    uint i = (uint)get_global_id(0);
    if (i < total)
        match(values[i], 0u, i, 0u, i < n0 ? 0u : i < n1 ? 1u : 2u, target, limit,
              n0, n1, budget, capacity, values, slots, mask, counts, records);
}

inline int pair_indices(uint id, uint n0, uint n1, uint total,
                        __global const uint *left, __global const uint *right,
                        __private uint *out_i, __private uint *out_j) {
    uint two_count = total - n1;
    uint one_count = n1 - n0;
    uint pairs20 = two_count * n0;
    uint pairs11 = one_count * one_count;
    uint i, j;
    if (id < pairs20) {
        i = n1 + id / n0;
        j = id % n0;
    } else if (id < pairs20 + pairs11) {
        id -= pairs20;
        i = id / one_count;
        j = id % one_count;
        if (i > j)
            return 0;
        i += n0;
        j += n0;
    } else {
        id -= pairs20 + pairs11;
        i = n1 + id / 3u;
        if (i >= total)
            return 0;
        uint mode = id % 3u;
        j = mode == 0u ? i : mode == 1u ? left[i] : right[i];
        if (j < n0 || (j >= n1 && j != i))
            return 0;
        if (mode == 2u && j == left[i])
            return 0;
    }
    *out_i = i;
    *out_j = j;
    return 1;
}

__kernel void join_three(__global const ulong *values, __global const uint *slots,
                         __global const uint *left, __global const uint *right,
                         uint n0, uint n1, uint total, uint mask,
                         ulong target, ulong limit, uint budget, uint capacity,
                         volatile __global uint *counts, __global uint *records) {
    uint id = (uint)get_global_id(0);
    uint i, j;
    if (!pair_indices(id, n0, n1, total, left, right, &i, &j))
        return;
    match_pair(i, j, target, limit, n0, n1, budget, capacity, values, slots, mask, counts, records);
}

__kernel void materialize_three(__global const ulong *values,
                                __global const uint *left, __global const uint *right,
                                uint n0, uint n1, uint total, uint pair_count,
                                ulong limit, __global ulong *raw) {
    uint id = (uint)get_global_id(0);
    if (id >= pair_count)
        return;
    ulong a = 0ul, b = 0ul;
    uint i, j;
    if (pair_indices(id, n0, n1, total, left, right, &i, &j)) {
        a = max(values[i], values[j]);
        b = min(values[i], values[j]);
    }
    size_t at = (size_t)id * 4u;
    raw[at + 0u] = a + b <= limit ? a + b : 0ul;
    raw[at + 1u] = a - b;
    raw[at + 2u] = b > 1ul && a <= limit / b ? a * b : 0ul;
    raw[at + 3u] = b > 1ul && a > b && a % b == 0ul ? a / b : 0ul;
}

__kernel void insert_unique(__global const ulong *raw,
                            uint count, uint mask, uint offset,
                            volatile __global uint *slots) {
    uint id = (uint)get_global_id(0) + offset;
    if (id >= count || raw[id] == 0ul)
        return;
    ulong value = raw[id];
    uint place = hash_value(value, mask);
    while (1) {
        uint existing = slots[place];
        if (existing == 0u) {
            existing = atomic_cmpxchg(&slots[place], 0u, id + 1u);
            if (existing == 0u)
                return;
        }
        if (raw[existing - 1u] == value)
            return;
        place = (place + 1u) & mask;
    }
}

inline void match_raw(ulong complement, uint id, uint root, uint reverse,
                      uint capacity, __global const ulong *raw,
                      __global const uint *slots, uint mask,
                      volatile __global uint *counts, __global uint *records) {
    uint found = lookup(complement, raw, slots, mask);
    if (found != 0u)
        record_match(7u, capacity, 5u, id, found - 1u, root, reverse, 0u, counts, records);
}

__kernel void join_seven(__global const ulong *raw, __global const uint *slots,
                         uint count, uint mask, uint offset,
                         ulong target, ulong limit, uint capacity,
                         volatile __global uint *counts, __global uint *records) {
    uint id = (uint)get_global_id(0) + offset;
    if (id >= count || counts[7] >= capacity)
        return;
    ulong value = raw[id];
    if (value == 0ul || value == target || lookup(value, raw, slots, mask) != id + 1u)
        return;
    if (value < target)
        match_raw(target - value, id, ADD, 0u, capacity, raw, slots, mask, counts, records);
    else
        match_raw(value - target, id, SUB, 0u, capacity, raw, slots, mask, counts, records);
    if (target <= limit - value)
        match_raw(value + target, id, SUB, 1u, capacity, raw, slots, mask, counts, records);
    if (value > 1ul && value < target && target % value == 0ul)
        match_raw(target / value, id, MUL, 0u, capacity, raw, slots, mask, counts, records);
    if (value > 1ul && value <= limit / target)
        match_raw(target * value, id, DIV, 1u, capacity, raw, slots, mask, counts, records);
    if (target > 1ul && value > target && value % target == 0ul)
        match_raw(value / target, id, DIV, 0u, capacity, raw, slots, mask, counts, records);
}

#define RAW_FLAG 0x80000000u
#define NO_VALUE 0xffffffffu

inline uint pool_lookup(ulong value,
                         __global const ulong *known, __global const uint *short_slots, uint short_mask,
                         __global const ulong *raw, __global const uint *long_slots, uint long_mask) {
    uint index = lookup(value, known, short_slots, short_mask);
    if (index)
        return index - 1u;
    if (long_mask != 0u) {
        index = lookup(value, raw, long_slots, long_mask);
        if (index)
            return (index - 1u) | RAW_FLAG;
    }
    return NO_VALUE;
}

inline uint operand_cost(uint index, uint n0, uint n1) {
    if (index == NO_VALUE)
        return 0u;
    if (index & RAW_FLAG)
        return 3u;
    return index < n0 ? 0u : index < n1 ? 1u : 2u;
}

inline void record_affine(uint scale, uint quotient, uint residual, uint sign,
                           uint n0, uint n1, uint budget, uint capacity,
                           volatile __global uint *counts, __global uint *records) {
    if (quotient == NO_VALUE)
        return;
    uint cost = operand_cost(scale, n0, n1) + operand_cost(quotient, n0, n1)
        + operand_cost(residual, n0, n1) + (residual == NO_VALUE ? 1u : 2u);
    if (cost <= budget)
        record_match(cost, capacity, 6u, scale, quotient, residual, sign, 0u, counts, records);
}

__kernel void affine_near(__global const ulong *known, __global const uint *short_slots,
                          __global const ulong *raw, __global const uint *long_slots,
                          uint n0, uint n1, uint short_mask, uint long_mask,
                          __global const uint *scales, uint scales_count, uint radius,
                          ulong target, ulong limit, uint budget, uint capacity,
                          volatile __global uint *counts, __global uint *records) {
    uint id = (uint)get_global_id(0);
    uint strip = 2u * radius + 1u;
    if (id >= scales_count * strip)
        return;
    uint scale_index = scales[id / strip];
    ulong scale = known[scale_index];
    long q = (long)(target / scale) + (long)(id % strip) - (long)radius;
    if (q < 2l || (ulong)q > limit / scale)
        return;
    uint quotient = pool_lookup((ulong)q, known, short_slots, short_mask, raw, long_slots, long_mask);
    if (quotient == NO_VALUE)
        return;
    ulong product = scale * (ulong)q;
    ulong residual = product > target ? product - target : target - product;
    uint offset = NO_VALUE;
    if (residual != 0ul) {
        offset = pool_lookup(residual, known, short_slots, short_mask, raw, long_slots, long_mask);
        if (offset == NO_VALUE)
            return;
    }
    record_affine(scale_index, quotient, offset, (uint)(product > target),
                   n0, n1, budget, capacity, counts, records);
}

inline void test_residue(ulong product, uint scale_index, ulong scale, uint offset, uint sign,
                         ulong limit, uint n0, uint n1, uint budget, uint capacity,
                         __global const ulong *known, __global const uint *short_slots, uint short_mask,
                         __global const ulong *raw, __global const uint *long_slots, uint long_mask,
                         volatile __global uint *counts, __global uint *records) {
    if (product <= scale || product > limit || product % scale != 0ul)
        return;
    uint quotient = pool_lookup(product / scale, known, short_slots, short_mask, raw, long_slots, long_mask);
    if ((offset & RAW_FLAG) && quotient != NO_VALUE) {
        uint index = offset & ~RAW_FLAG;
        if (pool_lookup(raw[index], known, short_slots, short_mask, raw, long_slots, long_mask) != offset)
            return;
    }
    record_affine(scale_index, quotient, offset, sign, n0, n1, budget, capacity, counts, records);
}

__kernel void affine_residues(__global const ulong *known, __global const uint *short_slots,
                              __global const ulong *raw, __global const uint *long_slots,
                              uint n0, uint n1, uint short_mask, uint long_mask,
                              __global const uint *scales, uint scales_count, uint residues_count,
                              uint offset, uint read_raw,
                              ulong target, ulong limit, uint budget, uint capacity,
                              volatile __global uint *counts, __global uint *records) {
    uint id = (uint)get_global_id(0) + offset;
    uint scale_number = id / residues_count;
    if (scale_number >= scales_count)
        return;
    uint residue_index = id % residues_count;
    ulong residue = read_raw ? raw[residue_index] : known[residue_index];
    if (residue == 0ul)
        return;
    uint scale_index = scales[scale_number];
    ulong scale = known[scale_index];
    uint witness = read_raw ? residue_index | RAW_FLAG : residue_index;
    if (target > residue) {
        test_residue(target - residue, scale_index, scale, witness, 0u,
                     limit, n0, n1, budget, capacity, known, short_slots, short_mask,
                     raw, long_slots, long_mask, counts, records);
    } else if (residue > target) {
        test_residue(residue - target, scale_index, scale, witness, 2u,
                     limit, n0, n1, budget, capacity, known, short_slots, short_mask,
                     raw, long_slots, long_mask, counts, records);
    }
    if (residue <= limit - target)
        test_residue(target + residue, scale_index, scale, witness, 1u,
                     limit, n0, n1, budget, capacity, known, short_slots, short_mask,
                     raw, long_slots, long_mask, counts, records);
}
