// Signed quotient/remainder search over expressions available in the current puzzle.
// Solver core by Tony Li (https://www.kaggle.com/code/tonylica/elf-calculator-with-register-reuse).
// Changes in this notebook: the four tunables below are read from the command line.
// Local changes: optionally grow the index, price shared expressions once, and select target-aware leaves.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <map>
#include <set>
#include <unordered_map>
#include <vector>
using namespace std;
using Int = int64_t;

static double ALPHA = 0.18;  // beam rank = instructions spent + ALPHA * log2(remaining integer)
static int N_DONE = 52;      // leaf budget after adding previous targets (largest first)
static int N_RECENT = 56;    // leaf budget after adding the most recent intermediate values
static int INDEX_BITS = 20;  // log2(slots) of the open-addressing index
static bool COUNT_REUSE = false;
static bool TARGET_LEAVES = false;

struct Expr {
    Int v;
    int a = -1, b = -1;
    char op = 0;
    int cost = 0;
};
Int apply(char op, Int a, Int b) {
    if (op == '+')
        return a + b;
    if (op == '-')
        return a - b;
    if (op == '/')
        return a / b;
    return a * b; // All callers check the puzzle limit before multiplying.
}

// Integer-key index reused between targets. Zero is outside the calculator domain.
struct Index {
    vector<Int> keys;
    vector<int> ids, used;
    size_t mask;
    bool adaptive;
    Index(int bits) : keys(1u << abs(bits)), ids(keys.size()), mask(keys.size() - 1),
                      adaptive(bits < 0) {}
    size_t slot(Int v) const {
        uint64_t h = uint64_t(v) * 0x9e3779b97f4a7c15ULL;
        h ^= h >> 31;
        size_t i = h & mask;
        while (keys[i] && keys[i] != v)
            i = (i + 1) & mask;
        return i;
    }
    int get(Int v) const {
        size_t i = slot(v);
        return keys[i] ? ids[i] : -1;
    }
    bool insert(Int v, int id) {
        size_t i = slot(v);
        if (keys[i])
            return false;
        if (adaptive && used.size() * 5 >= keys.size() * 3) {
            grow();
            i = slot(v);
        }
        if (!adaptive && used.size() * 8 > keys.size() * 7)
            return false;
        used.push_back(i);
        keys[i] = v;
        ids[i] = id;
        return true;
    }
    void grow() {
        auto previous_keys = move(keys);
        auto previous_ids = move(ids);
        auto previous_used = move(used);
        keys = vector<Int>(previous_keys.size() * 2);
        ids = vector<int>(keys.size());
        used.clear();
        used.reserve(previous_used.size() * 2);
        mask = keys.size() - 1;
        for (int position : previous_used) {
            auto new_position = slot(previous_keys[position]);
            keys[new_position] = previous_keys[position];
            ids[new_position] = previous_ids[position];
            used.push_back(new_position);
        }
    }
    void clear() {
        for (int i : used)
            keys[i] = 0;
        used.clear();
    }
};

struct Dictionary {
    Int limit;
    Index index{INDEX_BITS};
    vector<Expr> e;
    array<vector<pair<Int, int>>, 3> sorted;
    int n0 = 0, n1 = 0;
    explicit Dictionary(Int limit) : limit(limit) {}
    void add(Int v, int a, int b, char op, int cost) {
        if (v > 0 && v <= limit && index.insert(v, e.size()))
            e.push_back({v, a, b, op, cost});
    }
    void combine(int i, int j, int cost) {
        Int a = e[i].v, b = e[j].v;
        add(a + b, i, j, '+', cost);
        if (a != b)
            add(abs(a - b), a > b ? i : j, a > b ? j : i, '-', cost);
        if (a <= limit / b)
            add(a * b, i, j, '*', cost);
        if (a > b && a % b == 0)
            add(a / b, i, j, '/', cost);
        if (b > a && b % a == 0)
            add(b / a, j, i, '/', cost);
    }
    void build(const vector<Int> &leaves) {
        index.clear();
        e.clear();
        for (auto &s : sorted)
            s.clear();
        for (Int v : leaves)
            add(v, -1, -1, 0, 0);
        n0 = e.size();
        for (int i = 0; i < n0; i++)
            for (int j = 0; j <= i; j++)
                combine(i, j, 1);
        n1 = e.size();
        for (int i = n0; i < n1; i++)
            for (int j = 0; j < n0; j++)
                combine(i, j, 2);
        for (int i = 0; i < int(e.size()); i++)
            sorted[e[i].cost].emplace_back(e[i].v, i);
        for (auto &s : sorted)
            sort(s.begin(), s.end());
    }
};

