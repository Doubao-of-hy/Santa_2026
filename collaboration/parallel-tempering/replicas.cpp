// Replica exchange of complete physical states. Compile with -I generative/wang.
// The included single-trajectory search and primitive graph moves are from the
// repository's Apache-2.0 Wang extraction. See generative/wang/license-receipt.json.
#include <cstdlib>
#include <stdexcept>
#define main original_search_main
#define Puzzle WangPuzzle
#include "incremental.cpp"
#undef Puzzle
#undef main

struct State {
    Graph graph;
    Tape program;
};

bool same_graph(const Graph& a, const Graph& b) {
    if (a.size() != b.size()) return false;
    for (const auto& [v, r] : a) {
        auto it = b.find(v);
        if (it == b.end()) return false;
        auto other = it->second;
        if (other.op != r.op || other.a != r.a || other.b != r.b) return false;
    }
    return true;
}

struct Replica {
    WangPuzzle engine;
    State state, best;
    int stagnant = 0;
};

struct TemperedPuzzle : WangPuzzle {
    Tape improve(const std::vector<Tape>& tapes) {
        const auto* mode = std::getenv("SANTA_REPLICA_EXCHANGES");
        if (!mode || rounds % 4 || tapes.size() != 1) throw std::runtime_error("Bad replica configuration");
        const bool exchange = std::string(mode) == "1";
        constexpr std::array<double, 4> temperature{.25, .65, 1.4, 2.8};
        constexpr std::array<int, 4> slack{2, 4, 6, 9};
        std::mt19937 swap_rng(rng());
        auto draw = [](auto& gen) { return std::generate_canonical<double, 32>(gen); };
        State first{graph_from(tapes.front()), tapes.front()};
        Tape winner = first.program;
        std::array<Replica, 4> replicas;
        for (auto& r : replicas) {
            r.engine.limit = limit; r.engine.registers = registers;
            r.engine.starts = starts; r.engine.targets = targets;
            r.engine.rounds = rounds; r.engine.max_neighbors = max_neighbors;
            r.engine.rng.seed(rng());
            r.state = r.best = first;
        }
        int attempts = 0, accepted = 0, uphill = 0, resets = 0;
        int swap_tests = 0, swap_accept = 0, different = 0, unequal = 0;
        for (int sweep = 0; sweep < rounds / 4; ++sweep) {
            for (int k = 0; k < 4; ++k) {
                auto& r = replicas[k];
                if (r.stagnant >= 15) { r.state = r.best; r.stagnant = 0; ++resets; }
                auto& e = r.engine;
                std::shuffle(e.targets.begin(), e.targets.end(), e.rng);
                State next{r.state.graph, {}};
                const size_t cap = first.program.size() + slack[k];
                const unsigned width = 2 + k + 2 * std::min(2, r.stagnant / 4) + e.rng() % 4;
                e.perturb(next.graph, cap, width);
                e.rotate(next.graph, cap);
                ++attempts; ++r.stagnant;
                if (!e.compile(next.graph, next.program) || next.program.size() > cap) continue;
                e.knockout(next.graph, next.program);
                double delta = double(next.program.size()) - double(r.state.program.size());
                if (delta > 0 && draw(e.rng) >= std::exp(-delta / temperature[k])) continue;
                ++accepted; uphill += delta > 0;
                r.state = std::move(next);
                if (r.state.program.size() < r.best.program.size()) {
                    r.best = r.state; r.stagnant = 0;
                    if (r.best.program.size() < winner.size()) winner = r.best.program;
                }
            }
            if (!exchange || (sweep + 1) % 3) continue;
            const int first_pair = ((sweep + 1) / 3 - 1) % 2;
            for (int k = first_pair; k < 3; k += 2) {
                ++swap_tests;
                auto &left = replicas[k], &right = replicas[k + 1];
                const double diff = double(left.state.program.size()) - double(right.state.program.size());
                const double exponent = (1.0 / temperature[k] - 1.0 / temperature[k + 1]) * diff;
                const double random = draw(swap_rng);
                if (right.state.program.size() > first.program.size() + slack[k] ||
                    (exponent < 0 && random >= std::exp(exponent))) continue;
                ++swap_accept; different += !same_graph(left.state.graph, right.state.graph);
                unequal += diff != 0;
                std::swap(left.state, right.state);
                for (auto* r : {&left, &right}) if (r->state.program.size() < r->best.program.size()) {
                    r->best = r->state; r->stagnant = 0;
                }
            }
        }
        std::cerr << "replicas " << attempts << ' ' << accepted << ' ' << uphill << ' ' << resets << ' '
                  << swap_tests << ' ' << swap_accept << ' ' << different << ' ' << unequal << '\n';
        return winner;
    }
};

#define Puzzle TemperedPuzzle
#include "main.inc"
