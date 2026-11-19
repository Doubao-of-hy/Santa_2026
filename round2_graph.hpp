#pragma once
#include <algorithm>
#include <cstdint>
#include <functional>
#include <iostream>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include <stdexcept>

using Num = std::int64_t;
#include "cut_search.hpp"

using Step = std::pair<Num, Arithmetic>;
using Patch = std::vector<Step>;

template <class F>
void forward(Num a, Num b, Num limit, F out) {
    if (a <= limit - b) out(a + b, Arithmetic{a, b, '+'});
    if (a <= limit / b) out(a * b, Arithmetic{a, b, '*'});
    if (a < b) std::swap(a, b);
    if (a > b) out(a - b, Arithmetic{a, b, '-'});
    if (a % b == 0) out(a / b, Arithmetic{a, b, '/'});
}

struct Circuit {
    Num limit;
    Values seeds;
    std::vector<Num> targets, original;
    Definitions expr;

    // A blocked root costs one placeholder node; its ancestors may disappear.
    std::vector<Num> trace(Num stop = 0) const {
        Values done = seeds, pending;
        std::vector<Num> order;
        std::function<void(Num)> walk = [&](Num v) {
            if (done.count(v)) return;
            if (!pending.insert(v).second) throw std::logic_error("cycle");
            if (v != stop) {
                auto e = expr.at(v);
                walk(e.a);
                walk(e.b);
            }
            pending.erase(v);
            done.insert(v);
            order.push_back(v);
        };
        for (Num t : targets) walk(t);
        return order;
    }
    std::vector<Num> keep_order() const {
        auto order = trace();
        std::unordered_map<Num, int> rank;
        for (int i = 0; i < (int)original.size(); ++i) rank[original[i]] = i;
        // Preserve input order when it still respects all dependencies.
        std::unordered_map<Num, int> priority;
        for (Num v : order) {
            auto e = expr.at(v);
            int base = rank.count(v) ? rank.at(v) : 0;
            priority[v] = std::max({base, priority[e.a] + 1, priority[e.b] + 1});
        }
        std::stable_sort(order.begin(), order.end(),
                         [&](Num a, Num b) { return priority[a] < priority[b]; });
        return order;
    }
    void apply(const Patch& patch) {
        for (auto [v, e] : patch) expr[v] = e;
    }
    std::vector<Num> anchors() const {
        std::vector<Num> result(seeds.begin(), seeds.end());
        std::sort(result.begin(), result.end());
        auto active = keep_order();
        result.insert(result.end(), active.begin(), active.end());
        return result;
    }
    void print() const {
        auto active = trace();
        std::cout << active.size() << '\n';
        for (Num v : active) {
            auto e = expr.at(v);
            std::cout << v << ' ' << e.a << ' ' << e.op << ' ' << e.b << '\n';
        }
    }
};

// Common protocol for the row driver. Only the bidirectional engine uses
// depth and pivot_passes. The other searches have explicit CLI parameters.
struct SearchOptions {
    int width, depth, passes, extra;
    unsigned seed;
};
inline bool read_circuit(std::istream& input, Circuit& graph, SearchOptions& options) {
    int ns, nt, n;
    if (!(input >> graph.limit >> ns >> nt >> n >> options.width >> options.depth >>
          options.passes >> options.extra >> options.seed))
        return false;
    for (int i = 0; i < ns; ++i) {
        Num x;
        if (!(input >> x)) return false;
        graph.seeds.insert(x);
    }
    for (int i = 0; i < nt; ++i) {
        Num x;
        if (!(input >> x)) return false;
        graph.targets.push_back(x);
    }
    for (int i = 0; i < n; ++i) {
        Num v, a, b;
        char op;
        if (!(input >> v >> a >> op >> b)) return false;
        graph.original.push_back(v);
        graph.expr[v] = {a, b, op};
    }
    return true;
}
