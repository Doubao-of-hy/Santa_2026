#include "quotient_search.hpp"

// Maintain a compact arithmetic basis and solve the cheapest pending target
// first. Dependencies not used by any target are removed when serializing.
struct Builder {
    Circuit g;
    int width, beam;
    bool target_first = false;
    std::vector<Num> history;
    std::unordered_map<Num, int> freq;
    Values known;
    void put(Num v, Arithmetic e) {
        if (known.insert(v).second) {
            g.expr[v] = e;
            history.push_back(v);
            freq[e.a]++;
            freq[e.b]++;
        }
    }
    bool direct(Num target) {
        if (known.count(target)) return false;
        // Take an available seed pair before paying to construct small constants.
        Arithmetic recipe{};
        for (Num a : known)
            if (inverse(target, a, g.limit, [&](Num b, Arithmetic e) {
                    if (!known.count(b)) return false;
                    recipe = e;
                    return true;
                })) {
                put(target, recipe);
                return true;
            }
        return false;
    }
    void fallback(Num v) {
        if (known.count(v) || (target_first && direct(v))) return;
        if (v == 1) {
            Num a = *std::min_element(g.seeds.begin(), g.seeds.end());
            put(1, {a, a, '/'});
            return;
        }
        if (v <= 64) {
            fallback(v / 2);
            put((v / 2) * 2, {v / 2, v / 2, '+'});
            if (v % 2) {
                fallback(1);
                put(v, {v - 1, 1, '+'});
            }
            return;
        }
        Num q = v / 64, r = v % 64;
        if (r > 32 && q + 1 <= g.limit / 64) {
            q++;
            r -= 64;
        }
        fallback(q);
        fallback(64);
        put(q * 64, {q, 64, '*'});
        if (r) {
            fallback(std::abs(r));
            put(v, {q * 64, std::abs(r), r > 0 ? '+' : '-'});
        }
    }
    std::vector<Num> priority() {
        std::vector<Num> p(g.seeds.begin(), g.seeds.end());
        std::sort(p.begin(), p.end());
        auto h = history;
        std::reverse(h.begin(), h.end());
        std::stable_sort(h.begin(), h.end(), [&](Num a, Num b) { return freq[a] > freq[b]; });
        std::vector<Num> r = p;
        Values added = g.seeds;
        auto add = [&](Num x) {
            if (added.insert(x).second) r.push_back(x);
        };
        for (int i = 0; i < (int)h.size() && i < width / 2; ++i) add(h[i]);
        for (auto i = history.rbegin(); i != history.rend(); ++i)
            if ((int)r.size() < width) add(*i);
        for (Num x : h) add(x);
        return r;
    }
    void run() {
        known = g.seeds;
        if (target_first) {
            bool changed;
            do {
                changed = false;
                for (Num t : g.targets)
                    if (direct(t)) changed = true;
            } while (changed);
        }
        for (Num c : {1, 2, 3, 4, 5, 7, 8, 9, 16, 32, 64, 128, 256, 4096, 65536})
            if (c <= g.limit) fallback(c);
        while (true) {
            std::vector<Num> pending;
            for (Num t : g.targets)
                if (!known.count(t)) pending.push_back(t);
            if (pending.empty()) return;
            QuotientTable table(g.limit, width, beam, known, priority());
            Patch best;
            int length = 64;
            std::vector<std::pair<double, Num>> focus;
            for (Num t : pending) {
                Patch candidate;
                if (table.shallow(t, length, candidate, true)) {
                    best = std::move(candidate);
                    length = best.size();
                }
                focus.push_back({table.rank(t), t});
            }
            std::sort(focus.begin(), focus.end());
            if (length > 3) {
                for (int j = 0; j < std::min<int>(2, focus.size()); ++j) {
                    auto shot = table.search(focus[j].second, std::min(length - 1, 14));
                    if (!shot.empty() && (int)shot.size() < length) {
                        length = shot.size();
                        best = std::move(shot);
                    }
                }
            }
            if (best.empty()) {
                fallback(focus.front().second);
                continue;
            }
            for (auto [v, e] : best) put(v, e);
        }
    }
};
int main(int argc, char** argv) {
    std::ios::sync_with_stdio(false);
    Builder b;
    b.target_first = argc == 2 && std::string(argv[1]) == "--target-first";
    int n, m;
    if (!(std::cin >> b.g.limit >> n >> m >> b.width >> b.beam)) return 1;
    if (b.width < 2 || b.width > 63 || b.beam < 1) return 2;
    for (int i = 0; i < n; ++i) {
        Num x;
        std::cin >> x;
        b.g.seeds.insert(x);
    }
    for (int i = 0; i < m; ++i) {
        Num x;
        std::cin >> x;
        b.g.targets.push_back(x);
    }
    b.run();
    Values needed(b.g.targets.begin(), b.g.targets.end());
    for (auto it = b.history.rbegin(); it != b.history.rend(); ++it)
        if (needed.count(*it)) {
            auto e = b.g.expr.at(*it);
            needed.insert(e.a);
            needed.insert(e.b);
        }
    for (auto x : b.history)
        if (needed.count(x)) {
            auto e = b.g.expr.at(x);
            std::cout << x << ' ' << e.a << ' ' << e.op << ' ' << e.b << '\n';
        }
}
