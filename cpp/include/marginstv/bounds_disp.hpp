#pragma once

// Displacement lower bound (compute_disp_lb_* in stvtree.py) and the
// ballot summaries it is computed from, which nodes cache for their
// children.

#include "marginstv/bounds_eqlb.hpp"
#include "marginstv/pynum.hpp"

#include <memory>
#include <vector>

namespace marginstv {

using SharedArray = std::shared_ptr<const std::vector<double>>;

// DispCache in stvtree.py. The four summaries are immutable once built, so
// children that carry them forward share one copy.
//   present[x]      value of ballots on which x still stands
//   above[x*N+y]    value of ballots on which x and y stand, x ranked above y
//   curtally[x]     value of ballots whose first standing candidate is x
//   reassign[g*N+x] value of ballots with g first and x next among standing
struct DispCache {
    int ncands = 0;
    bool new_winner = false;
    CandSet winners;
    SharedArray above;
    SharedArray present;
    SharedArray curtally;
    SharedArray reassign;
    int start = 0;
    PyNum lowerbound = PyNum::integer(0);

    // The cache an initial node starts from is built from the election's
    // ballot metadata. In the Python those summaries are plain lists, and
    // there 'curtally + reassign[ce]' joins two lists rather than adding
    // them, so the tally used is curtally alone. Kept for identical results.
    bool from_metadata_lists = false;

    [[nodiscard]] bool complete() const { return above && present && curtally && reassign; }
};

DispCache disp_cache_from_metadata(const BoundInputs& bi);

// Quota-prefix mode.
DispCache update_disp_cache_q_prefix(const DispCache& dc, const BoundInputs& bi,
                                     std::span<const Cand> order_c, const OrderQ& q,
                                     std::span<const Cand> rem, const Transfers& transfer);
DispCache compute_disp_lb_stv26_q_prefix(const DispCache& dc, const BoundInputs& bi,
                                         const PrefixRef& p, const CandSet& winner_set,
                                         std::span<const Cand> rem, const Transfers& transfer);

// Range mode.
DispCache update_disp_cache(const DispCache& dc, const BoundInputs& bi,
                            std::span<const Cand> order_c, std::span<const int> order_a,
                            std::span<const Cand> rem, const Transfers& transfer);
DispCache compute_disp_lb_stv26(const DispCache& dc, const BoundInputs& bi, const PrefixRef& p,
                                const CandSet& winner_set, std::span<const Cand> rem,
                                const Transfers& transfer);

} // namespace marginstv
