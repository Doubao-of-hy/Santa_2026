#pragma once
#include "round2_graph.hpp"
struct Entry {
    Num value;
    uint64_t mask;
    int left, right;
    char op;
    int cost;
};

// Immutable value catalog per sweep. Integer indices survive vector growth.
// Open addressing avoids allocating a separate hash node for every expression.
struct Table {
    std::vector<Entry> entries;
    std::vector<int> slots;
    explicit Table(int basis) {
        size_t capacity = 1;
        while (capacity < static_cast<size_t>(basis) * basis * basis * 11 + 256) capacity *= 2;
        slots.assign(capacity, -1);
    }
    size_t initial(Num value) const {
        uint64_t h = value;
        h ^= h >> 30;
        h *= 0xbf58476d1ce4e5b9ULL;
        h ^= h >> 27;
        h *= 0x94d049bb133111ebULL;
        return (h ^ (h >> 31)) & (slots.size() - 1);
    }
    int find(Num value) const {
        size_t k = initial(value);
        while (slots[k] >= 0 && entries[slots[k]].value != value) k = (k + 1) & (slots.size() - 1);
        return slots[k];
    }
    void put(Num v, uint64_t mask, int a, int b, char op, int cost) {
        size_t k = initial(v);
        while (slots[k] >= 0) {
            if (entries[slots[k]].value == v) return;
            k = (k + 1) & (slots.size() - 1);
        }
        slots[k] = entries.size();
        entries.push_back({v, mask, a, b, op, cost});
    }
};
