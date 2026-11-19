#pragma once
#include "round2_graph.hpp"
#include <set>

struct Occurrence {
    Num target;
    Arithmetic recipe;
    int rank;
};
struct PivotGroup {
    Num x;
    std::vector<Occurrence> hits;
    int promise;
};

// Mine inverse arithmetic identities across different nodes. Each proposed pivot
// must have a producer earlier than every consumer it changes. Score all changes
// together on the complete multi-target graph, including reclaimed ancestors.
struct SharedPivot {
    Circuit& g;
    std::unordered_map<Num, int> rank, uses;
    std::vector<Num> pool;
    Definitions one;
    std::unordered_map<Num, std::vector<Occurrence>> index;

    void catalogue() {
        pool = g.anchors();
        for (int i = 0; i < (int)pool.size(); ++i) rank[pool[i]] = i;
        for (Num x : pool)
            if (!g.seeds.count(x)) {
                auto e = g.expr.at(x);
                uses[e.a]++;
                if (e.a != e.b) uses[e.b]++;
            }
        for (Num x : g.targets) uses[x]++;
        for (int i = 0; i < (int)pool.size(); ++i)
            for (int j = 0; j <= i; ++j) {
                Num a = pool[i], b = pool[j];
                forward(a, b, g.limit, [&](Num x, Arithmetic e) {
                    if (!rank.count(x)) one.emplace(x, e);
                });
            }
        for (int i = 0; i < (int)pool.size(); ++i) {
            Num t = pool[i];
            if (g.seeds.count(t)) continue;
            // With neither operand reclaimable the rewrite can only help via
            // a larger simultaneous deletion; keep those occurrences as well.
            for (int j = 0; j < i; ++j) {
                Num a = pool[j];
                inverse(t, a, g.limit, [&](Num x, Arithmetic e) {
                    if (x != t && !rank.count(x)) {
                        auto& hits = index[x];
                        if (hits.empty() || hits.back().target != t) hits.push_back({t, e, i});
                    }
                    return false;
                });
            }
        }
    }
    std::vector<Patch> producers(Num x, int latest) {
        std::vector<Patch> plans;
        auto it = one.find(x);
        if (it != one.end()) plans.push_back({{x, it->second}});
        for (int j = 0; j < latest && plans.size() < 12; ++j) {
            Num a = pool[j];
            inverse(x, a, g.limit, [&](Num y, Arithmetic e) {
                auto f = one.find(y);
                if (y != x && f != one.end() &&
                    std::max(rank[f->second.a], rank[f->second.b]) < latest)
                    plans.push_back({{y, f->second}, {x, e}});
                return false;
            });
        }
        return plans;
    }
    bool run() {
        catalogue();
        std::vector<PivotGroup> groups;
        for (auto& [x, hits] : index) {
            if (hits.size() < 2) continue;
            int potential = 0;
            for (auto& h : hits) {
                auto d = g.expr.at(h.target);
                potential += (uses[d.a] == 1) + (d.a != d.b && uses[d.b] == 1);
            }
            // Two simultaneous replacements may release a doubly used operand.
            if (potential == 0 && hits.size() < 3) continue;
            groups.push_back({x, std::move(hits), potential});
        }
        std::sort(groups.begin(), groups.end(), [](const auto& a, const auto& b) {
            if (a.promise != b.promise) return a.promise > b.promise;
            if (a.hits.size() != b.hits.size()) return a.hits.size() > b.hits.size();
            return a.x < b.x;
        });
        int original = g.trace().size(), best = original;
        Patch winner;
        // Never use stale ranks after accepting a pivot. Rebuild the catalogue
        // in the next pass, when deleted operands and new opportunities are known.
        for (auto& group : groups) {
            int last = group.hits.back().rank;
            for (auto setup : producers(group.x, last)) {
                int earliest = -1;
                for (auto [v, e] : setup)
                    for (Num operand : {e.a, e.b})
                        if (rank.count(operand)) earliest = std::max(earliest, rank[operand]);
                Patch trial = setup;
                for (auto& h : group.hits)
                    if (h.rank > earliest) trial.emplace_back(h.target, h.recipe);
                if (trial.size() < setup.size() + 2) continue;
                Patch saved;
                for (size_t i = setup.size(); i < trial.size(); ++i)
                    saved.emplace_back(trial[i].first, g.expr.at(trial[i].first));
                g.apply(trial);
                int size = g.trace().size();
                if (size < best) {
                    best = size;
                    winner = trial;
                }
                g.apply(saved);
                for (auto [v, e] : setup) g.expr.erase(v);
            }
        }
        if (best < original) {
            g.apply(winner);
            return true;
        }
        return false;
    }
};
