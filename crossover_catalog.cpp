// Discover one-operation identities between values found in candidate programs.
#include "round2_graph.hpp"
int main() {
    std::ios::sync_with_stdio(false);
    int n;
    Num limit;
    if (!(std::cin >> limit >> n)) return 1;
    std::vector<Num> values(n);
    Values known;
    for (Num& x : values) {
        std::cin >> x;
        known.insert(x);
    }
    for (int i = 0; i < n; ++i)
        for (int j = 0; j <= i; ++j) {
            Num a = values[i], b = values[j];
            forward(a, b, limit, [&](Num v, Arithmetic e) {
                if (v != a && v != b && known.count(v))
                    std::cout << v << ' ' << e.a << ' ' << e.op << ' ' << e.b << '\n';
            });
        }
}
