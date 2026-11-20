// Driver for wang Jakie's Apache-2.0 v5 headers. The control calls the upstream crossover.
#include <cmath>
#include <map>
#include <stdexcept>
#include "common.inc"
#include "compact.inc"
    int charged_attempts = 0;
#include "cross_counted.inc"
#include "recipe_lookup.inc"
#include "fast_perturb.inc"

    Tape improve(const std::vector<Tape>& inputs) {
        const Tape& initial = inputs.at(0);
        Graph source = graph_from(initial);
        if (inputs.size() == 1) {
            Graph current = source;
            Tape guide = initial;
            int greatest_difference = 0;
            for (int i = 0; i < rounds; ++i) {
                if (i % 15 == 0) current = source;
                perturb(current, initial.size() + std::max<size_t>(4,initial.size()/20), 7);
                Tape physical;
                if (!compile(current,physical) || physical.size() > initial.size() + std::max<size_t>(4,initial.size()/20)) continue;
                Graph actual = graph_from(physical);
                int difference = 0;
                for (const auto& item : actual) {
                    auto it = source.find(item.first);
                    if (it == source.end()) { ++difference; continue; }
                    auto r = item.second, s = it->second;
                    if (r.op != s.op || r.a != s.a || r.b != s.b) ++difference;
                }
                if (difference > greatest_difference || (difference == greatest_difference && physical.size() < guide.size())) {
                    greatest_difference = difference;
                    guide = physical;
                }
            }
            std::cerr << greatest_difference << "\n";
            return guide;
        }
        std::vector<Graph> parents{source, graph_from(inputs.at(1))};
        Tape answer = initial.size() <= inputs[1].size() ? initial : inputs[1];
        int call = 0;
        while (charged_attempts < rounds) {
            int direction = call++ % 2;
            Graph improved;
            crossover(parents[direction], {parents[1-direction]}, improved, answer);
        }
        std::cerr << charged_attempts << ' ' << call << "\n";
        return answer;
    }
};
#include "main.inc"
