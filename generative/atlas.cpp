// Deterministic Real-Machine Synthesizer & Post-Optimizer for Santa 2026 (Elf Calculator)
// Compiles cleanly with: g++ -O3 -std=c++20 -pthread solver.cpp -o solver
//
// Modes (100% bit-for-bit deterministic regardless of thread count):
//   1. Standalone synthesis:
//        ./solver <puzzles.csv> <output_submission.csv> [num_threads]
//      Combines exact tiny BFS, backward quotient-remainder Beam DAG solver with
//      cost-aware 48-register allocation, real-machine MitM fallback, helper elision,
//      window/cut passes, and fast scaffold exchange.
//   2. Multi-bank deterministic post-optimizer:
//        ./solver --optimize <puzzles.csv> <output_submission.csv> <num_threads> <bank1.csv> [bank2.csv ...]
//      Replays & verifies all candidate programs per puzzle, selects diverse donor
//      traces, and runs five deterministic passes: (1) spill-free & cost-aware
//      lowering with live-frontier ordering, (2) acyclic 1/2-op peephole, shared-helper
//      introduction, and Pollard-Rho cofactor cuts, (3) helper elision and 1/2-goal
//      1..3-step sliding-window/cut sweeps, (4) bounded single-target reverse rebuilds,
//      (5) complete fan-out scaffold exchange with flat-table demand intersection,
//      exact subset bitmask DP, and bounded multi-output block search, plus
//      (6) square-peeling chain resynthesis, dependency reversal, and cross-trace
//      hypergraph recombination.

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <numeric>
#include <queue>
#include <set>
#include <string>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace {

using i64 = int64_t;
using u64 = uint64_t;
using i128 = __int128_t;

constexpr int kNumRegs = 48;
constexpr int kMaxProgramLen = 4096;
constexpr size_t kMaxCellBytes = 131072;

enum Op : uint8_t { OP_ADD = 0, OP_SUB = 1, OP_MUL = 2, OP_DIV = 3 };

inline char op_char(Op op) {
    switch (op) {
        case OP_ADD: return '+';
        case OP_SUB: return '-';
        case OP_MUL: return '*';
        case OP_DIV: return '/';
    }
    return '+';
}

inline Op char_to_op(char c) {
    if (c == '+') return OP_ADD;
    if (c == '-') return OP_SUB;
    if (c == '*') return OP_MUL;
    return OP_DIV;
}

struct Instr {
    Op op;
    uint8_t i;
    uint8_t j;
    uint8_t d;
};

struct Puzzle {
    std::string id;
    std::vector<i64> starts;
    std::vector<i64> targets;
    i64 limit = 0;
    int registers = kNumRegs;
    std::string family;
    u64 numeric_id = 0;
};

// Deterministic SplitMix64 PRNG (never relies on std::random_device or wall clock)
struct SplitMix64 {
    u64 state;
    explicit SplitMix64(u64 seed) : state(seed) {}
    inline u64 next_u64() {
        u64 z = (state += 0x9e3779b97f4a7c15ULL);
        z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ULL;
        z = (z ^ (z >> 27)) * 0x94d049bb133111ebULL;
        return z ^ (z >> 31);
    }
    inline double next_unit() {
        return static_cast<double>(next_u64() >> 11) * (1.0 / 9007199254740992.0);
    }
};

// --- CSV / JSON lightweight deterministic parser ---

std::vector<std::string> parse_csv_row(const std::string& line) {
    std::vector<std::string> fields;
    std::string cur;
    bool in_quotes = false;
    for (size_t idx = 0; idx < line.size(); ++idx) {
        char c = line[idx];
        if (c == '\r') continue;
        if (in_quotes) {
            if (c == '"') {
                if (idx + 1 < line.size() && line[idx + 1] == '"') {
                    cur.push_back('"');
                    ++idx;
                } else {
                    in_quotes = false;
                }
            } else {
                cur.push_back(c);
            }
        } else {
            if (c == '"') {
                in_quotes = true;
            } else if (c == ',') {
                fields.push_back(std::move(cur));
                cur.clear();
            } else {
                cur.push_back(c);
            }
        }
    }
    fields.push_back(std::move(cur));
    return fields;
}

std::vector<i64> parse_int_list(const std::string& s) {
    std::vector<i64> out;
    i64 val = 0;
    bool in_num = false;
    for (char c : s) {
        if (c >= '0' && c <= '9') {
            val = val * 10 + (c - '0');
            in_num = true;
        } else if (in_num) {
            out.push_back(val);
            val = 0;
            in_num = false;
        }
    }
    if (in_num) out.push_back(val);
    return out;
}

u64 parse_numeric_suffix(const std::string& id) {
    u64 v = 0;
    for (char c : id) {
        if (c >= '0' && c <= '9') v = v * 10 + static_cast<u64>(c - '0');
    }
    if (v == 0) {
        for (unsigned char c : id) v = v * 131 + c;
    }
    return v;
}

std::vector<Puzzle> load_puzzles_csv(const std::string& path) {
    std::ifstream in(path);
    if (!in) throw std::runtime_error("Cannot open puzzles CSV: " + path);
    std::string header_line;
    std::getline(in, header_line);
    if (header_line.size() >= 3 &&
        static_cast<unsigned char>(header_line[0]) == 0xEF &&
        static_cast<unsigned char>(header_line[1]) == 0xBB &&
        static_cast<unsigned char>(header_line[2]) == 0xBF) {
        header_line.erase(0, 3);
    }
    auto headers = parse_csv_row(header_line);
    std::unordered_map<std::string, int> col;
    for (int i = 0; i < static_cast<int>(headers.size()); ++i) col[headers[i]] = i;

    std::vector<Puzzle> puzzles;
    std::string line;
    while (std::getline(in, line)) {
        if (line.empty()) continue;
        auto f = parse_csv_row(line);
        if (f.size() < 5) continue;
        Puzzle p;
        p.id = f[col.at("id")];
        p.starts = parse_int_list(f[col.at("starting_values")]);
        p.targets = parse_int_list(f[col.at("targets")]);
        p.limit = std::stoll(f[col.at("value_limit")]);
        p.registers = std::stoi(f[col.at("registers")]);
        if (col.count("family")) p.family = f[col.at("family")];
        p.numeric_id = parse_numeric_suffix(p.id);
        puzzles.push_back(std::move(p));
    }
    return puzzles;
}

bool parse_program_json(const std::string& raw, std::vector<Instr>& out) {
    out.clear();
    if (raw.size() > kMaxCellBytes) return false;
    size_t i = 0, n = raw.size();
    while (i < n && (raw[i] == ' ' || raw[i] == '\t' || raw[i] == '\n' || raw[i] == '\r')) ++i;
    if (i >= n || raw[i] != '[') return false;
    ++i;
    while (i < n) {
        while (i < n && (raw[i] == ' ' || raw[i] == '\t' || raw[i] == ',' || raw[i] == '\n' || raw[i] == '\r')) ++i;
        if (i >= n) return false;
        if (raw[i] == ']') return true;
        if (raw[i] != '[') return false;
        ++i;
        while (i < n && raw[i] != '"') ++i;
        ++i;
        if (i >= n) return false;
        char op_c = raw[i++];
        if (op_c != '+' && op_c != '-' && op_c != '*' && op_c != '/') return false;
        while (i < n && raw[i] != '"') ++i;
        ++i;
        int vals[3]{0, 0, 0};
        for (int k = 0; k < 3; ++k) {
            while (i < n && (raw[i] < '0' || raw[i] > '9')) {
                if (raw[i] == '-') return false;
                ++i;
            }
            if (i >= n) return false;
            int v = 0;
            while (i < n && raw[i] >= '0' && raw[i] <= '9') {
                v = v * 10 + (raw[i] - '0');
                ++i;
            }
            if (v >= kNumRegs) return false;
            vals[k] = v;
        }
        while (i < n && raw[i] != ']') ++i;
        if (i >= n) return false;
        ++i;
        out.push_back({char_to_op(op_c), static_cast<uint8_t>(vals[0]),
                       static_cast<uint8_t>(vals[1]), static_cast<uint8_t>(vals[2])});
        if (static_cast<int>(out.size()) > kMaxProgramLen) return false;
    }
    return false;
}

// --- Exact VM verification ---

bool verify_program(const Puzzle& p, const std::vector<Instr>& prog) {
    if (static_cast<int>(prog.size()) > kMaxProgramLen) return false;
    std::array<i64, kNumRegs> regs{};
    std::array<bool, kNumRegs> valid{};
    for (size_t k = 0; k < p.starts.size(); ++k) {
        regs[k] = p.starts[k];
        valid[k] = true;
    }
    std::vector<i64> need;
    for (i64 t : p.targets) {
        if (std::find(p.starts.begin(), p.starts.end(), t) == p.starts.end()) {
            need.push_back(t);
        }
    }
    std::sort(need.begin(), need.end());
    need.erase(std::unique(need.begin(), need.end()), need.end());
    std::vector<bool> covered(need.size(), false);
    auto mark = [&](i64 v) {
        auto it = std::lower_bound(need.begin(), need.end(), v);
        if (it != need.end() && *it == v) {
            covered[static_cast<size_t>(it - need.begin())] = true;
        }
    };

    for (const auto& ins : prog) {
        if (ins.i >= p.registers || ins.j >= p.registers || ins.d >= p.registers) return false;
        if (!valid[ins.i] || !valid[ins.j]) return false;
        i128 a = regs[ins.i];
        i128 b = regs[ins.j];
        i128 v = 0;
        if (ins.op == OP_ADD) v = a + b;
        else if (ins.op == OP_SUB) v = a - b;
        else if (ins.op == OP_MUL) v = a * b;
        else {
            if (b == 0 || a % b != 0) return false;
            v = a / b;
        }
        if (v <= 0 || v > p.limit) return false;
        regs[ins.d] = static_cast<i64>(v);
        valid[ins.d] = true;
        mark(static_cast<i64>(v));
    }
    return std::all_of(covered.begin(), covered.end(), [](bool c) { return c; });
}

inline i64 apply_op(Op op, i64 a, i64 b, i64 L) {
    if (a <= 0 || b <= 0) return 0;
    if (op == OP_ADD) {
        return (a <= L - b) ? (a + b) : 0;
    } else if (op == OP_SUB) {
        return (a > b) ? (a - b) : 0;
    } else if (op == OP_MUL) {
        i128 p = static_cast<i128>(a) * b;
        return (p <= L) ? static_cast<i64>(p) : 0;
    } else {
        return (b > 0 && a % b == 0) ? (a / b) : 0;
    }
}

struct WBackStep {
    i64 u;
    Op op;
    bool rev;  // if true, op(old, tmp), else op(tmp, old)
};

inline int gen_win_inverses(i64 v, i64 x, i64 limit, WBackStep* out) {
    int n = 0;
    if (v > x) out[n++] = {v - x, OP_ADD, false};
    if (v <= limit - x) out[n++] = {v + x, OP_SUB, false};
    if (x > v) out[n++] = {x - v, OP_SUB, true};
    if (x > 0 && v % x == 0) out[n++] = {v / x, OP_MUL, false};
    if (v > 0 && x > v && x % v == 0) out[n++] = {x / v, OP_DIV, true};
    if (static_cast<i128>(v) * x <= limit) out[n++] = {v * x, OP_DIV, false};
    return n;
}

inline bool one_step_regs(const std::array<i64, kNumRegs>& r, int nreg,
                          i64 target, i64 limit, int dest, Instr& out) {
    WBackStep bs[6];
    for (int ri = 0; ri < nreg; ++ri) {
        i64 x = r[ri];
        if (x <= 0) continue;
        int nb = gen_win_inverses(target, x, limit, bs);
        for (int k = 0; k < nb; ++k) {
            i64 u = bs[k].u;
            for (int rj = 0; rj < nreg; ++rj) {
                if (r[rj] == u) {
                    out = {bs[k].op,
                           static_cast<uint8_t>(bs[k].rev ? ri : rj),
                           static_cast<uint8_t>(bs[k].rev ? rj : ri),
                           static_cast<uint8_t>(dest)};
                    return true;
                }
            }
        }
    }
    return false;
}

// --- Stage 1: Exact BFS solver for tiny puzzles ---

bool try_solve_tiny(const Puzzle& p, std::vector<Instr>& out_prog) {
    if (p.limit > 300 || p.targets.size() > 6) return false;

    std::vector<i64> need;
    for (i64 t : p.targets) {
        if (std::find(p.starts.begin(), p.starts.end(), t) == p.starts.end()) need.push_back(t);
    }
    std::sort(need.begin(), need.end());
    need.erase(std::unique(need.begin(), need.end()), need.end());
    if (need.empty()) {
        out_prog.clear();
        return true;
    }

    struct Node {
        std::vector<i64> vals;
        int parent;
        Op op;
        i64 lhs_val, rhs_val, res_val;
        uint32_t mask;
    };

    auto target_mask = [&](const std::vector<i64>& vals) -> uint32_t {
        uint32_t m = 0;
        for (size_t idx = 0; idx < need.size(); ++idx) {
            if (std::binary_search(vals.begin(), vals.end(), need[idx])) m |= (1u << idx);
        }
        return m;
    };

    const uint32_t full_mask = (1u << need.size()) - 1u;
    std::vector<i64> init = p.starts;
    std::sort(init.begin(), init.end());
    init.erase(std::unique(init.begin(), init.end()), init.end());

    std::vector<Node> nodes;
    nodes.push_back({init, -1, OP_ADD, 0, 0, 0, target_mask(init)});
    std::map<std::vector<i64>, int> visited;
    visited[init] = 0;
    std::queue<int> q;
    q.push(0);

    constexpr int kMaxBfsNodes = 15000;
    int goal_node = -1;

    while (!q.empty() && static_cast<int>(nodes.size()) < kMaxBfsNodes) {
        int u = q.front();
        q.pop();
        if (nodes[u].mask == full_mask) { goal_node = u; break; }
        const auto vals = nodes[u].vals;
        if (static_cast<int>(vals.size()) >= p.registers - 1) continue;

        const int m = static_cast<int>(vals.size());
        for (int a = 0; a < m; ++a) {
            for (int b = a; b < m; ++b) {
                i64 va = vals[a], vb = vals[b];
                struct Cand { Op op; i64 l, r, v; };
                std::vector<Cand> cands;
                i128 s = static_cast<i128>(va) + vb;
                if (s <= p.limit) cands.push_back({OP_ADD, va, vb, static_cast<i64>(s)});
                i128 mul = static_cast<i128>(va) * vb;
                if (mul <= p.limit) cands.push_back({OP_MUL, va, vb, static_cast<i64>(mul)});
                if (vb > va) cands.push_back({OP_SUB, vb, va, vb - va});
                if (vb % va == 0) cands.push_back({OP_DIV, vb, va, vb / va});
                if (va == vb) cands.push_back({OP_DIV, va, vb, 1});

                for (const auto& c : cands) {
                    if (c.v <= 0 || c.v > p.limit) continue;
                    if (std::binary_search(vals.begin(), vals.end(), c.v)) continue;
                    std::vector<i64> nxt = vals;
                    nxt.insert(std::lower_bound(nxt.begin(), nxt.end(), c.v), c.v);
                    if (visited.count(nxt)) continue;
                    uint32_t nm = target_mask(nxt);
                    int nid = static_cast<int>(nodes.size());
                    visited[nxt] = nid;
                    nodes.push_back({std::move(nxt), u, c.op, c.l, c.r, c.v, nm});
                    if (nm == full_mask) { goal_node = nid; break; }
                    q.push(nid);
                    if (static_cast<int>(nodes.size()) >= kMaxBfsNodes) break;
                }
                if (goal_node != -1 || static_cast<int>(nodes.size()) >= kMaxBfsNodes) break;
            }
            if (goal_node != -1 || static_cast<int>(nodes.size()) >= kMaxBfsNodes) break;
        }
    }

    if (goal_node == -1) return false;
    std::vector<int> chain;
    for (int cur = goal_node; cur > 0; cur = nodes[cur].parent) chain.push_back(cur);
    std::reverse(chain.begin(), chain.end());

    std::map<i64, uint8_t> val_to_reg;
    for (size_t k = 0; k < p.starts.size(); ++k) {
        if (!val_to_reg.count(p.starts[k])) val_to_reg[p.starts[k]] = static_cast<uint8_t>(k);
    }
    uint8_t next_reg = static_cast<uint8_t>(p.starts.size());
    out_prog.clear();
    for (int nid : chain) {
        const auto& nd = nodes[nid];
        uint8_t ri = val_to_reg.at(nd.lhs_val);
        uint8_t rj = val_to_reg.at(nd.rhs_val);
        uint8_t rd = next_reg++;
        out_prog.push_back({nd.op, ri, rj, rd});
        val_to_reg[nd.res_val] = rd;
    }
    return verify_program(p, out_prog);
}

// --- Deterministic Flat Open-Addressed Hash Maps ---

struct FlatMap {
    static constexpr int kLogCap = 19;  // 524,288 slots (~8 MB)
    static constexpr u64 kCap = 1ULL << kLogCap;
    static constexpr u64 kMask = kCap - 1;

    std::vector<u64> keys;
    std::vector<int> vals;
    std::vector<uint32_t> stamps;
    uint32_t cur_stamp = 1;

    FlatMap() : keys(kCap, 0), vals(kCap, 0), stamps(kCap, 0) {}

    void clear() {
        if (++cur_stamp == 0) {
            std::fill(stamps.begin(), stamps.end(), 0);
            cur_stamp = 1;
        }
    }

    static inline u64 mix(u64 k) {
        k ^= k >> 33;
        k *= 0xff51afd7ed558ccdULL;
        k ^= k >> 33;
        k *= 0xc4ceb9fe1a85ec53ULL;
        k ^= k >> 33;
        return k & kMask;
    }

    inline int find(u64 k) const {
        u64 idx = mix(k);
        while (stamps[idx] == cur_stamp) {
            if (keys[idx] == k) return vals[idx];
            idx = (idx + 1) & kMask;
        }
        return -1;
    }

    inline bool insert(u64 k, int v) {
        u64 idx = mix(k);
        while (stamps[idx] == cur_stamp) {
            if (keys[idx] == k) return false;
            idx = (idx + 1) & kMask;
        }
        stamps[idx] = cur_stamp;
        keys[idx] = k;
        vals[idx] = v;
        return true;
    }
};

// O(used) reset open-addressed hash table for BeamDagSolver & Dict48
struct FastIndex {
    std::vector<i64> keys;
    std::vector<int> ids;
    std::vector<uint32_t> used;
    size_t mask;

    explicit FastIndex(int bits = 20)
        : keys(1ULL << bits, 0), ids(1ULL << bits, -1), mask((1ULL << bits) - 1) {
        used.reserve(1 << 16);
    }

    inline size_t slot(i64 v) const {
        u64 h = static_cast<u64>(v) * 0x9e3779b97f4a7c15ULL;
        h ^= h >> 31;
        size_t i = static_cast<size_t>(h) & mask;
        while (keys[i] && keys[i] != v) i = (i + 1) & mask;
        return i;
    }

    inline int get(i64 v) const {
        if (v <= 0) return -1;
        size_t i = slot(v);
        return keys[i] ? ids[i] : -1;
    }

    inline bool insert(i64 v, int id) {
        if (v <= 0 || used.size() * 8 > keys.size() * 7) return false;
        size_t i = slot(v);
        if (keys[i]) return false;
        used.push_back(static_cast<uint32_t>(i));
        keys[i] = v;
        ids[i] = id;
        return true;
    }

    void clear() {
        for (uint32_t i : used) keys[i] = 0;
        used.clear();
    }
};

// Reusable stamp-resettable open-addressed pair table (262,144 slots ~8 MiB)
struct FlatPairTable {
    static constexpr int kLogCap = 18;
    static constexpr size_t kCap = 1ULL << kLogCap;
    static constexpr size_t kMask = kCap - 1;

    struct PairRec {
        uint16_t a;
        uint16_t b;
        Op op;
    };
    struct Bucket {
        i64 key = 0;
        uint32_t stamp = 0;
        uint8_t cnt = 0;
        PairRec recs[3]{};
    };

    std::vector<Bucket> table;
    std::vector<i64> inserted_keys;
    uint32_t cur_stamp = 1;

    FlatPairTable() : table(kCap) { inserted_keys.reserve(1 << 16); }

    void clear() {
        inserted_keys.clear();
        if (++cur_stamp == 0) {
            for (auto& b : table) b.stamp = 0;
            cur_stamp = 1;
        }
    }

    static inline size_t slot_mix(i64 k) {
        u64 h = static_cast<u64>(k) * 0x9e3779b97f4a7c15ULL;
        h ^= h >> 31;
        h *= 0xbf58476d1ce4e5b9ULL;
        h ^= h >> 27;
        return static_cast<size_t>(h) & kMask;
    }

    inline void add(i64 key, uint16_t a, uint16_t b, Op op) {
        if (key <= 0) return;
        size_t idx = slot_mix(key);
        while (table[idx].stamp == cur_stamp) {
            if (table[idx].key == key) {
                if (table[idx].cnt < 3) {
                    table[idx].recs[table[idx].cnt++] = {a, b, op};
                }
                return;
            }
            idx = (idx + 1) & kMask;
        }
        if (inserted_keys.size() * 8 >= kCap * 7) return;
        table[idx].stamp = cur_stamp;
        table[idx].key = key;
        table[idx].cnt = 1;
        table[idx].recs[0] = {a, b, op};
        inserted_keys.push_back(key);
    }

    inline const Bucket* find(i64 key) const {
        if (key <= 0) return nullptr;
        size_t idx = slot_mix(key);
        while (table[idx].stamp == cur_stamp) {
            if (table[idx].key == key) return &table[idx];
            idx = (idx + 1) & kMask;
        }
        return nullptr;
    }
};

struct Dict48 {
    static constexpr int kLogCap = 14;  // 16,384 slots (L2-cache resident!)
    static constexpr size_t kCap = 1ULL << kLogCap;
    static constexpr size_t kMask = kCap - 1;

    i64 lim = 0;
    std::array<i64, kCap> ht_keys{};
    std::array<int, kCap> ht_vals{};  // 0 if in v0, else (1 + idx in e1)
    std::vector<uint32_t> ht_used;

    struct E1 { i64 v, a, b; Op op; };
    std::vector<i64> v0;
    std::vector<E1> e1;
    std::vector<i64> basis;

    Dict48() { ht_used.reserve(4096); }

    inline size_t slot(i64 v) const {
        u64 h = static_cast<u64>(v) * 0x9e3779b97f4a7c15ULL;
        h ^= h >> 31;
        size_t i = static_cast<size_t>(h) & kMask;
        while (ht_keys[i] && ht_keys[i] != v) i = (i + 1) & kMask;
        return i;
    }

    inline int lookup(i64 v) const {
        if (v <= 0) return -1;
        size_t i = slot(v);
        return ht_keys[i] ? ht_vals[i] : -1;
    }

    inline bool insert_val(i64 v, int val) {
        if (v <= 0 || ht_used.size() * 8 > kCap * 7) return false;
        size_t i = slot(v);
        if (ht_keys[i]) return false;
        ht_used.push_back(static_cast<uint32_t>(i));
        ht_keys[i] = v;
        ht_vals[i] = val;
        return true;
    }

    void build(const std::array<i64, kNumRegs>& reg, int nreg, i64 limit) {
        for (uint32_t i : ht_used) ht_keys[i] = 0;
        ht_used.clear();
        v0.clear();
        e1.clear();
        basis.clear();
        lim = limit;

        for (int r = 0; r < nreg; ++r) {
            if (reg[r] > 0 && insert_val(reg[r], 0)) v0.push_back(reg[r]);
        }
        std::sort(v0.begin(), v0.end());

        for (size_t i = 0; i < v0.size(); ++i) {
            for (size_t j = 0; j <= i; ++j) {
                i64 a = v0[i], b = v0[j];
                auto try1 = [&](i64 v, Op op, i64 x, i64 y) {
                    if (v > 0 && v <= lim) {
                        int nid = 1 + static_cast<int>(e1.size());
                        if (insert_val(v, nid)) e1.push_back({v, x, y, op});
                    }
                };
                if (a <= lim - b) try1(a + b, OP_ADD, a, b);
                if (a > b) try1(a - b, OP_SUB, a, b);
                i128 prod = static_cast<i128>(a) * b;
                if (prod <= lim) try1(static_cast<i64>(prod), OP_MUL, a, b);
                if (b > 0 && a % b == 0) try1(a / b, OP_DIV, a, b);
            }
        }
        basis.reserve(v0.size() + e1.size());
        for (i64 v : v0) basis.push_back(v);
        for (const auto& e : e1) basis.push_back(e.v);
        std::sort(basis.begin(), basis.end());
    }

    inline int cost(i64 x) const {
        int lv = lookup(x);
        if (lv < 0) return 99;
        return lv == 0 ? 0 : 1;
    }

    struct ValOp { Op op; i64 a, b, out; };
    void emit_val(i64 x, std::vector<ValOp>& ops) const {
        int lv = lookup(x);
        if (lv > 0) {
            const auto& e = e1[lv - 1];
            ops.push_back({e.op, e.a, e.b, e.v});
        }
    }
};

struct BeamExpr {
    i64 v;
    int a, b;
    Op op;
    int cost;
};

struct BeamDict {
    i64 limit = 0;
    FastIndex& index;
    std::vector<BeamExpr> e;
    std::array<std::vector<std::pair<i64, int>>, 3> sorted;
    int n0 = 0, n1 = 0;

    BeamDict(i64 lim, FastIndex& idx) : limit(lim), index(idx) {}

    void add(i64 v, int a, int b, Op op, int cost) {
        if (v > 0 && v <= limit && index.insert(v, static_cast<int>(e.size()))) {
            e.push_back({v, a, b, op, cost});
        }
    }

    void combine(int i, int j, int cost) {
        i64 a = e[i].v, b = e[j].v;
        if (a <= limit - b) add(a + b, i, j, OP_ADD, cost);
        if (a != b) add(a > b ? a - b : b - a, a > b ? i : j, a > b ? j : i, OP_SUB, cost);
        i128 prod = static_cast<i128>(a) * b;
        if (prod <= limit) add(static_cast<i64>(prod), i, j, OP_MUL, cost);
        if (a > b && b > 0 && a % b == 0) add(a / b, i, j, OP_DIV, cost);
        if (b > a && a > 0 && b % a == 0) add(b / a, j, i, OP_DIV, cost);
    }

    void build(const std::vector<i64>& leaves) {
        index.clear();
        e.clear();
        for (auto& s : sorted) s.clear();
        for (i64 v : leaves) add(v, -1, -1, OP_ADD, 0);
        n0 = static_cast<int>(e.size());
        for (int i = 0; i < n0; ++i) {
            for (int j = 0; j <= i; ++j) combine(i, j, 1);
        }
        n1 = static_cast<int>(e.size());
        for (int i = n0; i < n1; ++i) {
            for (int j = 0; j < n0; ++j) combine(i, j, 2);
        }
        for (int i = 0; i < static_cast<int>(e.size()); ++i) {
            sorted[e[i].cost].emplace_back(e[i].v, i);
        }
        for (auto& s : sorted) std::sort(s.begin(), s.end());
    }
};

struct WorkerScratch {
    FlatMap p2_map;
    FastIndex beam_idx{18};
    FlatPairTable pair_table;
    FastIndex small_idx{14};
    Dict48 dict48;
};

// --- Arithmetic Graph & Register Lowering (Pass 1) ---

struct DagDef {
    Op op = OP_ADD;
    i64 a = 0;
    i64 b = 0;
};

struct DagGraph {
    std::unordered_map<i64, DagDef> defs;
    std::vector<i64> order;  // topological order of needed non-start values
};

DagGraph extract_needed_dag(const Puzzle& p, const std::vector<Instr>& prog) {
    std::array<i64, kNumRegs> regs{};
    std::unordered_set<i64> starts_set(p.starts.begin(), p.starts.end());
    for (size_t k = 0; k < p.starts.size(); ++k) regs[k] = p.starts[k];

    std::unordered_map<i64, DagDef> all_defs;
    std::vector<i64> creation_order;
    all_defs.reserve(prog.size() + 8);
    creation_order.reserve(prog.size() + 8);

    for (const auto& ins : prog) {
        i64 a = regs[ins.i];
        i64 b = regs[ins.j];
        i64 v = apply_op(ins.op, a, b, p.limit);
        regs[ins.d] = v;
        if (!starts_set.count(v) && !all_defs.count(v)) {
            all_defs[v] = {ins.op, a, b};
            creation_order.push_back(v);
        }
    }

    std::unordered_set<i64> need;
    need.reserve(all_defs.size() + 8);
    std::vector<i64> stack;
    for (i64 t : p.targets) {
        if (!starts_set.count(t)) stack.push_back(t);
    }
    while (!stack.empty()) {
        i64 x = stack.back();
        stack.pop_back();
        if (starts_set.count(x) || need.count(x)) continue;
        auto it = all_defs.find(x);
        if (it == all_defs.end()) continue;
        need.insert(x);
        stack.push_back(it->second.a);
        stack.push_back(it->second.b);
    }

    DagGraph out;
    out.defs.reserve(need.size() + 8);
    out.order.reserve(need.size());
    for (i64 v : creation_order) {
        if (need.count(v)) {
            out.defs[v] = all_defs[v];
            out.order.push_back(v);
        }
    }
    return out;
}

std::vector<i64> topo_from_targets(const std::unordered_set<i64>& starts_set,
                                   const std::unordered_map<i64, DagDef>& defs,
                                   const std::vector<i64>& target_seq) {
    std::unordered_set<i64> placed = starts_set;
    placed.reserve(defs.size() + starts_set.size() + 8);
    std::vector<i64> seq;
    seq.reserve(defs.size());
    auto visit = [&](auto&& self, i64 v) -> void {
        if (placed.count(v)) return;
        auto it = defs.find(v);
        if (it == defs.end()) return;
        placed.insert(v);
        self(self, it->second.a);
        self(self, it->second.b);
        seq.push_back(v);
    };
    for (i64 t : target_seq) visit(visit, t);
    return seq;
}

std::vector<i64> compute_pressure_order_fwd(const Puzzle& p,
                                            const std::unordered_map<i64, DagDef>& defs,
                                            const std::vector<i64>& base_order) {
    std::unordered_set<i64> starts_set(p.starts.begin(), p.starts.end());
    std::unordered_map<i64, int> priority;
    for (size_t i = 0; i < base_order.size(); ++i) priority[base_order[i]] = static_cast<int>(i);

    std::unordered_map<i64, std::vector<i64>> outgoing;
    std::unordered_map<i64, int> pending;
    std::unordered_map<i64, int> remaining;
    for (i64 v : base_order) {
        const auto& d = defs.at(v);
        int cnt = 0;
        if (!starts_set.count(d.a)) ++cnt;
        if (d.b != d.a && !starts_set.count(d.b)) ++cnt;
        pending[v] = cnt;
        outgoing[d.a].push_back(v);
        if (d.b != d.a) outgoing[d.b].push_back(v);
    }
    for (const auto& kv : outgoing) remaining[kv.first] = static_cast<int>(kv.second.size());

    std::vector<i64> ready;
    for (i64 v : base_order) {
        if (pending[v] == 0) ready.push_back(v);
    }

    std::vector<i64> sched;
    sched.reserve(base_order.size());
    while (!ready.empty()) {
        int best_idx = 0;
        std::pair<int, int> best_key{-1000000, -1000000};
        for (int idx = 0; idx < static_cast<int>(ready.size()); ++idx) {
            i64 v = ready[idx];
            const auto& d = defs.at(v);
            int rel = (remaining[d.a] == 1 ? 1 : 0) + (d.b != d.a && remaining[d.b] == 1 ? 1 : 0);
            int stay = (remaining.count(v) && remaining[v] > 0) ? 1 : 0;
            std::pair<int, int> key{rel - stay, -priority[v]};
            if (idx == 0 || key > best_key) {
                best_key = key;
                best_idx = idx;
            }
        }
        i64 v = ready[best_idx];
        ready[best_idx] = ready.back();
        ready.pop_back();
        sched.push_back(v);

        const auto& d = defs.at(v);
        remaining[d.a]--;
        if (d.b != d.a) remaining[d.b]--;
        for (i64 ch : outgoing[v]) {
            if (--pending[ch] == 0) ready.push_back(ch);
        }
    }
    if (sched.size() != base_order.size()) return base_order;
    return sched;
}

