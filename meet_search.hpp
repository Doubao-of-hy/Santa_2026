#pragma once
#include "round2_graph.hpp"
#include <cmath>
#include <random>
#include <limits>

#include "value_table.hpp"
struct MeetSearch {
    Circuit& g;
    int width, level;
    std::vector<Num> basis;
    Table table;
    size_t one_end = 0;
    MeetSearch(Circuit& graph, int w, int depth, uint32_t salt)
        : g(graph), width(w), level(depth), table(w) {
        auto all = g.anchors();
        std::unordered_map<Num, int> counts;
        for (Num v : all)
            if (!g.seeds.count(v)) {
                auto e = g.expr.at(v);
                counts[e.a]++;
                counts[e.b]++;
            }
        std::mt19937 gen(salt);
        auto ranked = all;
        std::shuffle(ranked.begin(), ranked.end(), gen);
        std::stable_sort(ranked.begin(), ranked.end(),
                         [&](Num a, Num b) { return counts[a] > counts[b]; });
        Values seen;
        auto select = [&](Num x) {
            if ((int)basis.size() < width && seen.insert(x).second) basis.push_back(x);
        };
        for (Num v : all)
            if (g.seeds.count(v)) select(v);
        for (int i = 0; i < (int)ranked.size() && (int)basis.size() < width * 2 / 3; ++i)
            select(ranked[i]);
        std::shuffle(all.begin(), all.end(), gen);
        for (Num v : all) select(v);
        for (int i = 0; i < (int)basis.size(); ++i)
            table.put(basis[i], uint64_t(1) << i, -1, -1, 0, 0);
        int m = basis.size();
        auto combine = [&](int a, int b, int cost) {
            auto x = table.entries[a], y = table.entries[b];
            forward(x.value, y.value, g.limit, [&](Num v, Arithmetic e) {
                bool same = e.a == x.value;
                table.put(v, x.mask | y.mask, same ? a : b, same ? b : a, e.op, cost);
            });
        };
        for (int a = 0; a < m; ++a)
            for (int b = 0; b <= a; ++b) combine(a, b, 1);
        one_end = table.entries.size();
        for (int a = m; a < (int)one_end; ++a) {
            for (int b = 0; b < m; ++b) combine(a, b, 2);
            combine(a, a, 2);
        }
    }
    bool replace(Num t, const Values& free, const Values& forbidden, int budget, Patch& output) {
        uint64_t banned = 0;
        for (int i = 0; i < (int)basis.size(); ++i)
            if (!free.count(basis[i])) banned |= uint64_t(1) << i;
        std::vector<Num> pivots(free.begin(), free.end());
        std::sort(pivots.begin(), pivots.end());
        auto eligible = [&](int i) { return i >= 0 && !(table.entries[i].mask & banned); };
        auto accept = [&](int first, int second, const Patch& tail) {
            if (!eligible(first) || (second >= 0 && !eligible(second))) return false;
            Patch patch;
            Values done;
            auto visit = [&](auto&& self, int i) -> bool {
                auto e = table.entries[i];
                if (free.count(e.value) || done.count(e.value)) return true;
                if (forbidden.count(e.value) || e.cost == 0) return false;
                if (!self(self, e.left) || !self(self, e.right)) return false;
                done.insert(e.value);
                patch.push_back(
                    {e.value, {table.entries[e.left].value, table.entries[e.right].value, e.op}});
                return true;
            };
            if (!visit(visit, first) || (second >= 0 && !visit(visit, second))) return false;
            for (auto [v, e] : tail) {
                if (free.count(v) || done.count(v)) continue;
                if (forbidden.count(v)) return false;
                done.insert(v);
                patch.emplace_back(v, e);
            }
            if (patch.empty() || patch.back().first != t || (int)patch.size() > budget)
                return false;
            output = std::move(patch);
            return true;
        };
        if (accept(table.find(t), -1, {})) return true;
        for (Num a : pivots)
            if (inverse(t, a, g.limit, [&](Num x, Arithmetic e) {
                    return x != t && accept(table.find(x), -1, {{t, e}});
                }))
                return true;
        if (budget < 4) return false;
        auto fork = [&](Num y, size_t count, const Patch& suffix) {
            for (size_t i = basis.size(); i < count; ++i) {
                if (!eligible(i)) continue;
                Num x = table.entries[i].value;
                if (x == y || x == t) continue;
                if (inverse(y, x, g.limit, [&](Num z, Arithmetic e) {
                        if (z == t || z == y) return false;
                        int j = table.find(z);
                        if (!eligible(j)) return false;
                        Patch tail{{y, e}};
                        tail.insert(tail.end(), suffix.begin(), suffix.end());
                        return accept(i, j, tail);
                    }))
                    return true;
            }
            return false;
        };
        if (fork(t, one_end, {})) return true;
        for (Num a : pivots)
            if (inverse(t, a, g.limit, [&](Num y, Arithmetic last) {
                    if (y == t || forbidden.count(y) || free.count(y)) return false;
                    for (Num b : pivots)
                        if (inverse(y, b, g.limit, [&](Num x, Arithmetic middle) {
                                if (x == t || x == y) return false;
                                int i = table.find(x);
                                return eligible(i) && accept(i, -1, {{y, middle}, {t, last}});
                            }))
                            return true;
                    return false;
                }))
                return true;
        if (budget < 5) return false;
        if (fork(t, table.entries.size(), {})) return true;
        // Non-balanced five-operation trees, using active values that need not
        // belong to the forward basis as the final pivot.
        for (Num a : pivots)
            if (inverse(t, a, g.limit, [&](Num y, Arithmetic last) {
                    return y != t && !free.count(y) && !forbidden.count(y) &&
                           fork(y, one_end, {{t, last}});
                }))
                return true;
        if (budget < 6) return false;
        for (Num a : basis)
            if (free.count(a) && inverse(t, a, g.limit, [&](Num y, Arithmetic last) {
                    return y != t && !free.count(y) && !forbidden.count(y) &&
                           fork(y, table.entries.size(), {{t, last}});
                }))
                return true;
        return false;
    }
    bool run() {
        auto order = g.keep_order();
        bool improved = false;
        for (auto it = order.rbegin(); it != order.rend(); ++it) {
            Num t = *it;
            auto active = g.trace();
            if (std::find(active.begin(), active.end(), t) == active.end()) continue;
            auto kept = g.trace(t);
            int freed = static_cast<int>(active.size() - kept.size());
            if (freed < 3) continue;
            Values free = g.seeds, bad{t};
            for (Num v : kept) {
                if (v == t) continue;
                auto e = g.expr.at(v);
                if (bad.count(e.a) || bad.count(e.b))
                    bad.insert(v);
                else
                    free.insert(v);
            }
            bad.erase(t);
            Patch patch;
            if (replace(t, free, bad, std::min(level, freed), patch)) {
                g.apply(patch);
                if (g.trace().size() >= active.size())
                    throw std::logic_error("non-improving replacement");
                improved = true;
            }
        }
        return improved;
    }
};
