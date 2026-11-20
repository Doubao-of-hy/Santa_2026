// Exhaustive helper-budget decision search, in the permanent-value relaxation.
// A completed unsuccessful search rules out every machine program of that length.
#include <algorithm>
#include <array>
#include <string>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <unordered_map>
#include <unordered_set>
#include <vector>

using Num = std::int64_t;
using Mask = std::uint64_t;
using Values = std::vector<Num>;
using Set = std::unordered_set<Num>;

struct Search {
    Num limit;
    Values seeds, goals, base;
    std::unordered_map<Num, Mask> goal_bit, unary;
    // At a two-helper boundary, these index all single-helper witnesses
    // using seeds, any goals (even future ones), and the earlier helpers.
    std::vector<Mask> dense_unary, dense_goals;
    std::vector<Values> partners;
    std::unordered_map<Num, Values> exceptional;
    unsigned shard = 0, shards = 1, shard_two = 0, shards_two = 1;
    unsigned shard_three = 0, shards_three = 1;
    bool elsewhere(std::size_t depth, unsigned& index) const {
        if (depth == 0) return index++ % shards != shard;
        if (depth == 1) return index++ % shards_two != shard_two;
        if (depth == 2 && shards_three > 1) return index++ % shards_three != shard_three;
        return false;
    }
    using Wide = __int128_t;
    static Num isqrt(Wide n) {
        Num r = static_cast<Num>(std::sqrt(static_cast<long double>(n)));
        while (Wide(r + 1) * (r + 1) <= n) ++r;
        while (Wide(r) * r > n) --r;
        return r;
    }
    // Two different outputs of one pair select two of sum, positive
    // difference, product and exact quotient. Invert all six combinations.
    void exceptional_pairs() {
        auto add = [&](Num a, Num b) {
            if (b < 1 || a <= b || a > limit || __builtin_popcountll(hits(a, b)) < 2) return;
            exceptional[a].push_back(b);
            exceptional[b].push_back(a);
        };
        for (Num x : goals)
            for (Num y : goals)
                if (x != y) {
                    if (x > y && (x - y) % 2 == 0) add((x + y) / 2, (x - y) / 2);
                    for (int sign : {-1, 1}) {
                        Wide d = Wide(x) * x + sign * Wide(4) * y;
                        if (d < 0) continue;
                        Num r = isqrt(d);
                        if (Wide(r) * r != d || (x + r) % 2) continue;
                        add((x + r) / 2, sign < 0 ? (x - r) / 2 : (r - x) / 2);
                    }
                    if (x % (y + 1) == 0) {
                        Num b = x / (y + 1);
                        add(x - b, b);
                    }
                    if (y > 1 && x % (y - 1) == 0) {
                        Num b = x / (y - 1);
                        add(x + b, b);
                    }
                    if (x % y == 0) {
                        Num b = isqrt(x / y);
                        if (Wide(b) * b * y == x) add(b * y, b);
                    }
                }
        for (auto& entry : exceptional) {
            auto& v = entry.second;
            std::sort(v.begin(), v.end());
            v.erase(std::unique(v.begin(), v.end()), v.end());
        }
    }
    struct Edit {
        Num value;
        unsigned goal;
        Mask before;
    };
    Mask current(Num x) const {
        if (!dense_unary.empty()) return dense_unary[x];
        auto it = unary.find(x);
        return it == unary.end() ? 0 : it->second;
    }
    void put(Num x, Mask m) {
        if (!dense_unary.empty())
            dense_unary[x] = m;
        else if (m)
            unary[x] = m;
        else
            unary.erase(x);
    }
    Mask all = 0, initial_supported = 0;
    std::uint64_t nodes = 0, max_nodes, last_candidates = 0;
    bool interrupted = false;
    Values witness;

