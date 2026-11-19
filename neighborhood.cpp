#include "quotient_search.hpp"
#include <numeric>

// Remove several roots simultaneously. The surviving subgraph may keep values
// from much later in the original program. Regrow each removed root from that
// shared boundary and replay the complete circuit before accepting a checkpoint.
struct Regrow {
    Circuit graph;
    int width, beam, passes, group_size;
    std::mt19937 rng;

    void restore(Num v, const Circuit& old, Values& known, Patch& patch) const {
        if (!known.insert(v).second) return;
        auto e = old.expr.at(v);
        restore(e.a, old, known, patch);
        restore(e.b, old, known, patch);
        patch.emplace_back(v, e);
    }
    Circuit trial(const std::vector<Num>& group, int variant) {
        Circuit candidate = graph;
        Values cuts(group.begin(), group.end()), visited = graph.seeds;
        std::vector<Num> kept;
        std::function<void(Num)> walk = [&](Num x) {
            if (!visited.insert(x).second) return;
            if (!cuts.count(x)) {
                auto e = graph.expr.at(x);
                walk(e.a);
                walk(e.b);
            }
            kept.push_back(x);
        };
        for (Num x : graph.targets) walk(x);
        Values known = graph.seeds, tainted = cuts;
        std::vector<Num> live(graph.seeds.begin(), graph.seeds.end());
        std::sort(live.begin(), live.end());
        for (Num x : kept) {
            if (cuts.count(x)) continue;
            auto e = graph.expr.at(x);
            if (tainted.count(e.a) || tainted.count(e.b))
                tainted.insert(x);
            else {
                known.insert(x);
                live.push_back(x);
            }
        }
        std::unordered_map<Num, int> uses;
        auto active = graph.trace();
        for (Num x : active) {
            auto e = graph.expr.at(x);
            uses[e.a]++;
            uses[e.b]++;
        }
        std::shuffle(live.begin(), live.end(), rng);
        size_t split = std::min(live.size(), static_cast<size_t>(width * 2 / 3));
        std::partial_sort(live.begin(), live.begin() + split, live.end(), [&](Num a, Num b) {
            return uses[a] != uses[b] ? uses[a] > uses[b] : a < b;
        });
        QuotientTable table(graph.limit, width, beam, known, live);
        std::vector<Num> order = group;
        std::shuffle(order.begin(), order.end(), rng);
        for (Num root : order) {
            if (known.count(root)) continue;
            Values temporary = known;
            Patch fallback;
            restore(root, graph, temporary, fallback);
            int bound = fallback.size() + (variant % 3 == 2);
            Patch new_path;
            if (bound >= 2) new_path = table.search(root, bound);
            const Patch& chosen =
                (new_path.empty() || (int)new_path.size() > bound) ? fallback : new_path;
            for (auto [v, e] : chosen)
                if (known.insert(v).second) {
                    candidate.expr[v] = e;
                    table.pivots.push_back(v);
                }
        }
        return candidate;
    }
    void run() {
        auto champion = graph;
        int record = graph.trace().size();
        for (int pass = 0; pass < passes; ++pass) {
            if (pass % 3 == 0) graph = champion;
            auto active = graph.keep_order();
            std::unordered_map<Num, int> uses;
            for (Num v : active) {
                auto e = graph.expr.at(v);
                uses[e.a]++;
                if (e.a != e.b) uses[e.b]++;
            }
            Values goals(graph.targets.begin(), graph.targets.end());
            for (Num x : graph.targets) uses[x]++;
            std::function<int(Num)> solo = [&](Num v) {
                if (graph.seeds.count(v)) return 0;
                auto e = graph.expr.at(v);
                return 1 + (uses[e.a] == 1 ? solo(e.a) : 0) +
                       (e.b != e.a && uses[e.b] == 1 ? solo(e.b) : 0);
            };
            std::vector<Num> nodes;
            for (Num x : active)
                if (solo(x) >= 2 && (goals.count(x) || pass % 2 == 1)) nodes.push_back(x);
            std::shuffle(nodes.begin(), nodes.end(), rng);
            for (size_t begin = 0; begin < nodes.size(); begin += group_size) {
                auto now = graph.trace();
                Values present(now.begin(), now.end());
                std::vector<Num> group;
                for (size_t j = begin; j < std::min(nodes.size(), begin + group_size); ++j)
                    if (present.count(nodes[j])) group.push_back(nodes[j]);
                if (group.empty()) continue;
                Circuit proposal = trial(group, pass);
                int n = proposal.trace().size();
                if (n < record) {
                    graph = std::move(proposal);
                    record = n;
                    champion = graph;
                    graph.print();
                } else if (n <= (int)now.size() && n <= record + 1)
                    graph = std::move(proposal);
            }
        }
    }
};
int main() {
    std::ios::sync_with_stdio(false);
    Regrow s;
    SearchOptions opt;
    if (!read_circuit(std::cin, s.graph, opt) || opt.width < 2 || opt.width > 63 || opt.extra < 1 ||
        opt.depth < 1)
        return 1;
    s.width = opt.width;
    s.group_size = opt.depth;
    s.beam = opt.extra;
    s.passes = opt.passes;
    s.rng.seed(opt.seed);
    s.run();
}
