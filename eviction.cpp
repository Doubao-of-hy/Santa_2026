// Delete a shared value and jointly repair every consumer. This can recover a
// producer whose cost cannot be reclaimed by changing any one consumer alone.
#include "round2_graph.hpp"
#include <random>
#include <array>

struct Producers {
    std::array<Arithmetic, 4> options;
    int count = 0;
};

struct Eviction {
    Circuit g;
    std::mt19937 rng;
    int breadth;
    using Catalog = std::unordered_map<Num, Producers>;

    bool attempt() {
        auto active = g.keep_order();
        auto pool = g.anchors();
        std::unordered_map<Num, std::vector<Num>> users;
        std::unordered_map<Num, int> position;
        for (int i = 0; i < (int)active.size(); ++i) {
            Num v = active[i];
            position[v] = i;
            auto e = g.expr.at(v);
            users[e.a].push_back(v);
            if (e.a != e.b) users[e.b].push_back(v);
        }
        Values goals(g.targets.begin(), g.targets.end());
        std::vector<Num> victims;
        for (Num v : active)
            if (!goals.count(v) && users[v].size() >= 2 && users[v].size() <= 5)
                victims.push_back(v);
        std::shuffle(victims.begin(), victims.end(), rng);
        // Vary duplicate producers across sweeps. Preserve several ways to make
        // the same intermediate, because one of their inputs might be evicted.
        std::shuffle(pool.begin(), pool.end(), rng);
        Catalog table;
        table.reserve(pool.size() * pool.size() * 2);
        for (size_t i = 0; i < pool.size(); ++i)
            for (size_t j = 0; j <= i; ++j)
                forward(pool[i], pool[j], g.limit, [&](Num v, Arithmetic e) {
                    if (v == e.a || v == e.b) return;
                    auto& entry = table[v];
                    if (entry.count < (int)entry.options.size()) entry.options[entry.count++] = e;
                });
        for (Num victim : victims) {
            Values downstream{victim}, boundary = g.seeds;
            Values blocked(users[victim].begin(), users[victim].end());
            // Stop at all outputs being rewritten. Other reachable nodes will
            // survive the joint deletion and can be used without extra cost.
            std::function<void(Num)> collect = [&](Num v) {
                if (!boundary.insert(v).second || blocked.count(v)) return;
                auto e = g.expr.at(v);
                collect(e.a);
                collect(e.b);
            };
            for (Num t : g.targets) collect(t);
            std::unordered_map<Num, int> cost;
            for (Num v : active) {
                auto e = g.expr.at(v);
                if (downstream.count(e.a) || downstream.count(e.b)) downstream.insert(v);
                if (!boundary.count(v))
                    cost[v] = 1 + std::min(100, cost[e.a] + (e.a != e.b ? cost[e.b] : 0));
            }
            std::vector<std::vector<Patch>> options;
            for (Num c : users[victim]) {
                int pos = position.at(c);
                auto allowed = [&](Num v) {
                    return v != victim && (!downstream.count(v) || position.at(v) < pos);
                };
                std::vector<std::pair<int, Patch>> choices;
                auto offer = [&](Num x, Arithmetic inner, Arithmetic outer) {
                    if (!allowed(inner.a) || !allowed(inner.b)) return;
                    int weight = cost[inner.a] + (inner.a != inner.b ? cost[inner.b] : 0);
                    Patch patch;
                    if (x == c)
                        patch.push_back({c, inner});
                    else {
                        Num leaf = outer.a == x ? outer.b : outer.a;
                        if (!allowed(leaf)) return;
                        weight += 1 + cost[leaf];
                        patch = {{x, inner}, {c, outer}};
                    }
                    choices.push_back({weight, std::move(patch)});
                };
                const auto& direct = table.at(c);
                for (int i = 0; i < direct.count; ++i) offer(c, direct.options[i], {});
                for (Num a : pool)
                    if (allowed(a))
                        inverse(c, a, g.limit, [&](Num x, Arithmetic outer) {
                            if (x == c || x == victim || position.count(x) || g.seeds.count(x))
                                return false;
                            auto it = table.find(x);
                            if (it == table.end()) return false;
                            for (int i = 0; i < it->second.count; ++i)
                                offer(x, it->second.options[i], outer);
                            return false;
                        });
                if (choices.empty()) break;
                std::shuffle(choices.begin(), choices.end(), rng);
                std::stable_sort(choices.begin(), choices.end(),
                                 [](const auto& a, const auto& b) { return a.first < b.first; });
                std::vector<Patch> shortlist;
                for (auto& e : choices) {
                    if ((int)shortlist.size() >= breadth || e.first > choices.front().first + 3)
                        break;
                    shortlist.push_back(std::move(e.second));
                }
                options.push_back(std::move(shortlist));
            }
            if (options.size() != blocked.size()) continue;
            // Enumerate a narrow beam. Count actual live DAG nodes after each
            // combined edit, so shared newly introduced operands are priced once.
            std::vector<Patch> beam(1);
            for (const auto& list : options) {
                std::vector<std::pair<int, Patch>> next;
                for (const Patch& prefix : beam)
                    for (const Patch& add : list) {
                        Patch all = prefix;
                        all.insert(all.end(), add.begin(), add.end());
                        Patch old;
                        Values inserted;
                        // A new value might be independently proposed twice with
                        // different producers. Use its first already legal producer.
                        for (auto [v, e] : all) {
                            if (!position.count(v) && !inserted.insert(v).second) continue;
                            auto it = g.expr.find(v);
                            if (it != g.expr.end()) old.push_back(*it);
                            g.expr[v] = e;
                        }
                        int size = g.trace().size();
                        if (size < (int)active.size()) {
                            g.print();
                            return true;
                        }
                        for (Num v : inserted) g.expr.erase(v);
                        g.apply(old);
                        next.push_back({size, std::move(all)});
                    }
                std::stable_sort(next.begin(), next.end(),
                                 [](const auto& a, const auto& b) { return a.first < b.first; });
                beam.clear();
                for (auto& entry : next) {
                    if ((int)beam.size() >= breadth) break;
                    beam.push_back(std::move(entry.second));
                }
            }
        }
        return false;
    }
};
int main() {
    std::ios::sync_with_stdio(false);
    Eviction s;
    SearchOptions opt;
    if (!read_circuit(std::cin, s.g, opt) || opt.width < 1) return 1;
    s.breadth = opt.width;
    s.rng.seed(opt.seed);
    for (int i = 0; i < opt.passes; ++i) s.attempt();
}
