#pragma once

// The distance MINLP: the fewest ballot changes that make an outcome prefix
// happen (stvdistance.py and stvdistance-qprefix.py), solved with SCIP.

#include "marginstv/bounds_eqlb.hpp"
#include "marginstv/pynum.hpp"

#include <optional>
#include <span>
#include <string>
#include <vector>

namespace marginstv {

struct DistanceSettings {
    double time_limit = 100;      // -t, for internal nodes
    double leaf_time_limit = 150; // -thard, for leaves
    double gap = 0.01;            // -g
    bool qprefix = false;         // -useqprefix: exact quota rounds
    std::string sidecar_path;     // per-solve CSV (range mode only); empty for none
};

struct DistanceProblem {
    std::span<const Cand> order_c;
    std::span<const int> order_a;
    std::span<const Cand> rem;
    const CandSet* winners = nullptr;
    const OrderQ* order_q = nullptr;
    std::span<const Cand> merge_map; // per original candidate
    std::span<const Cand> supers;
    PyNum upperbound;
    int last_round = 0;
    PyNum lowerbound;
    bool isleaf = false;
};

struct DistanceResult {
    bool feasible = false;
    std::optional<PyNum> dist;    // ceil of the dual bound
    std::optional<PyNum> dist_ub; // ceil of the primal bound, or SCIP's infinity
};

// For tests: write the model SCIP is given (.cip), its changed parameters
// (.set) and objective limit before solving, and optionally skip the solve.
struct ModelDump {
    std::string stem;   // writes stem.cip and stem.set
    bool solve = true;
    double objlimit = 0; // filled in
};

DistanceResult solve_stvdistance(const BoundInputs& bi, const PyNum& tot_ballots,
                                 const DistanceProblem& p, const DistanceSettings& s,
                                 ModelDump* dump = nullptr);

// Ballot equivalence classes over a prefix and its remaining candidates:
// the Python's gen_equivalence_classes order.
std::vector<std::vector<Cand>> equivalence_classes(std::span<const Cand> order_c,
                                                   std::span<const Cand> remainder);

} // namespace marginstv
