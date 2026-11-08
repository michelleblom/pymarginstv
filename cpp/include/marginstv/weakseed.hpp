#pragma once

// -weakseed: splitting the candidates standing at a node into strong, weak
// and other, so the node can be expanded into blocks of eliminations
// (split_stats, choose_split and weak_seed_split in stvtree.py).

#include "marginstv/bounds_eqlb.hpp"
#include "marginstv/pynum.hpp"

#include <optional>
#include <span>
#include <vector>

namespace marginstv {

// Every election that follows the node with fewer than k changed ballots
// eliminates all of 'weak' and some subset of 'other', in some order,
// before any strong candidate is eliminated or anyone is seated. x is the
// largest budget the split proves; 'order' is every standing candidate,
// largest tally first.
struct WeakSplit {
    PyNum k;
    double x = 0;
    std::vector<Cand> strong;
    std::vector<Cand> weak;
    std::vector<Cand> other;
    std::vector<Cand> order;
};

// The split to expand a node with, or nothing to expand it normally. Tried
// only where a run of eliminations starts (the prefix is empty or ends with
// a seating). The budget must be at least seedf times orig_ub (or
// running_ub, if lower), with at most max_children children.
std::optional<WeakSplit> weak_seed_split(const BoundInputs& bi, std::span<const Cand> order_c,
                                         std::span<const int> order_a, const OrderQ& order_q,
                                         const PyNum& running_ub, const PyNum& orig_ub,
                                         double seedf, int max_children);

} // namespace marginstv