std::vector<i64> compute_pressure_order_bwd(const Puzzle& p,
                                            const std::unordered_map<i64, DagDef>& defs,
                                            const std::vector<i64>& base_order) {
    std::unordered_set<i64> starts_set(p.starts.begin(), p.starts.end());
    std::unordered_map<i64, int> priority;
    for (size_t i = 0; i < base_order.size(); ++i) priority[base_order[i]] = static_cast<int>(i);

    std::unordered_map<i64, int> rem_out;
    for (i64 v : base_order) {
        const auto& d = defs.at(v);
        if (!starts_set.count(d.a)) rem_out[d.a]++;
        if (d.b != d.a && !starts_set.count(d.b)) rem_out[d.b]++;
    }

    std::vector<i64> ready;
    for (i64 v : base_order) {
        if (rem_out[v] == 0) ready.push_back(v);
    }

    std::unordered_set<i64> frontier;
    std::vector<i64> rev;
    rev.reserve(base_order.size());
    while (!ready.empty()) {
        int weight = (static_cast<int>(frontier.size() + starts_set.size()) >= p.registers - 7) ? 80 : 5;
        int best_idx = 0;
        std::tuple<int, int, i64> best_key{std::numeric_limits<int>::min(), 0, 0};
        for (int idx = 0; idx < static_cast<int>(ready.size()); ++idx) {
            i64 v = ready[idx];
            const auto& d = defs.at(v);
            int added = 0;
            if (!starts_set.count(d.a) && !frontier.count(d.a)) ++added;
            if (d.b != d.a && !starts_set.count(d.b) && !frontier.count(d.b)) ++added;
            int growth = added - (frontier.count(v) ? 1 : 0);
            int ord = priority[v];
            std::tuple<int, int, i64> key{ord - weight * growth, ord, v};
            if (idx == 0 || key > best_key) {
                best_key = key;
                best_idx = idx;
            }
        }
        i64 v = ready[best_idx];
        ready[best_idx] = ready.back();
        ready.pop_back();
        rev.push_back(v);
        frontier.erase(v);
        const auto& d = defs.at(v);
        if (!starts_set.count(d.a)) {
            frontier.insert(d.a);
            if (--rem_out[d.a] == 0) ready.push_back(d.a);
        }
        if (d.b != d.a && !starts_set.count(d.b)) {
            frontier.insert(d.b);
            if (--rem_out[d.b] == 0) ready.push_back(d.b);
        }
    }
    if (rev.size() != base_order.size()) return base_order;
    std::reverse(rev.begin(), rev.end());
    return rev;
}

// Linear-scan zero-spill exact 48-register allocator (retiring sources can be overwritten immediately)
bool allocate_exact(const Puzzle& p,
                    const std::unordered_map<i64, DagDef>& defs,
                    const std::vector<i64>& seq,
                    std::vector<Instr>& out) {
    out.clear();
    std::unordered_map<i64, int> rem;
    rem.reserve(seq.size() * 2 + 8);
    for (i64 v : seq) {
        const auto& d = defs.at(v);
        rem[d.a]++;
        if (d.b != d.a) rem[d.b]++;
    }

    std::unordered_map<i64, int> live;
    std::array<bool, kNumRegs> used_reg{};
    for (size_t k = 0; k < p.starts.size(); ++k) {
        i64 sv = p.starts[k];
        if (rem[sv] > 0 && !live.count(sv)) {
            live[sv] = static_cast<int>(k);
            used_reg[k] = true;
        }
    }
    std::vector<int> free_regs;
    free_regs.reserve(p.registers);
    for (int r = p.registers - 1; r >= 0; --r) {
        if (!used_reg[r]) free_regs.push_back(r);
    }

    out.reserve(seq.size());
    for (i64 v : seq) {
        const auto& d = defs.at(v);
        auto ita = live.find(d.a);
        auto itb = live.find(d.b);
        if (ita == live.end() || itb == live.end()) return false;
        int ra = ita->second;
        int rb = itb->second;

        if (--rem[d.a] == 0) {
            free_regs.push_back(ra);
            live.erase(d.a);
        }
        if (d.b != d.a && --rem[d.b] == 0) {
            free_regs.push_back(rb);
            live.erase(d.b);
        }
        if (free_regs.empty()) return false;
        int rd = free_regs.back();
        free_regs.pop_back();
        out.push_back({d.op, static_cast<uint8_t>(ra), static_cast<uint8_t>(rb), static_cast<uint8_t>(rd)});
        if (rem[v] > 0) live[v] = rd;
        else free_regs.push_back(rd);
    }
    return verify_program(p, out);
}

// Mizero-style cost-aware spill-and-rebuild 48-register allocator (dense integer IDs)
bool allocate_cost_aware(const Puzzle& p,
                         const std::unordered_map<i64, DagDef>& defs,
                         const std::vector<i64>& seq,
                         double jitter,
                         SplitMix64& rng,
                         int max_len,
                         std::vector<Instr>& out) {
    out.clear();
    const int N = static_cast<int>(seq.size());
    std::unordered_map<i64, int> val_to_id;
    val_to_id.reserve(N * 2 + p.starts.size() * 2 + 8);
    std::vector<i64> id_to_val;
    id_to_val.reserve(N + p.starts.size() + 4);
    for (i64 s : p.starts) {
        if (!val_to_id.count(s)) {
            val_to_id[s] = static_cast<int>(id_to_val.size());
            id_to_val.push_back(s);
        }
    }
    const int n_roots = static_cast<int>(id_to_val.size());
    for (i64 v : seq) {
        if (!val_to_id.count(v)) {
            val_to_id[v] = static_cast<int>(id_to_val.size());
            id_to_val.push_back(v);
        }
    }
    const int M = static_cast<int>(id_to_val.size());
    std::vector<Op> node_op(M, OP_ADD);
    std::vector<int> node_a(M, -1), node_b(M, -1);
    std::vector<std::vector<int>> uses(M);
    for (int id = n_roots; id < M; ++id) {
        const auto& d = defs.at(id_to_val[id]);
        node_op[id] = d.op;
        node_a[id] = val_to_id.at(d.a);
        node_b[id] = val_to_id.at(d.b);
    }
    for (int i = N - 1; i >= 0; --i) {
        int id = val_to_id.at(seq[i]);
        int a = node_a[id], b = node_b[id];
        uses[a].push_back(i);
        if (b != a) uses[b].push_back(i);
    }

    std::array<int, kNumRegs> bank_id{};
    bank_id.fill(-1);
    std::vector<int> id_reg(M, -1);
    std::vector<uint8_t> is_seed(M, 0);
    for (size_t k = 0; k < p.starts.size(); ++k) {
        int sid = val_to_id.at(p.starts[k]);
        is_seed[sid] = 1;
        if (id_reg[sid] < 0) {
            bank_id[k] = sid;
            id_reg[sid] = static_cast<int>(k);
        }
    }

    auto rebuild_cost_fast = [&](auto&& self, int id, int depth) -> int {
        if (id_reg[id] >= 0) return 0;
        if (depth >= 3 || id < n_roots) return 6;
        int a = node_a[id], b = node_b[id];
        return 1 + self(self, a, depth + 1) + (a != b ? self(self, b, depth + 1) : 0);
    };

    int cur = -1;
    std::function<int(int, u64, int)> emit = [&](int id, u64 locked, int depth) -> int {
        if (id_reg[id] >= 0) return id_reg[id];
        if (static_cast<int>(out.size()) >= max_len || depth > 40 || id < n_roots) return -1;

        Op emit_op = node_op[id];
        int ra = -1, rb = -1;
        bool shortcut = false;
        if (id_reg[node_a[id]] < 0 || id_reg[node_b[id]] < 0) {
            i64 target_val = id_to_val[id];
            WBackStep bs[6];
            for (int r1 = 0; r1 < p.registers && !shortcut; ++r1) {
                if (bank_id[r1] < 0) continue;
                i64 x = id_to_val[bank_id[r1]];
                int nb = gen_win_inverses(target_val, x, p.limit, bs);
                for (int k = 0; k < nb; ++k) {
                    auto it = val_to_id.find(bs[k].u);
                    if (it == val_to_id.end()) continue;
                    int r2 = id_reg[it->second];
                    if (r2 < 0) continue;
                    emit_op = bs[k].op;
                    ra = bs[k].rev ? r1 : r2;
                    rb = bs[k].rev ? r2 : r1;
                    shortcut = true;
                    break;
                }
            }
        }
        if (!shortcut) {
            ra = emit(node_a[id], locked, depth + 1);
            if (ra < 0) return -1;
            rb = emit(node_b[id], locked | (1ULL << ra), depth + 1);
            if (rb < 0) return -1;
            emit_op = node_op[id];
        }
        if (static_cast<int>(out.size()) >= max_len) return -1;

        int rd = -1;
        double best_sc = 1e18;
        for (int k = 0; k < p.registers; ++k) {
            int old_id = bank_id[k];
            if ((locked >> k) & 1ULL) continue;
            if (old_id < 0) {
                rd = k;
                break;
            }
            if (is_seed[old_id]) continue;
            double sc = 0.0;
            if (uses[old_id].empty()) {
                sc = -1.0 / static_cast<double>(1 + k);
            } else {
                int dist = std::max(1, uses[old_id].back() - cur + 1);
                int oa = node_a[old_id], ob = node_b[old_id];
                double rc = 1.0 + rebuild_cost_fast(rebuild_cost_fast, oa, 0) +
                            (oa != ob ? rebuild_cost_fast(rebuild_cost_fast, ob, 0) : 0);
                sc = (rc * rc) / static_cast<double>(dist);
                if (jitter > 0.0) {
                    double u = rng.next_unit() * 2.0 - 1.0;
                    sc *= std::exp(jitter * u);
                }
            }
            if (sc < best_sc) {
                best_sc = sc;
                rd = k;
            }
        }
        if (rd < 0) return -1;
        if (bank_id[rd] >= 0) id_reg[bank_id[rd]] = -1;
        bank_id[rd] = id;
        id_reg[id] = rd;
        out.push_back({emit_op, static_cast<uint8_t>(ra), static_cast<uint8_t>(rb), static_cast<uint8_t>(rd)});
        return rd;
    };

    for (i64 v : seq) {
        ++cur;
        int id = val_to_id.at(v);
        int a = node_a[id], b = node_b[id];
        if (!uses[a].empty()) uses[a].pop_back();
        if (b != a && !uses[b].empty()) uses[b].pop_back();
        if (emit(id, 0ULL, 0) < 0) return false;
    }
    return verify_program(p, out);
}

std::vector<i64> compute_pressure_order_bwd_jit(const Puzzle& p,
                                                const std::unordered_map<i64, DagDef>& defs,
                                                const std::vector<i64>& base_order,
                                                SplitMix64& rng) {
    std::unordered_set<i64> starts_set(p.starts.begin(), p.starts.end());
    std::unordered_map<i64, int> priority;
    for (size_t i = 0; i < base_order.size(); ++i) priority[base_order[i]] = static_cast<int>(i);
    std::unordered_map<i64, int> rem_out;
    for (i64 v : base_order) {
        const auto& d = defs.at(v);
        if (!starts_set.count(d.a)) rem_out[d.a]++;
        if (d.b != d.a && !starts_set.count(d.b)) rem_out[d.b]++;
    }
    std::vector<i64> ready;
    for (i64 v : base_order) {
        if (rem_out[v] == 0) ready.push_back(v);
    }
    std::unordered_set<i64> frontier;
    std::vector<i64> rev;
    rev.reserve(base_order.size());
    while (!ready.empty()) {
        int weight = (static_cast<int>(frontier.size() + starts_set.size()) >= p.registers - 7) ? 80 : 10;
        int best_idx = 0;
        double best_key = -1e18;
        for (int idx = 0; idx < static_cast<int>(ready.size()); ++idx) {
            i64 v = ready[idx];
            const auto& d = defs.at(v);
            int added = 0;
            if (!starts_set.count(d.a) && !frontier.count(d.a)) ++added;
            if (d.b != d.a && !starts_set.count(d.b) && !frontier.count(d.b)) ++added;
            int growth = added - (frontier.count(v) ? 1 : 0);
            double key = static_cast<double>(priority[v]) - static_cast<double>(weight * growth) +
                         (rng.next_unit() - 0.5) * 24.0;
            if (idx == 0 || key > best_key) {
                best_key = key;
                best_idx = idx;
            }
        }
        i64 v = ready[best_idx];
        ready[best_idx] = ready.back();
        ready.pop_back();
        rev.push_back(v);
        frontier.erase(v);
        const auto& d = defs.at(v);
        if (!starts_set.count(d.a)) {
            frontier.insert(d.a);
            if (--rem_out[d.a] == 0) ready.push_back(d.a);
        }
        if (d.b != d.a && !starts_set.count(d.b)) {
            frontier.insert(d.b);
            if (--rem_out[d.b] == 0) ready.push_back(d.b);
        }
    }
    if (rev.size() != base_order.size()) return base_order;
    std::reverse(rev.begin(), rev.end());
    return rev;
}

std::vector<i64> compute_live_frontier_order(const Puzzle& p,
                                             const std::unordered_map<i64, DagDef>& defs,
                                             const std::vector<i64>& req_targets,
                                             int start_idx,
                                             int strength) {
    std::unordered_set<i64> starts_set(p.starts.begin(), p.starts.end());
    if (req_targets.size() <= 1) return topo_from_targets(starts_set, defs, req_targets);

    std::vector<i64> idx_to_val;
    idx_to_val.reserve(defs.size());
    for (const auto& kv : defs) idx_to_val.push_back(kv.first);
    std::sort(idx_to_val.begin(), idx_to_val.end());

    std::unordered_map<i64, int> val_to_idx;
    val_to_idx.reserve(idx_to_val.size() * 2 + 8);
    for (size_t i = 0; i < idx_to_val.size(); ++i) {
        val_to_idx[idx_to_val[i]] = static_cast<int>(i);
    }

    const int n = static_cast<int>(idx_to_val.size());
    const int t = static_cast<int>(req_targets.size());
    std::vector<int> pending(n, 0);
    std::vector<uint8_t> opened(n, 0), done(t, 0), visit(n, 0);
    std::vector<std::vector<int>> dependencies(t);

    for (int i = 0; i < t; ++i) {
        std::fill(visit.begin(), visit.end(), 0);
        std::vector<int> stk;
        auto push_val = [&](i64 v) {
            if (starts_set.count(v)) return;
            auto it = val_to_idx.find(v);
            if (it != val_to_idx.end() && !visit[it->second]) {
                visit[it->second] = 1;
                stk.push_back(it->second);
            }
        };
        push_val(req_targets[i]);
        while (!stk.empty()) {
            int vid = stk.back();
            stk.pop_back();
            ++pending[vid];
            dependencies[i].push_back(vid);
            const auto& d = defs.at(idx_to_val[vid]);
            push_val(d.a);
            push_val(d.b);
        }
    }

    std::vector<i64> target_order;
    target_order.reserve(t);
    for (int step = 0; step < t; ++step) {
        int choose = -1;
        int best_cost = std::numeric_limits<int>::max();
        for (int j = 0; j < t; ++j) {
            if (done[j]) continue;
            if (step == 0 && start_idx >= 0 && start_idx < t && j != start_idx) continue;
            int cost = 0;
            for (int v : dependencies[j]) {
                if (!opened[v] && pending[v] > 1) cost += strength;
                if (opened[v] && pending[v] == 1) cost -= strength;
                if (!opened[v]) ++cost;
            }
            if (cost < best_cost) {
                best_cost = cost;
                choose = j;
            }
        }
        if (choose < 0) break;
        done[choose] = 1;
        for (int v : dependencies[choose]) {
            opened[v] = 1;
            --pending[v];
        }
        target_order.push_back(req_targets[choose]);
    }
    return topo_from_targets(starts_set, defs, target_order);
}


std::vector<i64> compute_pull_jit_order(const Puzzle& p,
                                        const std::unordered_map<i64, DagDef>& defs,
                                        const std::vector<i64>& base_order) {
    std::unordered_set<i64> starts_set(p.starts.begin(), p.starts.end());
    std::unordered_map<i64, int> hint_pos;
    hint_pos.reserve(base_order.size() * 2 + 4);
    for (size_t i = 0; i < base_order.size(); ++i) hint_pos[base_order[i]] = static_cast<int>(i);

    std::unordered_map<i64, std::vector<i64>> consumers;
    std::unordered_map<i64, int> indeg;
    for (i64 v : base_order) {
        const auto& d = defs.at(v);
        int deg = 0;
        if (!starts_set.count(d.a)) { ++deg; consumers[d.a].push_back(v); }
        if (d.b != d.a && !starts_set.count(d.b)) { ++deg; consumers[d.b].push_back(v); }
        indeg[v] = deg;
    }

    std::unordered_map<i64, double> prio;
    for (int idx = static_cast<int>(base_order.size()) - 1; idx >= 0; --idx) {
        i64 v = base_order[idx];
        double jit = 1e18;
        auto it = consumers.find(v);
        if (it != consumers.end()) {
            for (i64 c : it->second) {
                auto pit = prio.find(c);
                if (pit != prio.end()) jit = std::min(jit, pit->second - 0.5);
            }
        }
        auto hit = hint_pos.find(v);
        prio[v] = (hit != hint_pos.end()) ? std::min(static_cast<double>(hit->second), jit) : jit;
    }

    using QItem = std::pair<double, i64>;
    std::priority_queue<QItem, std::vector<QItem>, std::greater<QItem>> pq;
    for (i64 v : base_order) {
        if (indeg[v] == 0) pq.push({prio[v], v});
    }
    std::vector<i64> seq;
    seq.reserve(base_order.size());
    while (!pq.empty()) {
        auto [pr, v] = pq.top();
        pq.pop();
        seq.push_back(v);
        auto it = consumers.find(v);
        if (it != consumers.end()) {
            for (i64 c : it->second) {
                if (--indeg[c] == 0) pq.push({prio[c], c});
            }
        }
    }
    return (seq.size() == base_order.size()) ? seq : base_order;
}

void dag_reallocate_cap(const Puzzle& p,
                        const DagGraph& dag,
                        std::vector<Instr>& best,
                        int cap_exclusive,
                        int cost_trials = 80) {
    if (dag.defs.empty()) return;
    int cap_len = best.empty() ? cap_exclusive : std::min(cap_exclusive, static_cast<int>(best.size()));
    if (static_cast<int>(dag.defs.size()) >= cap_len) return;

    std::unordered_set<i64> starts_set(p.starts.begin(), p.starts.end());
    std::vector<i64> req_targets;
    for (i64 t : p.targets) {
        if (!starts_set.count(t)) req_targets.push_back(t);
    }
    std::sort(req_targets.begin(), req_targets.end());
    req_targets.erase(std::unique(req_targets.begin(), req_targets.end()), req_targets.end());

    std::vector<i64> targets_desc = req_targets;
    std::reverse(targets_desc.begin(), targets_desc.end());

    std::unordered_map<i64, int> hint_pos;
    for (size_t i = 0; i < dag.order.size(); ++i) hint_pos[dag.order[i]] = static_cast<int>(i);
    std::vector<i64> targets_hint = req_targets;
    std::sort(targets_hint.begin(), targets_hint.end(), [&](i64 a, i64 b) {
        return hint_pos[a] < hint_pos[b];
    });

    std::vector<std::vector<i64>> schedules;
    schedules.push_back(dag.order);
    schedules.push_back(topo_from_targets(starts_set, dag.defs, targets_hint));
    schedules.push_back(topo_from_targets(starts_set, dag.defs, req_targets));
    schedules.push_back(topo_from_targets(starts_set, dag.defs, targets_desc));
    schedules.push_back(compute_pressure_order_fwd(p, dag.defs, schedules[0]));
    schedules.push_back(compute_pressure_order_bwd(p, dag.defs, schedules[0]));
    schedules.push_back(compute_live_frontier_order(p, dag.defs, req_targets, -1, 3));
    schedules.push_back(compute_live_frontier_order(p, dag.defs, req_targets, -1, 2));
    schedules.push_back(compute_pull_jit_order(p, dag.defs, schedules[0]));

    std::vector<Instr> cand;

    for (const auto& seq : schedules) {
        if (allocate_exact(p, dag.defs, seq, cand)) {
            if (static_cast<int>(cand.size()) < cap_len) {
                best = std::move(cand);
                cap_len = static_cast<int>(best.size());
                if (best.size() == dag.defs.size()) return;
            }
        }
    }

    // If still spilling, sweep all start_idx for live-frontier exact allocation
    if (static_cast<int>(dag.defs.size()) < cap_len && cost_trials >= 60) {
        for (int sidx = 0; sidx < static_cast<int>(req_targets.size()); ++sidx) {
            for (int str : {2, 3, 4}) {
                auto seq = compute_live_frontier_order(p, dag.defs, req_targets, sidx, str);
                if (allocate_exact(p, dag.defs, seq, cand)) {
                    if (static_cast<int>(cand.size()) < cap_len) {
                        best = std::move(cand);
                        cap_len = static_cast<int>(best.size());
                        if (best.size() == dag.defs.size()) return;
                    }
                }
            }
        }
    }

    // Try 24 deterministic random target orderings + 24 jittered pressure schedules with allocate_exact
    for (u64 trial = 0; trial < 24; ++trial) {
        SplitMix64 rng(p.numeric_id * 1009ULL + trial + 1ULL);
        std::vector<i64> perm = req_targets;
        for (int idx = static_cast<int>(perm.size()) - 1; idx > 0; --idx) {
            int j = static_cast<int>(rng.next_u64() % static_cast<u64>(idx + 1));
            std::swap(perm[idx], perm[j]);
        }
        auto seq = topo_from_targets(starts_set, dag.defs, perm);
        if (allocate_exact(p, dag.defs, seq, cand)) {
            if (static_cast<int>(cand.size()) < cap_len) {
                best = std::move(cand);
                cap_len = static_cast<int>(best.size());
                if (best.size() == dag.defs.size()) return;
            }
        }
        auto pseq = compute_pressure_order_bwd_jit(p, dag.defs, schedules[0], rng);
        if (allocate_exact(p, dag.defs, pseq, cand)) {
            if (static_cast<int>(cand.size()) < cap_len) {
                best = std::move(cand);
                cap_len = static_cast<int>(best.size());
                if (best.size() == dag.defs.size()) return;
            }
        }
    }

    // Fallback: fast array-indexed deterministic trials of cost-aware allocator
    for (int trial = 0; trial < cost_trials; ++trial) {
        SplitMix64 rng(p.numeric_id * 1009ULL + 100ULL + static_cast<u64>(trial));
        const std::vector<i64>* seq_ptr = &schedules[static_cast<size_t>(trial) % schedules.size()];
        std::vector<i64> perm_seq;
        if (trial >= 12 && (trial % 3 == 0)) {
            perm_seq = compute_pressure_order_bwd_jit(p, dag.defs, schedules[0], rng);
            seq_ptr = &perm_seq;
        }
        double jit = (trial < static_cast<int>(schedules.size())) ? 0.0 : 1.5;
        int max_emit = std::max(1, cap_len - 1);
        if (allocate_cost_aware(p, dag.defs, *seq_ptr, jit, rng, max_emit, cand)) {
            if (static_cast<int>(cand.size()) < cap_len) {
                best = std::move(cand);
                cap_len = static_cast<int>(best.size());
                if (best.size() == dag.defs.size()) return;
            }
        }
    }
}

void dag_reallocate(const Puzzle& p, const DagGraph& dag, std::vector<Instr>& best) {
    int cap = best.empty() ? kMaxProgramLen : static_cast<int>(best.size());
    dag_reallocate_cap(p, dag, best, cap, 80);
}

// --- Stage 3: Window MitM & Single-Use Expression Tree Cut (Pass 3) ---

inline u64 reg_bit(int r) { return 1ULL << r; }

inline int find_scratch_reg(u64 forbidden, int nreg) {
    u64 avail = (((nreg >= 64) ? ~0ULL : ((1ULL << nreg) - 1ULL))) & ~forbidden;
    return avail ? __builtin_ctzll(avail) : -1;
}

struct WindowEntry {
    i64 val;
    Instr ins;
};

struct OneStepBank {
    std::vector<WindowEntry> entries;
    std::unordered_map<i64, int> lookup;

    void build(const std::array<i64, kNumRegs>& r, int nreg, i64 limit) {
        entries.clear();
        lookup.clear();
        entries.reserve(2400);
        lookup.reserve(4096);
        auto add = [&](i64 v, Op op, int x, int y) {
            if (v > 0 && v <= limit && !lookup.count(v)) {
                lookup[v] = static_cast<int>(entries.size());
                entries.push_back({v, {op, static_cast<uint8_t>(x), static_cast<uint8_t>(y), 0}});
            }
        };
        for (int i = 0; i < nreg; ++i) {
            if (r[i] <= 0) continue;
            for (int j = i; j < nreg; ++j) {
                if (r[j] <= 0) continue;
                i64 a = r[i], b = r[j];
                if (a <= limit - b) add(a + b, OP_ADD, i, j);
                i128 prod = static_cast<i128>(a) * b;
                if (prod <= limit) add(static_cast<i64>(prod), OP_MUL, i, j);
                int hi = (a >= b) ? i : j;
                int lo = (a >= b) ? j : i;
                if (r[hi] > r[lo]) add(r[hi] - r[lo], OP_SUB, hi, lo);
                if (r[lo] > 0 && r[hi] % r[lo] == 0) add(r[hi] / r[lo], OP_DIV, hi, lo);
            }
        }
    }

    int find(i64 v) const {
        auto it = lookup.find(v);
        return (it == lookup.end()) ? -1 : it->second;
    }
};

struct WinGoal {
    i64 val;
    int dest;  // physical reg, or -1 for target-only write
};

struct SymOp {
    Op op;
    int a, b;
};

bool place_fragment(const std::array<SymOp, 3>& frag, int dest, u64 live, int nreg,
                    std::vector<Instr>& repl) {
    int allocated[3] = {0, 0, dest};
    for (int first = 0; first < nreg; ++first) {
        if (first != dest && (live & reg_bit(first))) continue;
        allocated[0] = first;
        for (int second = 0; second < nreg; ++second) {
            if (second != dest && (live & reg_bit(second))) continue;
            allocated[1] = second;
            std::array<int, kNumRegs> physical{};
            for (int r = 0; r < nreg; ++r) physical[r] = r;
            Instr prop[3]{};
            bool ok = true;
            for (int s = 0; s < 3; ++s) {
                const auto& op = frag[s];
                int a = (op.a >= kNumRegs) ? allocated[op.a - kNumRegs] : op.a;
                int b = (op.b >= kNumRegs) ? allocated[op.b - kNumRegs] : op.b;
                if (physical[a] != op.a || physical[b] != op.b) {
                    ok = false;
                    break;
                }
                prop[s] = {op.op, static_cast<uint8_t>(a), static_cast<uint8_t>(b),
                           static_cast<uint8_t>(allocated[s])};
                physical[allocated[s]] = kNumRegs + s;
            }
            if (ok) {
                repl.assign(prop, prop + 3);
                return true;
            }
        }
    }
    return false;
}

bool find_shorter_window(i64 v, int dest, u64 live, const std::array<i64, kNumRegs>& r,
                         int nreg, i64 limit, const OneStepBank& direct, int budget,
                         std::vector<Instr>& repl) {
    if (budget < 1) return false;
    int idx1 = direct.find(v);
    if (idx1 >= 0) {
        Instr first = direct.entries[idx1].ins;
        first.d = static_cast<uint8_t>(dest);
        repl = {first};
        return true;
    }
    if (budget < 2) return false;

    auto make_comb = [&](Op op, int tmp, int old_r, bool rev, int d) -> Instr {
        return {op, static_cast<uint8_t>(rev ? old_r : tmp),
                static_cast<uint8_t>(rev ? tmp : old_r), static_cast<uint8_t>(d)};
    };

    for (int i = 0; i < nreg; ++i) {
        if (r[i] <= 0) continue;
        WBackStep bs[6];
        int nb = gen_win_inverses(v, r[i], limit, bs);
        for (int k = 0; k < nb; ++k) {
            int iu = direct.find(bs[k].u);
            if (iu < 0) continue;
            int tmp = find_scratch_reg((live & ~reg_bit(dest)) | reg_bit(i), nreg);
            if (tmp < 0) continue;
            Instr first = direct.entries[iu].ins;
            first.d = static_cast<uint8_t>(tmp);
            repl = {first, make_comb(bs[k].op, tmp, i, bs[k].rev, dest)};
            return true;
        }
    }
    if ((v & 1LL) == 0) {
        int ih = direct.find(v / 2);
        if (ih >= 0) {
            Instr first = direct.entries[ih].ins;
            first.d = static_cast<uint8_t>(dest);
            repl = {first, {OP_ADD, static_cast<uint8_t>(dest), static_cast<uint8_t>(dest),
                            static_cast<uint8_t>(dest)}};
            return true;
        }
    }
    if (budget < 3) return false;

    // Chained 3-step expressions with optional intermediate squaring or doubling
    auto in_regs = [&](i64 val) -> bool {
        for (int ri = 0; ri < nreg; ++ri) {
            if (r[ri] == val) return true;
        }
        return false;
    };
    for (int rb = 0; rb < nreg; ++rb) {
        if (r[rb] <= 0) continue;
        WBackStep bs1[6];
        int nb1 = gen_win_inverses(v, r[rb], limit, bs1);
        for (int k1 = 0; k1 < nb1; ++k1) {
            i64 x = bs1[k1].u;
            if (in_regs(x) || direct.find(x) >= 0) continue;
            SymOp last_sym{bs1[k1].op, bs1[k1].rev ? rb : kNumRegs + 1,
                           bs1[k1].rev ? kNumRegs + 1 : rb};
            for (int rc = 0; rc < nreg; ++rc) {
                if (r[rc] <= 0) continue;
                WBackStep bs2[6];
                int nb2 = gen_win_inverses(x, r[rc], limit, bs2);
                for (int k2 = 0; k2 < nb2; ++k2) {
                    int ih = direct.find(bs2[k2].u);
                    if (ih < 0) continue;
                    const Instr& hi = direct.entries[ih].ins;
                    std::array<SymOp, 3> frag{{
                        {hi.op, hi.i, hi.j},
                        {bs2[k2].op, bs2[k2].rev ? rc : kNumRegs, bs2[k2].rev ? kNumRegs : rc},
                        last_sym,
                    }};
                    if (place_fragment(frag, dest, live, nreg, repl)) return true;
                }
            }
            i64 sq = static_cast<i64>(std::sqrt(static_cast<long double>(x)));
            while (static_cast<i128>(sq + 1) * (sq + 1) <= x) ++sq;
            while (sq > 0 && static_cast<i128>(sq) * sq > x) --sq;
            if (sq > 0 && static_cast<i128>(sq) * sq == x) {
                int ih = direct.find(sq);
                if (ih >= 0) {
                    const Instr& hi = direct.entries[ih].ins;
                    std::array<SymOp, 3> frag{{
                        {hi.op, hi.i, hi.j},
                        {OP_MUL, kNumRegs, kNumRegs},
                        last_sym,
                    }};
                    if (place_fragment(frag, dest, live, nreg, repl)) return true;
                }
            }
            if ((x & 1LL) == 0) {
                int ih = direct.find(x / 2);
                if (ih >= 0) {
                    const Instr& hi = direct.entries[ih].ins;
                    std::array<SymOp, 3> frag{{
                        {hi.op, hi.i, hi.j},
                        {OP_ADD, kNumRegs, kNumRegs},
                        last_sym,
                    }};
                    if (place_fragment(frag, dest, live, nreg, repl)) return true;
                }
            }
        }
    }

    for (const auto& item : direct.entries) {
        WBackStep bs[6];
        int nb = gen_win_inverses(v, item.val, limit, bs);
        for (int k = 0; k < nb; ++k) {
            int iu = direct.find(bs[k].u);
            if (iu < 0) continue;
            Instr a = direct.entries[iu].ins;
            Instr b = item.ins;
            u64 keep = live & ~reg_bit(dest);
            int ad = find_scratch_reg(keep | reg_bit(b.i) | reg_bit(b.j), nreg);
            if (ad < 0) continue;
            int bd = find_scratch_reg(keep | reg_bit(ad), nreg);
            if (bd < 0) continue;
            a.d = static_cast<uint8_t>(ad);
            b.d = static_cast<uint8_t>(bd);
            repl = {a, b, make_comb(bs[k].op, ad, bd, bs[k].rev, dest)};
            return true;
        }
    }
    return false;
}