    template <class F>
    void operations(Num a, Num b, F emit) const {
        if (a <= limit - b) emit(a + b);
        if (a <= limit / b) emit(a * b);
        if (a < b) std::swap(a, b);
        if (a > b) emit(a - b);
        if (a % b == 0) emit(a / b);
    }
    Mask hits(Num a, Num b) const {
        Mask m = 0;
        operations(a, b, [&](Num z) {
            if (z == a || z == b) return;
            if (!dense_goals.empty())
                m |= dense_goals[z];
            else {
                auto i = goal_bit.find(z);
                if (i != goal_bit.end()) m |= i->second;
            }
        });
        return m;
    }
    template <class F>
    void inverse(Num t, Num b, F add) const {
        if (t > b) add(t - b);
        if (b > t) add(b - t);
        if (t <= limit - b) add(t + b);
        if (t <= limit / b) add(t * b);
        if (b % t == 0) add(b / t);
        if (t % b == 0) add(t / b);
    }
    void prepare() {
        base = seeds;
        base.insert(base.end(), goals.begin(), goals.end());
        std::sort(base.begin(), base.end());
        base.erase(std::unique(base.begin(), base.end()), base.end());
        for (std::size_t i = 0; i < goals.size(); ++i) {
            Num t = goals[i];
            Mask bit = Mask(1) << i;
            goal_bit[t] = bit;
            all |= bit;
            if (std::find(seeds.begin(), seeds.end(), t) != seeds.end()) initial_supported |= bit;
            for (Num b : base)
                if (b != t) inverse(t, b, [&](Num h) { unary[h] |= bit; });
            if (t % 2 == 0) unary[t / 2] |= bit;
            Num root = static_cast<Num>(std::sqrt(static_cast<long double>(t)));
            while (root + 1 <= t / (root + 1)) ++root;
            while (root > t / root) --root;
            if (root * root == t) unary[root] |= bit;
            // One is either a seed or can be made by dividing any other seed by itself.
        }
        partners.resize(goals.size());
        for (auto [x, m] : unary)
            while (m) {
                unsigned j = __builtin_ctzll(m);
                partners[j].push_back(x);
                m &= m - 1;
            }
        if (limit <= 4000000) {
            dense_unary.assign(limit + 1, 0);
            dense_goals.assign(limit + 1, 0);
            for (auto [x, m] : unary) dense_unary[x] = m;
            for (auto [x, m] : goal_bit) dense_goals[x] = m;
        }
        exceptional_pairs();
        for (Num a : base)
            for (Num b : base)
                if (a >= b) initial_supported |= hits(a, b);
    }
    Mask support(Num h, const Values& helpers) const {
        auto it = unary.find(h);
        Mask m = it == unary.end() ? 0 : it->second;
        for (Num x : helpers) m |= hits(x, h);
        return m;
    }
    void extend_index(Num v, std::vector<Edit>& edits) {
        for (unsigned j = 0; j < goals.size(); ++j)
            inverse(goals[j], v, [&](Num x) {
                Mask bit = Mask(1) << j, old = current(x);
                if (!(old & bit)) {
                    edits.push_back({x, j, old});
                    partners[j].push_back(x);
                    put(x, old | bit);
                }
            });
    }
    void undo_index(const std::vector<Edit>& edits) {
        for (auto i = edits.rbegin(); i != edits.rend(); ++i) {
            partners[i->goal].pop_back();
            put(i->value, i->before);
        }
    }
    using Shortlists = std::unordered_map<Mask, Values>;
    template <class Forbidden>
    bool last_possible(Num first, Mask missing, const Forbidden& forbidden, Shortlists& cache) const {
        if (!missing) return true;
        auto covers = [&](Num last) {
            if (last == first || forbidden.count(last)) return false;
            Mask left = missing & ~current(last);
            return !left || (hits(first, last) & left) == left;
        };
        unsigned j = __builtin_ctzll(missing);
        if ((missing & (missing - 1)) == 0) {
            // If first and last jointly produce the sole residual goal,
            // the partner must be one of its inverse images.
            for (Num last : partners[j])
                if (covers(last)) return true;
            bool possible = false;
            inverse(goals[j], first, [&](Num last) {
                if (covers(last)) possible = true;
            });
            return possible;
        }
        auto [it, inserted] = cache.try_emplace(missing);
        if (inserted) {
            unsigned k = __builtin_ctzll(missing & (missing - 1));
            // A helper that covers all but one of >=2 residual goals covers
            // at least one of these two. Cache the list across first choices.
            for (unsigned pivot : {j, k})
                for (Num v : partners[pivot]) {
                    Mask left = missing & ~current(v);
                    if (!(left & (left - 1))) it->second.push_back(v);
                }
        }
        for (Num last : it->second)
            if (covers(last)) return true;
        auto ei = exceptional.find(first);
        if (ei != exceptional.end())
            for (Num last : ei->second)
                if (covers(last)) return true;
        return false;
    }
    // Saturating newly reachable targets is lossless when all computed values
    // can be retained. Each missing target costs exactly one first occurrence.
    void close(Values& active, Mask& seen, std::size_t start) const {
        for (std::size_t i = start; i < active.size(); ++i) {
            Mask next = 0;
            for (std::size_t j = 0; j <= i; ++j) next |= hits(active[i], active[j]);
            next &= ~seen;
            while (next) {
                int index = __builtin_ctzll(next);
                active.push_back(goals[index]);
                seen |= Mask(1) << index;
                next &= next - 1;
            }
        }
    }
    bool visit(const Values& active, Mask seen, Mask supported, Values& helpers, Set& forbidden,
               unsigned remaining) {
        if (seen == all) {
            witness = active;
            return true;
        }
        if (!remaining) return false;
        if (nodes == max_nodes) {
            interrupted = true;
            return false;
        }
        ++nodes;
        Values options;
        for (std::size_t i = 0; i < active.size(); ++i)
            for (std::size_t j = 0; j <= i; ++j)
                operations(active[i], active[j], [&](Num v) { options.push_back(v); });
        std::sort(options.begin(), options.end());
        options.erase(std::unique(options.begin(), options.end()), options.end());
        const Set known(active.begin(), active.end());
        Values excluded_here;
        Shortlists cache;
        unsigned index = 0;
        for (Num v : options) {
            if (known.count(v) || forbidden.count(v)) continue;
            if (elsewhere(helpers.size(), index)) {
                forbidden.insert(v);
                excluded_here.push_back(v);
                continue;
            }
            Mask sup = supported | (remaining == 1 ? support(v, helpers) : current(v));
            if (remaining == 2 && !last_possible(v, all & ~sup, forbidden, cache)) continue;
            if (remaining == 1) {
                ++last_candidates;
                // Allow even not-yet-produced goals as operands for this test.
                if (sup != all) continue;
            }
            Values next = active;
            next.push_back(v);
            Mask covered = seen;
            close(next, covered, active.size());
            std::vector<Edit> edits;
            if (remaining > 2) extend_index(v, edits);
            helpers.push_back(v);
            bool found = visit(next, covered, sup, helpers, forbidden, remaining - 1);
            helpers.pop_back();
            undo_index(edits);
            if (found || interrupted) return found;
            // Any successful extension using v is covered by the v-first
            // branch. Later siblings need only consider extensions omitting v.
            forbidden.insert(v);
            excluded_here.push_back(v);
        }
        for (Num v : excluded_here) forbidden.erase(v);
        return false;
    }
    // Independent finite-domain audit of the two-output shortcut. For each
    // possible first operand, visit every inverse image of each target. A
    // missed pair producing two targets would invalidate negative results.
    bool audit_pairs() const {
        for (Num a = 1; a <= limit; ++a)
            for (Num t : goals) {
                bool okay = true;
                inverse(t, a, [&](Num b) {
                    if (b >= a || __builtin_popcountll(hits(a, b)) < 2) return;
                    auto it = exceptional.find(a);
                    if (it == exceptional.end() ||
                        !std::binary_search(it->second.begin(), it->second.end(), b))
                        okay = false;
                });
                if (!okay) return false;
            }
        return true;
    }
    bool run(unsigned budget) {
        Values active;
        Mask seen = 0;
        for (Num v : seeds)
            if (std::find(active.begin(), active.end(), v) == active.end()) {
                active.push_back(v);
                auto it = goal_bit.find(v);
                if (it != goal_bit.end()) seen |= it->second;
            }
        close(active, seen, 0);
        Values helpers;
        Set banned;
        return visit(active, seen, initial_supported, helpers, banned, budget);
    }
};
// Exact same search with an incremental bitmap for one-step outputs.
// At these limits the bitmap is 1 KiB and arithmetic fits in 32 bits.
struct DenseSearch : Search {
    static constexpr Num dense_limit = 8191;
    using Bitmap = std::array<uint64_t, 128>;
    struct DenseSet {
        std::array<uint8_t, dense_limit + 1> bits{};
        bool count(Num v) const { return bits[v] != 0; }
        void insert(Num v) { bits[v] = 1; }
        void erase(Num v) { bits[v] = 0; }
    };
    template <class F>
    void dense_ops(unsigned a, unsigned b, F emit) const {
        if (a + b <= unsigned(limit)) emit(a + b);
        if (a * b <= unsigned(limit)) emit(a * b);
        if (a < b) std::swap(a, b);
        if (a > b) emit(a - b);
        if (a % b == 0) emit(a / b);
    }
    // Before entry bits contains the reachable non-active values of the
    // parent. Only the newly appended active values introduce new pairs.
    void close_dense(Values& active, Mask& seen, std::size_t start, Bitmap& bits) const {
        for (std::size_t i = start; i < active.size(); ++i) {
            Mask next = 0;
            for (std::size_t j = 0; j <= i; ++j) {
                const auto a = active[i], b = active[j];
                dense_ops(a, b, [&](Num v) {
                    bits[v >> 6] |= uint64_t(1) << (v & 63);
                    if (v != a && v != b)
                        next |= dense_goals[v];
                });
            }
            next &= ~seen;
            while (next) {
                int index = __builtin_ctzll(next);
                active.push_back(goals[index]);
                seen |= Mask(1) << index;
                next &= next - 1;
            }
        }
        for (Num v : active)
            bits[v >> 6] &= ~(uint64_t(1) << (v & 63));
    }
    bool visit_dense(const Values& active, Mask seen, Mask supported, Values& helpers,
                     DenseSet& forbidden, unsigned remaining, const Bitmap& bits) {
        if (seen == all) {
            witness = active;
            return true;
        }
        if (!remaining) return false;
        if (nodes == max_nodes) {
            interrupted = true;
            return false;
        }
        ++nodes;
        Values excluded_here;
        Shortlists cache;
        unsigned index = 0;
        for (Num block = 0; block <= (limit >> 6); ++block) {
            for (uint64_t word = bits[block]; word; word &= word - 1) {
                Num v = (block << 6) + __builtin_ctzll(word);
                if (forbidden.count(v)) continue;
                if (elsewhere(helpers.size(), index)) {
                    forbidden.insert(v);
                    excluded_here.push_back(v);
                    continue;
                }
                Mask sup = supported | (remaining == 1 ? support(v, helpers) : current(v));
                if (remaining == 2 && !last_possible(v, all & ~sup, forbidden, cache)) continue;
                if (remaining == 1) {
                    ++last_candidates;
                    if (sup != all) continue;
                }
                Values next = active;
                next.push_back(v);
                Mask covered = seen;
                Bitmap next_bits = bits;
                close_dense(next, covered, active.size(), next_bits);
                std::vector<Edit> edits;
                if (remaining > 2) extend_index(v, edits);
                helpers.push_back(v);
                bool found = visit_dense(next, covered, sup, helpers, forbidden,
                                         remaining - 1, next_bits);
                helpers.pop_back();
                undo_index(edits);
                if (found || interrupted) return found;
                forbidden.insert(v);
                excluded_here.push_back(v);
            }
        }
        for (Num v : excluded_here) forbidden.erase(v);
        return false;
    }
    bool run_dense(unsigned budget) {
        Values active;
        Mask seen = 0;
        for (Num v : seeds)
            if (std::find(active.begin(), active.end(), v) == active.end()) {
                active.push_back(v);
                auto it = goal_bit.find(v);
                if (it != goal_bit.end()) seen |= it->second;
            }
        Bitmap bits{};
        close_dense(active, seen, 0, bits);
        Values helpers;
        DenseSet forbidden;
        return visit_dense(active, seen, initial_supported, helpers, forbidden, budget, bits);
    }
};

