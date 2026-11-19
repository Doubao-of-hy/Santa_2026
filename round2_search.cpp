#include "shared_pivot.hpp"
#include "meet_search.hpp"
int main() {
    std::ios::sync_with_stdio(false);
    Circuit g;
    SearchOptions opt;
    if (!read_circuit(std::cin, g, opt) || opt.width < 1 || opt.width > 63 || opt.depth < 3 ||
        opt.depth > 6)
        return 1;
    for (int i = 0; i < opt.extra; ++i) {
        SharedPivot shared{g, {}, {}, {}, {}, {}};
        if (!shared.run()) break;
        g.print();
    }
    for (int i = 0; i < opt.passes; ++i) {
        MeetSearch meet(g, opt.width, opt.depth, opt.seed + 0x9e3779b9U * i);
        if (meet.run()) g.print();
    }
}
