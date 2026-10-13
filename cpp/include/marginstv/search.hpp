#pragma once

// The branch-and-bound search over outcome prefixes (treestv in stvtree.py).
//
// Each step pops the -pc nodes with the smallest distance and expands them
// all at once: the nodes, the work each node's children share, and the
// children themselves are evaluated in parallel. Results are then handled
// one by one in the order the Python handles them, against the upper bound
// as it stood when the step began, so the log does not depend on how many
// threads ran.

#include "marginstv/bounds_disp.hpp"
#include "marginstv/distance.hpp"
#include "marginstv/frontier.hpp"
#include "marginstv/options.hpp"
#include "marginstv/simulate.hpp"

#include <cstdint>
#include <optional>
#include <vector>

namespace marginstv {

struct SearchInputs {
    const Election* election = nullptr;
    const Options* options = nullptr;
    BoundInputs bounds;
    PyNum tot_ballots;
    CandSet winner_set;
    std::vector<Cand> full_order_c;
    std::vector<int> full_order_a;
    DistanceSettings distance;
};

struct SearchResult {
    PyNum lb;
    PyNum ub;
    std::uint64_t nexps = 0;
    std::uint64_t nsolves = 0;
    std::uint64_t ignores = 0;
    std::uint64_t agg_prunes = 0;
};

SearchResult treestv(const SearchInputs& in, PyNum upperbound, Logger& log);

// ------------------------------------------------------------------------
// Pieces of the search, exposed for the replay tests.

struct ChildSpec {
    PyNum parent_dist;
    std::vector<Cand> order_c;
    std::vector<int> order_a;
    OrderQ order_q;
    CandSet winners;
    std::vector<Cand> rem;
    bool isleaf = false;
    PyNum running_ub;
};

struct ChildResult {
    bool isleaf = false;
    EqlbCtx eqlbctx;
    DispCache disp_cache;
    std::vector<Cand> order_c;
    std::vector<int> order_a;
    OrderQ order_q;
    PyNum lb;
    PyNum dlb;
    PyNum eqlb;
    std::optional<PyNum> dist;
    std::optional<PyNum> dist_ub;
    bool solved = false;
};

struct InitialResult {
    PyNum lb;
    PyNum dlb;
    PyNum eqlb;
    EqlbCtx eqlbctx;
    DispCache disp_cache;
    std::vector<Cand> order_c;
    std::vector<int> order_a;
    OrderQ order_q;
    std::optional<PyNum> dist; // empty when the MINLP is infeasible
    std::optional<PyNum> dist_ub;
    bool solved = false;
};

// The context shared by all children of one expanded node.
struct Expansion {
    EqlbCtx eqlbctx;
    DispCache disp_cache;
    std::optional<RoundTallies> elim_tallies;
    std::vector<ChildSpec> children;
};

InitialResult eval_child_initial(const SearchInputs& in, std::vector<Cand> order_c,
                                 std::vector<int> order_a, OrderQ order_q, const CandSet& winners,
                                 std::vector<Cand> rem, const PyNum& running_ub);

Expansion generate_children(const SearchInputs& in, const TreeNode& node, const PyNum& running_ub);

ChildResult eval_child(const SearchInputs& in, const Expansion& ex, const ChildSpec& spec);

EqlbCtx blank_eqlb(int ncands);
DispCache blank_disp(int ncands);

} // namespace marginstv