#include "exact_frontier.hpp"

int main(int argc, char** argv) {
    IncrementalSearch s;
    bool force_original = false;
    bool incremental = false;
    if (argc >= 2 && (std::string(argv[1]) == "--early-pair" || std::string(argv[1]) == "--pair-bound")) {
        s.early_pair=true; s.pair_bound=true; s.inverse_terminal=true; incremental=true; --argc; ++argv;
    }
    if (argc >= 2 && std::string(argv[1]) == "--late-pair") {
        s.pair_bound=true; s.inverse_terminal=true; incremental=true; --argc; ++argv;
    }
    if (argc >= 2 && std::string(argv[1]) == "--terminal") {
        s.inverse_terminal = true; incremental = true; --argc; ++argv;
    }
    if (argc >= 2 && std::string(argv[1]) == "--incremental") {
        incremental = true; --argc; ++argv;
    }
    if (argc >= 2 && std::string(argv[1]) == "--original") {
        force_original = true;
        --argc;
        ++argv;
    }
    unsigned ns, nt, budget;
    bool audit = argc == 2 && std::string(argv[1]) == "--audit-pairs";
    if (argc != 1 && argc != 3 && argc != 5 && argc != 7 && !audit) return 2;
    if (argc >= 3) {
        s.shard = std::stoul(argv[1]);
        s.shards = std::stoul(argv[2]);
        if (!s.shards || s.shard >= s.shards) return 2;
        if (argc >= 5) {
            s.shard_two = std::stoul(argv[3]);
            s.shards_two = std::stoul(argv[4]);
            if (!s.shards_two || s.shard_two >= s.shards_two) return 2;
        }
        if (argc == 7) {
            s.shard_three = std::stoul(argv[5]);
            s.shards_three = std::stoul(argv[6]);
            if (!s.shards_three || s.shard_three >= s.shards_three) return 2;
        }
    }
    if (!(std::cin >> s.limit >> ns >> nt >> budget >> s.max_nodes) || s.limit < 1 ||
        s.limit > 1000000000000000000LL || ns == 0 || nt > 64 || budget > 4096)
        return 2;
    for (unsigned i = 0; i < ns + nt; ++i) {
        Num v;
        if (!(std::cin >> v) || v < 1 || v > s.limit) return 2;
        (i < ns ? s.seeds : s.goals).push_back(v);
    }
    std::sort(s.goals.begin(), s.goals.end());
    s.goals.erase(std::unique(s.goals.begin(), s.goals.end()), s.goals.end());
    // The second partition uses the ordinary completed-branch exclusion
    // invariant, so do not split the last-two shortcut branches.
    if ((argc >= 5 && budget < 4) || (argc == 7 && budget < 5)) return 2;
    s.prepare();
    if (audit) {
        if (!s.audit_pairs()) return 3;
        std::cout << "OK\n";
        return 0;
    }
    bool found = incremental ? s.run_frontier(budget) : !force_original && s.limit <= DenseSearch::dense_limit
        ? s.run_dense(budget) : s.run(budget);
    std::cout << (found           ? "FOUND"
                  : s.interrupted ? "UNKNOWN"
                                  : "UNSAT")
              << " " << s.nodes << " " << s.last_candidates << "\n";
    if (found) {
        for (Num v : s.witness) std::cout << v << " ";
        std::cout << "\n";
    }
    return 0;
}