bool find_two_goals_window(const std::array<i64, kNumRegs>& r, int nreg, i64 limit, u64 live_after,
                           WinGoal g0, WinGoal g1, const OneStepBank& direct,
                           std::vector<Instr>& repl) {
    WinGoal pair[2] = {g0, g1};
    for (int order = 0; order < 2; ++order) {
        WinGoal fst = pair[order];
        WinGoal lst = pair[1 - order];
        int idx1 = direct.find(fst.val);
        if (idx1 < 0) continue;
        Instr first_base = direct.entries[idx1].ins;
        for (int ri = 0; ri < nreg; ++ri) {
            if (fst.dest != -1 && ri != fst.dest) continue;
            if (fst.dest == -1 && (live_after & reg_bit(ri))) continue;
            Instr first = first_base;
            first.d = static_cast<uint8_t>(ri);
            auto next = r;
            next[ri] = fst.val;
            int d = (lst.dest == -1) ? ri : lst.dest;
            if (lst.dest == -1 && fst.dest != -1) {
                d = find_scratch_reg(live_after, nreg);
                if (d < 0) continue;
            }
            Instr last{};
            if (one_step_regs(next, nreg, lst.val, limit, d, last)) {
                repl = {first, last};
                return true;
            }
        }
    }
    return false;
}

std::vector<Instr> window_sweep_once(const Puzzle& p, const std::vector<Instr>& prog) {
    size_t n = prog.size();
    std::vector<u64> live(n + 1, 0);
    std::vector<i64> values(n, 0);
    std::array<i64, kNumRegs> r{};
    for (size_t k = 0; k < p.starts.size(); ++k) r[k] = p.starts[k];

    std::unordered_set<i64> missing(p.targets.begin(), p.targets.end());
    for (i64 x : p.starts) missing.erase(x);
    std::unordered_map<i64, size_t> last_target_write;
    last_target_write.reserve(missing.size() * 2 + 4);

    for (size_t i = n; i-- > 0;) {
        const auto& s = prog[i];
        live[i] = (live[i + 1] & ~reg_bit(s.d)) | reg_bit(s.i) | reg_bit(s.j);
    }
    for (size_t i = 0; i < n; ++i) {
        const auto& s = prog[i];
        values[i] = r[s.d] = apply_op(s.op, r[s.i], r[s.j], p.limit);
        if (missing.count(values[i])) last_target_write[values[i]] = i;
    }

    r.fill(0);
    for (size_t k = 0; k < p.starts.size(); ++k) r[k] = p.starts[k];

    std::vector<Instr> out;
    out.reserve(n);
    OneStepBank direct;

    struct WinCand {
        int j;
        int ng;
        WinGoal g0;
        WinGoal g1;
    };

    for (size_t i = 0; i < n;) {
        u64 written = 0;
        std::vector<WinCand> cands;
        std::array<i64, kNumRegs> after = r;

        for (size_t j = i; j < std::min(n, i + 16); ++j) {
            written |= reg_bit(prog[j].d);
            after[prog[j].d] = values[j];

            u64 needed = written & live[j + 1];
            for (u64 m = needed; m; m &= m - 1) {
                int d = __builtin_ctzll(m);
                if (r[d] == after[d]) needed &= ~reg_bit(d);
            }
            if (__builtin_popcountll(needed) > 2) continue;

            WinGoal goals[4]{};
            int ng = 0;
            for (u64 m = needed; m; m &= m - 1) {
                int d = __builtin_ctzll(m);
                goals[ng++] = {after[d], d};
            }
            for (size_t k = i; k <= j; ++k) {
                i64 v = values[k];
                auto ltw = last_target_write.find(v);
                if (ltw == last_target_write.end() || ltw->second != k || !missing.count(v)) continue;
                bool dup = false;
                for (int gi = 0; gi < ng; ++gi) {
                    if (goals[gi].val == v) {
                        dup = true;
                        break;
                    }
                }
                if (!dup && ng < 4) goals[ng++] = {v, -1};
            }

            int length = static_cast<int>(j - i + 1);
            if (ng > 2 || ng >= length) continue;
            if (ng == 0) {
                cands.push_back({static_cast<int>(j), 0, {}, {}});
                continue;
            }
            if (ng == 1) {
                if (goals[0].dest < 0) {
                    int d = find_scratch_reg(live[j + 1], p.registers);
                    if (d < 0) continue;
                    goals[0].dest = d;
                }
                cands.push_back({static_cast<int>(j), 1, goals[0], {}});
            } else {
                if (length < 3) continue;
                cands.push_back({static_cast<int>(j), 2, goals[0], goals[1]});
            }
        }

        bool replaced = false;
        bool built_direct = false;
        for (size_t k = cands.size(); k-- > 0;) {
            const auto& c = cands[k];
            std::vector<Instr> repl;
            if (c.ng > 0) {
                if (!built_direct) {
                    direct.build(r, p.registers, p.limit);
                    built_direct = true;
                }
                if (c.ng == 1) {
                    if (!find_shorter_window(c.g0.val, c.g0.dest, live[c.j + 1], r, p.registers,
                                             p.limit, direct, c.j - static_cast<int>(i), repl)) {
                        continue;
                    }
                } else {
                    if (!find_two_goals_window(r, p.registers, p.limit, live[c.j + 1],
                                               c.g0, c.g1, direct, repl)) {
                        continue;
                    }
                }
            }
            for (const auto& s : repl) {
                r[s.d] = apply_op(s.op, r[s.i], r[s.j], p.limit);
                missing.erase(r[s.d]);
                out.push_back(s);
            }
            i = static_cast<size_t>(c.j) + 1;
            replaced = true;
            break;
        }
        if (replaced) continue;
        const auto& s = prog[i++];
        r[s.d] = apply_op(s.op, r[s.i], r[s.j], p.limit);
        missing.erase(r[s.d]);
        out.push_back(s);
    }
    return out;
}

std::vector<Instr> cut_expression_once(const Puzzle& p, const std::vector<Instr>& prog, size_t& cursor) {
    int n = static_cast<int>(prog.size());
    std::vector<u64> live(n + 1, 0);
    std::vector<int> uses(n, 0);
    std::vector<std::array<int, 2>> parents(n);
    std::array<int, kNumRegs> producer;
    producer.fill(-1);
    std::array<i64, kNumRegs> r{};
    for (size_t k = 0; k < p.starts.size(); ++k) r[k] = p.starts[k];

    std::unordered_set<i64> missing(p.targets.begin(), p.targets.end());
    for (i64 x : p.starts) missing.erase(x);

    for (int i = 0; i < n; ++i) {
        const auto& s = prog[i];
        int a = producer[s.i], b = producer[s.j];
        parents[i] = {a, b};
        if (a >= 0) ++uses[a];
        if (b >= 0 && b != a) ++uses[b];
        i64 v = apply_op(s.op, r[s.i], r[s.j], p.limit);
        r[s.d] = v;
        if (missing.erase(v)) ++uses[i];
        producer[s.d] = i;
    }
    for (int i = n; i-- > 0;) {
        const auto& s = prog[i];
        live[i] = (live[i + 1] & ~reg_bit(s.d)) | reg_bit(s.i) | reg_bit(s.j);
    }

    producer.fill(-1);
    r.fill(0);
    for (size_t k = 0; k < p.starts.size(); ++k) r[k] = p.starts[k];

    OneStepBank direct;
    std::vector<bool> gone(n, false);
    for (int i = 0; i < n; ++i) {
        const auto& s = prog[i];
        i64 v = apply_op(s.op, r[s.i], r[s.j], p.limit);
        if (static_cast<size_t>(i) >= cursor) {
            std::vector<int> removed{i};
            for (size_t k = 0; k < removed.size() && removed.size() < 16; ++k) {
                int a = parents[removed[k]][0], b = parents[removed[k]][1];
                if (a >= 0 && uses[a] == 1) removed.push_back(a);
                if (b >= 0 && b != a && uses[b] == 1) removed.push_back(b);
            }
            if (removed.size() >= 2) {
                std::array<i64, kNumRegs> allowed = r;
                for (int nd : removed) gone[nd] = true;
                for (int d = 0; d < p.registers; ++d) {
                    if (producer[d] >= 0 && gone[producer[d]]) allowed[d] = 0;
                }
                while (removed.size() >= 2) {
                    direct.build(allowed, p.registers, p.limit);
                    std::vector<Instr> patch;
                    if (find_shorter_window(v, s.d, live[i + 1], allowed, p.registers, p.limit,
                                            direct, static_cast<int>(removed.size()) - 1, patch)) {
                        std::vector<Instr> q;
                        q.reserve(n - removed.size() + patch.size());
                        for (int j = 0; j < n; ++j) {
                            if (!gone[j]) q.push_back(prog[j]);
                            if (j == i) q.insert(q.end(), patch.begin(), patch.end());
                        }
                        cursor = static_cast<size_t>(i + 1) - removed.size() + patch.size();
                        return q;
                    }
                    int restored = removed.back();
                    removed.pop_back();
                    gone[restored] = false;
                    int d = prog[restored].d;
                    if (producer[d] == restored) allowed[d] = r[d];
                }
                for (int nd : removed) gone[nd] = false;
            }
        }
        r[s.d] = v;
        producer[s.d] = i;
    }
    cursor = static_cast<size_t>(n);
    return prog;
}

void dead_code_eliminate_prog(const Puzzle& p, std::vector<Instr>& prog) {
    std::unordered_set<i64> starts_set(p.starts.begin(), p.starts.end());
    std::vector<i64> targets = p.targets;
    std::sort(targets.begin(), targets.end());
    targets.erase(std::unique(targets.begin(), targets.end()), targets.end());

    bool changed = true;
    while (changed) {
        changed = false;
        std::array<i64, kNumRegs> regs{};
        for (size_t k = 0; k < p.starts.size(); ++k) regs[k] = p.starts[k];
        std::unordered_map<i64, int> first_cover;
        for (i64 s : p.starts) first_cover[s] = -1;
        std::vector<i64> step_val(prog.size(), 0);
        for (size_t t = 0; t < prog.size(); ++t) {
            i64 iv = apply_op(prog[t].op, regs[prog[t].i], regs[prog[t].j], p.limit);
            regs[prog[t].d] = iv;
            step_val[t] = iv;
            if (std::binary_search(targets.begin(), targets.end(), iv) && !first_cover.count(iv)) {
                first_cover[iv] = static_cast<int>(t);
            }
        }
        std::array<bool, kNumRegs> reg_live{};
        std::vector<bool> keep(prog.size(), false);
        for (int t = static_cast<int>(prog.size()) - 1; t >= 0; --t) {
            const auto& ins = prog[t];
            bool cov = first_cover.count(step_val[t]) && first_cover[step_val[t]] == t;
            if (reg_live[ins.d] || cov) {
                keep[t] = true;
                reg_live[ins.d] = false;
                reg_live[ins.i] = true;
                reg_live[ins.j] = true;
            }
        }
        std::vector<Instr> next;
        next.reserve(prog.size());
        for (size_t t = 0; t < prog.size(); ++t) {
            if (keep[t]) next.push_back(prog[t]);
            else changed = true;
        }
        if (changed) prog.swap(next);
    }
}

void elide_helpers_pass(const Puzzle& p, std::vector<Instr>& prog, int max_rounds = 6) {
    if (prog.size() <= 2) return;
    std::unordered_set<i64> required(p.targets.begin(), p.targets.end());
    for (i64 s : p.starts) required.erase(s);

    for (int round = 0; round < max_rounds; ++round) {
        const int n = static_cast<int>(prog.size());
        std::vector<std::array<i64, kNumRegs>> trace(n + 1);
        trace[0].fill(0);
        for (size_t k = 0; k < p.starts.size(); ++k) trace[0][k] = p.starts[k];

        std::vector<i64> writes(n, 0);
        std::vector<u64> live(n + 1, 0);
        std::unordered_map<i64, int> counts;
        counts.reserve(required.size() * 2 + 4);

        for (int i = 0; i < n; ++i) {
            trace[i + 1] = trace[i];
            const auto& op = prog[i];
            i64 val = apply_op(op.op, trace[i + 1][op.i], trace[i + 1][op.j], p.limit);
            trace[i + 1][op.d] = val;
            writes[i] = val;
            if (required.count(val)) ++counts[val];
        }
        for (int i = n - 1; i >= 0; --i) {
            const auto& op = prog[i];
            live[i] = (live[i + 1] & ~reg_bit(op.d)) | reg_bit(op.i) | reg_bit(op.j);
        }

        bool accepted = false;
        for (int begin = n - 1; begin >= 0; --begin) {
            auto tc = counts.find(writes[begin]);
            if (tc != counts.end() && tc->second <= 1) continue;

            std::array<i64, kNumRegs> regs = trace[begin];
            std::unordered_map<i64, int> skipped;
            if (tc != counts.end()) ++skipped[writes[begin]];

            std::vector<Instr> replacement;
            u64 changed = (regs[prog[begin].d] == writes[begin]) ? 0ULL : reg_bit(prog[begin].d);
            int stop = begin + 1;
            bool legal = true;
            for (; stop < n && (changed & live[stop]); ++stop) {
                Instr op = prog[stop];
                i64 res = apply_op(op.op, regs[op.i], regs[op.j], p.limit);
                if (res == writes[stop] ||
                    one_step_regs(regs, p.registers, writes[stop], p.limit, op.d, op)) {
                    i64 wv = apply_op(op.op, regs[op.i], regs[op.j], p.limit);
                    if (wv <= 0) {
                        legal = false;
                        break;
                    }
                    regs[op.d] = wv;
                    replacement.push_back(op);
                } else {
                    if (required.count(writes[stop]) && ++skipped[writes[stop]] >= counts[writes[stop]]) {
                        legal = false;
                        break;
                    }
                }
                u64 bit = reg_bit(op.d);
                if (regs[op.d] == writes[stop]) changed &= ~bit;
                else changed |= bit;
            }
            if (!legal) continue;

            std::vector<Instr> next;
            next.reserve(static_cast<size_t>(begin) + replacement.size() + static_cast<size_t>(n - stop));
            next.insert(next.end(), prog.begin(), prog.begin() + begin);
            next.insert(next.end(), replacement.begin(), replacement.end());
            next.insert(next.end(), prog.begin() + stop, prog.end());
            if (next.size() < prog.size() && verify_program(p, next)) {
                prog = std::move(next);
                accepted = true;
                break;
            }
        }
        if (!accepted) break;
    }
}

void window_and_cut_sweep(const Puzzle& p, std::vector<Instr>& best) {
    if (best.size() <= 2) return;
    std::vector<Instr> cur = best;
    dead_code_eliminate_prog(p, cur);
    elide_helpers_pass(p, cur);
    for (int pass = 0; pass < 3; ++pass) {
        auto nxt = window_sweep_once(p, cur);
        if (nxt.size() >= cur.size()) break;
        if (verify_program(p, nxt)) cur.swap(nxt);
        else break;
    }
    for (int pass = 0; pass < 2; ++pass) {
        size_t cursor = 0, old_sz = cur.size();
        while (cursor < cur.size()) {
            auto nxt = cut_expression_once(p, cur, cursor);
            if (nxt.size() < cur.size() && verify_program(p, nxt)) cur.swap(nxt);
        }
        if (cur.size() == old_sz) break;
    }
    elide_helpers_pass(p, cur);
    dead_code_eliminate_prog(p, cur);
    if (cur.size() < best.size() && verify_program(p, cur)) best = std::move(cur);
}

// --- 64-bit Deterministic Miller-Rabin + Pollard-Rho Divisor Enumeration ---

inline u64 mul_mod64(u64 a, u64 b, u64 m) {
    return static_cast<u64>(static_cast<unsigned __int128>(a) * b % m);
}

u64 pow_mod64(u64 a, u64 d, u64 m) {
    u64 r = 1;
    while (d) {
        if (d & 1ULL) r = mul_mod64(r, a, m);
        a = mul_mod64(a, a, m);
        d >>= 1;
    }
    return r;
}

bool is_prime64(u64 n) {
    if (n < 2) return false;
    for (u64 p : {2ULL, 3ULL, 5ULL, 7ULL, 11ULL, 13ULL, 17ULL, 19ULL, 23ULL, 29ULL, 31ULL, 37ULL}) {
        if (n == p) return true;
        if (n % p == 0) return false;
    }
    u64 d = n - 1;
    int s = __builtin_ctzll(d);
    d >>= s;
    for (u64 a : {2ULL, 325ULL, 9375ULL, 28178ULL, 450775ULL, 9780504ULL, 1795265022ULL}) {
        if (a % n == 0) continue;
        u64 x = pow_mod64(a, d, n);
        if (x == 1 || x == n - 1) continue;
        bool comp = true;
        for (int r = 1; r < s; ++r) {
            x = mul_mod64(x, x, n);
            if (x == n - 1) { comp = false; break; }
        }
        if (comp) return false;
    }
    return true;
}

u64 pollard_rho64(u64 n) {
    if ((n & 1ULL) == 0) return 2;
    for (u64 c = 1; c < 64; ++c) {
        auto f = [&](u64 x) { return (mul_mod64(x, x, n) + c) % n; };
        u64 x = 2, y = 2, d = 1;
        int iters = 0;
        while (d == 1 && ++iters < 60000) {
            x = f(x);
            y = f(f(y));
            u64 diff = (x > y) ? (x - y) : (y - x);
            d = std::gcd(diff, n);
        }
        if (d > 1 && d < n) return d;
    }
    return n;
}

void factor_rec64(u64 n, std::map<u64, int>& pf) {
    if (n <= 1) return;
    if (is_prime64(n)) {
        pf[n]++;
        return;
    }
    u64 d = pollard_rho64(n);
    if (d == n) {
        pf[n]++;
        return;
    }
    factor_rec64(d, pf);
    factor_rec64(n / d, pf);
}

void get_divisors64(u64 n, std::vector<u64>& divs) {
    divs.clear();
    std::map<u64, int> pf;
    for (u64 p : {2ULL, 3ULL, 5ULL, 7ULL, 11ULL, 13ULL, 17ULL, 19ULL, 23ULL, 29ULL, 31ULL, 37ULL, 41ULL, 43ULL, 47ULL}) {
        while (n % p == 0) {
            pf[p]++;
            n /= p;
        }
    }
    if (n > 1) factor_rec64(n, pf);
    divs.push_back(1);
    for (const auto& kv : pf) {
        size_t sz = divs.size();
        u64 cur = 1;
        for (int e = 1; e <= kv.second; ++e) {
            cur *= kv.first;
            for (size_t i = 0; i < sz; ++i) {
                if (divs.size() < 256) divs.push_back(divs[i] * cur);
            }
        }
    }
}

// --- Stage 2 (Mode 2, Pass 2): Acyclic Peephole, Shared Helpers, & Pollard-Rho Divisor Cuts ---

struct PeepDagState {
    std::vector<i64> nodes;
    std::unordered_map<i64, int> nid;
    std::vector<uint8_t> is_root;
    std::vector<int> cur_a, cur_b, refs;
    std::vector<std::array<u64, 8>> dep_mask;
    std::vector<int> seen_stamp;
    std::vector<int> bfs_stk;
    int M = 0;
    int active_count = 0;
    int cur_stamp = 0;
    bool use_bitmask = false;

    void init(const Puzzle& p,
              const std::unordered_set<i64>& starts_set,
              const std::vector<i64>& req_targets,
              const std::unordered_map<i64, DagDef>& defs,
              const std::vector<i64>& order) {
        nodes.clear();
        nid.clear();
        nodes.reserve(p.starts.size() + order.size());
        nid.reserve((p.starts.size() + order.size()) * 2 + 8);
        for (i64 s : p.starts) {
            if (!nid.count(s)) {
                nid[s] = static_cast<int>(nodes.size());
                nodes.push_back(s);
            }
        }
        for (i64 v : order) {
            if (!nid.count(v)) {
                nid[v] = static_cast<int>(nodes.size());
                nodes.push_back(v);
            }
        }
        M = static_cast<int>(nodes.size());
        is_root.assign(M, 0);
        cur_a.assign(M, -1);
        cur_b.assign(M, -1);
        refs.assign(M, 0);
        active_count = 0;
        for (int i = 0; i < M; ++i) {
            i64 v = nodes[i];
            if (starts_set.count(v)) {
                is_root[i] = 1;
            } else {
                const auto& d = defs.at(v);
                cur_a[i] = nid.at(d.a);
                cur_b[i] = nid.at(d.b);
                ++active_count;
            }
        }
        for (i64 t : req_targets) {
            refs[nid.at(t)]++;
        }
        for (int i = 0; i < M; ++i) {
            if (!is_root[i]) {
                refs[cur_a[i]]++;
                if (cur_b[i] != cur_a[i]) refs[cur_b[i]]++;
            }
        }
        use_bitmask = (M <= 512);
        if (use_bitmask) {
            dep_mask.assign(M, {});
            for (int i = 0; i < M; ++i) {
                if (!is_root[i]) {
                    int ia = cur_a[i], ib = cur_b[i];
                    for (int w = 0; w < 8; ++w) dep_mask[i][w] = dep_mask[ia][w] | dep_mask[ib][w];
                    dep_mask[i][ia >> 6] |= (1ULL << (ia & 63));
                    dep_mask[i][ib >> 6] |= (1ULL << (ib & 63));
                }
            }
        }
        seen_stamp.assign(M, 0);
        cur_stamp = 0;
        bfs_stk.reserve(64);
    }

    bool depends_on(int iu, int iv) {
        if (iu == iv) return true;
        if (use_bitmask) return ((dep_mask[iu][iv >> 6] >> (iv & 63)) & 1ULL) != 0;
        ++cur_stamp;
        bfs_stk.clear();
        bfs_stk.push_back(iu);
        while (!bfs_stk.empty()) {
            int x = bfs_stk.back();
            bfs_stk.pop_back();
            if (x == iv) return true;
            if (is_root[x] || seen_stamp[x] == cur_stamp) continue;
            seen_stamp[x] = cur_stamp;
            bfs_stk.push_back(cur_a[x]);
            bfs_stk.push_back(cur_b[x]);
        }
        return false;
    }

    void adjust(int u, int dir) {
        int before = refs[u];
        refs[u] += dir;
        if (is_root[u]) return;
        if (dir > 0 && before == 0) ++active_count;
        else if (dir < 0 && refs[u] == 0) --active_count;
        if (before != 0 && refs[u] != 0) return;
        adjust(cur_a[u], dir);
        if (cur_b[u] != cur_a[u]) adjust(cur_b[u], dir);
    }

    int added_cost(const int* roots_in, int nr, int bound) {
        ++cur_stamp;
        int cnt = 0;
        bfs_stk.clear();
        for (int ri = 0; ri < nr; ++ri) bfs_stk.push_back(roots_in[ri]);
        while (!bfs_stk.empty()) {
            int x = bfs_stk.back();
            bfs_stk.pop_back();
            if (is_root[x] || refs[x] > 0 || seen_stamp[x] == cur_stamp) continue;
            seen_stamp[x] = cur_stamp;
            if (++cnt >= bound) return cnt;
            bfs_stk.push_back(cur_a[x]);
            bfs_stk.push_back(cur_b[x]);
        }
        return cnt;
    }

    void fill_pair_table(i64 limit, FlatPairTable& pt) const {
        pt.clear();
        for (int i = 0; i < M; ++i) {
            i64 a = nodes[i];
            for (int j = 0; j <= i; ++j) {
                i64 b = nodes[j];
                if (a <= limit - b) {
                    pt.add(a + b, static_cast<uint16_t>(i), static_cast<uint16_t>(j), OP_ADD);
                }
                if (a != b) {
                    pt.add(a > b ? a - b : b - a,
                           static_cast<uint16_t>(a > b ? i : j),
                           static_cast<uint16_t>(a > b ? j : i), OP_SUB);
                }
                i128 prod = static_cast<i128>(a) * b;
                if (prod <= limit) {
                    pt.add(static_cast<i64>(prod), static_cast<uint16_t>(i), static_cast<uint16_t>(j), OP_MUL);
                }
                if (a >= b && b > 0 && a % b == 0) {
                    pt.add(a / b, static_cast<uint16_t>(i), static_cast<uint16_t>(j), OP_DIV);
                }
                if (b > a && a > 0 && b % a == 0) {
                    pt.add(b / a, static_cast<uint16_t>(j), static_cast<uint16_t>(i), OP_DIV);
                }
            }
        }
    }
};