// A reduction encodes parent = (child * factor) +/- atom, or atom - child.
struct Link {
    int factor = -1, atom = -1;
    char op = '+';
};
struct State {
    Int v;
    int cost = 0, parent = -1;
    Link link;
    double rank = 0;
    uint64_t context = 0;
};

struct Search {
    Dictionary &d;
    int width, best = 1000, end = -1, terminal = -1;
    vector<State> history, next;
    unordered_map<Int, int> visited;
    Search(Dictionary &d, int width) : d(d), width(width) {}
    int expr_cost(int id) const { return id < 0 ? 0 : 1 + d.e[id].cost; }
    static uint64_t fingerprint(int id) {
        return 1ULL << ((uint64_t(id) * 0x9e3779b97f4a7c15ULL) >> 58);
    }
    bool contains_component(int root, int id) const {
        if (root < d.n0)
            return false;
        if (root == id)
            return true;
        if (d.e[root].cost == 2)
            return d.e[root].a == id || d.e[root].b == id;
        return false;
    }
    bool previously_used(int p, int id) const {
        if (!(history[p].context & fingerprint(id)))
            return false;
        for (; p >= 0; p = history[p].parent) {
            auto link = history[p].link;
            if (contains_component(link.factor, id) || contains_component(link.atom, id))
                return true;
        }
        return false;
    }
    void require_components(int p, int root, array<int, 6> &needed, int &count) const {
        if (root < d.n0 || previously_used(p, root))
            return;
        for (int index = 0; index < count; ++index)
            if (needed[index] == root)
                return;
        needed[count++] = root;
        if (d.e[root].cost == 2) {
            require_components(p, d.e[root].a, needed, count);
            require_components(p, d.e[root].b, needed, count);
        }
    }
    int path_cost(int p, int f, int a, int terminal, uint64_t &context) const {
        array<int, 6> needed{};
        int count = 0;
        require_components(p, f, needed, count);
        require_components(p, a, needed, count);
        require_components(p, terminal, needed, count);
        for (int index = 0; index < count; ++index)
            context |= fingerprint(needed[index]);
        return history[p].cost + int(f >= 0) + int(a >= 0) + count;
    }
    void offer(int p, Int v, int f, int a, char op) {
        if (v <= 0 || v > d.limit)
            return;
        int cost = history[p].cost + expr_cost(f) + expr_cost(a);
        uint64_t context = history[p].context;
        if (COUNT_REUSE) {
            if (cost - 4 >= best)
                return;
            cost = path_cost(p, f, a, -1, context);
        }
        if (cost >= best)
            return;
        int t = d.index.get(v);
        if (t >= 0) {
            int estimate = COUNT_REUSE ? path_cost(p, f, a, t, context) : cost + d.e[t].cost;
            if (estimate < best) {
                best = estimate;
                end = history.size();
                terminal = t;
                history.push_back({v, cost, p, {f, a, op}, 0, context});
            }
            return;
        }
        if (cost + 3 >= best || v >= history[p].v)
            return;
        // Comparisons happen across instruction costs and residual sizes.
        double rank = cost + ALPHA * log2(double(v));
        if (int(next.size()) == width && rank >= next.back().rank)
            return;
        auto prev = visited.find(v);
        if (prev != visited.end() && prev->second <= cost)
            return;
        for (auto it = next.begin(); it != next.end(); ++it)
            if (it->v == v) {
                if (it->cost <= cost)
                    return;
                next.erase(it);
                break;
            }
        State s{v, cost, p, {f, a, op}, rank, context};
        auto it = upper_bound(next.begin(), next.end(), rank,
                              [](double k, const State &x) { return k < x.rank; });
        next.insert(it, s);
        if (int(next.size()) > width)
            next.pop_back();
    }
    void expand(int p) {
        Int v = history[p].v;
        for (auto &arr : d.sorted) {
            auto it = lower_bound(arr.begin(), arr.end(), make_pair(v, -1));
            for (int k = -4; k < 4; k++) {
                auto pos = (it - arr.begin()) + k;
                if (pos < 0 || pos >= int(arr.size()))
                    continue;
                auto [a, id] = arr[pos];
                offer(p, abs(v - a), -1, id, v > a ? '+' : 'r');
            }
        }
        for (int i = 0; i < d.n1; i++) {
            Int a = d.e[i].v;
            if (a == 1)
                continue;
            Int diff = abs(v - a);
            if (diff) {
                if (d.index.get(diff) >= 0)
                    offer(p, diff, -1, i, v > a ? '+' : 'r');
                if (v > a && (diff & 15) == 0)
                    shifted(p, diff, i, '+');
                if (a > v && (diff & 15) == 0)
                    shifted(p, diff, i, 'r');
            }
            if (a + v <= d.limit) {
                if (d.index.get(a + v) >= 0)
                    offer(p, a + v, -1, i, '-');
                if (((a + v) & 15) == 0)
                    shifted(p, a + v, i, '-');
            }
            if (a >= v)
                continue;
            Int q = v / a, r = v % a;
            if (!r) {
                offer(p, q, i, -1, '+');
                continue;
            }
            int rid = d.index.get(r);
            if (rid >= 0)
                offer(p, q, i, rid, '+');
            if (a - r <= d.limit - v) {
                rid = d.index.get(a - r);
                if (rid >= 0)
                    offer(p, q + 1, i, rid, '-');
            }
            // Approximate the quotient by a cached expression, then synthesize the error.
            if (i < d.n0 && q > 64) {
                for (auto &arr : d.sorted) {
                    auto it = lower_bound(arr.begin(), arr.end(), make_pair(q, -1));
                    for (int k = -1; k <= 0; k++) {
                        auto pos = (it - arr.begin()) + k;
                        if (pos < 0 || pos >= int(arr.size()))
                            continue;
                        auto [b, bi] = arr[pos];
                        if (b > d.limit / a)
                            continue;
                        Int mul = a * b;
                        if (mul == v)
                            continue;
                        int id = d.index.get(mul);
                        if (id >= 0)
                            offer(p, abs(mul - v), -1, id, mul < v ? '+' : 'r');
                    }
                }
            }
        }
    }
    void shifted(int p, Int diff, int atom, char op) {
        int k = __builtin_ctzll(diff);
        while (k >= 4) {
            int f = d.index.get(Int(1) << k);
            if (f >= 0) {
                offer(p, diff >> k, f, atom, op);
                break;
            }
            k--;
        }
    }
    void run(Int target) {
        history.push_back({target, 0, -1, {}});
        int id = d.index.get(target);
        if (id >= 0) {
            end = 0;
            terminal = id;
            best = d.e[id].cost;
            return;
        }
        vector<int> front{0};
        for (int depth = 0; depth < 20 && !front.empty(); depth++) {
            next.clear();
            for (int p : front)
                if (history[p].cost + 3 < best)
                    expand(p);
            front.clear();
            for (State s : next) {
                if (s.cost + 3 >= best)
                    continue;
                visited[s.v] = s.cost;
                front.push_back(history.size());
                history.push_back(s);
            }
        }
    }
};

