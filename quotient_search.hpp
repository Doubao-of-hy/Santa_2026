#pragma once
#include "value_table.hpp"
#include <cmath>
#include <random>

// A forward dictionary of two-instruction expressions. Reverse search may make
// an exact division or use a nearby multiple, paying explicitly for the residual.
struct QuotientTable {
    Num limit;
    int beam;
    const Values& live;
    std::vector<Num> pivots, sorted;
    Table tab;
    size_t one_end;
    QuotientTable(Num cap, int width, int breadth, const Values& available,
                  const std::vector<Num>& priority)
        : limit(cap), beam(breadth), live(available), tab(width) {
        Values seen;
        for (Num x : priority)
            if (seen.insert(x).second) pivots.push_back(x);
        int m = std::min<int>(width, pivots.size());
        auto add = [&](int i, int j, int cost) {
            auto x = tab.entries[i], y = tab.entries[j];
            forward(x.value, y.value, limit, [&](Num v, Arithmetic e) {
                bool keep = e.a == x.value;
                tab.put(v, 0, keep ? i : j, keep ? j : i, e.op, cost);
            });
        };
        for (int i = 0; i < m; ++i) tab.put(pivots[i], 0, -1, -1, 0, 0);
        for (int i = 0; i < m; ++i)
            for (int j = 0; j <= i; ++j) add(i, j, 1);
        one_end = tab.entries.size();
        for (int i = m; i < (int)one_end; ++i) {
            for (int j = 0; j < m; ++j) add(i, j, 2);
            add(i, i, 2);
        }
        if (pivots.size() > 110) pivots.resize(110);
        sorted.reserve(tab.entries.size());
        for (auto e : tab.entries) sorted.push_back(e.value);
        std::sort(sorted.begin(), sorted.end());
    }
    int cost(Num x) const {
        if (live.count(x)) return 0;
        int i = tab.find(x);
        return i < 0 ? 100 : tab.entries[i].cost;
    }
    void emit(Num x, Patch& p) const {
        if (live.count(x)) return;
        auto e = tab.entries.at(tab.find(x));
        Num a = tab.entries[e.left].value, b = tab.entries[e.right].value;
        emit(a, p);
        if (a != b) emit(b, p);
        p.push_back({x, {a, b, e.op}});
    }
    double rank(Num x) const {
        int c = cost(x);
        if (c < 100) return -100 + c;
        auto it = std::lower_bound(sorted.begin(), sorted.end(), x);
        Num diff = x;
        if (it != sorted.end()) diff = std::min(diff, *it - x);
        if (it != sorted.begin()) diff = std::min(diff, x - *std::prev(it));
        int trailing = __builtin_ctzll(static_cast<uint64_t>(x));
        return std::min(std::log2(1.0 + diff) + 2.5, std::log2(1.0 + x) - 0.9 * trailing);
    }
    bool shallow(Num t, int bound, Patch& best, bool thorough) const {
        int orig = bound;
        auto remember = [&](Num x, Num y, const Patch& suffix) {
            int a = cost(x), b = y == 0 || x == y ? 0 : cost(y);
            if (a + b + (int)suffix.size() >= bound) return;
            Patch out;
            emit(x, out);
            if (y && y != x) emit(y, out);
            out.insert(out.end(), suffix.begin(), suffix.end());
            best = std::move(out);
            bound = best.size();
        };
        remember(t, 0, {});
        if (bound <= 1) return bound < orig;
        for (Num a : pivots)
            inverse(t, a, limit, [&](Num x, Arithmetic op) {
                if (x != t && cost(x) + 1 < bound) remember(x, 0, {{t, op}});
                return false;
            });
        if (bound <= 2 || !thorough) return bound < orig;
        // For each available multiplier, inspect the exact quotient and nearby
        // dictionary values. Their signed remainder can itself cost up to two steps.
        for (Num a : pivots) {
            if (a <= 1 || a > t) continue;
            Num q = t / a;
            auto it = std::lower_bound(sorted.begin(), sorted.end(), q);
            int idx = it - sorted.begin();
            auto attempt = [&](Num x) {
                if (x <= 0 || x > limit / a) return;
                Num product = x * a;
                if (product == t) {
                    remember(x, 0, {{t, {x, a, '*'}}});
                    return;
                }
                Num r = std::abs(t - product);
                if (cost(x) + cost(r) + 2 >= bound) return;
                remember(x, r,
                         {{product, {x, a, '*'}}, {t, {product, r, t > product ? '+' : '-'}}});
            };
            attempt(q);
            attempt(q + 1);
            for (int j = std::max(0, idx - 3); j < std::min<int>(sorted.size(), idx + 4); ++j)
                attempt(sorted[j]);
        }
        if (bound <= 3) return bound < orig;
        // Enumerate one-step vs. two-step branches only for promising states.
        for (int i = 0; i < (int)one_end; ++i) {
            Num a = tab.entries[i].value;
            if (a == t) continue;
            inverse(t, a, limit, [&](Num x, Arithmetic op) {
                if (x != t && cost(x) + cost(a) + 1 < bound) remember(a, x, {{t, op}});
                return false;
            });
        }
        return bound < orig;
    }
    struct State {
        Num v;
        int parent;
        Patch suffix;
        double quality;
    };
    Patch search(Num target, int bound) const {
        Patch answer;
        shallow(target, bound + 1, answer, true);
        int best = answer.empty() ? bound + 1 : (int)answer.size();
        std::vector<State> states{{target, -1, {}, 0}};
        std::vector<std::vector<int>> layers(std::min(best, 12) + 1);
        layers[0].push_back(0);
        std::unordered_map<Num, int> distance{{target, 0}};
        for (int depth = 0; depth < (int)layers.size() && depth < best; ++depth) {
            auto& bucket = layers[depth];
            int keep = std::min<int>(beam, bucket.size());
            auto cmp = [&](int a, int b) {
                if (states[a].quality != states[b].quality)
                    return states[a].quality < states[b].quality;
                return a < b;
            };
            std::partial_sort(bucket.begin(), bucket.begin() + keep, bucket.end(), cmp);
            for (int k = 0; k < keep; ++k) {
                int idx = bucket[k];
                Num v = states[idx].v;
                if (distance[v] != depth) continue;
                Patch tail;
                if (shallow(v, best - depth, tail, k < 2 && depth != 0)) {
                    for (int j = idx; states[j].parent >= 0; j = states[j].parent)
                        tail.insert(tail.end(), states[j].suffix.begin(), states[j].suffix.end());
                    best = tail.size();
                    answer = std::move(tail);
                }
                if (depth + 2 >= best) continue;
                auto push = [&](Num x, Patch suffix) {
                    int d = depth + suffix.size();
                    if (d >= best || d >= (int)layers.size()) return;
                    auto it = distance.find(x);
                    if (it != distance.end() && it->second <= d) return;
                    distance[x] = d;
                    double h = rank(x);
                    layers[d].push_back(states.size());
                    states.push_back({x, idx, std::move(suffix), h});
                };
                for (Num a : pivots) {
                    inverse(v, a, limit, [&](Num x, Arithmetic op) {
                        if (x != v) push(x, {{v, op}});
                        return false;
                    });
                    if (a <= 1 || a >= v) continue;
                    Num q = v / a, r = v % a;
                    if (r && live.count(r)) push(q, {{q * a, {q, a, '*'}}, {v, {q * a, r, '+'}}});
                    if (r && q + 1 <= limit / a && live.count(a - r)) {
                        Num product = (q + 1) * a;
                        push(q + 1, {{product, {q + 1, a, '*'}}, {v, {product, a - r, '-'}}});
                    }
                }
                // Allow a newly synthesized large component and solve only its residual.
                int at = std::lower_bound(sorted.begin(), sorted.end(), v) - sorted.begin();
                for (int j = std::max(0, at - 3); j < std::min<int>(sorted.size(), at + 4); ++j) {
                    Num a = sorted[j], diff = std::abs(v - a);
                    if (!diff || (a > v && diff >= v)) continue;
                    Patch plan;
                    emit(a, plan);
                    plan.push_back({v, {a, diff, v > a ? '+' : '-'}});
                    push(diff, std::move(plan));
                }
            }
        }
        return answer;
    }
};