void dag_peephole_and_cofactor(const Puzzle& p,
                               const DagGraph& init_dag,
                               std::vector<Instr>& best,
                               WorkerScratch& ws) {
    if (init_dag.defs.empty()) return;
    std::unordered_set<i64> starts_set(p.starts.begin(), p.starts.end());
    std::vector<i64> req_targets;
    for (i64 t : p.targets) {
        if (!starts_set.count(t)) req_targets.push_back(t);
    }
    std::sort(req_targets.begin(), req_targets.end());
    req_targets.erase(std::unique(req_targets.begin(), req_targets.end()), req_targets.end());

    std::unordered_map<i64, DagDef> defs = init_dag.defs;
    std::vector<i64> order = init_dag.order;

    auto rebuild_needed = [&](std::unordered_map<i64, DagDef>& dmap, std::vector<i64>& ord) {
        std::unordered_set<i64> keep;
        std::vector<i64> stk = req_targets;
        while (!stk.empty()) {
            i64 x = stk.back();
            stk.pop_back();
            if (starts_set.count(x) || keep.count(x)) continue;
            keep.insert(x);
            auto it = dmap.find(x);
            if (it != dmap.end()) {
                stk.push_back(it->second.a);
                stk.push_back(it->second.b);
            }
        }
        std::unordered_map<i64, DagDef> next_defs;
        next_defs.reserve(keep.size() + 4);
        for (i64 v : keep) next_defs[v] = dmap.at(v);
        dmap.swap(next_defs);
        ord = topo_from_targets(starts_set, dmap, req_targets);
    };

    PeepDagState st;

    // Pass 2a: O(1)-refcount Acyclic 1/2-op and 2-helper peephole over existing graph nodes
    for (int round = 0; round < 6; ++round) {
        bool changed = false;
        st.init(p, starts_set, req_targets, defs, order);
        st.fill_pair_table(p.limit, ws.pair_table);

        std::vector<i64> rev_order = order;
        std::reverse(rev_order.begin(), rev_order.end());
        for (i64 v : rev_order) {
            auto nit = st.nid.find(v);
            if (nit == st.nid.end()) continue;
            int iv = nit->second;
            if (st.is_root[iv] || st.refs[iv] == 0) continue;

            int before_act = st.active_count;
            int old_a = st.cur_a[iv], old_b = st.cur_b[iv];
            st.adjust(old_a, -1);
            if (old_b != old_a) st.adjust(old_b, -1);
            int gain_max = before_act - st.active_count;

            if (gain_max <= 0) {
                st.adjust(old_a, 1);
                if (old_b != old_a) st.adjust(old_b, 1);
                continue;
            }

            int best_cost = gain_max;
            DagDef best_v_def{};
            i64 add_w = 0, add_w2 = 0;
            DagDef best_w_def{}, best_w2_def{};
            bool found = false;

            for (int ia = 0; ia < st.M; ++ia) {
                i64 a = st.nodes[ia];
                if (ia == iv || st.depends_on(ia, iv)) continue;
                auto try_1op = [&](Op op, i64 x, i64 y) {
                    if (x <= 0 || y <= 0 || x == v || y == v) return;
                    auto ix_it = st.nid.find(x), iy_it = st.nid.find(y);
                    if (ix_it == st.nid.end() || iy_it == st.nid.end()) return;
                    int ix = ix_it->second, iy = iy_it->second;
                    if (st.depends_on(ix, iv) || st.depends_on(iy, iv)) return;
                    if (ix == old_a && iy == old_b && op == defs[v].op) return;
                    int rarr[2] = {ix, iy};
                    int ac = st.added_cost(rarr, (ix == iy ? 1 : 2), best_cost);
                    if (ac < best_cost) {
                        best_cost = ac;
                        best_v_def = {op, x, y};
                        add_w = 0;
                        add_w2 = 0;
                        found = true;
                    }
                };
                if (v > a) try_1op(OP_ADD, a, v - a);
                if (a > v) try_1op(OP_SUB, a, a - v);
                if (v <= p.limit - a) try_1op(OP_SUB, v + a, a);
                if (a > 0 && v % a == 0) try_1op(OP_MUL, a, v / a);
                if (static_cast<i128>(v) * a <= p.limit) try_1op(OP_DIV, v * a, a);
            }

            if (best_cost >= 2) {
                int tried2 = 0;
                for (int ic = 0; ic < st.M; ++ic) {
                    i64 c = st.nodes[ic];
                    if (ic == iv || st.depends_on(ic, iv)) continue;
                    WBackStep bs[6];
                    int nb = gen_win_inverses(v, c, p.limit, bs);
                    for (int ci = 0; ci < nb; ++ci) {
                        i64 w = bs[ci].u;
                        if (w <= 0 || st.nid.count(w)) continue;
                        const auto* pb = ws.pair_table.find(w);
                        if (!pb) continue;
                        for (uint8_t ri = 0; ri < pb->cnt; ++ri) {
                            const auto& pd = pb->recs[ri];
                            if (pd.a == iv || pd.b == iv ||
                                st.depends_on(pd.a, iv) || st.depends_on(pd.b, iv)) {
                                continue;
                            }
                            int rarr[3] = {pd.a, pd.b, ic};
                            int ac = 1 + st.added_cost(rarr, 3, best_cost - 1);
                            if (ac < best_cost) {
                                best_cost = ac;
                                best_v_def = bs[ci].rev ? DagDef{bs[ci].op, c, w} : DagDef{bs[ci].op, w, c};
                                add_w = w;
                                best_w_def = {pd.op, st.nodes[pd.a], st.nodes[pd.b]};
                                add_w2 = 0;
                                found = true;
                            }
                        }
                        if (++tried2 > 160) break;
                    }
                    if (tried2 > 160) break;
                }
            }

            // 2-helper single-node rewrite (v = h1 op h2) for high-saving removals
            if (best_cost >= 3 && st.M <= 260) {
                size_t scanned = 0;
                for (i64 y : ws.pair_table.inserted_keys) {
                    if (st.nid.count(y)) continue;
                    if (++scanned > 2500) break;
                    const auto* yb = ws.pair_table.find(y);
                    if (!yb) continue;
                    int r_pick = -1;
                    for (uint8_t ri = 0; ri < yb->cnt; ++ri) {
                        const auto& rp = yb->recs[ri];
                        if (rp.a != iv && rp.b != iv &&
                            !st.depends_on(rp.a, iv) && !st.depends_on(rp.b, iv)) {
                            r_pick = ri;
                            break;
                        }
                    }
                    if (r_pick < 0) continue;
                    const auto& rp = yb->recs[r_pick];
                    WBackStep bs[6];
                    int nb = gen_win_inverses(v, y, p.limit, bs);
                    for (int k = 0; k < nb; ++k) {
                        i64 x = bs[k].u;
                        if (x == y || st.nid.count(x)) continue;
                        const auto* xb = ws.pair_table.find(x);
                        if (!xb) continue;
                        for (uint8_t li = 0; li < xb->cnt; ++li) {
                            const auto& lp = xb->recs[li];
                            if (lp.a == iv || lp.b == iv ||
                                st.depends_on(lp.a, iv) || st.depends_on(lp.b, iv)) {
                                continue;
                            }
                            int rarr[4] = {lp.a, lp.b, rp.a, rp.b};
                            int ac = 2 + st.added_cost(rarr, 4, best_cost - 2);
                            if (ac < best_cost) {
                                best_cost = ac;
                                best_v_def = bs[k].rev ? DagDef{bs[k].op, y, x} : DagDef{bs[k].op, x, y};
                                add_w = x;
                                best_w_def = {lp.op, st.nodes[lp.a], st.nodes[lp.b]};
                                add_w2 = y;
                                best_w2_def = {rp.op, st.nodes[rp.a], st.nodes[rp.b]};
                                found = true;
                                break;
                            }
                        }
                    }
                    if (best_cost <= 2) break;
                }
            }

            st.adjust(old_a, 1);
            if (old_b != old_a) st.adjust(old_b, 1);

            if (found) {
                if (add_w > 0) defs[add_w] = best_w_def;
                if (add_w2 > 0) defs[add_w2] = best_w2_def;
                defs[v] = best_v_def;
                rebuild_needed(defs, order);
                changed = true;
                break;
            }
        }
        if (!changed) break;
    }

    // Pass 2a-bis: Shared helper introduction (1 new helper rewiring 2 active nodes)
    for (int round = 0; round < 4; ++round) {
        if (p.starts.size() + order.size() > 512) break;
        st.init(p, starts_set, req_targets, defs, order);
        st.fill_pair_table(p.limit, ws.pair_table);

        struct ShareLink {
            i64 helper_val;
            int id;
            int operand;
            Op op;
            bool helper_first;
        };
        std::vector<ShareLink> links;
        links.reserve(1024);

        for (int id = 0; id < st.M; ++id) {
            if (st.is_root[id] || st.refs[id] == 0) continue;
            if (st.refs[st.cur_a[id]] > 2 && st.refs[st.cur_b[id]] > 2) continue;
            i64 root_val = st.nodes[id];
            for (int b = 0; b < st.M; ++b) {
                if (st.depends_on(b, id)) continue;
                WBackStep bs[6];
                int nb = gen_win_inverses(root_val, st.nodes[b], p.limit, bs);
                for (int k = 0; k < nb; ++k) {
                    i64 hv = bs[k].u;
                    if (st.nid.count(hv) || !ws.pair_table.find(hv)) continue;
                    links.push_back({hv, id, b, bs[k].op, !bs[k].rev});
                }
            }
        }

        if (links.size() < 2) break;
        std::sort(links.begin(), links.end(), [](const ShareLink& a, const ShareLink& b) {
            return std::tie(a.helper_val, a.id, a.operand, a.op, a.helper_first) <
                   std::tie(b.helper_val, b.id, b.operand, b.op, b.helper_first);
        });

        int best_saving = 0;
        i64 best_h = 0;
        FlatPairTable::PairRec best_rp{};
        ShareLink best_l1{}, best_l2{};

        size_t pos = 0;
        while (pos < links.size()) {
            size_t end = pos + 1;
            while (end < links.size() && links[end].helper_val == links[pos].helper_val) ++end;
            if (end - pos >= 2) {
                i64 hv = links[pos].helper_val;
                const auto* hb = ws.pair_table.find(hv);
                size_t cap_end = std::min(end, pos + 20);
                for (uint8_t ri = 0; hb && ri < hb->cnt; ++ri) {
                    const auto& rp = hb->recs[ri];
                    for (size_t i = pos; i < cap_end; ++i) {
                        const auto& l1 = links[i];
                        int u = l1.id;
                        if (st.depends_on(rp.a, u) || st.depends_on(rp.b, u)) continue;
                        for (size_t j = i + 1; j < cap_end; ++j) {
                            const auto& l2 = links[j];
                            int w = l2.id;
                            if (u == w || st.depends_on(u, w) || st.depends_on(w, u)) continue;
                            if (st.depends_on(rp.a, w) || st.depends_on(rp.b, w)) continue;
                            if (st.depends_on(l1.operand, w) || st.depends_on(l2.operand, u)) continue;

                            int before = st.active_count;
                            st.adjust(rp.a, 1);
                            if (rp.b != rp.a) st.adjust(rp.b, 1);
                            st.adjust(l1.operand, 1);
                            st.adjust(l2.operand, 1);
                            st.adjust(st.cur_a[u], -1);
                            if (st.cur_b[u] != st.cur_a[u]) st.adjust(st.cur_b[u], -1);
                            st.adjust(st.cur_a[w], -1);
                            if (st.cur_b[w] != st.cur_a[w]) st.adjust(st.cur_b[w], -1);

                            int saving = before - st.active_count - 1;
                            if (saving > best_saving) {
                                best_saving = saving;
                                best_h = hv;
                                best_rp = rp;
                                best_l1 = l1;
                                best_l2 = l2;
                            }

                            if (st.cur_b[w] != st.cur_a[w]) st.adjust(st.cur_b[w], 1);
                            st.adjust(st.cur_a[w], 1);
                            if (st.cur_b[u] != st.cur_a[u]) st.adjust(st.cur_b[u], 1);
                            st.adjust(st.cur_a[u], 1);
                            st.adjust(l2.operand, -1);
                            st.adjust(l1.operand, -1);
                            if (rp.b != rp.a) st.adjust(rp.b, -1);
                            st.adjust(rp.a, -1);
                        }
                    }
                }
            }
            pos = end;
        }

        if (best_saving <= 0) break;
        defs[best_h] = {best_rp.op, st.nodes[best_rp.a], st.nodes[best_rp.b]};
        defs[st.nodes[best_l1.id]] = best_l1.helper_first
            ? DagDef{best_l1.op, best_h, st.nodes[best_l1.operand]}
            : DagDef{best_l1.op, st.nodes[best_l1.operand], best_h};
        defs[st.nodes[best_l2.id]] = best_l2.helper_first
            ? DagDef{best_l2.op, best_h, st.nodes[best_l2.operand]}
            : DagDef{best_l2.op, st.nodes[best_l2.operand], best_h};
        rebuild_needed(defs, order);
    }

    // Pass 2b: Fast Pollard-Rho divisor cuts ONLY over starts + small constants <= 32 on cuts with budget >= 4
    std::vector<u64> divs;
    for (int round = 0; round < 2; ++round) {
        bool changed = false;
        st.init(p, starts_set, req_targets, defs, order);
        st.fill_pair_table(p.limit, ws.pair_table);

        std::vector<uint8_t> gone(st.M, 0), is_free(st.M, 0);
        std::vector<int> lost(st.M, 0);
        for (i64 v : order) {
            int iv = st.nid.at(v);
            std::fill(gone.begin(), gone.end(), 0);
            std::fill(lost.begin(), lost.end(), 0);
            gone[iv] = 1;
            int budget = 1;
            std::vector<int> stk{iv};
            while (!stk.empty()) {
                int cur = stk.back();
                stk.pop_back();
                if (st.is_root[cur]) continue;
                int ps[2] = {st.cur_a[cur], st.cur_b[cur]};
                int np = (ps[0] == ps[1]) ? 1 : 2;
                for (int pi = 0; pi < np; ++pi) {
                    int u = ps[pi];
                    if (!st.is_root[u] && ++lost[u] == st.refs[u] && !gone[u]) {
                        gone[u] = 1;
                        ++budget;
                        stk.push_back(u);
                    }
                }
            }
            if (budget < 4) continue;

            std::fill(is_free.begin(), is_free.end(), 0);
            for (int i = 0; i < st.M; ++i) {
                if (st.is_root[i]) {
                    is_free[i] = 1;
                } else if (!gone[i] && !st.depends_on(i, iv)) {
                    is_free[i] = 1;
                }
            }

            auto free_reach = [&](i64 val, int& out_cost, DagDef& out_def) -> bool {
                auto nit = st.nid.find(val);
                if (nit != st.nid.end() && is_free[nit->second]) {
                    out_cost = 0;
                    return true;
                }
                const auto* pb = ws.pair_table.find(val);
                if (!pb) return false;
                for (uint8_t pi = 0; pi < pb->cnt; ++pi) {
                    const auto& pr = pb->recs[pi];
                    if (is_free[pr.a] && is_free[pr.b]) {
                        out_cost = 1;
                        out_def = {pr.op, st.nodes[pr.a], st.nodes[pr.b]};
                        return true;
                    }
                }
                return false;
            };

            std::vector<i64> d_cands;
            for (i64 s : p.starts) {
                if (std::find(d_cands.begin(), d_cands.end(), s) == d_cands.end()) d_cands.push_back(s);
            }
            for (i64 c : {1,2,3,4,5,6,7,8,9,10,12,16,24,32}) {
                auto cit = st.nid.find(c);
                if (cit != st.nid.end() && is_free[cit->second] &&
                    std::find(d_cands.begin(), d_cands.end(), c) == d_cands.end()) {
                    d_cands.push_back(c);
                }
                if (d_cands.size() >= 16) break;
            }

            int best_cost = budget;
            std::unordered_map<i64, DagDef> best_edits;

            for (i64 d : d_cands) {
                for (int mode = 0; mode < 3; ++mode) {
                    i64 prod = (mode == 0) ? (v > d ? v - d : 0)
                             : (mode == 1) ? (v <= p.limit - d ? v + d : 0)
                                           : (d > v ? d - v : 0);
                    if (prod < 4) continue;
                    get_divisors64(static_cast<u64>(prod), divs);
                    for (u64 uf : divs) {
                        i64 f = static_cast<i64>(uf);
                        i64 q = prod / f;
                        if (f <= 1 || q <= 1 || f > q) continue;
                        int cf = 0, cq = 0;
                        DagDef df{}, dq{};
                        if (!free_reach(f, cf, df) || !free_reach(q, cq, dq)) continue;
                        int tot = 2 + cf + (f == q ? 0 : cq);
                        if (tot < best_cost) {
                            best_cost = tot;
                            best_edits.clear();
                            if (cf == 1) best_edits[f] = df;
                            if (cq == 1) best_edits[q] = dq;
                            best_edits[prod] = {OP_MUL, f, q};
                            if (mode == 0) best_edits[v] = {OP_ADD, prod, d};
                            else if (mode == 1) best_edits[v] = {OP_SUB, prod, d};
                            else best_edits[v] = {OP_SUB, d, prod};
                        }
                    }
                }
            }

            if (!best_edits.empty()) {
                for (const auto& kv : best_edits) defs[kv.first] = kv.second;
                rebuild_needed(defs, order);
                changed = true;
                break;
            }
        }
        if (!changed) break;
    }

    if (defs.size() < best.size()) {
        DagGraph final_dag{std::move(defs), std::move(order)};
        dag_reallocate(p, final_dag, best);
    }
}

// --- Stage 4 (Mode 2, Pass 4): Bounded Single-Target Reverse Quotient-Remainder Search ---

std::vector<Dict48::ValOp> reverse_rebuild_bounded(i64 target, i64 lim, const Dict48& bank,
                                                   int width, int budget) {
    if (budget <= 0) return {};
    if (bank.cost(target) < budget) {
        std::vector<Dict48::ValOp> ops;
        bank.emit_val(target, ops);
        return ops;
    }
    struct Jump { i64 q, m, r, prod, num; };
    struct Node { i64 val; int parent; Jump jmp; };
    std::vector<Node> nodes{{target, -1, {}}};
    int max_layers = std::min(budget, 12);
    std::vector<std::vector<int>> layers(max_layers + 1);
    layers[0].push_back(0);
    std::unordered_map<i64, int> vis{{target, 0}};
    int best = std::min(budget, max_layers + 2);
    int fin = -1;
    std::vector<Dict48::ValOp> base;
    std::vector<u64> divs;
    int expansions = 0;
    constexpr int kMaxExpansions = 150;

    for (int c = 0; c < best && c < max_layers && expansions < kMaxExpansions; ++c) {
        auto& lay = layers[c];
        if (static_cast<int>(lay.size()) > width) {
            std::nth_element(lay.begin(), lay.begin() + width, lay.end(),
                             [&](int i, int j) { return nodes[i].val < nodes[j].val; });
            lay.resize(width);
        }
        for (int id : lay) {
            if (expansions >= kMaxExpansions) break;
            ++expansions;
            i64 n = nodes[id].val;
            if (vis[n] < c) continue;
            int bc = bank.cost(n);
            if (bc < 99 && c + bc < best) {
                best = c + bc;
                fin = id;
                base.clear();
                bank.emit_val(n, base);
                continue;
            }
            // Root-only Pollard-Rho factor_offsets over v0 (<= 48 live register values, NEVER 2500!)
            if (id == 0 && budget >= 4 && c + 2 < best) {
                for (i64 d : bank.v0) {
                    if (d == n) continue;
                    for (int mode = 0; mode < 3; ++mode) {
                        i64 prod = (mode == 0) ? (n > d ? n - d : 0)
                                 : (mode == 1) ? (n <= lim - d ? n + d : 0)
                                               : (d > n ? d - n : 0);
                        if (prod < 4) continue;
                        get_divisors64(static_cast<u64>(prod), divs);
                        for (u64 uf : divs) {
                            i64 f = static_cast<i64>(uf), q = prod / f;
                            if (f <= 1 || q <= 1 || f > q) continue;
                            int cf = bank.cost(f), cq = bank.cost(q);
                            if (cf >= 99 || cq >= 99) continue;
                            int tot = c + 2 + (f == d ? 0 : cf) + ((q == d || q == f) ? 0 : cq);
                            if (tot < best) {
                                best = tot;
                                fin = id;
                                base.clear();
                                bank.emit_val(f, base);
                                if (q != f) bank.emit_val(q, base);
                                base.push_back({OP_MUL, f, q, prod});
                                if (mode == 0) base.push_back({OP_ADD, prod, d, n});
                                else if (mode == 1) base.push_back({OP_SUB, prod, d, n});
                                else base.push_back({OP_SUB, d, prod, n});
                            }
                        }
                    }
                }
            }

            auto join2 = [&](Op op, i64 a, i64 b) {
                int ca = bank.cost(a), cb = bank.cost(b);
                if (ca >= 99 || cb >= 99) return;
                int tot = c + 1 + ca + (a == b ? 0 : cb);
                if (tot < best) {
                    best = tot;
                    fin = id;
                    base.clear();
                    bank.emit_val(a, base);
                    if (b != a) bank.emit_val(b, base);
                    base.push_back({op, a, b, n});
                }
            };
            auto push_q = [&](i64 q, i64 m, i64 r, int fee) {
                if (q <= 1 || q >= n || c + fee >= best) return;
                i64 prod = apply_op(OP_MUL, q, m, lim);
                if (prod <= 0) return;
                int nd = c + fee;
                if (nd > max_layers) return;
                auto [it, ok] = vis.emplace(q, nd);
                if (!ok && it->second <= nd) return;
                it->second = nd;
                int cq = bank.cost(q);
                if (cq < 99) {
                    if (nd + cq < best) {
                        best = nd + cq;
                        fin = static_cast<int>(nodes.size());
                        base.clear();
                        bank.emit_val(q, base);
                        nodes.push_back({q, id, {q, m, r, prod, n}});
                    }
                } else {
                    layers[nd].push_back(static_cast<int>(nodes.size()));
                    nodes.push_back({q, id, {q, m, r, prod, n}});
                }
            };

            for (i64 m : bank.basis) {
                int cm = bank.cost(m);
                if (c + 1 + cm >= best) continue;
                if (n > m) join2(OP_ADD, m, n - m);
                if (n <= lim - m) join2(OP_SUB, n + m, m);
                if (m > n) join2(OP_SUB, m, m - n);
                if (m > n && m % n == 0) join2(OP_DIV, m, m / n);
                if (m <= 1 || m >= n) continue;
                i64 q = n / m, r = n % m;
                int fee = 1 + cm;
                if (r == 0) {
                    join2(OP_MUL, m, q);
                    push_q(q, m, 0, fee);
                } else {
                    int cr = bank.cost(r);
                    if (cr < 99) push_q(q, m, r, fee + 1 + cr);
                    if (m - r <= lim - n) {
                        int cmr = bank.cost(m - r);
                        if (cmr < 99) push_q(q + 1, m, -(m - r), fee + 1 + cmr);
                    }
                    if (q > 2) {
                        int cpr = bank.cost(r + m);
                        if (cpr < 99) push_q(q - 1, m, r + m, fee + 1 + cpr);
                    }
                }
            }
        }
    }
    if (fin < 0) return {};
    for (int i = fin; nodes[i].parent != -1; i = nodes[i].parent) {
        const auto& j = nodes[i].jmp;
        bank.emit_val(j.m, base);
        base.push_back({OP_MUL, j.q, j.m, j.prod});
        if (j.r != 0) {
            i64 ar = std::abs(j.r);
            bank.emit_val(ar, base);
            base.push_back({j.r > 0 ? OP_ADD : OP_SUB, j.prod, ar, j.num});
        }
    }
    return base;
}

std::vector<Instr> retain_targets_stream(const Puzzle& p, const std::vector<Instr>& prog,
                                         const std::unordered_set<i64>& keep,
                                         int old_pos = -1, int* new_pos = nullptr) {
    std::array<i64, kNumRegs> r{};
    for (size_t k = 0; k < p.starts.size(); ++k) r[k] = p.starts[k];
    std::vector<i64> out(prog.size());
    for (size_t i = 0; i < prog.size(); ++i) {
        out[i] = apply_op(prog[i].op, r[prog[i].i], r[prog[i].j], p.limit);
        r[prog[i].d] = out[i];
    }
    auto unseen = keep;
    std::vector<char> first(prog.size(), 0);
    for (size_t i = 0; i < prog.size(); ++i) first[i] = unseen.erase(out[i]) ? 1 : 0;
    u64 live = 0;
    std::vector<Instr> res;
    res.reserve(prog.size());
    for (int i = static_cast<int>(prog.size()) - 1; i >= 0; --i) {
        u64 db = 1ULL << prog[i].d;
        if (first[i] || (live & db)) {
            live = (live & ~db) | (1ULL << prog[i].i) | (1ULL << prog[i].j);
            res.push_back(prog[i]);
            if (new_pos && i < old_pos) ++(*new_pos);
        }
    }
    std::reverse(res.begin(), res.end());
    return res;
}

bool execute_valops_on_regs(std::array<i64, kNumRegs>& reg, int nreg, i64 lim,
                            u64 pinned_mask, const std::vector<Dict48::ValOp>& ops,
                            std::vector<Instr>& prog) {
    std::array<int, kNumRegs> used{};
    for (size_t k = 0; k < ops.size(); ++k) {
        const auto& s = ops[k];
        int ex = -1;
        for (int i = 0; i < nreg; ++i) {
            if (reg[i] == s.out) { ex = i; break; }
        }
        if (ex >= 0) continue;
        int ra = -1, rb = -1;
        for (int i = 0; i < nreg; ++i) {
            if (reg[i] == s.a && ra < 0) ra = i;
            if (reg[i] == s.b && rb < 0) rb = i;
        }
        if (ra < 0 || rb < 0) return false;
        if (apply_op(s.op, reg[ra], reg[rb], lim) != s.out) return false;
        int dest = -1;
        for (int i = 0; i < nreg; ++i) {
            if (reg[i] == 0) { dest = i; break; }
        }
        if (dest < 0) {
            u64 keep = pinned_mask;
            for (size_t j = k + 1; j < ops.size(); ++j) {
                for (int r = 0; r < nreg; ++r) {
                    if (reg[r] == ops[j].a || reg[r] == ops[j].b) keep |= (1ULL << r);
                }
            }
            int oldest = std::numeric_limits<int>::max();
            for (int i = 0; i < nreg; ++i) {
                if (!(keep & (1ULL << i)) && used[i] < oldest) {
                    oldest = used[i];
                    dest = i;
                }
            }
        }
        if (dest < 0) return false;
        prog.push_back({s.op, static_cast<uint8_t>(ra), static_cast<uint8_t>(rb), static_cast<uint8_t>(dest)});
        reg[dest] = s.out;
        used[ra] = used[rb] = used[dest] = static_cast<int>(prog.size());
    }
    return true;
}

void target_rebuild_pass(const Puzzle& p, std::vector<Instr>& best, Dict48& bank) {
    if (best.size() <= 4) return;
    std::unordered_set<i64> starts_set(p.starts.begin(), p.starts.end());
    std::vector<i64> uniq_targets;
    for (i64 t : p.targets) {
        if (!starts_set.count(t)) uniq_targets.push_back(t);
    }
    std::sort(uniq_targets.begin(), uniq_targets.end());
    uniq_targets.erase(std::unique(uniq_targets.begin(), uniq_targets.end()), uniq_targets.end());

    for (int round = 0; round < 3; ++round) {
        std::unordered_set<i64> req(uniq_targets.begin(), uniq_targets.end());
        std::array<i64, kNumRegs> r{};
        for (size_t k = 0; k < p.starts.size(); ++k) r[k] = p.starts[k];
        std::vector<i64> out(best.size());
        for (size_t i = 0; i < best.size(); ++i) {
            out[i] = apply_op(best[i].op, r[best[i].i], r[best[i].j], p.limit);
            r[best[i].d] = out[i];
        }

        struct Trial {
            i64 target;
            std::vector<Instr> prefix;
            int boundary;
            int budget;
        };
        std::vector<Trial> trials;
        trials.reserve(uniq_targets.size());
        for (i64 t : uniq_targets) {
            req.erase(t);
            int pos = static_cast<int>(std::find(out.begin(), out.end(), t) - out.begin());
            int boundary = 0;
            auto pref = retain_targets_stream(p, best, req, pos, &boundary);
            req.insert(t);
            int budget = static_cast<int>(best.size()) - static_cast<int>(pref.size());
            if (budget >= 3) trials.push_back({t, std::move(pref), boundary, budget});
        }
        std::sort(trials.begin(), trials.end(), [](const Trial& a, const Trial& b) {
            if (a.budget != b.budget) return a.budget > b.budget;
            return a.target < b.target;
        });
        if (trials.size() > 12) trials.resize(12);

        bool improved = false;
        for (const auto& tr : trials) {
            int cuts[2] = {tr.boundary, static_cast<int>(tr.prefix.size())};
            int ncuts = (cuts[0] == cuts[1]) ? 1 : 2;
            for (int ci = 0; ci < ncuts; ++ci) {
                int cut = cuts[ci];
                std::array<i64, kNumRegs> reg{};
                for (size_t k = 0; k < p.starts.size(); ++k) reg[k] = p.starts[k];
                std::unordered_set<i64> cov(p.starts.begin(), p.starts.end());
                for (int i = 0; i < cut; ++i) {
                    i64 v = apply_op(tr.prefix[i].op, reg[tr.prefix[i].i], reg[tr.prefix[i].j], p.limit);
                    reg[tr.prefix[i].d] = v;
                    cov.insert(v);
                }
                if (cov.count(tr.target)) {
                    if (tr.prefix.size() < best.size() && verify_program(p, tr.prefix)) {
                        best = tr.prefix;
                        improved = true;
                        break;
                    }
                    continue;
                }
                u64 live = 0;
                for (int j = static_cast<int>(tr.prefix.size()) - 1; j >= cut; --j) {
                    live = (live & ~(1ULL << tr.prefix[j].d)) | (1ULL << tr.prefix[j].i) | (1ULL << tr.prefix[j].j);
                }
                bank.build(reg, p.registers, p.limit);
                auto ops = reverse_rebuild_bounded(tr.target, p.limit, bank, 10, tr.budget);
                if (ops.empty()) continue;

                std::vector<Instr> cand(tr.prefix.begin(), tr.prefix.begin() + cut);
                auto reg_copy = reg;
                if (!execute_valops_on_regs(reg_copy, p.registers, p.limit, live, ops, cand)) continue;
                cand.insert(cand.end(), tr.prefix.begin() + cut, tr.prefix.end());
                cand = retain_targets_stream(p, cand, req);
                if (cand.size() < best.size() && verify_program(p, cand)) {
                    best = std::move(cand);
                    improved = true;
                    break;
                }
            }
            if (improved) break;
        }
        if (!improved) break;
    }
}


inline i64 exact_isqrt64(i64 n) {
    if (n <= 1) return (n == 1) ? 1 : -1;
    i64 r = static_cast<i64>(std::sqrt(static_cast<long double>(n)));
    while (static_cast<i128>(r + 1) * (r + 1) <= n) ++r;
    while (r > 0 && static_cast<i128>(r) * r > n) --r;
    return (static_cast<i128>(r) * r == n) ? r : -1;
}

