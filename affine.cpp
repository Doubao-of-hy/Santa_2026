// Mine shared multipliers beyond a single reverse operation:
// t = a*x + b, a*x - b, or b - a*x. Goals may mix one- and two-step uses
// of x. Charge its construction once and score all rewrites on the full DAG.
#include "round2_graph.hpp"

struct Use {
    Num target, product;
    Arithmetic root, multiply;
    int rank, benefit;
};
struct Recurrence {
    Num pivot;
    int benefit;
    size_t count;
};
struct Affine {
    Circuit g;
    int width;
    bool sweep() {
        auto pool = g.anchors();
        std::unordered_map<Num, int> rank, uses;
        std::unordered_map<Num, Arithmetic> one;
        for (int i = 0; i < (int)pool.size(); ++i) rank[pool[i]] = i;
        for (Num t : g.targets) uses[t]++;
        for (Num v : pool)
            if (!g.seeds.count(v)) {
                auto e = g.expr.at(v);
                uses[e.a]++;
                if (e.a != e.b) uses[e.b]++;
            }
        for (int i = 0; i < (int)pool.size(); ++i)
            for (int j = 0; j <= i; ++j)
                forward(pool[i], pool[j], g.limit, [&](Num x, Arithmetic e) {
                    if (!rank.count(x)) one.emplace(x, e);
                });
        auto multipliers = pool;
        std::stable_sort(multipliers.begin(), multipliers.end(),
                         [&](Num a, Num b) { return uses[a] > uses[b]; });
        if ((int)multipliers.size() > width) multipliers.resize(width);
        std::unordered_map<Num, std::vector<Use>> uses_of;
        std::unordered_map<Num, int> cost;
        auto record = [&](Num x, Use u) {
            if (x <= 1 || rank.count(x)) return;
            auto& entries = uses_of[x];
            if (!entries.empty() && entries.back().target == u.target) {
                if (u.benefit > entries.back().benefit) entries.back() = u;
            } else
                entries.push_back(u);
        };
        for (int i = 0; i < (int)pool.size(); ++i) {
            Num t = pool[i];
            if (g.seeds.count(t)) continue;
            auto e = g.expr.at(t);
            int exclusive = 1 + (uses[e.a] == 1 ? cost[e.a] : 0) +
                            (e.a != e.b && uses[e.b] == 1 ? cost[e.b] : 0);
            cost[t] = exclusive;
            for (int j = 0; j < i; ++j) {
                Num b = pool[j];
                inverse(t, b, g.limit, [&](Num x, Arithmetic root) {
                    record(x, {t, 0, root, {}, i, exclusive - 1});
                    return false;
                });
                if (exclusive < 2) continue;
                Num products[3] = {t > b ? t - b : 0, t <= g.limit - b ? t + b : 0,
                                   b > t ? b - t : 0};
                for (int op = 0; op < 3; ++op) {
                    Num product = products[op];
                    if (!product) continue;
                    // A pre-existing product is already available to the one-step catalogue.
                    if (rank.count(product)) continue;
                    for (Num a : multipliers) {
                        if (a < 2 || a >= product || rank[a] >= i || product % a) continue;
                        Num x = product / a;
                        Arithmetic root = op == 0   ? Arithmetic{product, b, '+'}
                                          : op == 1 ? Arithmetic{product, b, '-'}
                                                    : Arithmetic{b, product, '-'};
                        record(x, {t, product, root, {x, a, '*'}, i, exclusive - 2});
                    }
                }
            }
        }
        std::vector<Recurrence> candidates;
        for (const auto& [x, list] : uses_of) {
            if (list.size() < 2) continue;
            bool affine = false;
            int benefit = 0;
            for (const auto& u : list) {
                affine |= u.product != 0;
                benefit += u.benefit;
            }
            if (affine && benefit >= 1) candidates.push_back({x, benefit, list.size()});
        }
        std::sort(candidates.begin(), candidates.end(), [](auto a, auto b) {
            if (a.benefit != b.benefit) return a.benefit > b.benefit;
            if (a.count != b.count) return a.count > b.count;
            return a.pivot < b.pivot;
        });
        int best = g.trace().size(), initial = best;
        Patch winner;
        for (auto candidate : candidates) {
            Num x = candidate.pivot;
            const auto& list = uses_of.at(x);
            std::vector<Patch> plans;
            auto direct = one.find(x);
            if (direct != one.end()) plans.push_back({{x, direct->second}});
            for (int i = 0; i < list.back().rank && plans.size() < 12; ++i)
                inverse(x, pool[i], g.limit, [&](Num y, Arithmetic e) {
                    auto it = one.find(y);
                    if (y != x && it != one.end() &&
                        std::max(rank[it->second.a], rank[it->second.b]) < list.back().rank)
                        plans.push_back({{y, it->second}, {x, e}});
                    return false;
                });
            for (auto plan : plans) {
                int earliest = -1, n = 0;
                Values made;
                for (auto [v, e] : plan) {
                    made.insert(v);
                    for (Num operand : {e.a, e.b})
                        if (rank.count(operand)) earliest = std::max(earliest, rank.at(operand));
                }
                for (const auto& u : list) {
                    if (u.rank <= earliest) continue;
                    if (u.product && made.insert(u.product).second)
                        plan.emplace_back(u.product, u.multiply);
                    plan.emplace_back(u.target, u.root);
                    n++;
                }
                if (n < 2) continue;
                Patch old;
                for (auto [v, e] : plan)
                    if (g.expr.count(v)) old.emplace_back(v, g.expr.at(v));
                g.apply(plan);
                int size = g.trace().size();
                if (size < best) {
                    best = size;
                    winner = plan;
                }
                for (auto [v, e] : plan) g.expr.erase(v);
                g.apply(old);
            }
        }
        if (best == initial) return false;
        g.apply(winner);
        g.print();
        return true;
    }
};
int main() {
    std::ios::sync_with_stdio(false);
    Affine s;
    SearchOptions opt;
    if (!read_circuit(std::cin, s.g, opt) || opt.width < 1) return 1;
    s.width = opt.width;
    for (int i = 0; i < opt.passes; ++i)
        if (!s.sweep()) break;
}