struct Puzzle {
    Int limit;
    vector<Int> starts, targets, palette;
    map<Int, Expr> defs;
    vector<Int> order;
    int width;
    Puzzle(Int limit, int width) : limit(limit), width(width) {}
    Int make(char op, Int a, Int b) {
        Int v = apply(op, a, b);
        if (v <= 0 || v > limit)
            throw runtime_error("invalid construction");
        if (!defs.count(v)) {
            defs[v] = {v, -1, -1, op};
            args[v] = {a, b};
            order.push_back(v);
            if (TARGET_LEAVES) {
                uses[a]++;
                if (a != b)
                    uses[b]++;
            }
        }
        return v;
    }
    map<Int, pair<Int, Int>> args;
    map<Int, int> uses;
    Int power(int k) {
        Int v = Int(1) << k;
        if (defs.count(v))
            return v;
        if (k == 1)
            return make('+', 1, 1);
        Int right = power(k - k / 2);
        Int left = power(k / 2);
        return make('*', left, right);
    }
    void setup() {
        for (Int v : starts)
            defs[v] = {v};
        if (!defs.count(1))
            make('/', starts[0], starts[0]);
        palette = {1};
        for (int k : {1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 16, 20, 24, 32, 40, 48}) {
            if ((Int(1) << k) <= limit)
                palette.push_back(power(k));
        }
        for (int i : {3, 5, 7, 9, 11, 13, 15, 17, 19, 23, 31})
            if (i <= limit) {
                if (!defs.count(i)) {
                    if (i == 11 || i == 13 || i == 19 || i == 23)
                        make('+', i - (i == 23 ? 16 : 8), i == 23 ? 16 : 8);
                    else if ((i & (i + 1)) == 0 && i + 1 <= limit)
                        make('-', i + 1, 1);
                    else
                        binary(i);
                }
                palette.push_back(i);
            }
    }
    Int materialize(Dictionary &d, int id) {
        const Expr &e = d.e[id];
        if (defs.count(e.v))
            return e.v;
        Int right = materialize(d, e.b);
        Int left = materialize(d, e.a);
        return make(e.op, left, right);
    }
    Int binary(Int v) {
        if (defs.count(v))
            return v;
        Int h = binary(v / 2);
        Int twice = make('+', h, h);
        return v % 2 ? make('+', twice, 1) : twice;
    }
    vector<Int> select_leaves(Int target, const set<Int> &taken, int count) const {
        vector<pair<double, Int>> relevance;
        vector<pair<int, Int>> frequency;
        for (Int value : order) {
            if (taken.count(value))
                continue;
            auto use = uses.find(value);
            int fanout = use == uses.end() ? 0 : use->second;
            if (fanout)
                frequency.emplace_back(-fanout, value);
            Int factor = target / value;
            if (factor > 64)
                continue;
            Int residual = factor ? target % value : value - target;
            if (factor && value - residual <= limit - target)
                residual = min(residual, value - residual);
            double cost = log2(double(max<Int>(1, residual))) + 0.35 * log2(double(max<Int>(1, factor)));
            relevance.emplace_back(cost, value);
        }
        sort(relevance.begin(), relevance.end());
        sort(frequency.begin(), frequency.end());
        vector<Int> result;
        set<Int> added;
        for (auto [cost, value] : relevance) {
            if (int(result.size()) >= count / 3)
                break;
            result.push_back(value);
            added.insert(value);
        }
        for (auto [uses, value] : frequency) {
            if (int(result.size()) >= count * 2 / 3)
                break;
            if (added.insert(value).second)
                result.push_back(value);
        }
        return result;
    }
    void solve() {
        setup();
        Dictionary d(limit);
        set<Int> done;
        for (Int target : targets) {
            if (!defs.count(target)) {
                vector<Int> leaves;
                set<Int> used;
                auto add = [&](Int v) {
                    if (used.insert(v).second)
                        leaves.push_back(v);
                };
                for (Int v : palette)
                    add(v);
                for (Int v : starts)
                    add(v);
                for (auto it = done.rbegin(); it != done.rend() && int(leaves.size()) < N_DONE; ++it)
                    add(*it);
                if (TARGET_LEAVES)
                    for (Int value : select_leaves(target, used, max(0, N_RECENT - int(leaves.size()))))
                        add(value);
                for (auto it = order.rbegin(); it != order.rend() && int(leaves.size()) < N_RECENT; ++it)
                    add(*it);
                d.build(leaves);
                Search s(d, width);
                s.run(target);
                if (s.end < 0)
                    binary(target);
                else {
                    Int v = materialize(d, s.terminal);
                    for (int p = s.end; s.history[p].parent >= 0; p = s.history[p].parent) {
                        Link l = s.history[p].link;
                        if (l.factor >= 0)
                            v = make('*', v, materialize(d, l.factor));
                        if (l.atom >= 0) {
                            Int a = materialize(d, l.atom);
                            v = l.op == 'r' ? make('-', a, v) : make(l.op, v, a);
                        }
                    }
                    if (v != target)
                        throw runtime_error("search reconstruction failed");
                }
            }
            done.insert(target);
        }
    }
    // Walk dependencies on demand, then allocate registers by their next use.
    // An evicted value can always be rebuilt from its expression or a protected seed.
    vector<array<int, 4>> compile() {
        set<Int> placed(starts.begin(), starts.end());
        vector<Int> sequence;
        auto visit = [&](auto &&self, Int v) -> void {
            if (!placed.insert(v).second)
                return;
            auto [a, b] = args.at(v);
            self(self, a);
            self(self, b);
            sequence.push_back(v);
        };
        for (Int t : targets)
            visit(visit, t);
        map<Int, vector<int>> uses;
        for (int i = int(sequence.size()) - 1; i >= 0; --i) {
            auto [a, b] = args.at(sequence[i]);
            uses[a].push_back(i);
            if (a != b)
                uses[b].push_back(i);
        }
        array<Int, 48> bank{};
        set<Int> seeds(starts.begin(), starts.end());
        copy(starts.begin(), starts.end(), bank.begin());
        vector<array<int, 4>> program;
        auto emit = [&](auto &&self, Int v, uint64_t locked) -> int {
            auto found = find(bank.begin(), bank.end(), v);
            if (found != bank.end())
                return found - bank.begin();
            auto [a, b] = args.at(v);
            int ra = self(self, a, locked), rb = self(self, b, locked | (1ULL << ra));
            int rd = -1, latest = -1;
            for (int k = 0; k < 48; k++) {
                Int old = bank[k];
                if ((locked >> k & 1) || seeds.count(old))
                    continue;
                int nextuse = uses[old].empty() ? 1000000 : uses[old].back();
                if (!old) {
                    rd = k;
                    break;
                }
                if (nextuse > latest) {
                    rd = k;
                    latest = nextuse;
                }
            }
            if (rd < 0)
                throw runtime_error("register allocation failed");
            bank[rd] = v;
            program.push_back({defs.at(v).op, ra, rb, rd});
            return rd;
        };
        for (Int v : sequence) {
            auto [a, b] = args.at(v);
            uses[a].pop_back();
            if (a != b)
                uses[b].pop_back();
            emit(emit, v, 0);
        }
        return program;
    }
};