void dag_deep_chain_and_reversal(const Puzzle& p, std::vector<Instr>& best, WorkerScratch& ws) {
    if (best.size() <= 4) return;
    DagGraph cur_dag = extract_needed_dag(p, best);
    if (cur_dag.defs.empty()) return;

    std::unordered_set<i64> starts_set(p.starts.begin(), p.starts.end());
    std::vector<i64> req_targets;
    for (i64 t : p.targets) {
        if (!starts_set.count(t)) req_targets.push_back(t);
    }
    std::sort(req_targets.begin(), req_targets.end());
    req_targets.erase(std::unique(req_targets.begin(), req_targets.end()), req_targets.end());

    std::unordered_map<i64, DagDef> defs = std::move(cur_dag.defs);
    std::vector<i64> order = std::move(cur_dag.order);

    auto rebuild_needed = [&](std::unordered_map<i64, DagDef>& dmap, std::vector<i64>& ord) {
        std::unordered_set<i64> keep;
        std::vector<i64> stk = req_targets;
        while (!stk.empty()) {
            i64 x = stk.back();
            stk.pop_back();
            if (starts_set.count(x) || keep.count(x)) continue;
            keep.insert(x);
            auto it = dmap.find(x);
            if (it != dmap.end()) {
                stk.push_back(it->second.a);
                stk.push_back(it->second.b);
            }
        }
        std::unordered_map<i64, DagDef> next_defs;
        next_defs.reserve(keep.size() + 4);
        for (i64 v : keep) next_defs[v] = dmap.at(v);
        dmap.swap(next_defs);
        ord = topo_from_targets(starts_set, dmap, req_targets);
    };

    PeepDagState st;

    // Pass 2c: Fast square-peeling & depth-3/4 chain resynthesis
    for (int round = 0; round < 3; ++round) {
        bool changed = false;
        st.init(p, starts_set, req_targets, defs, order);
        st.fill_pair_table(p.limit, ws.pair_table);

        std::vector<uint8_t> gone(st.M, 0), is_free(st.M, 0), is_leaf(st.M, 0);
        std::vector<int> lost(st.M, 0);
        for (i64 v : order) {
            int iv = st.nid.at(v);
            std::fill(gone.begin(), gone.end(), 0);
            std::fill(lost.begin(), lost.end(), 0);
            gone[iv] = 1;
            int budget = 1;
            std::vector<int> stk{iv};
            while (!stk.empty()) {
                int cur = stk.back();
                stk.pop_back();
                if (st.is_root[cur]) continue;
                int ps[2] = {st.cur_a[cur], st.cur_b[cur]};
                int np = (ps[0] == ps[1]) ? 1 : 2;
                for (int pi = 0; pi < np; ++pi) {
                    int u = ps[pi];
                    if (!st.is_root[u] && ++lost[u] == st.refs[u] && !gone[u]) {
                        gone[u] = 1;
                        ++budget;
                        stk.push_back(u);
                    }
                }
            }
            if (budget < 3) continue;

            std::fill(is_free.begin(), is_free.end(), 0);
            std::fill(is_leaf.begin(), is_leaf.end(), 0);
            for (int i = 0; i < st.M; ++i) {
                if (st.is_root[i] || (!gone[i] && !st.depends_on(i, iv))) is_free[i] = 1;
                if (gone[i] && !st.is_root[i]) {
                    if (is_free[st.cur_a[i]]) is_leaf[st.cur_a[i]] = 1;
                    if (is_free[st.cur_b[i]]) is_leaf[st.cur_b[i]] = 1;
                }
            }

            std::vector<int> free_ids;
            free_ids.reserve(st.M);
            for (int i = 0; i < st.M; ++i) {
                if (is_free[i]) free_ids.push_back(i);
            }
            std::stable_sort(free_ids.begin(), free_ids.end(), [&](int a, int b) {
                if (is_leaf[a] != is_leaf[b]) return is_leaf[a] > is_leaf[b];
                if (st.refs[a] != st.refs[b]) return st.refs[a] > st.refs[b];
                return a < b;
            });

            auto can_create = [&](i64 x) -> bool {
                if (x <= 0 || x > p.limit) return false;
                auto it = st.nid.find(x);
                if (it == st.nid.end()) return true;
                return gone[it->second] != 0;
            };
            auto free_reach = [&](i64 val, int& out_cost, DagDef& out_def) -> bool {
                auto nit = st.nid.find(val);
                if (nit != st.nid.end()) {
                    if (is_free[nit->second]) { out_cost = 0; return true; }
                    return false;
                }
                const auto* pb = ws.pair_table.find(val);
                if (!pb) return false;
                for (uint8_t pi = 0; pi < pb->cnt; ++pi) {
                    const auto& pr = pb->recs[pi];
                    if (is_free[pr.a] && is_free[pr.b]) {
                        out_cost = 1;
                        out_def = {pr.op, st.nodes[pr.a], st.nodes[pr.b]};
                        return true;
                    }
                }
                return false;
            };

            int best_cost = budget;
            std::vector<std::pair<i64, DagDef>> best_edits;

            auto try_commit = [&](const std::vector<std::pair<i64, DagDef>>& edits) {
                int tot = static_cast<int>(edits.size());
                if (tot >= best_cost) return;
                for (size_t i = 0; i < edits.size(); ++i) {
                    for (size_t j = i + 1; j < edits.size(); ++j) {
                        if (edits[i].first == edits[j].first) return;
                    }
                }
                best_cost = tot;
                best_edits = edits;
            };

            auto check_square_at = [&](i64 u, const std::vector<std::pair<i64, DagDef>>& tail) {
                int outer = static_cast<int>(tail.size());
                if (outer + 2 >= best_cost || u <= 1) return;
                i64 r = exact_isqrt64(u);
                if (r <= 1) return;
                if (outer > 0 && !can_create(u)) return;
                int cr = 0;
                DagDef dr{};
                if (free_reach(r, cr, dr)) {
                    if (outer + 1 + cr < best_cost) {
                        auto ed = tail;
                        ed.push_back({u, {OP_MUL, r, r}});
                        if (cr == 1) ed.push_back({r, dr});
                        try_commit(ed);
                    }
                    return;
                }
                if (!can_create(r)) return;
                i64 r2 = exact_isqrt64(r);
                if (r2 > 1 && free_reach(r2, cr, dr) && outer + 2 + cr < best_cost) {
                    auto ed = tail;
                    ed.push_back({u, {OP_MUL, r, r}});
                    ed.push_back({r, {OP_MUL, r2, r2}});
                    if (cr == 1) ed.push_back({r2, dr});
                    try_commit(ed);
                }
                if (outer + 3 > best_cost) return;
                WBackStep bs_r[6];
                for (int idc : free_ids) {
                    i64 c = st.nodes[idc];
                    int nbr = gen_win_inverses(r, c, p.limit, bs_r);
                    for (int kr = 0; kr < nbr; ++kr) {
                        i64 ur = bs_r[kr].u;
                        if (ur == r || ur == u || ur == v) continue;
                        if (free_reach(ur, cr, dr) && outer + 2 + cr < best_cost) {
                            auto ed = tail;
                            ed.push_back({u, {OP_MUL, r, r}});
                            ed.push_back({r, bs_r[kr].rev ? DagDef{bs_r[kr].op, c, ur} : DagDef{bs_r[kr].op, ur, c}});
                            if (cr == 1) ed.push_back({ur, dr});
                            try_commit(ed);
                        }
                    }
                }
                // 2 backward steps from r when u IS already a square!
                if (outer + 4 <= best_cost) {
                    size_t lim_c = std::min<size_t>(free_ids.size(), 32);
                    for (size_t ic = 0; ic < lim_c; ++ic) {
                        i64 c = st.nodes[free_ids[ic]];
                        int nbr = gen_win_inverses(r, c, p.limit, bs_r);
                        for (int kr = 0; kr < nbr; ++kr) {
                            i64 ur1 = bs_r[kr].u;
                            if (ur1 == r || ur1 == u || ur1 == v || !can_create(ur1)) continue;
                            WBackStep bs_r2[6];
                            for (size_t id2 = 0; id2 < lim_c; ++id2) {
                                i64 d = st.nodes[free_ids[id2]];
                                int nbr2 = gen_win_inverses(ur1, d, p.limit, bs_r2);
                                for (int kr2 = 0; kr2 < nbr2; ++kr2) {
                                    i64 ur2 = bs_r2[kr2].u;
                                    if (ur2 == ur1 || ur2 == r || ur2 == u || ur2 == v) continue;
                                    if (free_reach(ur2, cr, dr) && outer + 3 + cr < best_cost) {
                                        auto ed = tail;
                                        ed.push_back({u, {OP_MUL, r, r}});
                                        ed.push_back({r, bs_r[kr].rev ? DagDef{bs_r[kr].op, c, ur1} : DagDef{bs_r[kr].op, ur1, c}});
                                        ed.push_back({ur1, bs_r2[kr2].rev ? DagDef{bs_r2[kr2].op, d, ur2} : DagDef{bs_r2[kr2].op, ur2, d}});
                                        if (cr == 1) ed.push_back({ur2, dr});
                                        try_commit(ed);
                                    }
                                }
                            }
                        }
                    }
                }
            };

            check_square_at(v, {});
            if (budget >= 4) {
                WBackStep bs1[6];
                size_t lim1 = free_ids.size();
                for (size_t ia = 0; ia < lim1; ++ia) {
                    i64 a = st.nodes[free_ids[ia]];
                    int nb1 = gen_win_inverses(v, a, p.limit, bs1);
                    for (int k1 = 0; k1 < nb1; ++k1) {
                        i64 u1 = bs1[k1].u;
                        if (u1 == v || !can_create(u1)) continue;
                        DagDef d1 = bs1[k1].rev ? DagDef{bs1[k1].op, a, u1} : DagDef{bs1[k1].op, u1, a};
                        check_square_at(u1, {{v, d1}});
                        if ((u1 & 1LL) == 0 && u1 > 2) {
                            i64 h = u1 >> 1;
                            i64 rh = exact_isqrt64(h);
                            int cr = 0; DagDef dr{};
                            if (rh > 1 && can_create(h) && free_reach(rh, cr, dr) && 3 + cr < best_cost) {
                                std::vector<std::pair<i64, DagDef>> ed{{v, d1}, {u1, {OP_ADD, h, h}}, {h, {OP_MUL, rh, rh}}};
                                if (cr == 1) ed.push_back({rh, dr});
                                try_commit(ed);
                            }
                        }
                        if (best_cost >= 5 && ia < 24) {
                            size_t lim2 = std::min<size_t>(free_ids.size(), 24);
                            WBackStep bs2[6];
                            for (size_t jb = 0; jb < lim2; ++jb) {
                                i64 b = st.nodes[free_ids[jb]];
                                int nb2 = gen_win_inverses(u1, b, p.limit, bs2);
                                for (int k2 = 0; k2 < nb2; ++k2) {
                                    i64 u2 = bs2[k2].u;
                                    if (u2 == u1 || u2 == v || !can_create(u2)) continue;
                                    DagDef d2 = bs2[k2].rev ? DagDef{bs2[k2].op, b, u2} : DagDef{bs2[k2].op, u2, b};
                                    check_square_at(u2, {{v, d1}, {u1, d2}});
                                }
                            }
                        }
                    }
                }
            }

            // 3-op and bounded 4-op linear chains
            if (best_cost >= 4) {
                size_t lim_a = std::min<size_t>(free_ids.size(), 44);
                size_t lim_b = std::min<size_t>(free_ids.size(), 32);
                WBackStep bs1[6], bs2[6], bs3[6];
                for (size_t ia = 0; ia < lim_a && best_cost >= 4; ++ia) {
                    i64 a = st.nodes[free_ids[ia]];
                    int nb1 = gen_win_inverses(v, a, p.limit, bs1);
                    for (int k1 = 0; k1 < nb1 && best_cost >= 4; ++k1) {
                        i64 u1 = bs1[k1].u;
                        if (u1 == v || !can_create(u1)) continue;
                        DagDef d1 = bs1[k1].rev ? DagDef{bs1[k1].op, a, u1} : DagDef{bs1[k1].op, u1, a};
                        for (size_t ib = 0; ib < lim_b; ++ib) {
                            i64 b = st.nodes[free_ids[ib]];
                            int nb2 = gen_win_inverses(u1, b, p.limit, bs2);
                            for (int k2 = 0; k2 < nb2; ++k2) {
                                i64 u2 = bs2[k2].u;
                                if (u2 == u1 || u2 == v || !can_create(u2)) continue;
                                DagDef d2 = bs2[k2].rev ? DagDef{bs2[k2].op, b, u2} : DagDef{bs2[k2].op, u2, b};
                                int c2 = 0; DagDef dr2{};
                                if (free_reach(u2, c2, dr2) && 2 + c2 < best_cost) {
                                    std::vector<std::pair<i64, DagDef>> ed{{v, d1}, {u1, d2}};
                                    if (c2 == 1) ed.push_back({u2, dr2});
                                    try_commit(ed);
                                } else if (best_cost >= 5 && ia < 14 && ib < 14) {
                                    size_t lim_c = std::min<size_t>(free_ids.size(), 14);
                                    for (size_t ic = 0; ic < lim_c; ++ic) {
                                        i64 c = st.nodes[free_ids[ic]];
                                        int nb3 = gen_win_inverses(u2, c, p.limit, bs3);
                                        for (int k3 = 0; k3 < nb3; ++k3) {
                                            i64 u3 = bs3[k3].u;
                                            if (u3 == u2 || u3 == u1 || u3 == v || !can_create(u3)) continue;
                                            int c3 = 0; DagDef dr3{};
                                            if (free_reach(u3, c3, dr3) && 3 + c3 < best_cost) {
                                                DagDef d3 = bs3[k3].rev ? DagDef{bs3[k3].op, c, u3} : DagDef{bs3[k3].op, u3, c};
                                                std::vector<std::pair<i64, DagDef>> ed{{v, d1}, {u1, d2}, {u2, d3}};
                                                if (c3 == 1) ed.push_back({u3, dr3});
                                                try_commit(ed);
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            if (!best_edits.empty()) {
                for (const auto& kv : best_edits) defs[kv.first] = kv.second;
                rebuild_needed(defs, order);
                changed = true;
                break;
            }
        }
        if (!changed) break;
    }

    // Pass 2d: Dependency reversal (build consumer w directly, recover predecessor u from w in 1 op)
    for (int round = 0; round < 3; ++round) {
        bool changed = false;
        st.init(p, starts_set, req_targets, defs, order);
        st.fill_pair_table(p.limit, ws.pair_table);

        std::vector<std::vector<int>> consumers(st.M);
        for (int i = 0; i < st.M; ++i) {
            if (!st.is_root[i]) {
                consumers[st.cur_a[i]].push_back(i);
                if (st.cur_b[i] != st.cur_a[i]) consumers[st.cur_b[i]].push_back(i);
            }
        }
        std::vector<uint8_t> is_target(st.M, 0);
        for (i64 t : req_targets) {
            auto it = st.nid.find(t);
            if (it != st.nid.end()) is_target[it->second] = 1;
        }
        std::vector<uint8_t> gone(st.M, 0), is_free(st.M, 0);
        std::vector<int> lost(st.M, 0);
        std::vector<u64> rdivs;

        for (i64 u_val : order) {
            int iu = st.nid.at(u_val);
            if (st.is_root[iu] || consumers[iu].empty() || consumers[iu].size() > 3) continue;
            for (int iw : consumers[iu]) {
                i64 w_val = st.nodes[iw];
                std::fill(gone.begin(), gone.end(), 0);
                std::fill(lost.begin(), lost.end(), 0);
                gone[iw] = 1;
                gone[iu] = 1;
                bool u_needed_after = (is_target[iu] != 0) || (consumers[iu].size() > 1);
                std::vector<int> stk{iw, iu};
                int budget = 2;
                while (!stk.empty()) {
                    int cur = stk.back();
                    stk.pop_back();
                    if (st.is_root[cur]) continue;
                    int ps[2] = {st.cur_a[cur], st.cur_b[cur]};
                    int np = (ps[0] == ps[1]) ? 1 : 2;
                    for (int pi = 0; pi < np; ++pi) {
                        int anc = ps[pi];
                        if (!st.is_root[anc] && !gone[anc] && ++lost[anc] == st.refs[anc]) {
                            gone[anc] = 1;
                            ++budget;
                            stk.push_back(anc);
                        }
                    }
                }
                if (budget < (u_needed_after ? 3 : 2)) continue;

                std::fill(is_free.begin(), is_free.end(), 0);
                std::vector<int> free_ids;
                for (int i = 0; i < st.M; ++i) {
                    if (st.is_root[i] || (!gone[i] && !st.depends_on(i, iu) && !st.depends_on(i, iw))) {
                        is_free[i] = 1;
                        free_ids.push_back(i);
                    }
                }
                bool has_recovery = !u_needed_after;
                DagDef rec_u_def{};
                if (u_needed_after) {
                    WBackStep ubs[6];
                    int nu = gen_win_inverses(u_val, w_val, p.limit, ubs);
                    for (int idx : free_ids) {
                        i64 x = st.nodes[idx];
                        for (int ku = 0; ku < nu; ++ku) {
                            if (ubs[ku].u == x) {
                                rec_u_def = ubs[ku].rev ? DagDef{ubs[ku].op, w_val, x} : DagDef{ubs[ku].op, x, w_val};
                                has_recovery = true;
                                break;
                            }
                        }
                        if (has_recovery) break;
                    }
                }
                if (!has_recovery) continue;

                auto can_create = [&](i64 x) -> bool {
                    if (x <= 0 || x > p.limit) return false;
                    auto it = st.nid.find(x);
                    if (it == st.nid.end()) return true;
                    return gone[it->second] != 0;
                };
                auto free_reach = [&](i64 val, int& out_cost, DagDef& out_def) -> bool {
                    auto nit = st.nid.find(val);
                    if (nit != st.nid.end()) {
                        if (is_free[nit->second]) { out_cost = 0; return true; }
                        return false;
                    }
                    const auto* pb = ws.pair_table.find(val);
                    if (!pb) return false;
                    for (uint8_t pi = 0; pi < pb->cnt; ++pi) {
                        const auto& pr = pb->recs[pi];
                        if (is_free[pr.a] && is_free[pr.b]) {
                            out_cost = 1;
                            out_def = {pr.op, st.nodes[pr.a], st.nodes[pr.b]};
                            return true;
                        }
                    }
                    return false;
                };

                int rec_cost = u_needed_after ? 1 : 0;
                int best_cost = budget;
                std::vector<std::pair<i64, DagDef>> best_edits;

                int cw = 0; DagDef dw{};
                if (free_reach(w_val, cw, dw) && cw + rec_cost < best_cost) {
                    best_cost = cw + rec_cost;
                    best_edits.clear();
                    if (cw == 1) best_edits.push_back({w_val, dw});
                    if (u_needed_after) best_edits.push_back({u_val, rec_u_def});
                }
                if (2 + rec_cost < best_cost) {
                    WBackStep wbs[6];
                    for (int idx : free_ids) {
                        i64 c = st.nodes[idx];
                        int nw = gen_win_inverses(w_val, c, p.limit, wbs);
                        for (int kw = 0; kw < nw; ++kw) {
                            i64 z = wbs[kw].u;
                            if (z == w_val || z == u_val || !can_create(z)) continue;
                            int cz = 0; DagDef dz{};
                            if (free_reach(z, cz, dz) && 1 + cz + rec_cost < best_cost) {
                                best_cost = 1 + cz + rec_cost;
                                best_edits.clear();
                                if (cz == 1) best_edits.push_back({z, dz});
                                best_edits.push_back({w_val, wbs[kw].rev ? DagDef{wbs[kw].op, c, z} : DagDef{wbs[kw].op, z, c}});
                                if (u_needed_after) best_edits.push_back({u_val, rec_u_def});
                            }
                        }
                    }
                    i64 rw = exact_isqrt64(w_val);
                    int cr = 0; DagDef dr{};
                    if (rw > 1 && free_reach(rw, cr, dr) && 1 + cr + rec_cost < best_cost) {
                        best_cost = 1 + cr + rec_cost;
                        best_edits.clear();
                        if (cr == 1) best_edits.push_back({rw, dr});
                        best_edits.push_back({w_val, {OP_MUL, rw, rw}});
                        if (u_needed_after) best_edits.push_back({u_val, rec_u_def});
                    }
                }
                if (budget >= 5 && best_cost > 2 + rec_cost && (is_target[iu] || is_target[iw])) {
                    std::vector<i64> d_cands;
                    for (i64 s : p.starts) if (std::find(d_cands.begin(), d_cands.end(), s) == d_cands.end()) d_cands.push_back(s);
                    for (i64 c : {1, 2, 3, 4}) {
                        auto cit = st.nid.find(c);
                        if (cit != st.nid.end() && is_free[cit->second] &&
                            std::find(d_cands.begin(), d_cands.end(), c) == d_cands.end()) d_cands.push_back(c);
                    }
                    for (i64 d : d_cands) {
                        for (int mode = 0; mode < 2; ++mode) {
                            i64 prod = (mode == 0) ? (w_val > d ? w_val - d : 0) : (w_val <= p.limit - d ? w_val + d : 0);
                            if (prod < 4 || !can_create(prod)) continue;
                            get_divisors64(static_cast<u64>(prod), rdivs);
                            for (u64 uf : rdivs) {
                                i64 f = static_cast<i64>(uf), q = prod / f;
                                if (f <= 1 || q <= 1 || f > q) continue;
                                int cf = 0, cq = 0; DagDef df{}, dq{};
                                if (!free_reach(f, cf, df) || !free_reach(q, cq, dq)) continue;
                                int tot = 2 + cf + (f == q ? 0 : cq) + rec_cost;
                                if (tot < best_cost) {
                                    best_cost = tot;
                                    best_edits.clear();
                                    if (cf == 1) best_edits.push_back({f, df});
                                    if (cq == 1 && q != f) best_edits.push_back({q, dq});
                                    best_edits.push_back({prod, {OP_MUL, f, q}});
                                    best_edits.push_back({w_val, (mode == 0) ? DagDef{OP_ADD, prod, d} : DagDef{OP_SUB, prod, d}});
                                    if (u_needed_after) best_edits.push_back({u_val, rec_u_def});
                                }
                            }
                        }
                    }
                }

                if (!best_edits.empty()) {
                    for (const auto& kv : best_edits) defs[kv.first] = kv.second;
                    rebuild_needed(defs, order);
                    changed = true;
                    break;
                }
            }
            if (changed) break;
        }
        if (!changed) break;
    }

    if (defs.size() < best.size()) {
        DagGraph final_dag{std::move(defs), std::move(order)};
        dag_reallocate(p, final_dag, best);
    }
}


void cross_trace_recombine_pass(const Puzzle& p,
                                const std::vector<DagGraph>& distinct_dags,
                                std::vector<Instr>& best,
                                WorkerScratch& ws) {
    if (distinct_dags.empty() || best.size() <= 4) return;
    std::unordered_set<i64> starts_set(p.starts.begin(), p.starts.end());
    std::vector<i64> req_targets;
    for (i64 t : p.targets) {
        if (!starts_set.count(t)) req_targets.push_back(t);
    }
    std::sort(req_targets.begin(), req_targets.end());
    req_targets.erase(std::unique(req_targets.begin(), req_targets.end()), req_targets.end());
    if (req_targets.empty()) return;

    DagGraph best_dag = extract_needed_dag(p, best);
    std::vector<const DagGraph*> dags;
    dags.push_back(&best_dag);
    for (const auto& dg : distinct_dags) {
        if (dags.size() < 6) dags.push_back(&dg);
    }

    std::vector<i64> U;
    ws.small_idx.clear();
    auto push_u = [&](i64 v) -> int {
        if (v <= 0 || v > p.limit) return -1;
        int id = ws.small_idx.get(v);
        if (id >= 0) return id;
        if (U.size() >= 440) return -1;
        id = static_cast<int>(U.size());
        ws.small_idx.insert(v, id);
        U.push_back(v);
        return id;
    };
    for (i64 s : p.starts) push_u(s);
    const int n_roots = static_cast<int>(U.size());
    for (const DagGraph* dg : dags) {
        for (i64 v : dg->order) push_u(v);
    }
    if (static_cast<int>(U.size()) <= n_roots) return;

    struct CRecipe { Op op; int a; int b; };
    std::vector<std::vector<CRecipe>> choices(U.size());
    auto add_choice = [&](int v_id, Op op, int ia, int ib) {
        if (v_id < n_roots || ia < 0 || ib < 0 || ia == v_id || ib == v_id) return;
        if ((op == OP_ADD || op == OP_MUL) && ia < ib) std::swap(ia, ib);
        for (const auto& r : choices[v_id]) {
            if (r.op == op && r.a == ia && r.b == ib) return;
        }
        if (choices[v_id].size() < 24) choices[v_id].push_back({op, ia, ib});
    };

    for (const DagGraph* dg : dags) {
        for (const auto& kv : dg->defs) {
            add_choice(ws.small_idx.get(kv.first), kv.second.op,
                       ws.small_idx.get(kv.second.a), ws.small_idx.get(kv.second.b));
        }
    }

    ws.pair_table.clear();
    const int nu_base = static_cast<int>(U.size());
    for (int i = 0; i < nu_base; ++i) {
        i64 a = U[i];
        for (int j = 0; j <= i; ++j) {
            i64 b = U[j];
            auto handle = [&](i64 val, Op op, int x, int y) {
                if (val <= 0 || val > p.limit) return;
                int vid = ws.small_idx.get(val);
                if (vid >= n_roots) add_choice(vid, op, x, y);
                else if (vid < 0) ws.pair_table.add(val, static_cast<uint16_t>(x), static_cast<uint16_t>(y), op);
            };
            if (a <= p.limit - b) handle(a + b, OP_ADD, i, j);
            if (a != b) handle(a > b ? a - b : b - a, OP_SUB, a > b ? i : j, a > b ? j : i);
            i128 prod = static_cast<i128>(a) * b;
            if (prod <= p.limit) handle(static_cast<i64>(prod), OP_MUL, i, j);
            if (a >= b && b > 0 && a % b == 0) handle(a / b, OP_DIV, i, j);
            if (b > a && a > 0 && b % a == 0) handle(b / a, OP_DIV, j, i);
        }
    }

    struct FreshHit { i64 h; int v_id; Op op; int x_id; bool h_first; };
    std::vector<FreshHit> fhits;
    fhits.reserve(1024);
    WBackStep bs[6];
    for (int vid = n_roots; vid < nu_base; ++vid) {
        i64 v = U[vid];
        for (int xid = 0; xid < nu_base; ++xid) {
            int nb = gen_win_inverses(v, U[xid], p.limit, bs);
            for (int k = 0; k < nb; ++k) {
                i64 hv = bs[k].u;
                if (ws.small_idx.get(hv) >= 0) continue;
                if (ws.pair_table.find(hv)) fhits.push_back({hv, vid, bs[k].op, xid, !bs[k].rev});
            }
        }
    }
    std::sort(fhits.begin(), fhits.end(), [](const FreshHit& a, const FreshHit& b) {
        return std::tie(a.h, a.v_id, a.x_id) < std::tie(b.h, b.v_id, b.x_id);
    });
    struct RankedHelper { int neg_cnt; i64 h; size_t beg; size_t end; };
    std::vector<RankedHelper> rhelpers;
    for (size_t pos = 0; pos < fhits.size();) {
        size_t end = pos + 1;
        int distinct_v = 1;
        while (end < fhits.size() && fhits[end].h == fhits[pos].h) {
            if (fhits[end].v_id != fhits[end - 1].v_id) ++distinct_v;
            ++end;
        }
        if (distinct_v >= 2) rhelpers.push_back({-distinct_v, fhits[pos].h, pos, end});
        pos = end;
    }
    std::sort(rhelpers.begin(), rhelpers.end(), [](const RankedHelper& a, const RankedHelper& b) {
        return std::tie(a.neg_cnt, a.h) < std::tie(b.neg_cnt, b.h);
    });
    size_t add_h = std::min<size_t>(rhelpers.size(), 40);
    for (size_t hi = 0; hi < add_h; ++hi) {
        const auto& rh = rhelpers[hi];
        int hid = push_u(rh.h);
        if (hid < 0) break;
        choices.resize(U.size());
        const auto* hb = ws.pair_table.find(rh.h);
        for (uint8_t ri = 0; hb && ri < hb->cnt; ++ri) {
            add_choice(hid, hb->recs[ri].op, hb->recs[ri].a, hb->recs[ri].b);
        }
        for (size_t k = rh.beg; k < rh.end; ++k) {
            const auto& fh = fhits[k];
            add_choice(fh.v_id, fh.op, fh.h_first ? hid : fh.x_id, fh.h_first ? fh.x_id : hid);
        }
    }

    const int NU = static_cast<int>(U.size());
    std::vector<int> target_ids;
    for (i64 t : req_targets) {
        int id = ws.small_idx.get(t);
        if (id >= n_roots) target_ids.push_back(id);
    }

    auto build_merged_order = [&](const std::vector<int>& rank_prio) -> std::vector<int> {
        std::vector<int> ord(NU, -1);
        std::vector<uint8_t> done(NU, 0);
        for (int r = 0; r < n_roots; ++r) { ord[r] = 0; done[r] = 1; }
        struct EdgeRef { int node; int dep_rem; };
        std::vector<EdgeRef> erefs;
        std::vector<std::vector<int>> adj(NU);
        for (int v = n_roots; v < NU; ++v) {
            for (const auto& rec : choices[v]) {
                int need = (!done[rec.a] ? 1 : 0) + (rec.b != rec.a && !done[rec.b] ? 1 : 0);
                int eid = static_cast<int>(erefs.size());
                erefs.push_back({v, need});
                if (!done[rec.a]) adj[rec.a].push_back(eid);
                if (rec.b != rec.a && !done[rec.b]) adj[rec.b].push_back(eid);
            }
        }
        using Item = std::pair<int, int>;
        std::priority_queue<Item, std::vector<Item>, std::greater<Item>> pq;
        std::vector<uint8_t> pushed(NU, 0);
        for (const auto& er : erefs) {
            if (er.dep_rem == 0 && !pushed[er.node]) {
                pushed[er.node] = 1;
                pq.push({rank_prio[er.node], er.node});
            }
        }
        int step = 1;
        while (!pq.empty()) {
            auto [pr, v] = pq.top();
            pq.pop();
            if (done[v]) continue;
            done[v] = 1;
            ord[v] = step++;
            for (int eid : adj[v]) {
                if (--erefs[eid].dep_rem == 0) {
                    int w = erefs[eid].node;
                    if (!done[w] && !pushed[w]) { pushed[w] = 1; pq.push({rank_prio[w], w}); }
                }
            }
        }
        return ord;
    };

    std::vector<std::vector<int>> orderings;
    {
        std::vector<int> rp(NU, 100000);
        for (size_t i = 0; i < best_dag.order.size(); ++i) rp[ws.small_idx.get(best_dag.order[i])] = static_cast<int>(i);
        orderings.push_back(build_merged_order(rp));
        std::vector<int> rp_rev(NU, 100000);
        for (size_t i = 0; i < best_dag.order.size(); ++i) {
            rp_rev[ws.small_idx.get(best_dag.order[i])] = static_cast<int>(best_dag.order.size() - i);
        }
        orderings.push_back(build_merged_order(rp_rev));
    }
    for (size_t di = 1; di < std::min<size_t>(dags.size(), 4); ++di) {
        std::vector<int> rp(NU, 100000);
        for (size_t i = 0; i < dags[di]->order.size(); ++i) {
            int id = ws.small_idx.get(dags[di]->order[i]);
            if (id >= 0) rp[id] = static_cast<int>(i);
        }
        orderings.push_back(build_merged_order(rp));
    }

    for (size_t oi = 0; oi < orderings.size(); ++oi) {
        const auto& ord = orderings[oi];
        bool all_ok = true;
        for (int tid : target_ids) { if (ord[tid] < 0) { all_ok = false; break; } }
        if (!all_ok) continue;

        std::vector<std::vector<CRecipe>> vc(NU);
        for (int v = n_roots; v < NU; ++v) {
            if (ord[v] < 0) continue;
            for (const auto& r : choices[v]) {
                if (ord[r.a] >= 0 && ord[r.b] >= 0 && ord[r.a] < ord[v] && ord[r.b] < ord[v]) vc[v].push_back(r);
            }
        }
        std::vector<int> desc_nodes;
        for (int v = n_roots; v < NU; ++v) if (ord[v] > 0) desc_nodes.push_back(v);
        std::sort(desc_nodes.begin(), desc_nodes.end(), [&](int x, int y) { return ord[x] > ord[y]; });

        int n_trials = (oi == 0) ? 4 : 2;
        for (int trial = 0; trial < n_trials; ++trial) {
            SplitMix64 rng(p.numeric_id * 1009ULL + oi * 31ULL + static_cast<u64>(trial));
            std::vector<int> cur_a(NU, -1), cur_b(NU, -1), refs(NU, 0);
            std::vector<Op> cur_op(NU, OP_ADD);
            for (int tid : target_ids) refs[tid]++;

            if (oi == 0 && trial == 0) {
                for (const auto& kv : best_dag.defs) {
                    int vid = ws.small_idx.get(kv.first);
                    cur_op[vid] = kv.second.op;
                    cur_a[vid] = ws.small_idx.get(kv.second.a);
                    cur_b[vid] = ws.small_idx.get(kv.second.b);
                }
            } else {
                for (int v : desc_nodes) {
                    if (refs[v] == 0 || vc[v].empty()) continue;
                    int best_ri = 0;
                    double best_sc = 1e18;
                    for (int ri = 0; ri < static_cast<int>(vc[v].size()); ++ri) {
                        const auto& r = vc[v][ri];
                        int sc = (r.a >= n_roots && refs[r.a] == 0 ? 1 : 0) +
                                 (r.b != r.a && r.b >= n_roots && refs[r.b] == 0 ? 1 : 0);
                        double rsc = static_cast<double>(sc) + rng.next_unit() * 0.45;
                        if (rsc < best_sc) { best_sc = rsc; best_ri = ri; }
                    }
                    const auto& r = vc[v][best_ri];
                    cur_op[v] = r.op; cur_a[v] = r.a; cur_b[v] = r.b;
                    refs[r.a]++;
                    if (r.b != r.a) refs[r.b]++;
                }
            }
            for (int v = n_roots; v < NU; ++v) {
                if (cur_a[v] < 0 && !vc[v].empty()) {
                    cur_op[v] = vc[v][0].op; cur_a[v] = vc[v][0].a; cur_b[v] = vc[v][0].b;
                }
            }
            std::fill(refs.begin(), refs.end(), 0);
            for (int tid : target_ids) refs[tid]++;
            int active_cnt = 0;
            bool valid_state = true;
            for (int v : desc_nodes) {
                if (refs[v] > 0) {
                    if (cur_a[v] < 0) { valid_state = false; break; }
                    ++active_cnt;
                    refs[cur_a[v]]++;
                    if (cur_b[v] != cur_a[v]) refs[cur_b[v]]++;
                }
            }
            if (!valid_state) continue;

            auto adjust_node = [&](auto&& self, int u, int dir) -> void {
                int before = refs[u];
                refs[u] += dir;
                if (u < n_roots) return;
                if (dir > 0 && before == 0) ++active_cnt;
                else if (dir < 0 && refs[u] == 0) --active_cnt;
                if (before != 0 && refs[u] != 0) return;
                self(self, cur_a[u], dir);
                if (cur_b[u] != cur_a[u]) self(self, cur_b[u], dir);
            };

            for (int round = 0; round < 3; ++round) {
                bool changed = false;
                for (int v : desc_nodes) {
                    if (refs[v] == 0 || vc[v].size() <= 1) continue;
                    int before = active_cnt;
                    int oa = cur_a[v], ob = cur_b[v];
                    adjust_node(adjust_node, oa, -1);
                    if (ob != oa) adjust_node(adjust_node, ob, -1);

                    int best_act = before, best_ri = -1;
                    for (int ri = 0; ri < static_cast<int>(vc[v].size()); ++ri) {
                        const auto& r = vc[v][ri];
                        adjust_node(adjust_node, r.a, 1);
                        if (r.b != r.a) adjust_node(adjust_node, r.b, 1);
                        if (active_cnt < best_act) { best_act = active_cnt; best_ri = ri; }
                        if (r.b != r.a) adjust_node(adjust_node, r.b, -1);
                        adjust_node(adjust_node, r.a, -1);
                    }
                    if (best_ri >= 0) {
                        const auto& r = vc[v][best_ri];
                        cur_op[v] = r.op; cur_a[v] = r.a; cur_b[v] = r.b;
                        adjust_node(adjust_node, r.a, 1);
                        if (r.b != r.a) adjust_node(adjust_node, r.b, 1);
                        changed = true;
                    } else {
                        adjust_node(adjust_node, oa, 1);
                        if (ob != oa) adjust_node(adjust_node, ob, 1);
                    }
                }
                for (int h = n_roots; h < NU; ++h) {
                    if (ord[h] < 0 || refs[h] > 0 || cur_a[h] < 0) continue;
                    std::vector<std::pair<int, CRecipe>> cands;
                    for (int u : desc_nodes) {
                        if (ord[u] <= ord[h] || refs[u] == 0) continue;
                        for (const auto& r : vc[u]) {
                            auto ok_op = [&](int x) -> bool {
                                return x < n_roots || x == h || refs[x] > 0 ||
                                       (cur_a[x] >= 0 && refs[cur_a[x]] > 0 && refs[cur_b[x]] > 0);
                            };
                            if ((r.a == h && ok_op(r.b)) || (r.b == h && ok_op(r.a))) {
                                cands.push_back({u, r});
                                break;
                            }
                        }
                    }
                    if (cands.size() < 2) continue;
                    int before = active_cnt;
                    adjust_node(adjust_node, cur_a[h], 1);
                    if (cur_b[h] != cur_a[h]) adjust_node(adjust_node, cur_b[h], 1);
                    ++active_cnt;
                    refs[h] = 1;
                    std::vector<std::tuple<int, Op, int, int>> backups;
                    for (const auto& [u, r] : cands) {
                        backups.emplace_back(u, cur_op[u], cur_a[u], cur_b[u]);
                        adjust_node(adjust_node, cur_a[u], -1);
                        if (cur_b[u] != cur_a[u]) adjust_node(adjust_node, cur_b[u], -1);
                        cur_op[u] = r.op; cur_a[u] = r.a; cur_b[u] = r.b;
                        adjust_node(adjust_node, r.a, 1);
                        if (r.b != r.a) adjust_node(adjust_node, r.b, 1);
                    }
                    refs[h] -= 1;
                    if (active_cnt < before) {
                        changed = true;
                    } else {
                        refs[h] += 1;
                        for (size_t bi = backups.size(); bi-- > 0;) {
                            auto [u, oop, oa, ob] = backups[bi];
                            adjust_node(adjust_node, cur_a[u], -1);
                            if (cur_b[u] != cur_a[u]) adjust_node(adjust_node, cur_b[u], -1);
                            cur_op[u] = oop; cur_a[u] = oa; cur_b[u] = ob;
                            adjust_node(adjust_node, oa, 1);
                            if (ob != oa) adjust_node(adjust_node, ob, 1);
                        }
                        refs[h] = 0;
                        --active_cnt;
                        if (cur_b[h] != cur_a[h]) adjust_node(adjust_node, cur_b[h], -1);
                        adjust_node(adjust_node, cur_a[h], -1);
                    }
                }
                if (!changed) break;
            }

            if (active_cnt < static_cast<int>(best.size())) {
                DagGraph cand_dag;
                for (int v = n_roots; v < NU; ++v) {
                    if (ord[v] > 0 && refs[v] > 0) {
                        cand_dag.defs[U[v]] = {cur_op[v], U[cur_a[v]], U[cur_b[v]]};
                        cand_dag.order.push_back(v);
                    }
                }
                std::sort(cand_dag.order.begin(), cand_dag.order.end(), [&](i64 x, i64 y) { return ord[x] < ord[y]; });
                for (auto& x : cand_dag.order) x = U[x];
                dag_reallocate(p, cand_dag, best);
            }
        }
    }
}

// --- Stage 5 (Mode 2, Pass 5): Complete Fan-Out Scaffold Exchange ---

struct ExNode {
    i64 value = 0;
    Op op = OP_ADD;
    int a = -1;
    int b = -1;
    bool is_op = false;
};

struct ExGraph {
    std::vector<ExNode> nodes;
    std::vector<int> targets;
    std::array<int, kNumRegs> initial{};
};

struct ExStep {
    i64 x = 0;
    Op op = OP_ADD;
    i64 a = 0;
    i64 b = 0;
};

struct ExCut {
    std::vector<int> roots;
    std::vector<uint8_t> fixed;
    std::vector<uint8_t> terminal;
    int budget = 0;
};

struct ExPatch {
    int rank = 0;
    std::vector<int> rim;
};

ExGraph topo_ex_graph(const ExGraph& g) {
    ExGraph out;
    out.initial.fill(-1);
    std::vector<int> mapping(g.nodes.size(), -1);
    auto visit = [&](auto&& self, int id) -> int {
        if (mapping[id] >= 0) return mapping[id];
        ExNode nd = g.nodes[id];
        if (nd.is_op) {
            nd.a = self(self, nd.a);
            nd.b = self(self, nd.b);
        }
        mapping[id] = static_cast<int>(out.nodes.size());
        out.nodes.push_back(nd);
        return mapping[id];
    };
    for (int i = 0; i < kNumRegs; ++i) {
        if (g.initial[i] >= 0) out.initial[i] = visit(visit, g.initial[i]);
    }
    for (int t : g.targets) {
        out.targets.push_back(visit(visit, t));
    }
    return out;
}

ExGraph recover_ex_graph(const Puzzle& p, const std::vector<Instr>& prog) {
    ExGraph g;
    g.initial.fill(-1);
    std::array<i64, kNumRegs> regs{};
    for (size_t k = 0; k < p.starts.size(); ++k) regs[k] = p.starts[k];
    std::unordered_map<i64, int> by_val;
    by_val.reserve(prog.size() + p.starts.size() + 8);
    std::unordered_set<i64> rem(p.targets.begin(), p.targets.end());
    for (int r = 0; r < p.registers; ++r) {
        if (regs[r] > 0) {
            auto [it, added] = by_val.emplace(regs[r], static_cast<int>(g.nodes.size()));
            if (added) g.nodes.push_back({regs[r], OP_ADD, -1, -1, false});
            g.initial[r] = it->second;
            rem.erase(regs[r]);
        }
    }
    for (const auto& ins : prog) {
        int la = by_val.at(regs[ins.i]);
        int lb = by_val.at(regs[ins.j]);
        i64 res = apply_op(ins.op, regs[ins.i], regs[ins.j], p.limit);
        regs[ins.d] = res;
        auto [it, added] = by_val.emplace(res, static_cast<int>(g.nodes.size()));
        if (added) g.nodes.push_back({res, ins.op, la, lb, true});
        if (rem.erase(res)) g.targets.push_back(it->second);
    }
    return topo_ex_graph(g);
}

ExCut make_ex_cut(const ExGraph& g, const std::vector<int>& roots) {
    const int n = static_cast<int>(g.nodes.size());
    std::vector<uint8_t> fixed(n, 0), blocked(n, 0), removed(n, 0);
    for (int id : roots) removed[id] = 1;
    auto visit = [&](auto&& self, int id) -> void {
        if (fixed[id] || removed[id]) return;
        fixed[id] = 1;
        const auto& nd = g.nodes[id];
        if (nd.is_op) {
            self(self, nd.a);
            self(self, nd.b);
        }
    };
    for (int t : g.targets) visit(visit, t);
    for (int id : g.initial) {
        if (id >= 0) visit(visit, id);
    }
    int budget = 0;
    for (int i = 0; i < n; ++i) {
        const auto& nd = g.nodes[i];
        blocked[i] = removed[i] || (nd.is_op && (blocked[nd.a] || blocked[nd.b]));
        if (!fixed[i] && nd.is_op) ++budget;
    }
    if (budget <= static_cast<int>(roots.size())) budget = 0;
    std::vector<uint8_t> terminal = fixed;
    for (int i = 0; i < n; ++i) terminal[i] = (terminal[i] && !blocked[i]) ? 1 : 0;
    return {roots, std::move(fixed), std::move(terminal), budget};
}

std::vector<ExPatch> generate_scaffold_cuts(const ExGraph& g, int budget, int variant) {
    const int n = static_cast<int>(g.nodes.size());
    std::vector<std::vector<int>> uses(n);
    std::vector<uint8_t> is_goal(n, 0);
    for (int t : g.targets) is_goal[t] = 1;
    for (int i = 0; i < n; ++i) {
        if (g.nodes[i].is_op) {
            const auto& nd = g.nodes[i];
            uses[nd.a].push_back(i);
            if (nd.a != nd.b) uses[nd.b].push_back(i);
        }
    }
    std::vector<int> hints;
    for (int i = 0; i < n; ++i) {
        if (g.nodes[i].is_op && uses[i].size() >= 2 && uses[i].size() <= 7) {
            hints.push_back(i);
        }
    }
    std::vector<ExPatch> pool;
    std::set<std::vector<int>> seen;
    auto add = [&](std::vector<int> rim, int bonus) {
        std::sort(rim.begin(), rim.end());
        rim.erase(std::unique(rim.begin(), rim.end()), rim.end());
        if (rim.size() < 2 || rim.size() > 6 || !seen.insert(rim).second) return;
        ExCut cut = make_ex_cut(g, rim);
        int extra = cut.budget - static_cast<int>(rim.size());
        if (extra < 1 || cut.budget > 26) return;
        int rank = 9 * std::min(extra, 11) + bonus - 3 * static_cast<int>(rim.size());
        for (int r : rim) rank += std::min(4, static_cast<int>(uses[r].size()));
        pool.push_back({rank, std::move(rim)});
    };

    for (int x : hints) {
        const auto& children = uses[x];
        add(children, 6);
        std::vector<int> rim = children;
        for (int y : children) {
            if (!is_goal[y] && !uses[y].empty() && uses[y].size() <= 3) {
                std::vector<int> expanded = children;
                auto it = std::find(expanded.begin(), expanded.end(), y);
                if (it != expanded.end()) expanded.erase(it);
                expanded.insert(expanded.end(), uses[y].begin(), uses[y].end());
                add(std::move(expanded), 9);
                if ((variant & 1) == 1 && uses[y].size() <= 2) {
                    rim.erase(std::remove(rim.begin(), rim.end(), y), rim.end());
                    rim.insert(rim.end(), uses[y].begin(), uses[y].end());
                }
            }
        }
        add(std::move(rim), 11);
    }

    for (size_t ii = 0; ii < hints.size(); ++ii) {
        for (size_t jj = ii + 1; jj < hints.size(); ++jj) {
            int x = hints[ii], y = hints[jj];
            if (uses[x].size() + uses[y].size() > 9) continue;
            bool common = std::any_of(uses[x].begin(), uses[x].end(), [&](int u) {
                return u == y || std::binary_search(uses[y].begin(), uses[y].end(), u);
            });
            if (!common) continue;
            std::vector<int> rim = uses[x];
            rim.insert(rim.end(), uses[y].begin(), uses[y].end());
            if (!is_goal[y]) {
                rim.erase(std::remove(rim.begin(), rim.end(), y), rim.end());
            }
            add(std::move(rim), 15);
        }
    }

    int k = std::min(budget, static_cast<int>(pool.size()));
    std::vector<int> repeats(n, 0);
    for (int i = 0; i < k; ++i) {
        auto score = [&](const ExPatch& a) {
            int s = a.rank;
            for (int v : a.rim) s -= 5 * repeats[v];
            return std::make_pair(s, -static_cast<int>(a.rim.size()));
        };
        auto best_it = pool.begin() + i;
        auto best_sc = score(*best_it);
        for (auto it = pool.begin() + i + 1; it != pool.end(); ++it) {
            auto sc = score(*it);
            if (sc > best_sc || (sc == best_sc && it->rim < best_it->rim)) {
                best_sc = sc;
                best_it = it;
            }
        }
        std::iter_swap(pool.begin() + i, best_it);
        for (int v : pool[i].rim) ++repeats[v];
    }
    pool.resize(static_cast<size_t>(k));
    return pool;
}

std::vector<ExStep> scaffold_back_join(const ExGraph& g,
                                       const ExCut& cut,
                                       i64 limit,
                                       int allowed,
                                       WorkerScratch& ws) {
    ws.small_idx.clear();
    std::vector<i64> atoms;
    atoms.reserve(g.nodes.size());
    for (size_t i = 0; i < g.nodes.size(); ++i) {
        if (cut.terminal[i]) {
            i64 v = g.nodes[i].value;
            if (ws.small_idx.insert(v, 1)) atoms.push_back(v);
        }
    }
    std::vector<i64> roots;
    roots.reserve(cut.roots.size());
    for (int id : cut.roots) roots.push_back(g.nodes[id].value);
    const int K = static_cast<int>(roots.size());
    if (K == 0 || K > 6) return {};

    auto lookup_forward = [&](i64 val, ExStep& out_step) -> bool {
        const auto* b = ws.pair_table.find(val);
        if (!b) return false;
        for (uint8_t ri = 0; ri < b->cnt; ++ri) {
            const auto& rec = b->recs[ri];
            if (rec.a < g.nodes.size() && rec.b < g.nodes.size() &&
                cut.terminal[rec.a] && cut.terminal[rec.b]) {
                out_step = {val, rec.op, g.nodes[rec.a].value, g.nodes[rec.b].value};
                return true;
            }
        }
        return false;
    };

    auto has_val = [&](i64 val, const std::vector<i64>& extra) -> bool {
        if (ws.small_idx.get(val) >= 0) return true;
        for (i64 ev : extra) {
            if (ev == val) return true;
        }
        return false;
    };

    auto single_extra = [&](const std::vector<i64>& extra, i64 target, ExStep& out_step) -> bool {
        WBackStep bs[6];
        auto try_base = [&](i64 x) -> bool {
            int nb = gen_win_inverses(target, x, limit, bs);
            for (int k = 0; k < nb; ++k) {
                if (has_val(bs[k].u, extra)) {
                    out_step = {target, bs[k].op, bs[k].rev ? x : bs[k].u, bs[k].rev ? bs[k].u : x};
                    return true;
                }
            }
            return false;
        };
        for (i64 x : atoms) {
            if (try_base(x)) return true;
        }
        for (i64 x : extra) {
            if (try_base(x)) return true;
        }
        return false;
    };

    struct DemHit { i64 val; int ri; };
    std::vector<DemHit> dem_hits;
    dem_hits.reserve(static_cast<size_t>(K) * atoms.size());
    for (int i = 0; i < K; ++i) {
        WBackStep bs[6];
        for (i64 x : atoms) {
            int nb = gen_win_inverses(roots[i], x, limit, bs);
            for (int k = 0; k < nb; ++k) {
                i64 y = bs[k].u;
                if (y != roots[i] && ws.small_idx.get(y) < 0) {
                    dem_hits.push_back({y, i});
                }
            }
        }
    }
    std::sort(dem_hits.begin(), dem_hits.end(), [](const DemHit& a, const DemHit& b) {
        return (a.val != b.val) ? (a.val < b.val) : (a.ri < b.ri);
    });
    struct RankedDem { int neg_hits; int has_fwd_pen; i64 val; };
    std::vector<RankedDem> ranked;
    for (size_t idx = 0; idx < dem_hits.size();) {
        i64 v = dem_hits[idx].val;
        unsigned mask = 0;
        while (idx < dem_hits.size() && dem_hits[idx].val == v) {
            mask |= (1u << dem_hits[idx].ri);
            ++idx;
        }
        int hits = __builtin_popcount(mask);
        if (hits >= 2) {
            ExStep tmp{};
            ranked.push_back({-hits, lookup_forward(v, tmp) ? 0 : 1, v});
        }
    }
    std::sort(ranked.begin(), ranked.end(), [](const RankedDem& a, const RankedDem& b) {
        return std::tie(a.neg_hits, a.has_fwd_pen, a.val) <
               std::tie(b.neg_hits, b.has_fwd_pen, b.val);
    });

    std::vector<ExStep> answer;
    auto finish_single_last = [&](std::vector<ExStep>& code,
                                  std::vector<i64>& extra,
                                  i64 last_t) -> bool {
        ExStep helper{}, ending{};
        WBackStep bs[6];
        auto try_close = [&](i64 x) -> bool {
            int nb = gen_win_inverses(last_t, x, limit, bs);
            for (int k = 0; k < nb; ++k) {
                i64 y = bs[k].u;
                if (y == last_t || has_val(y, extra)) continue;
                if (lookup_forward(y, helper) || single_extra(extra, y, helper)) {
                    ending = {last_t, bs[k].op, bs[k].rev ? x : y, bs[k].rev ? y : x};
                    return true;
                }
            }
            return false;
        };
        for (i64 x : atoms) {
            if (try_close(x)) break;
        }
        if (!ending.x) {
            for (i64 x : extra) {
                if (try_close(x)) break;
            }
        }
        if (ending.x) {
            code.push_back(helper);
            code.push_back(ending);
            extra.push_back(helper.x);
            extra.push_back(ending.x);
            return true;
        }
        return false;
    };

    auto complete = [&](std::vector<ExStep> code) {
        std::vector<i64> extra;
        extra.reserve(code.size() + static_cast<size_t>(K) + 2);
        for (const auto& op : code) extra.push_back(op.x);
        bool progress = true;
        for (int r = 0; r < K && progress; ++r) {
            progress = false;
            for (i64 t : roots) {
                if (has_val(t, extra)) continue;
                ExStep step{};
                if (single_extra(extra, t, step)) {
                    extra.push_back(t);
                    code.push_back(step);
                    progress = true;
                }
            }
        }
        int missing = 0;
        i64 last_t = 0;
        for (i64 t : roots) {
            if (!has_val(t, extra)) {
                ++missing;
                last_t = t;
            }
        }
        if (missing == 1 && static_cast<int>(code.size()) + 2 <= allowed) {
            if (finish_single_last(code, extra, last_t)) missing = 0;
        }
        if (missing != 0 || code.empty() || static_cast<int>(code.size()) > allowed) return;
        if (answer.empty() || code.size() < answer.size()) answer = std::move(code);
    };

    complete({});
    const size_t dem_limit = std::min<size_t>(ranked.size(), 36);
    for (size_t i = 0; i < dem_limit; ++i) {
        i64 h = ranked[i].val;
        ExStep hstep{};
        if (lookup_forward(h, hstep)) {
            complete({hstep});
            continue;
        }
        if (K + 2 > allowed) continue;
        WBackStep bs[6];
        for (i64 x : atoms) {
            int nb = gen_win_inverses(h, x, limit, bs);
            bool solved = false;
            for (int k = 0; k < nb; ++k) {
                i64 y = bs[k].u;
                ExStep ystep{};
                if (y != h && lookup_forward(y, ystep)) {
                    complete({ystep, {h, bs[k].op, bs[k].rev ? x : y, bs[k].rev ? y : x}});
                    solved = true;
                    break;
                }
            }
            if (solved) break;
        }
    }

    // Exact subset bitmask bundle DP + 1-remaining-root 2-step closure
    struct Bundle {
        unsigned hits = 0;
        ExStep stem{};
        std::array<ExStep, 6> root{};
    };
    const unsigned all = (1u << K) - 1u;
    unsigned ready0 = 0;
    std::vector<ExStep> direct;
    std::vector<i64> anchored_extra;
    for (int i = 0; i < K; ++i) {
        ExStep step{};
        if (single_extra({}, roots[i], step)) {
            ready0 |= (1u << i);
            direct.push_back(step);
            anchored_extra.push_back(roots[i]);
        }
    }
    std::vector<i64> allowed_atoms = atoms;
    for (i64 v : anchored_extra) {
        if (ws.small_idx.get(v) < 0) allowed_atoms.push_back(v);
    }

    std::map<i64, Bundle> bundles;
    for (int i = 0; i < K; ++i) {
        if (ready0 & (1u << i)) continue;
        WBackStep bs[6];
        for (i64 x : allowed_atoms) {
            int nb = gen_win_inverses(roots[i], x, limit, bs);
            for (int k = 0; k < nb; ++k) {
                i64 y = bs[k].u;
                if (y == roots[i]) continue;
                ExStep rstep{roots[i], bs[k].op, bs[k].rev ? x : y, bs[k].rev ? y : x};
                if (has_val(y, anchored_extra)) {
                    auto& item = bundles[0];
                    item.hits |= (1u << i);
                    item.root[i] = rstep;
                } else {
                    ExStep fstep{};
                    if (lookup_forward(y, fstep)) {
                        auto& item = bundles[y];
                        item.hits |= (1u << i);
                        item.stem = fstep;
                        item.root[i] = rstep;
                    }
                }
            }
        }
    }

    std::map<std::pair<unsigned, bool>, std::pair<i64, Bundle>> distinct;
    for (const auto& kv : bundles) {
        if (!kv.second.hits) continue;
        auto dk = std::make_pair(kv.second.hits, kv.first == 0);
        if (!distinct.count(dk)) distinct[dk] = kv;
    }

    std::vector<std::vector<ExStep>> best_dp(all + 1);
    std::vector<uint8_t> visited(all + 1, 0);
    visited[ready0] = 1;
    best_dp[ready0] = direct;

    for (unsigned mask = ready0; mask <= all; ++mask) {
        if (!visited[mask]) continue;
        unsigned rem_mask = all ^ mask;
        if (__builtin_popcount(rem_mask) == 1 &&
            static_cast<int>(best_dp[mask].size()) + 2 <= allowed) {
            int last_i = __builtin_ctz(rem_mask);
            i64 last_t = roots[last_i];
            std::vector<ExStep> cand = best_dp[mask];
            std::vector<i64> extra;
            extra.reserve(cand.size() + 4);
            for (const auto& op : cand) extra.push_back(op.x);
            ExStep step1{};
            if (single_extra(extra, last_t, step1)) {
                cand.push_back(step1);
                if (answer.empty() || cand.size() < answer.size()) answer = std::move(cand);
            } else if (finish_single_last(cand, extra, last_t)) {
                if (static_cast<int>(cand.size()) <= allowed &&
                    (answer.empty() || cand.size() < answer.size())) {
                    answer = std::move(cand);
                }
            }
        }

        for (const auto& dkv : distinct) {
            const auto& item = dkv.second.second;
            unsigned delta = item.hits & ~mask;
            if (!delta) continue;
            unsigned next = mask | delta;
            std::vector<ExStep> code = best_dp[mask];
            if (item.stem.x &&
                std::none_of(code.begin(), code.end(), [&](const ExStep& s) { return s.x == item.stem.x; })) {
                code.push_back(item.stem);
            }
            for (int i = 0; i < K; ++i) {
                if ((delta & (1u << i)) &&
                    std::none_of(code.begin(), code.end(), [&](const ExStep& s) { return s.x == roots[i]; })) {
                    code.push_back(item.root[i]);
                }
            }
            if (static_cast<int>(code.size()) > allowed) continue;
            if (!visited[next] || code.size() < best_dp[next].size()) {
                visited[next] = 1;
                best_dp[next] = std::move(code);
            }
        }
    }

    if (visited[all] && !best_dp[all].empty() &&
        (answer.empty() || best_dp[all].size() < answer.size())) {
        answer = std::move(best_dp[all]);
    }
    return answer;
}

std::vector<ExStep> scaffold_blocks_search(const ExGraph& g,
                                           const ExCut& cut,
                                           i64 limit,
                                           int allowed,
                                           int leaves,
                                           int width,
                                           int depth,
                                           int variant,
                                           WorkerScratch& ws) {
    std::vector<std::pair<double, int>> ranks;
    ranks.reserve(g.nodes.size());
    for (size_t i = 0; i < g.nodes.size(); ++i) {
        if (!cut.terminal[i]) continue;
        const auto& nd = g.nodes[i];
        i64 v = nd.value;
        double w = nd.is_op ? 20.0 : -30.0;
        for (int root : cut.roots) {
            i64 t = g.nodes[root].value;
            i64 delta = (v < t) ? (t - v) : (v - t);
            double favor = 2.1 + 0.21 * std::log2(1.0 + static_cast<double>(delta));
            if (t > v) {
                i64 r = t % v;
                double q = std::log2(1.0 + static_cast<double>(t / v));
                double rem = std::log2(1.0 + static_cast<double>(std::min(r, v - r)));
                favor = std::min(favor, 1.0 + ((variant & 1) ? 0.24 : 0.16) * q + 0.28 * rem);
            }
            w = std::min(w, favor);
        }
        if (v < 40) w -= 5.0;
        if (v > 0 && (v & (v - 1)) == 0) w -= 4.0;
        ranks.emplace_back(w, static_cast<int>(i));
    }
    size_t keep_leaves = std::min(ranks.size(), static_cast<size_t>(leaves));
    std::partial_sort(ranks.begin(), ranks.begin() + keep_leaves, ranks.end());

    ws.small_idx.clear();
    std::vector<i64> ready_leaves;
    ready_leaves.reserve(keep_leaves);
    for (size_t i = 0; i < keep_leaves; ++i) {
        i64 v = g.nodes[ranks[i].second].value;
        if (ws.small_idx.insert(v, 1)) ready_leaves.push_back(v);
    }

    BeamDict d(limit, ws.beam_idx);
    d.build(ready_leaves);

    std::vector<i64> goals;
    goals.reserve(cut.roots.size());
    for (int r : cut.roots) goals.push_back(g.nodes[r].value);
    const int K = static_cast<int>(goals.size());
    if (K == 0 || K > 6) return {};

    auto in_code = [&](i64 val, const std::vector<ExStep>& code) -> bool {
        if (ws.small_idx.get(val) >= 0) return true;
        for (const auto& s : code) {
            if (s.x == val) return true;
        }
        return false;
    };

    auto add_step = [&](const ExStep& st, std::vector<ExStep>& out, const std::vector<ExStep>& prefix) {
        if (!in_code(st.x, prefix) && !in_code(st.x, out)) out.push_back(st);
    };

    auto fetch_dict = [&](auto&& self, int id, std::vector<ExStep>& out, const std::vector<ExStep>& prefix) -> void {
        const auto& e = d.e[id];
        if (in_code(e.v, prefix) || in_code(e.v, out)) return;
        if (e.cost == 0) return;
        self(self, e.a, out, prefix);
        self(self, e.b, out, prefix);
        add_step({e.v, e.op, d.e[e.a].v, d.e[e.b].v}, out, prefix);
    };

    auto mix_val = [](u64& hash, i64 x) {
        u64 z = static_cast<u64>(x) + 0x9e3779b97f4a7c15ULL;
        z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ULL;
        z = (z ^ (z >> 27)) * 0x94d049bb133111ebULL;
        hash ^= z ^ (z >> 31);
    };

    auto sig_of = [&](const std::vector<ExStep>& code) -> u64 {
        u64 h = 0;
        for (const auto& s : code) mix_val(h, s.x);
        return h;
    };

    auto metrics_of = [&](const std::vector<ExStep>& code) -> std::pair<int, unsigned> {
        unsigned mask = 0;
        for (int i = 0; i < K; ++i) {
            if (in_code(goals[i], code)) mask |= (1u << i);
        }
        return {__builtin_popcount(mask), mask};
    };

    std::vector<std::vector<std::vector<ExStep>>> options(K);
    for (int gi = 0; gi < K; ++gi) {
        i64 t = goals[gi];
        int maximum = std::min(depth, allowed - K + 1);
        if (maximum < 1 || ws.small_idx.get(t) >= 0) continue;
        std::unordered_set<u64> seen;
        std::vector<std::vector<ExStep>> found;
        auto take = [&](std::vector<ExStep> plan) {
            if (!plan.empty() && static_cast<int>(plan.size()) <= maximum &&
                seen.insert(sig_of(plan)).second) {
                found.push_back(std::move(plan));
            }
        };
        int exact = d.index.get(t);
        if (exact >= 0) {
            std::vector<ExStep> plan;
            fetch_dict(fetch_dict, exact, plan, {});
            take(std::move(plan));
        }
        int stop = (depth >= 5) ? static_cast<int>(d.e.size()) : d.n1;
        WBackStep bs[6];
        for (int j = 0; j < stop; ++j) {
            i64 b = d.e[j].v;
            int nb = gen_win_inverses(t, b, limit, bs);
            for (int k = 0; k < nb; ++k) {
                i64 a = bs[k].u;
                int id_i = d.index.get(a);
                if (id_i < 0 || a == t || b == t) continue;
                const auto& ex = d.e[id_i];
                const auto& ey = d.e[j];
                if (ex.cost + ey.cost > maximum && id_i != j) continue;
                if (j >= d.n1 && id_i <= j) continue;
                std::vector<ExStep> code;
                fetch_dict(fetch_dict, id_i, code, {});
                fetch_dict(fetch_dict, j, code, {});
                add_step({t, bs[k].op, bs[k].rev ? b : a, bs[k].rev ? a : b}, code, {});
                take(std::move(code));
            }
        }
        auto rank_plan = [&](const std::vector<ExStep>& code) -> int {
            int cover = metrics_of(code).first;
            int discounts = 0;
            WBackStep rbs[6];
            for (const auto& step : code) {
                for (int i = 0; i < K; ++i) {
                    if (i == gi || step.x == goals[i]) continue;
                    int nr = gen_win_inverses(goals[i], step.x, limit, rbs);
                    bool direct = false;
                    for (int rk = 0; rk < nr; ++rk) {
                        if (d.index.get(rbs[rk].u) >= 0) {
                            direct = true;
                            break;
                        }
                    }
                    discounts += direct ? 1 : 0;
                }
            }
            return static_cast<int>(code.size()) * 8 - cover * 7 - std::min(5, discounts);
        };
        std::vector<std::pair<int, size_t>> order;
        order.reserve(found.size());
        for (size_t i = 0; i < found.size(); ++i) order.emplace_back(rank_plan(found[i]), i);
        size_t keep = std::min(order.size(), static_cast<size_t>(std::max(4, width * 2)));
        std::partial_sort(order.begin(), order.begin() + keep, order.end());
        for (size_t i = 0; i < keep; ++i) {
            options[gi].push_back(std::move(found[order[i].second]));
        }
    }

    // Forward multi-output beam search
    struct FState {
        std::vector<ExStep> code;
        unsigned covered = 0;
        int rank = 0;
    };
    auto [done0, bits0] = metrics_of({});
    std::vector<FState> frontier{{{}, bits0, 0}};
    std::vector<ExStep> best;

    for (int level = 0; level < K && !frontier.empty(); ++level) {
        std::vector<FState> next;
        std::unordered_set<u64> seen;
        for (const auto& state : frontier) {
            int ceiling = best.empty() ? allowed : static_cast<int>(best.size()) - 1;
            for (int i = 0; i < K; ++i) {
                if (state.covered & (1u << i)) continue;
                int move_budget = ceiling - static_cast<int>(state.code.size());
                if (move_budget < 1) continue;
                std::vector<std::vector<ExStep>> moves;
                for (const auto& recipe : options[i]) {
                    std::vector<ExStep> extra;
                    for (const auto& s : recipe) add_step(s, extra, state.code);
                    if (!extra.empty() && static_cast<int>(extra.size()) <= move_budget) {
                        moves.push_back(std::move(extra));
                    }
                }
                WBackStep bs[6];
                for (const auto& pstep : state.code) {
                    i64 b = pstep.x;
                    if (b == goals[i]) continue;
                    int nb = gen_win_inverses(goals[i], b, limit, bs);
                    for (int k = 0; k < nb; ++k) {
                        i64 a = bs[k].u;
                        if (a == goals[i]) continue;
                        ExStep finish{goals[i], bs[k].op, bs[k].rev ? b : a, bs[k].rev ? a : b};
                        if (in_code(a, state.code)) {
                            moves.push_back({finish});
                        } else {
                            int at = d.index.get(a);
                            if (move_budget > 1 && at >= 0 && d.e[at].cost < move_budget) {
                                std::vector<ExStep> extra;
                                fetch_dict(fetch_dict, at, extra, state.code);
                                add_step(finish, extra, state.code);
                                if (!extra.empty() && static_cast<int>(extra.size()) <= move_budget) {
                                    moves.push_back(std::move(extra));
                                }
                            }
                        }
                    }
                }

                for (const auto& mv : moves) {
                    std::vector<ExStep> cand = state.code;
                    cand.insert(cand.end(), mv.begin(), mv.end());
                    auto [count, mask] = metrics_of(cand);
                    int remaining = K - count;
                    if (static_cast<int>(cand.size()) + remaining > ceiling) continue;
                    if (remaining == 0) {
                        if (best.empty() || cand.size() < best.size()) {
                            best = std::move(cand);
                            ceiling = static_cast<int>(best.size()) - 1;
                        }
                        continue;
                    }
                    if (!seen.insert(sig_of(cand)).second) continue;
                    int future = 0;
                    for (int j = 0; j < K; ++j) {
                        if (mask & (1u << j)) continue;
                        int so_far = std::min(4, allowed);
                        for (const auto& opt : options[j]) {
                            int cost = 0;
                            for (const auto& os : opt) {
                                if (!in_code(os.x, cand)) ++cost;
                            }
                            so_far = std::min(so_far, cost);
                        }
                        for (const auto& s : cand) {
                            int nb2 = gen_win_inverses(goals[j], s.x, limit, bs);
                            for (int k2 = 0; k2 < nb2; ++k2) {
                                int nidx = d.index.get(bs[k2].u);
                                if (nidx >= 0) so_far = std::min(so_far, 1 + d.e[nidx].cost);
                            }
                        }
                        future += so_far;
                    }
                    int rank = 4 * static_cast<int>(cand.size()) + 3 * future + remaining;
                    next.push_back({std::move(cand), mask, rank});
                }
            }
        }
        std::stable_sort(next.begin(), next.end(), [](const FState& a, const FState& b) {
            return std::make_pair(a.rank, a.code.size()) < std::make_pair(b.rank, b.code.size());
        });
        if (static_cast<int>(next.size()) > width) next.resize(static_cast<size_t>(width));
        frontier = std::move(next);
    }

    // Bounded set-based backward search over unresolved value sets
    struct BNeed {
        std::vector<i64> pending;
        std::vector<ExStep> reverse;
        double rank = 0.0;
    };
    auto bit_len = [](i64 v) -> int {
        return v > 0 ? (64 - __builtin_clzll(static_cast<u64>(v))) : 0;
    };
    auto infer_cost = [&](i64 x) -> double {
        int id = d.index.get(x);
        if (id >= 0) return static_cast<double>(d.e[id].cost);
        return 2.5 + 0.035 * static_cast<double>(bit_len(x));
    };

    std::vector<i64> init_pending;
    for (i64 gv : goals) {
        if (ws.small_idx.get(gv) < 0) init_pending.push_back(gv);
    }
    std::sort(init_pending.begin(), init_pending.end());
    init_pending.erase(std::unique(init_pending.begin(), init_pending.end()), init_pending.end());

    std::vector<i64> atoms = ready_leaves;
    int span1 = d.n1 - d.n0;
    int sample_cnt = std::min(span1, 36);
    for (int i = 0; i < sample_cnt; ++i) {
        i64 v = d.e[d.n0 + (span1 * i) / sample_cnt].v;
        if (ws.small_idx.get(v) < 0) atoms.push_back(v);
    }

    int max_bw = 4;
    int ceiling = best.empty() ? allowed : static_cast<int>(best.size()) - 1;
    std::vector<BNeed> bqueue;
    if (!init_pending.empty()) bqueue.push_back({init_pending, {}, 0.0});

    for (int level = 0; level < ceiling && !bqueue.empty(); ++level) {
        std::vector<BNeed> next;
        std::unordered_set<u64> signatures;
        for (const auto& state : bqueue) {
            if (static_cast<int>(state.reverse.size() + state.pending.size()) > ceiling) continue;
            for (i64 x : state.pending) {
                auto is_defined = [&](i64 val) -> bool {
                    for (const auto& op : state.reverse) {
                        if (op.x == val) return true;
                    }
                    return false;
                };
                auto candidate = [&](i64 a, i64 b, Op op) {
                    if (a <= 0 || b <= 0 || a == x || b == x || is_defined(a) || is_defined(b)) return;
                    if (apply_op(op, a, b, limit) != x) return;
                    BNeed n = state;
                    n.reverse.push_back({x, op, a, b});
                    auto it_p = std::find(n.pending.begin(), n.pending.end(), x);
                    if (it_p != n.pending.end()) n.pending.erase(it_p);
                    if (ws.small_idx.get(a) < 0) n.pending.push_back(a);
                    if (ws.small_idx.get(b) < 0) n.pending.push_back(b);
                    std::sort(n.pending.begin(), n.pending.end());
                    n.pending.erase(std::unique(n.pending.begin(), n.pending.end()), n.pending.end());
                    int work = static_cast<int>(n.reverse.size() + n.pending.size());
                    if (work > ceiling) return;
                    if (n.pending.empty()) {
                        ceiling = static_cast<int>(n.reverse.size()) - 1;
                        best.assign(n.reverse.rbegin(), n.reverse.rend());
                        return;
                    }
                    double future = 0.0;
                    for (i64 pv : n.pending) future += infer_cost(pv);
                    n.rank = static_cast<double>(n.reverse.size()) + 0.78 * future +
                             0.19 * static_cast<double>(n.pending.size());
                    u64 key = sig_of(n.reverse);
                    for (i64 pv : n.pending) mix_val(key, static_cast<i64>(static_cast<u64>(pv) ^ 0xb492b66fbe98f273ULL));
                    if (!signatures.insert(key).second) return;
                    next.push_back(std::move(n));
                };

                int fixed = d.index.get(x);
                if (fixed >= 0 && d.e[fixed].cost > 0) {
                    const auto& ex = d.e[fixed];
                    candidate(d.e[ex.a].v, d.e[ex.b].v, ex.op);
                }
                for (int gi = 0; gi < K; ++gi) {
                    if (goals[gi] == x) {
                        for (const auto& opt : options[gi]) {
                            if (!opt.empty() && opt.back().x == x) {
                                candidate(opt.back().a, opt.back().b, opt.back().op);
                            }
                        }
                    }
                }
                WBackStep bs[6];
                auto expand_b = [&](i64 b) {
                    if (b == x || is_defined(b)) return;
                    int nb = gen_win_inverses(x, b, limit, bs);
                    for (int k = 0; k < nb; ++k) {
                        i64 a = bs[k].u;
                        bool shared = std::binary_search(state.pending.begin(), state.pending.end(), a);
                        if (a < x || shared || d.index.get(a) >= 0) {
                            candidate(bs[k].rev ? b : a, bs[k].rev ? a : b, bs[k].op);
                        }
                    }
                };
                for (i64 b : state.pending) expand_b(b);
                for (i64 b : atoms) expand_b(b);
            }
        }
        size_t keep = std::min<size_t>(next.size(), static_cast<size_t>(max_bw));
        std::partial_sort(next.begin(), next.begin() + keep, next.end(), [](const BNeed& a, const BNeed& b) {
            if (a.rank != b.rank) return a.rank < b.rank;
            if (a.pending.size() != b.pending.size()) return a.pending.size() < b.pending.size();
            return a.pending < b.pending;
        });
        next.resize(keep);
        bqueue = std::move(next);
    }

    return best;
}

std::vector<Instr> replace_ex_block(const Puzzle& p,
                                    const ExGraph& g,
                                    const ExCut& cut,
                                    const std::vector<ExStep>& plan,
                                    int cap) {
    ExGraph draft = g;
    std::unordered_map<i64, int> known, outputs;
    known.reserve(g.nodes.size() * 2 + plan.size() * 2 + 8);
    for (size_t i = 0; i < g.nodes.size(); ++i) {
        if (cut.terminal[i]) known.emplace(g.nodes[i].value, static_cast<int>(i));
    }
    for (int r : cut.roots) outputs.emplace(g.nodes[r].value, r);

    for (const auto& step : plan) {
        if (known.count(step.x)) continue;
        auto ita = known.find(step.a);
        auto itb = known.find(step.b);
        if (ita == known.end() || itb == known.end()) return {};
        if (apply_op(step.op, step.a, step.b, p.limit) != step.x) return {};
        ExNode nd{step.x, step.op, ita->second, itb->second, true};
        auto have = outputs.find(step.x);
        if (have != outputs.end()) {
            known.emplace(step.x, have->second);
            draft.nodes[have->second] = nd;
        } else {
            known.emplace(step.x, static_cast<int>(draft.nodes.size()));
            draft.nodes.push_back(nd);
        }
    }
    for (const auto& kv : outputs) {
        if (!known.count(kv.first)) return {};
    }

    draft = topo_ex_graph(draft);
    DagGraph dg;
    dg.defs.reserve(draft.nodes.size() + 4);
    dg.order.reserve(draft.nodes.size());
    for (const auto& nd : draft.nodes) {
        if (nd.is_op) {
            dg.defs[nd.value] = {nd.op, draft.nodes[nd.a].value, draft.nodes[nd.b].value};
            dg.order.push_back(nd.value);
        }
    }
    if (static_cast<int>(dg.defs.size()) >= cap) return {};

    std::vector<Instr> cand;
    dag_reallocate_cap(p, dg, cand, cap, 32);
    if (!cand.empty() && static_cast<int>(cand.size()) < cap && verify_program(p, cand)) {
        return cand;
    }
    return {};
}

inline bool same_prog(const std::vector<Instr>& a, const std::vector<Instr>& b) {
    if (a.size() != b.size()) return false;
    for (size_t i = 0; i < a.size(); ++i) {
        if (a[i].op != b[i].op || a[i].i != b[i].i || a[i].j != b[i].j || a[i].d != b[i].d) {
            return false;
        }
    }
    return true;
}

void scaffold_exchange_pass(const Puzzle& p,
                            const std::vector<Instr>& start_prog,
                            std::vector<Instr>& best,
                            WorkerScratch& ws,
                            bool run_blocks,
                            int blocks_max_cuts = 6,
                            int blocks_leaves = 32) {
    if (start_prog.size() <= 3) return;
    std::vector<Instr> incumbent = start_prog;

    for (int round = 0; round < 2; ++round) {
        ExGraph g = recover_ex_graph(p, incumbent);
        int logical = 0;
        for (const auto& nd : g.nodes) logical += nd.is_op ? 1 : 0;

        ws.pair_table.clear();
        const int n = static_cast<int>(g.nodes.size());
        for (int i = 0; i < n; ++i) {
            i64 a = g.nodes[i].value;
            for (int j = 0; j <= i; ++j) {
                i64 b = g.nodes[j].value;
                if (a <= p.limit - b) {
                    ws.pair_table.add(a + b, static_cast<uint16_t>(i), static_cast<uint16_t>(j), OP_ADD);
                }
                if (a != b) {
                    ws.pair_table.add(a > b ? a - b : b - a,
                                      static_cast<uint16_t>(a > b ? i : j),
                                      static_cast<uint16_t>(a > b ? j : i), OP_SUB);
                }
                i128 prod = static_cast<i128>(a) * b;
                if (prod <= p.limit) {
                    ws.pair_table.add(static_cast<i64>(prod), static_cast<uint16_t>(i), static_cast<uint16_t>(j), OP_MUL);
                }
                if (a >= b && b > 0 && a % b == 0) {
                    ws.pair_table.add(a / b, static_cast<uint16_t>(i), static_cast<uint16_t>(j), OP_DIV);
                }
                if (b > a && a > 0 && b % a == 0) {
                    ws.pair_table.add(b / a, static_cast<uint16_t>(j), static_cast<uint16_t>(i), OP_DIV);
                }
            }
        }

        auto todo = generate_scaffold_cuts(g, 44, round);
        bool improved = false;
        std::vector<Instr> plateau;
        int blocks_tried = 0;

        for (const auto& task : todo) {
            ExCut cut = make_ex_cut(g, task.rim);
            int cap = static_cast<int>(best.size()) + (round == 0 ? 1 : 0);
            int allowed = std::min(20, cap - 1 - logical + cut.budget);
            if (allowed < static_cast<int>(task.rim.size())) continue;

            auto try_plan = [&](const std::vector<ExStep>& plan) -> bool {
                if (plan.empty()) return false;
                auto cand = replace_ex_block(p, g, cut, plan, cap);
                if (cand.empty()) return false;
                if (cand.size() < best.size() && verify_program(p, cand)) {
                    best = std::move(cand);
                    improved = true;
                    return true;
                }
                if (cand.size() == best.size() && plateau.empty() && !same_prog(cand, incumbent) &&
                    verify_program(p, cand)) {
                    plateau = std::move(cand);
                }
                return false;
            };

            auto plan = scaffold_back_join(g, cut, p.limit, allowed, ws);
            bool got_win = try_plan(plan);
            if (run_blocks && !got_win && blocks_tried < blocks_max_cuts &&
                task.rim.size() <= 4 && (cut.budget - static_cast<int>(task.rim.size())) >= 2) {
                ++blocks_tried;
                auto bplan = scaffold_blocks_search(g, cut, p.limit, allowed, blocks_leaves, 6, 4, round, ws);
                try_plan(bplan);
            }
        }

        if (improved) {
            elide_helpers_pass(p, best);
            window_and_cut_sweep(p, best);
            incumbent = best;
        } else if (!plateau.empty()) {
            incumbent = std::move(plateau);
        } else {
            break;
        }
    }
}

// --- Stage 1 (Mode 1): Backward Quotient-Remainder Beam DAG Synthesizer ---

class BeamDagSolver {
public:
    BeamDagSolver(const Puzzle& p, FastIndex& idx, int width = 10, double alpha = 0.18,
                  int n_done = 56, int n_recent = 68)
        : p_(p), idx_(idx), width_(width), alpha_(alpha), n_done_(n_done), n_recent_(n_recent) {}

    std::vector<Instr> solve() {
        setup();
        BeamDict dict(p_.limit, idx_);
        std::set<i64> done;
        std::vector<i64> sorted_targets = p_.targets;
        std::sort(sorted_targets.begin(), sorted_targets.end());
        sorted_targets.erase(std::unique(sorted_targets.begin(), sorted_targets.end()), sorted_targets.end());

        for (i64 target : sorted_targets) {
            if (!defs_.count(target)) {
                std::vector<i64> leaves;
                std::unordered_set<i64> used;
                auto add_leaf = [&](i64 v) {
                    if (v > 0 && used.insert(v).second) leaves.push_back(v);
                };
                for (i64 v : palette_) add_leaf(v);
                for (i64 v : p_.starts) add_leaf(v);
                for (auto it = done.rbegin(); it != done.rend() && static_cast<int>(leaves.size()) < n_done_; ++it) {
                    add_leaf(*it);
                }
                for (auto it = order_.rbegin(); it != order_.rend() && static_cast<int>(leaves.size()) < n_recent_; ++it) {
                    add_leaf(*it);
                }
                dict.build(leaves);
                run_search(dict, target);
            }
            done.insert(target);
        }

        // Convert to minimal needed DAG and lower to physical registers
        std::unordered_set<i64> starts_set(p_.starts.begin(), p_.starts.end());
        std::unordered_map<i64, DagDef> needed_defs;
        std::vector<i64> stk;
        for (i64 t : sorted_targets) {
            if (!starts_set.count(t)) stk.push_back(t);
        }
        std::unordered_set<i64> keep;
        while (!stk.empty()) {
            i64 x = stk.back();
            stk.pop_back();
            if (starts_set.count(x) || keep.count(x)) continue;
            auto it = args_.find(x);
            if (it == args_.end()) continue;
            keep.insert(x);
            stk.push_back(it->second.first);
            stk.push_back(it->second.second);
        }
        for (i64 v : keep) {
            needed_defs[v] = {defs_.at(v), args_.at(v).first, args_.at(v).second};
        }
        DagGraph dag;
        dag.defs = std::move(needed_defs);
        dag.order = topo_from_targets(starts_set, dag.defs, sorted_targets);

        std::vector<Instr> out;
        dag_reallocate(p_, dag, out);
        if (!out.empty()) window_and_cut_sweep(p_, out);
        return out;
    }

private:
    const Puzzle& p_;
    FastIndex& idx_;
    int width_;
    double alpha_;
    int n_done_;
    int n_recent_;

    std::unordered_map<i64, Op> defs_;
    std::unordered_map<i64, std::pair<i64, i64>> args_;
    std::vector<i64> order_;
    std::vector<i64> palette_;

    i64 make_val(Op op, i64 a, i64 b) {
        i64 v = apply_op(op, a, b, p_.limit);
        if (v <= 0) throw std::runtime_error("BeamDagSolver invalid construction");
        if (!defs_.count(v)) {
            defs_[v] = op;
            args_[v] = {a, b};
            order_.push_back(v);
        }
        return v;
    }

    i64 make_power(int k) {
        i64 v = 1LL << k;
        if (defs_.count(v)) return v;
        if (k == 1) return make_val(OP_ADD, 1, 1);
        i64 right = make_power(k - k / 2);
        i64 left = make_power(k / 2);
        return make_val(OP_MUL, left, right);
    }

    i64 make_binary(i64 v) {
        if (defs_.count(v)) return v;
        i64 h = make_binary(v / 2);
        i64 twice = make_val(OP_ADD, h, h);
        return (v % 2) ? make_val(OP_ADD, twice, 1) : twice;
    }

    void setup() {
        for (i64 v : p_.starts) defs_[v] = OP_ADD;
        if (!defs_.count(1)) make_val(OP_DIV, p_.starts[0], p_.starts[0]);
        palette_ = {1};
        for (int k : {1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 16, 20, 24, 32, 40, 48}) {
            if ((static_cast<i128>(1) << k) <= p_.limit) {
                palette_.push_back(make_power(k));
            }
        }
        for (i64 i : {3, 5, 7, 9, 11, 13, 15, 17, 19, 23, 31}) {
            if (i <= p_.limit) {
                if (!defs_.count(i)) {
                    if ((i == 11 || i == 13) && defs_.count(8) && defs_.count(i - 8)) {
                        make_val(OP_ADD, i - 8, 8);
                    } else if ((i == 19 || i == 23) && defs_.count(16) && defs_.count(i - 16)) {
                        make_val(OP_ADD, i - 16, 16);
                    } else if (((i & (i + 1)) == 0) && (i + 1 <= p_.limit) && defs_.count(i + 1)) {
                        make_val(OP_SUB, i + 1, 1);
                    } else {
                        make_binary(i);
                    }
                }
                palette_.push_back(i);
            }
        }
    }

    i64 materialize(const BeamDict& d, int id) {
        const auto& ex = d.e[id];
        if (defs_.count(ex.v)) return ex.v;
        i64 right = materialize(d, ex.b);
        i64 left = materialize(d, ex.a);
        return make_val(ex.op, left, right);
    }

    struct Link {
        int factor = -1;
        int atom = -1;
        char op = '+';  // '+', '-', 'r' (atom - child)
    };
    struct State {
        i64 v = 0;
        int cost = 0;
        int parent = -1;
        Link link{};
        double rank = 0.0;
    };

    void run_search(const BeamDict& d, i64 target) {
        int id0 = d.index.get(target);
        if (id0 >= 0) {
            materialize(d, id0);
            return;
        }
        int best = 1000, end = -1, terminal = -1;
        std::vector<State> history;
        std::vector<State> next;
        std::unordered_map<i64, int> visited;
        history.push_back({target, 0, -1, {}, 0.0});

        auto expr_cost = [&](int eid) -> int { return (eid < 0) ? 0 : 1 + d.e[eid].cost; };
        auto offer = [&](int p, i64 v, int f, int a, char op) {
            if (v <= 0 || v > d.limit) return;
            int cost = history[p].cost + expr_cost(f) + expr_cost(a);
            if (cost >= best) return;
            int t = d.index.get(v);
            if (t >= 0) {
                if (cost + d.e[t].cost < best) {
                    best = cost + d.e[t].cost;
                    end = static_cast<int>(history.size());
                    terminal = t;
                    history.push_back({v, cost, p, {f, a, op}, 0.0});
                }
                return;
            }
            if (cost + 3 >= best || v >= history[p].v) return;
            double rank = cost + alpha_ * std::log2(static_cast<double>(v));
            if (static_cast<int>(next.size()) == width_ && rank >= next.back().rank) return;
            auto prev = visited.find(v);
            if (prev != visited.end() && prev->second <= cost) return;
            for (auto it = next.begin(); it != next.end(); ++it) {
                if (it->v == v) {
                    if (it->cost <= cost) return;
                    next.erase(it);
                    break;
                }
            }
            State s{v, cost, p, {f, a, op}, rank};
            auto it = std::upper_bound(next.begin(), next.end(), rank,
                                       [](double k, const State& x) { return k < x.rank; });
            next.insert(it, s);
            if (static_cast<int>(next.size()) > width_) next.pop_back();
        };

        auto shifted = [&](int p, i64 diff, int atom, char op) {
            int k = __builtin_ctzll(static_cast<u64>(diff));
            while (k >= 4) {
                if (k < 62) {
                    int f = d.index.get(1LL << k);
                    if (f >= 0) {
                        offer(p, diff >> k, f, atom, op);
                        break;
                    }
                }
                --k;
            }
        };

        auto expand = [&](int p) {
            i64 v = history[p].v;
            for (const auto& arr : d.sorted) {
                auto it = std::lower_bound(arr.begin(), arr.end(), std::make_pair(v, -1));
                for (int k = -4; k < 4; ++k) {
                    auto pos = (it - arr.begin()) + k;
                    if (pos < 0 || pos >= static_cast<ptrdiff_t>(arr.size())) continue;
                    i64 a = arr[pos].first;
                    int aid = arr[pos].second;
                    if (v != a) offer(p, std::abs(v - a), -1, aid, v > a ? '+' : 'r');
                }
            }
            for (int i = 0; i < d.n1; ++i) {
                i64 a = d.e[i].v;
                if (a == 1) continue;
                i64 diff = std::abs(v - a);
                if (diff > 0) {
                    if (d.index.get(diff) >= 0) offer(p, diff, -1, i, v > a ? '+' : 'r');
                    if (v > a && (diff & 15) == 0) shifted(p, diff, i, '+');
                    if (a > v && (diff & 15) == 0) shifted(p, diff, i, 'r');
                }
                if (a <= d.limit - v) {
                    i64 sum = a + v;
                    if (d.index.get(sum) >= 0) offer(p, sum, -1, i, '-');
                    if ((sum & 15) == 0) shifted(p, sum, i, '-');
                }
                if (a >= v) continue;
                i64 q = v / a, r = v % a;
                if (r == 0) {
                    offer(p, q, i, -1, '+');
                    continue;
                }
                int rid = d.index.get(r);
                if (rid >= 0) offer(p, q, i, rid, '+');
                if (a - r <= d.limit - v) {
                    rid = d.index.get(a - r);
                    if (rid >= 0) offer(p, q + 1, i, rid, '-');
                }
                if (i < d.n0 && q > 64) {
                    for (const auto& arr : d.sorted) {
                        auto it = std::lower_bound(arr.begin(), arr.end(), std::make_pair(q, -1));
                        for (int k = -1; k <= 0; ++k) {
                            auto pos = (it - arr.begin()) + k;
                            if (pos < 0 || pos >= static_cast<ptrdiff_t>(arr.size())) continue;
                            i64 b = arr[pos].first;
                            if (b <= 0 || a > d.limit / b) continue;
                            i64 mul = a * b;
                            if (mul == v) continue;
                            int mid = d.index.get(mul);
                            if (mid >= 0) offer(p, std::abs(mul - v), -1, mid, mul < v ? '+' : 'r');
                        }
                    }
                }
            }
        };

        std::vector<int> front{0};
        for (int depth = 0; depth < 20 && !front.empty(); ++depth) {
            next.clear();
            for (int p : front) {
                if (history[p].cost + 3 < best) expand(p);
            }
            front.clear();
            for (const auto& s : next) {
                if (s.cost + 3 >= best) continue;
                visited[s.v] = s.cost;
                front.push_back(static_cast<int>(history.size()));
                history.push_back(s);
            }
        }

        if (end < 0) {
            make_binary(target);
            return;
        }
        i64 v = materialize(d, terminal);
        for (int p = end; history[p].parent >= 0; p = history[p].parent) {
            Link l = history[p].link;
            if (l.factor >= 0) v = make_val(OP_MUL, v, materialize(d, l.factor));
            if (l.atom >= 0) {
                i64 a = materialize(d, l.atom);
                if (l.op == 'r') v = make_val(OP_SUB, a, v);
                else if (l.op == '+') v = make_val(OP_ADD, v, a);
                else v = make_val(OP_SUB, v, a);
            }
        }
    }
};

// --- Fallback Real-Register Synthesizer (from v1) ---

struct BackStep {
    i64 x;
    Op op;
    bool x_left;
};

inline int gen_backs(i64 res, i64 c, i64 L, BackStep* out) {
    int n = 0;
    if (res > c) out[n++] = {res - c, OP_ADD, true};
    if (res <= L - c) out[n++] = {res + c, OP_SUB, true};
    if (c > res) out[n++] = {c - res, OP_SUB, false};
    if (c > 1 && res % c == 0) out[n++] = {res / c, OP_MUL, true};
    if (c > 1 && static_cast<i128>(res) * c <= L) out[n++] = {res * c, OP_DIV, true};
    if (c > res && c % res == 0) out[n++] = {c / res, OP_DIV, false};
    return n;
}

struct P1Item { i64 val; Op op; uint8_t ra; uint8_t rb; };
struct P2Item { i64 val; int p1_idx; Op op; uint8_t rc; bool p1_left; };
struct PlanStep { Op op; int a; int b; };

struct Plan {
    std::vector<PlanStep> steps;
    int push(Op op, int a, int b) {
        steps.push_back({op, a, b});
        return -static_cast<int>(steps.size());
    }
    void clear() { steps.clear(); }
};

struct SolverConfig {
    int seed_mode = 1;
    int bucket_cap = 2;
    bool sort_asc = false;
    int max_p2 = 80000;
};

class RealMachineSolver {
public:
    RealMachineSolver(const Puzzle& p, FlatMap& p2_map, SolverConfig cfg = {})
        : p_(p), p2_map_(p2_map), cfg_(cfg) {
        regs_.fill(0);
        valid_.fill(false);
        last_used_.fill(0);
        for (size_t k = 0; k < p_.starts.size(); ++k) {
            regs_[k] = p_.starts[k];
            valid_[k] = true;
            last_used_[k] = 1;
        }
        all_targets_ = p_.targets;
        std::sort(all_targets_.begin(), all_targets_.end());
        all_targets_.erase(std::unique(all_targets_.begin(), all_targets_.end()), all_targets_.end());
        for (i64 t : all_targets_) {
            if (std::find(p_.starts.begin(), p_.starts.end(), t) == p_.starts.end()) {
                remaining_.push_back(t);
            }
        }
    }

    std::vector<Instr> solve() {
        seed_essential_smalls();
        while (!remaining_.empty()) {
            rebuild_tables();
            bool removed_any = false;
            for (int idx = static_cast<int>(remaining_.size()) - 1; idx >= 0; --idx) {
                if (find_reg(remaining_[idx]) >= 0) {
                    remaining_.erase(remaining_.begin() + idx);
                    removed_any = true;
                }
            }
            if (removed_any && remaining_.empty()) break;
            if (removed_any) rebuild_tables();

            int best_idx = 0;
            int best_cost = std::numeric_limits<int>::max();
            Plan best_plan;

            for (int idx = 0; idx < static_cast<int>(remaining_.size()); ++idx) {
                Plan cand;
                if (try_exact(remaining_[idx], cand, 2)) {
                    int c = static_cast<int>(cand.steps.size());
                    if (c < best_cost || (c == best_cost && remaining_[idx] < remaining_[best_idx])) {
                        best_cost = c;
                        best_idx = idx;
                        best_plan = std::move(cand);
                    }
                }
            }
            if (best_cost <= 2) {
                remaining_.erase(remaining_.begin() + best_idx);
                execute_plan(best_plan);
                continue;
            }
            int chosen_idx = 0;
            double best_score = 1e18;
            for (int idx = 0; idx < static_cast<int>(remaining_.size()); ++idx) {
                double est = estimate_target_difficulty(remaining_[idx]) + (cfg_.sort_asc ? idx * 1.5 : 0.0);
                if (est < best_score) {
                    best_score = est;
                    chosen_idx = idx;
                }
            }
            i64 goal = remaining_[chosen_idx];
            remaining_.erase(remaining_.begin() + chosen_idx);
            solve_target_recursive(goal, 0, 0ULL, true);
        }
        dead_code_eliminate_prog(p_, prog_);
        return prog_;
    }

private:
    const Puzzle& p_;
    FlatMap& p2_map_;
    SolverConfig cfg_;
    std::array<i64, kNumRegs> regs_;
    std::array<bool, kNumRegs> valid_;
    std::array<int, kNumRegs> last_used_;
    int clock_ = 1;
    std::vector<i64> all_targets_;
    std::vector<i64> remaining_;
    std::vector<Instr> prog_;
    std::vector<std::pair<i64, uint8_t>> v_sorted_;
    std::vector<P1Item> p1_sorted_;
    std::vector<P2Item> p2_items_;
    std::vector<std::pair<i64, int>> p2_sorted_;

    int find_reg(i64 val) const {
        for (int r = 0; r < p_.registers; ++r) {
            if (valid_[r] && regs_[r] == val) return r;
        }
        return -1;
    }

    int emit_instr(Op op, int ri, int rj, u64 pinned_mask) {
        i64 res = apply_op(op, regs_[ri], regs_[rj], p_.limit);
        if (res <= 0) throw std::runtime_error("Illegal op in emit_instr");
        int existing = find_reg(res);
        if (existing >= 0) {
            last_used_[existing] = ++clock_;
            return existing;
        }
        int rd = pick_dest_reg(ri, rj, pinned_mask);
        prog_.push_back({op, static_cast<uint8_t>(ri), static_cast<uint8_t>(rj), static_cast<uint8_t>(rd)});
        regs_[rd] = res;
        valid_[rd] = true;
        last_used_[ri] = ++clock_;
        last_used_[rj] = ++clock_;
        last_used_[rd] = ++clock_;
        return rd;
    }

    int pick_dest_reg(int ri, int rj, u64 pinned_mask) const {
        for (int r = 0; r < p_.registers; ++r) {
            if (!valid_[r]) return r;
        }
        for (int r = 0; r < p_.registers; ++r) {
            if (r == ri || r == rj || ((pinned_mask >> r) & 1ULL)) continue;
            for (int r2 = 0; r2 < p_.registers; ++r2) {
                if (r2 != r && valid_[r2] && regs_[r2] == regs_[r]) return r;
            }
        }
        std::array<int, 17> bucket_count{};
        for (int r = 0; r < p_.registers; ++r) {
            if (!valid_[r] || regs_[r] <= 0) continue;
            int bits = 64 - __builtin_clzll(static_cast<u64>(regs_[r]));
            bucket_count[std::min(16, bits / 4)]++;
        }
        int best_r = -1;
        double best_util = 1e18;
        for (int r = 0; r < p_.registers; ++r) {
            if (r == ri || r == rj || ((pinned_mask >> r) & 1ULL)) continue;
            i64 val = regs_[r];
            double util = 0.0;
            if (val == 1) util += 5000.0;
            else if (val <= 64) util += 2500.0;
            else if (val <= 4096) util += 800.0;
            if (val == 4 || val == 16 || val == 256 || val == 65536) util += 2000.0;
            if (r < static_cast<int>(p_.starts.size())) util += 300.0;
            int bits = 64 - __builtin_clzll(static_cast<u64>(val));
            int b = std::min(16, bits / 4);
            if (bucket_count[b] <= cfg_.bucket_cap) util += 3500.0;
            else util -= static_cast<double>(bucket_count[b] - cfg_.bucket_cap) * 800.0;
            bool is_anchor = false;
            for (i64 rem_t : remaining_) {
                if (rem_t == val) { util += 1e9; is_anchor = true; break; }
                i64 diff = std::abs(rem_t - val);
                if (diff <= 50000 || diff * 100 <= rem_t) {
                    util += 10000.0;
                    is_anchor = true;
                } else {
                    i64 q = (rem_t + val / 2) / val;
                    if (q >= 2 && q <= 64 && std::abs(rem_t - q * val) <= 50000) {
                        util += 8000.0;
                        is_anchor = true;
                    }
                }
            }
            if (!is_anchor && std::binary_search(all_targets_.begin(), all_targets_.end(), val) && val > 4096) {
                util -= 600.0;
            }
            util += static_cast<double>(last_used_[r]) * 0.01;
            if (util < best_util) {
                best_util = util;
                best_r = r;
            }
        }
        if (best_r >= 0) return best_r;
        for (int r = 0; r < p_.registers; ++r) {
            if (r != ri && r != rj) return r;
        }
        return 0;
    }

    void seed_essential_smalls() {
        if (find_reg(1) < 0) emit_instr(OP_DIV, 0, 0, 0ULL);
        i64 max_t = all_targets_.empty() ? 0 : all_targets_.back();
        if (p_.limit >= 2 && find_reg(2) < 0) {
            int r1 = find_reg(1);
            if (r1 >= 0) emit_instr(OP_ADD, r1, r1, 0ULL);
        }
        if (cfg_.seed_mode == 0) return;
        if (max_t >= 20 && p_.limit >= 3 && find_reg(3) < 0) {
            int r1 = find_reg(1), r2 = find_reg(2);
            if (r1 >= 0 && r2 >= 0) emit_instr(OP_ADD, r1, r2, 0ULL);
        }
        if (max_t >= 64 && p_.limit >= 4 && find_reg(4) < 0) {
            int r2 = find_reg(2);
            if (r2 >= 0) emit_instr(OP_MUL, r2, r2, 0ULL);
        }
        if (max_t >= 1000 && p_.limit >= 16 && find_reg(16) < 0) {
            int r4 = find_reg(4);
            if (r4 >= 0) emit_instr(OP_MUL, r4, r4, 0ULL);
        }
        if (max_t >= 100000 && p_.limit >= 256 && find_reg(256) < 0) {
            int r16 = find_reg(16);
            if (r16 >= 0) emit_instr(OP_MUL, r16, r16, 0ULL);
        }
        if (max_t >= 100000000LL && p_.limit >= 65536 && find_reg(65536) < 0) {
            int r256 = find_reg(256);
            if (r256 >= 0) emit_instr(OP_MUL, r256, r256, 0ULL);
        }
        if (cfg_.seed_mode >= 2 && max_t >= 10000000000000LL && p_.limit >= 4294967296LL && find_reg(4294967296LL) < 0) {
            int r65k = find_reg(65536);
            if (r65k >= 0) emit_instr(OP_MUL, r65k, r65k, 0ULL);
        }
    }

    void rebuild_tables(bool build_p2 = true) {
        v_sorted_.clear();
        for (int r = 0; r < p_.registers; ++r) {
            if (valid_[r]) v_sorted_.push_back({regs_[r], static_cast<uint8_t>(r)});
        }
        std::sort(v_sorted_.begin(), v_sorted_.end());
        v_sorted_.erase(std::unique(v_sorted_.begin(), v_sorted_.end(),
                                    [](const auto& a, const auto& b) { return a.first == b.first; }),
                        v_sorted_.end());
        p1_sorted_.clear();
        const int nv = static_cast<int>(v_sorted_.size());
        p1_sorted_.reserve(nv * nv * 2);
        for (int a = 0; a < nv; ++a) {
            i64 va = v_sorted_[a].first;
            uint8_t ra = v_sorted_[a].second;
            for (int b = a; b < nv; ++b) {
                i64 vb = v_sorted_[b].first;
                uint8_t rb = v_sorted_[b].second;
                i64 s = apply_op(OP_ADD, va, vb, p_.limit);
                if (s > 0 && find_reg(s) < 0) p1_sorted_.push_back({s, OP_ADD, ra, rb});
                i64 m = apply_op(OP_MUL, va, vb, p_.limit);
                if (m > 0 && find_reg(m) < 0) p1_sorted_.push_back({m, OP_MUL, ra, rb});
                if (vb > va && find_reg(vb - va) < 0) p1_sorted_.push_back({vb - va, OP_SUB, rb, ra});
                if (va > 0 && vb % va == 0 && find_reg(vb / va) < 0) p1_sorted_.push_back({vb / va, OP_DIV, rb, ra});
            }
        }
        std::sort(p1_sorted_.begin(), p1_sorted_.end(), [](const P1Item& x, const P1Item& y) {
            if (x.val != y.val) return x.val < y.val;
            if (x.op != y.op) return x.op < y.op;
            if (x.ra != y.ra) return x.ra < y.ra;
            return x.rb < y.rb;
        });
        p1_sorted_.erase(std::unique(p1_sorted_.begin(), p1_sorted_.end(),
                                     [](const P1Item& x, const P1Item& y) { return x.val == y.val; }),
                         p1_sorted_.end());

        p2_map_.clear();
        p2_items_.clear();
        p2_sorted_.clear();
        if (!build_p2) return;
        const size_t kMaxP2 = static_cast<size_t>(cfg_.max_p2);
        p2_items_.reserve(std::min<size_t>(kMaxP2, p1_sorted_.size() * v_sorted_.size() * 2));
        const int np1 = static_cast<int>(p1_sorted_.size());
        constexpr int kStride = 23;
        for (int phase = 0; phase < std::min(kStride, np1) && p2_items_.size() < kMaxP2; ++phase) {
            for (int idx = phase; idx < np1 && p2_items_.size() < kMaxP2; idx += kStride) {
                i64 vx = p1_sorted_[idx].val;
                for (const auto& vr : v_sorted_) {
                    i64 vc = vr.first;
                    uint8_t rc = vr.second;
                    auto try_add = [&](i64 val, Op op, bool p1_left) {
                        if (val <= 0 || p2_items_.size() >= kMaxP2) return;
                        int p2_id = static_cast<int>(p2_items_.size());
                        if (p2_map_.insert(static_cast<u64>(val), p2_id)) {
                            p2_items_.push_back({val, idx, op, rc, p1_left});
                        }
                    };
                    try_add(apply_op(OP_ADD, vx, vc, p_.limit), OP_ADD, true);
                    try_add(apply_op(OP_MUL, vx, vc, p_.limit), OP_MUL, true);
                    if (vx > vc) try_add(vx - vc, OP_SUB, true);
                    else if (vc > vx) try_add(vc - vx, OP_SUB, false);
                    if (vc > 1 && vx % vc == 0) try_add(vx / vc, OP_DIV, true);
                    if (vx > 1 && vc % vx == 0) try_add(vc / vx, OP_DIV, false);
                    if (p2_items_.size() >= kMaxP2) break;
                }
            }
        }
        p2_sorted_.reserve(p2_items_.size());
        for (int i = 0; i < static_cast<int>(p2_items_.size()); ++i) p2_sorted_.push_back({p2_items_[i].val, i});
        std::sort(p2_sorted_.begin(), p2_sorted_.end());
    }

    const P1Item* find_p1(i64 v) const {
        auto it = std::lower_bound(p1_sorted_.begin(), p1_sorted_.end(), v,
                                   [](const P1Item& e, i64 t) { return e.val < t; });
        return (it != p1_sorted_.end() && it->val == v) ? &(*it) : nullptr;
    }

    int emit_p1(const P1Item& e, Plan& pl) const { return pl.push(e.op, e.ra, e.rb); }
    int emit_p2(const P2Item& e2, Plan& pl) const {
        int r1 = emit_p1(p1_sorted_[e2.p1_idx], pl);
        return e2.p1_left ? pl.push(e2.op, r1, e2.rc) : pl.push(e2.op, e2.rc, r1);
    }

    bool try_exact(i64 t, Plan& out, int max_depth = 4) const {
        out.clear();
        if (t <= 0 || t > p_.limit) return false;
        if (find_reg(t) >= 0) return true;
        if (const P1Item* e1 = find_p1(t)) { emit_p1(*e1, out); return true; }
        int id2 = p2_map_.find(static_cast<u64>(t));
        if (id2 >= 0) { emit_p2(p2_items_[id2], out); return true; }
        for (const auto& e1 : p1_sorted_) {
            BackStep bs[6];
            int nb = gen_backs(t, e1.val, p_.limit, bs);
            for (int k = 0; k < nb; ++k) {
                if (const P1Item* other = find_p1(bs[k].x)) {
                    int r_a = emit_p1(*other, out), r_b = emit_p1(e1, out);
                    if (bs[k].x_left) out.push(bs[k].op, r_a, r_b);
                    else out.push(bs[k].op, r_b, r_a);
                    return true;
                }
            }
        }
        for (const auto& vr : v_sorted_) {
            BackStep bs[6];
            int nb = gen_backs(t, vr.first, p_.limit, bs);
            for (int k = 0; k < nb; ++k) {
                int pid = p2_map_.find(static_cast<u64>(bs[k].x));
                if (pid >= 0) {
                    int r_a = emit_p2(p2_items_[pid], out);
                    if (bs[k].x_left) out.push(bs[k].op, r_a, vr.second);
                    else out.push(bs[k].op, vr.second, r_a);
                    return true;
                }
            }
        }
        if (max_depth < 4) return false;
        for (const auto& e1 : p1_sorted_) {
            BackStep bs[6];
            int nb = gen_backs(t, e1.val, p_.limit, bs);
            for (int k = 0; k < nb; ++k) {
                int pid = p2_map_.find(static_cast<u64>(bs[k].x));
                if (pid >= 0) {
                    int r_p2 = emit_p2(p2_items_[pid], out), r_p1 = emit_p1(e1, out);
                    if (bs[k].x_left) out.push(bs[k].op, r_p2, r_p1);
                    else out.push(bs[k].op, r_p1, r_p2);
                    return true;
                }
            }
        }
        return false;
    }

    int execute_plan(const Plan& pl, u64 ext_pinned = 0ULL) {
        std::vector<int> step_regs;
        step_regs.reserve(pl.steps.size());
        auto resolve = [&](int operand) -> int {
            return (operand >= 0) ? operand : step_regs[static_cast<size_t>(-operand - 1)];
        };
        for (size_t s = 0; s < pl.steps.size(); ++s) {
            const auto& st = pl.steps[s];
            int ri = resolve(st.a), rj = resolve(st.b);
            u64 step_pin = ext_pinned;
            for (size_t rem_s = s + 1; rem_s < pl.steps.size(); ++rem_s) {
                if (pl.steps[rem_s].a >= 0) step_pin |= (1ULL << pl.steps[rem_s].a);
                else {
                    int dep = -pl.steps[rem_s].a - 1;
                    if (dep < static_cast<int>(step_regs.size())) step_pin |= (1ULL << step_regs[dep]);
                }
                if (pl.steps[rem_s].b >= 0) step_pin |= (1ULL << pl.steps[rem_s].b);
                else {
                    int dep = -pl.steps[rem_s].b - 1;
                    if (dep < static_cast<int>(step_regs.size())) step_pin |= (1ULL << step_regs[dep]);
                }
            }
            step_regs.push_back(emit_instr(st.op, ri, rj, step_pin));
        }
        return step_regs.empty() ? -1 : step_regs.back();
    }

    double estimate_target_difficulty(i64 t) const {
        double t_bits = std::log2(static_cast<double>(t) + 1.0);
        i64 best_rem = t;
        auto chk = [&](i64 approx) {
            if (approx > 0) best_rem = std::min(best_rem, std::abs(t - approx));
        };
        auto itv = std::lower_bound(v_sorted_.begin(), v_sorted_.end(), t,
                                    [](const auto& e, i64 val) { return e.first < val; });
        if (itv != v_sorted_.end()) chk(itv->first);
        if (itv != v_sorted_.begin()) chk(std::prev(itv)->first);
        auto itp = std::lower_bound(p1_sorted_.begin(), p1_sorted_.end(), t,
                                    [](const P1Item& e, i64 val) { return e.val < val; });
        if (itp != p1_sorted_.end()) chk(itp->val);
        if (itp != p1_sorted_.begin()) chk(std::prev(itp)->val);
        if (best_rem == 0) return 0.0;
        return std::min(t_bits, 2.0 + std::log2(static_cast<double>(best_rem) + 1.0));
    }

    struct CandSpec {
        i64 approx_val = 0, residual = 0;
        double rate = 0.0;
        uint8_t kind = 0;
        Op op = OP_ADD;
        int idx1 = -1, idx2 = -1;
        uint8_t cost = 0;
    };

    Plan materialize_cand(const CandSpec& c) const {
        Plan pl;
        if (c.kind == 0) return pl;
        if (c.kind == 1) { emit_p1(p1_sorted_[c.idx1], pl); return pl; }
        if (c.kind == 2) { int r1 = emit_p1(p1_sorted_[c.idx1], pl); pl.push(c.op, r1, c.idx2); return pl; }
        if (c.kind == 3) {
            int r1 = emit_p1(p1_sorted_[c.idx1], pl), r2 = emit_p1(p1_sorted_[c.idx2], pl);
            pl.push(c.op, r1, r2);
            return pl;
        }
        if (c.kind == 4) { emit_p2(p2_items_[c.idx1], pl); return pl; }
        if (c.kind == 5) { int r1 = emit_p2(p2_items_[c.idx1], pl); pl.push(c.op, r1, c.idx2); return pl; }
        if (c.kind == 6) {
            int r1 = emit_p2(p2_items_[c.idx1], pl), r2 = emit_p1(p1_sorted_[c.idx2], pl);
            pl.push(c.op, r1, r2);
            return pl;
        }
        int r1 = emit_p2(p2_items_[c.idx1], pl), r2 = emit_p2(p2_items_[c.idx2], pl);
        pl.push(c.op, r1, r2);
        return pl;
    }

    std::vector<CandSpec> generate_approximations(i64 t) const {
        std::vector<CandSpec> specs;
        specs.reserve(2048);
        const double t_bits = std::log2(static_cast<double>(t) + 1.0);
        auto record = [&](uint8_t kind, Op op, int idx1, int idx2, uint8_t plan_cost, i64 val) {
            if (val <= 0 || val > p_.limit || val == t) return;
            i64 r = std::abs(t - val);
            if (r >= t) return;
            double rate = (t_bits - std::log2(static_cast<double>(r) + 1.0)) / static_cast<double>(plan_cost + 1);
            if (rate > 0.25) specs.push_back({val, r, rate, kind, op, idx1, idx2, plan_cost});
        };

        auto itv = std::lower_bound(v_sorted_.begin(), v_sorted_.end(), t,
                                    [](const auto& e, i64 val) { return e.first < val; });
        if (itv != v_sorted_.end()) record(0, OP_ADD, itv->second, -1, 0, itv->first);
        if (itv != v_sorted_.begin()) record(0, OP_ADD, std::prev(itv)->second, -1, 0, std::prev(itv)->first);

        auto itp = std::lower_bound(p1_sorted_.begin(), p1_sorted_.end(), t,
                                    [](const P1Item& e, i64 val) { return e.val < val; });
        for (int off = -2; off <= 2; ++off) {
            int idx = static_cast<int>(itp - p1_sorted_.begin()) + off;
            if (idx >= 0 && idx < static_cast<int>(p1_sorted_.size())) record(1, OP_ADD, idx, -1, 1, p1_sorted_[idx].val);
        }
        for (int b = 0; b < static_cast<int>(p1_sorted_.size()); ++b) {
            i64 vb = p1_sorted_[b].val;
            if (vb < 2) continue;
            i64 q = t / vb;
            if (q < 1) continue;
            auto itq = std::lower_bound(p1_sorted_.begin(), p1_sorted_.end(), q,
                                        [](const P1Item& e, i64 val) { return e.val < val; });
            for (int off = -1; off <= 1; ++off) {
                int idx = static_cast<int>(itq - p1_sorted_.begin()) + off;
                if (idx >= 0 && idx < static_cast<int>(p1_sorted_.size())) {
                    i64 av = apply_op(OP_MUL, p1_sorted_[idx].val, vb, p_.limit);
                    if (av > 0) record(3, OP_MUL, idx, b, 3, av);
                }
            }
        }
        if (!p2_sorted_.empty()) {
            const int np2 = static_cast<int>(p2_sorted_.size());
            auto cmp_p2 = [](const std::pair<i64, int>& e, i64 val) { return e.first < val; };
            auto it2 = std::lower_bound(p2_sorted_.begin(), p2_sorted_.end(), t, cmp_p2);
            for (int off = -2; off <= 2; ++off) {
                int idx = static_cast<int>(it2 - p2_sorted_.begin()) + off;
                if (idx >= 0 && idx < np2) record(4, OP_ADD, p2_sorted_[idx].second, -1, 2, p2_sorted_[idx].first);
            }
            const int p1_step = std::max(1, static_cast<int>(p1_sorted_.size()) / 600);
            for (int b = 0; b < static_cast<int>(p1_sorted_.size()); b += p1_step) {
                i64 vb = p1_sorted_[b].val;
                if (vb < 2) continue;
                i64 q = t / vb;
                if (q < 1) continue;
                auto itq = std::lower_bound(p2_sorted_.begin(), p2_sorted_.end(), q, cmp_p2);
                for (int off = -1; off <= 0; ++off) {
                    int idx = static_cast<int>(itq - p2_sorted_.begin()) + off;
                    if (idx >= 0 && idx < np2) {
                        i64 av = apply_op(OP_MUL, p2_sorted_[idx].first, vb, p_.limit);
                        if (av > 0) record(6, OP_MUL, p2_sorted_[idx].second, b, 4, av);
                    }
                }
            }
        }
        std::sort(specs.begin(), specs.end(), [](const CandSpec& a, const CandSpec& b) {
            if (a.rate != b.rate) return a.rate > b.rate;
            return a.residual < b.residual;
        });
        if (specs.size() > 32) specs.resize(32);
        return specs;
    }

    int solve_target_recursive(i64 t, int depth, u64 pinned_mask, bool tables_ready = false) {
        int existing = find_reg(t);
        if (existing >= 0) return existing;
        if (!tables_ready) rebuild_tables(false);
        Plan exact_pl;
        if (try_exact(t, exact_pl, (depth == 0 ? 4 : 3))) return execute_plan(exact_pl, pinned_mask);
        if (depth >= 10) {
            int r_cur = find_reg(1);
            if (r_cur < 0) r_cur = emit_instr(OP_DIV, 0, 0, pinned_mask);
            int top_bit = 63 - __builtin_clzll(static_cast<u64>(t));
            for (int bit = top_bit - 1; bit >= 0; --bit) {
                r_cur = emit_instr(OP_ADD, r_cur, r_cur, pinned_mask);
                if ((t >> bit) & 1LL) {
                    int r1 = find_reg(1);
                    if (r1 < 0) r1 = emit_instr(OP_DIV, 0, 0, pinned_mask | (1ULL << r_cur));
                    r_cur = emit_instr(OP_ADD, r_cur, r1, pinned_mask);
                }
            }
            return r_cur;
        }
        auto cands = generate_approximations(t);
        if (cands.empty()) {
            int rh = solve_target_recursive(t / 2, depth + 1, pinned_mask);
            int r2h = emit_instr(OP_ADD, rh, rh, pinned_mask);
            if (t % 2 == 0) return r2h;
            int r1 = find_reg(1);
            if (r1 < 0) r1 = emit_instr(OP_DIV, 0, 0, pinned_mask | (1ULL << r2h));
            return emit_instr(OP_ADD, r2h, r1, pinned_mask);
        }
        int chosen_idx = 0;
        double best_total_est = 1e18;
        int check_limit = std::min<int>(16, static_cast<int>(cands.size()));
        for (int i = 0; i < check_limit; ++i) {
            i64 r = cands[i].residual;
            int exact_r_cost = -1;
            if (find_reg(r) >= 0) exact_r_cost = 0;
            else if (find_p1(r) != nullptr) exact_r_cost = 1;
            else if (p2_map_.find(static_cast<u64>(r)) >= 0) exact_r_cost = 2;
            double total_est = (exact_r_cost >= 0)
                                   ? static_cast<double>(cands[i].cost + 1 + exact_r_cost)
                                   : (static_cast<double>(cands[i].cost + 1) + estimate_target_difficulty(r) * 0.45);
            if (total_est < best_total_est) {
                best_total_est = total_est;
                chosen_idx = i;
            }
        }
        const auto& chosen = cands[chosen_idx];
        i64 approx_val = chosen.approx_val;
        i64 residual = chosen.residual;
        Plan approx_plan = materialize_cand(chosen);
        int r_approx = approx_plan.steps.empty() ? find_reg(approx_val) : execute_plan(approx_plan, pinned_mask);
        if (r_approx < 0) r_approx = solve_target_recursive(approx_val, depth + 1, pinned_mask);
        int r_res = solve_target_recursive(residual, depth + 1, pinned_mask | (1ULL << r_approx));
        r_approx = find_reg(approx_val);
        if (r_approx < 0) {
            r_approx = solve_target_recursive(approx_val, depth + 1, pinned_mask | (1ULL << r_res));
            r_res = find_reg(residual);
        }
        return emit_instr((t > approx_val) ? OP_ADD : OP_SUB, r_approx, r_res, pinned_mask);
    }
};

// Mode 1 solver per puzzle
std::vector<Instr> solve_puzzle(const Puzzle& p, WorkerScratch& ws) {
    std::vector<Instr> tiny_prog;
    if (try_solve_tiny(p, tiny_prog)) return tiny_prog;

    std::vector<Instr> best;

    // 1. Beam DAG synthesizer (fast cache-resident deterministic configuration)
    {
        BeamDagSolver bds(p, ws.beam_idx, 10, 0.18, 48, 56);
        auto cand = bds.solve();
        if (!cand.empty() && verify_program(p, cand)) {
            best = std::move(cand);
        }
    }

    // 2. RealMachineSolver fallback (only if BeamDagSolver failed or produced empty)
    if (best.empty()) {
        i64 max_t = p.targets.empty() ? 0 : *std::max_element(p.targets.begin(), p.targets.end());
        SolverConfig cfg;
        cfg.seed_mode = (max_t >= 100000000000000LL) ? 2 : 1;
        cfg.bucket_cap = 2;
        cfg.sort_asc = false;
        cfg.max_p2 = 60000;
        RealMachineSolver rms(p, ws.p2_map, cfg);
        auto rms_prog = rms.solve();
        if (verify_program(p, rms_prog)) best = std::move(rms_prog);
    }

    if (!best.empty()) {
        DagGraph dg = extract_needed_dag(p, best);
        dag_peephole_and_cofactor(p, dg, best, ws);
        dag_deep_chain_and_reversal(p, best, ws);
        window_and_cut_sweep(p, best);
        scaffold_exchange_pass(p, best, best, ws, false);
        dag_deep_chain_and_reversal(p, best, ws);
    }

    if (best.empty() || !verify_program(p, best)) {
        throw std::runtime_error("Internal verification failed for puzzle " + p.id);
    }
    return best;
}

std::vector<i64> get_prog_values(const Puzzle& p, const std::vector<Instr>& prog) {
    std::array<i64, kNumRegs> regs{};
    for (size_t k = 0; k < p.starts.size(); ++k) regs[k] = p.starts[k];
    std::vector<i64> vals;
    vals.reserve(p.starts.size() + prog.size());
    for (i64 s : p.starts) vals.push_back(s);
    for (const auto& ins : prog) {
        i64 v = apply_op(ins.op, regs[ins.i], regs[ins.j], p.limit);
        regs[ins.d] = v;
        vals.push_back(v);
    }
    std::sort(vals.begin(), vals.end());
    vals.erase(std::unique(vals.begin(), vals.end()), vals.end());
    return vals;
}

size_t symmetric_diff_size(const std::vector<i64>& a, const std::vector<i64>& b) {
    size_t i = 0, j = 0, diff = 0;
    while (i < a.size() && j < b.size()) {
        if (a[i] < b[j]) {
            ++diff;
            ++i;
        } else if (b[j] < a[i]) {
            ++diff;
            ++j;
        } else {
            ++i;
            ++j;
        }
    }
    diff += (a.size() - i) + (b.size() - j);
    return diff;
}

// Mode 2 optimizer per puzzle
std::vector<Instr> optimize_puzzle(const Puzzle& p,
                                   const std::vector<std::vector<Instr>>& bank_progs,
                                   WorkerScratch& ws) {
    std::vector<Instr> best;
    for (const auto& cand : bank_progs) {
        if (cand.empty()) continue;
        if (best.empty() || cand.size() < best.size()) best = cand;
    }
    if (best.empty()) return solve_puzzle(p, ws);

    // Select diverse donor contexts: best + up to 3 diverse traces within best.size() + 2
    std::vector<i64> best_vals = get_prog_values(p, best);
    std::set<std::vector<i64>> seen_vals;
    seen_vals.insert(best_vals);

    struct DonorCand {
        int neg_diff;
        int size;
        int bank_idx;
        const std::vector<Instr>* prog;
    };
    std::vector<DonorCand> donor_pool;
    for (size_t bi = 0; bi < bank_progs.size(); ++bi) {
        const auto& cand = bank_progs[bi];
        if (cand.empty() || cand.size() > best.size() + 2) continue;
        auto vals = get_prog_values(p, cand);
        if (seen_vals.insert(vals).second) {
            int diff = static_cast<int>(symmetric_diff_size(vals, best_vals));
            donor_pool.push_back({-diff, static_cast<int>(cand.size()), static_cast<int>(bi), &cand});
        }
    }
    std::sort(donor_pool.begin(), donor_pool.end(), [](const DonorCand& a, const DonorCand& b) {
        return std::tie(a.neg_diff, a.size, a.bank_idx) < std::tie(b.neg_diff, b.size, b.bank_idx);
    });
    if (donor_pool.size() > 3) donor_pool.resize(3);

    std::vector<std::vector<Instr>> contexts;
    contexts.reserve(1 + donor_pool.size());
    contexts.push_back(best);
    for (const auto& dc : donor_pool) contexts.push_back(*dc.prog);

    // Collect up to 4 distinct DAGs within best.size() + 2 (prioritizing diverse contexts)
    std::vector<DagGraph> distinct_dags;
    std::set<std::vector<std::tuple<i64, uint8_t, i64, i64>>> seen_dag_keys;
    auto push_dag = [&](const std::vector<Instr>& prog) {
        if (distinct_dags.size() >= 4) return;
        DagGraph dg = extract_needed_dag(p, prog);
        std::vector<std::tuple<i64, uint8_t, i64, i64>> sig;
        sig.reserve(dg.defs.size());
        for (const auto& kv : dg.defs) {
            sig.emplace_back(kv.first, static_cast<uint8_t>(kv.second.op), kv.second.a, kv.second.b);
        }
        std::sort(sig.begin(), sig.end());
        if (seen_dag_keys.insert(std::move(sig)).second) {
            distinct_dags.push_back(std::move(dg));
        }
    };
    for (const auto& ctx : contexts) push_dag(ctx);
    for (const auto& cand : bank_progs) {
        if (cand.empty() || cand.size() > best.size() + 2) continue;
        push_dag(cand);
    }

    // Pass 1: Spill elimination & multi-schedule 48-register lowering on each distinct DAG
    for (const auto& dg : distinct_dags) {
        dag_reallocate(p, dg, best);
    }

    // Pass 2: Acyclic 1/2-op & 2-helper peephole, shared-helper intro, & Pollard-Rho cuts
    for (const auto& dg : distinct_dags) {
        dag_peephole_and_cofactor(p, dg, best, ws);
    }

    const size_t init_sz = best.size();

    // Pass 2c+2d: Fast square-peeling chain resynthesis + dependency reversal on best
    dag_deep_chain_and_reversal(p, best, ws);

    // Pass 2e: Cross-trace multi-donor hypergraph recombination & fresh helper promotion
    cross_trace_recombine_pass(p, distinct_dags, best, ws);

    // Pass 3: Helper elision + 1/2-goal 1..3-step sliding-window & expression cuts
    window_and_cut_sweep(p, best);

    // Pass 5: Complete fan-out scaffold exchange on best + diverse donor contexts
    scaffold_exchange_pass(p, best, best, ws, true);
    for (size_t ci = 1; ci < contexts.size(); ++ci) {
        scaffold_exchange_pass(p, contexts[ci], best, ws, ci == 1);
    }

    // Pass 4: Bounded single-target removal & reverse quotient-remainder search
    target_rebuild_pass(p, best, ws.dict48);

    // Final Pass 1 + Pass 2 + Pass 3 cleanup only if any pass shortened best
    if (best.size() < init_sz) {
        DagGraph best_dag = extract_needed_dag(p, best);
        dag_reallocate(p, best_dag, best);
        dag_peephole_and_cofactor(p, best_dag, best, ws);
        dag_deep_chain_and_reversal(p, best, ws);
        window_and_cut_sweep(p, best);
    }

    if (!verify_program(p, best)) {
        throw std::runtime_error("Internal verification failed after optimize on puzzle " + p.id);
    }
    return best;
}

#include "atlas_splice.hpp"

std::string serialize_program(const std::vector<Instr>& prog) {
    std::string out;
    out.reserve(prog.size() * 14 + 4);
    out.push_back('[');
    for (size_t k = 0; k < prog.size(); ++k) {
        if (k > 0) out.push_back(',');
        out.append("[\"");
        out.push_back(op_char(prog[k].op));
        out.append("\",");
        out.append(std::to_string(prog[k].i));
        out.push_back(',');
        out.append(std::to_string(prog[k].j));
        out.push_back(',');
        out.append(std::to_string(prog[k].d));
        out.push_back(']');
    }
    out.push_back(']');
    return out;
}

void load_bank_csv(const std::string& bank_path,
                   const std::unordered_map<std::string, size_t>& pid_to_idx,
                   const std::vector<Puzzle>& puzzles,
                   std::vector<std::vector<std::vector<Instr>>>& bank_matrix,
                   size_t bank_slot) {
    std::ifstream in(bank_path);
    if (!in) throw std::runtime_error("Cannot open bank CSV: " + bank_path);
    std::string header_line;
    std::getline(in, header_line);
    if (header_line.size() >= 3 &&
        static_cast<unsigned char>(header_line[0]) == 0xEF &&
        static_cast<unsigned char>(header_line[1]) == 0xBB &&
        static_cast<unsigned char>(header_line[2]) == 0xBF) {
        header_line.erase(0, 3);
    }
    auto headers = parse_csv_row(header_line);
    std::unordered_map<std::string, int> col;
    for (int i = 0; i < static_cast<int>(headers.size()); ++i) col[headers[i]] = i;
    int col_id = col.at("id");
    int col_prog = col.at("program");

    std::string line;
    std::vector<Instr> parsed;
    while (std::getline(in, line)) {
        if (line.empty()) continue;
        auto f = parse_csv_row(line);
        if (static_cast<int>(f.size()) <= std::max(col_id, col_prog)) continue;
        auto it = pid_to_idx.find(f[col_id]);
        if (it == pid_to_idx.end()) continue;
        size_t idx = it->second;
        if (parse_program_json(f[col_prog], parsed) && verify_program(puzzles[idx], parsed)) {
            bank_matrix[idx][bank_slot] = std::move(parsed);
        }
    }
}

}  // namespace

int main(int argc, char** argv) {
    bool optimize_mode = false;
    int arg_off = 1;
    bool bridge_mode = argc >= 2 && std::string(argv[1]) == "--bridge-splice";
    bool splice_mode = bridge_mode || (argc >= 2 && std::string(argv[1]) == "--splice");
    if (argc >= 2 && (std::string(argv[1]) == "--optimize" || splice_mode)) {
        optimize_mode = true;
        arg_off = 2;
    }

    if ((!optimize_mode && argc < 3) || (optimize_mode && argc < 6)) {
        std::cerr << "Usage:\n"
                  << "  " << argv[0] << " <puzzles.csv> <output_submission.csv> [num_threads]\n"
                  << "  " << argv[0] << " --optimize <puzzles.csv> <output_submission.csv> <num_threads> <bank1.csv> [bank2.csv ...]\n";
        return 1;
    }

    const std::string puzzles_path = argv[arg_off];
    const std::string out_path = argv[arg_off + 1];
    unsigned int num_threads = std::thread::hardware_concurrency();
    if (argc >= arg_off + 3) {
        num_threads = static_cast<unsigned int>(std::max(1, std::stoi(argv[arg_off + 2])));
    }
    if (num_threads == 0) num_threads = 4;

    auto t0 = std::chrono::steady_clock::now();
    std::vector<Puzzle> puzzles = load_puzzles_csv(puzzles_path);
    std::unordered_map<std::string, size_t> pid_to_idx;
    pid_to_idx.reserve(puzzles.size() * 2);
    for (size_t i = 0; i < puzzles.size(); ++i) pid_to_idx[puzzles[i].id] = i;

    std::vector<std::vector<std::vector<Instr>>> bank_matrix;
    if (optimize_mode) {
        size_t n_banks = static_cast<size_t>(argc - (arg_off + 3));
        bank_matrix.assign(puzzles.size(), std::vector<std::vector<Instr>>(n_banks));
        for (size_t b = 0; b < n_banks; ++b) {
            load_bank_csv(argv[arg_off + 3 + static_cast<int>(b)], pid_to_idx, puzzles, bank_matrix, b);
        }
    }

    std::vector<std::vector<Instr>> results(puzzles.size());
    std::atomic<size_t> next_idx{0};

    std::vector<std::thread> workers;
    workers.reserve(num_threads);
    for (unsigned int w = 0; w < num_threads; ++w) {
        workers.emplace_back([&]() {
            WorkerScratch ws;
            while (true) {
                size_t idx = next_idx.fetch_add(1, std::memory_order_relaxed);
                if (idx >= puzzles.size()) break;
                if (optimize_mode) {
                    results[idx] = splice_mode ? splice_puzzle(puzzles[idx], bank_matrix[idx],bridge_mode) :
                                   optimize_puzzle(puzzles[idx], bank_matrix[idx], ws);
                } else {
                    results[idx] = solve_puzzle(puzzles[idx], ws);
                }
            }
        });
    }
    for (auto& th : workers) th.join();

    std::ofstream out(out_path);
    out << "id,program\n";
    long long total_steps = 0;
    long long total_new_targets = 0;
    std::map<std::string, std::pair<long long, long long>> fam_stats;

    for (size_t idx = 0; idx < puzzles.size(); ++idx) {
        const auto& p = puzzles[idx];
        const auto& prog = results[idx];
        total_steps += static_cast<long long>(prog.size());

        std::vector<i64> uniq_t = p.targets;
        std::sort(uniq_t.begin(), uniq_t.end());
        uniq_t.erase(std::unique(uniq_t.begin(), uniq_t.end()), uniq_t.end());
        long long new_t = 0;
        for (i64 t : uniq_t) {
            if (std::find(p.starts.begin(), p.starts.end(), t) == p.starts.end()) ++new_t;
        }
        total_new_targets += new_t;
        if (!p.family.empty()) {
            fam_stats[p.family].first += static_cast<long long>(prog.size());
            fam_stats[p.family].second += new_t;
        }

        std::string js = serialize_program(prog);
        out << p.id << ",\"";
        for (char c : js) {
            if (c == '"') out << "\"\"";
            else out << c;
        }
        out << "\"\n";
    }
    out.close();

    auto t1 = std::chrono::steady_clock::now();
    double elapsed = std::chrono::duration<double>(t1 - t0).count();
    std::cout << (optimize_mode ? "Optimized " : "Solved ")
              << puzzles.size() << " puzzles in " << std::fixed << std::setprecision(2)
              << elapsed << "s using " << num_threads << " threads\n";
    std::cout << "Total instructions: " << total_steps
              << " (new_targets=" << total_new_targets
              << ", instr/target=" << std::setprecision(3)
              << (static_cast<double>(total_steps) / std::max(1LL, total_new_targets)) << ")\n";
    if (!fam_stats.empty()) {
        std::cout << "Breakdown by family:\n";
        for (const auto& [fam, pr] : fam_stats) {
            std::cout << "  " << std::setw(15) << fam << ": " << pr.first
                      << " instr / " << pr.second << " targets ("
                      << std::setprecision(2) << (static_cast<double>(pr.first) / std::max(1LL, pr.second))
                      << ")\n";
        }
    }
    return 0;
}