int main(int argc, char **argv) {
    int width = argc > 1 ? stoi(argv[1]) : 3;
    if (argc > 2) ALPHA = stod(argv[2]);
    if (argc > 3) N_DONE = stoi(argv[3]);
    if (argc > 4) N_RECENT = stoi(argv[4]);
    if (argc > 5) INDEX_BITS = stoi(argv[5]);
    if (argc > 6) COUNT_REUSE = stoi(argv[6]) != 0;
    if (argc > 7) TARGET_LEAVES = stoi(argv[7]) != 0;
    if (INDEX_BITS < -28 || INDEX_BITS > 28 || INDEX_BITS == 0)
        return 2;
    string id;
    Int limit;
    int ns, nt;
    while (cin >> id >> limit >> ns >> nt) {
        Puzzle p(limit, width);
        p.starts.resize(ns);
        p.targets.resize(nt);
        for (auto &x : p.starts)
            cin >> x;
        for (auto &x : p.targets)
            cin >> x;
        p.solve();
        auto prog = p.compile();
        cout << id << " [";
        for (size_t k = 0; k < prog.size(); k++) {
            auto [op, a, b, c] = prog[k];
            if (k)
                cout << ',';
            cout << "[\"" << char(op) << "\"," << a << ',' << b << ',' << c << ']';
        }
        cout << "]\n" << flush;
    }
}
