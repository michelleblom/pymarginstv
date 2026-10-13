#pragma once

// Elimination, quota and no-quota lower bounds on the votes that must
// change for an outcome prefix to happen (compute_elim_quota_lb_* in
// stvtree.py), and the ballot valuations they rest on.

#include "marginstv/cand_set.hpp"
#include "marginstv/election.hpp"
#include "marginstv/prefix.hpp"

#include <cstdint>
#include <memory>
#include <span>
#include <vector>

namespace marginstv {

// What every bound needs to know about the election.
struct BoundInputs {
    const Election* election = nullptr;
    int ncands = 0;
    std::int64_t quota = 0;
    int seats = 0;
    std::vector<double> fp; // first preference votes, per candidate
};

// Transfer value bounds (lower, upper) for a candidate seated with a quota.
struct TransferValue {
    Cand c;
    double lo;
    double hi;
};

class Transfers {
  public:
    [[nodiscard]] const TransferValue* find(Cand c) const;
    void set(Cand c, double lo, double hi);
    [[nodiscard]] const std::vector<TransferValue>& items() const { return items_; }
    // Lower values per candidate number; candidates without one get 0.
    [[nodiscard]] std::vector<double> dense_lo(int ncands) const;
    [[nodiscard]] std::vector<double> dense_hi(int ncands) const;

  private:
    std::vector<TransferValue> items_;
};

// For each round, the candidates for whom no-quota constraints have been
// added, as bits. Rounds never touched read as empty.
class RoundMasks {
  public:
    [[nodiscard]] CandSet get(int round) const;
    void merge(int round, const CandSet& add);
    [[nodiscard]] const std::vector<CandSet>& rounds() const { return rounds_; }

  private:
    std::vector<CandSet> rounds_;
};

// Running state of the bound walk over a prefix (EqlbCtx in stvtree.py).
// The candidates already processed are always order_c[:round] of the
// prefix being walked, so they are rebuilt from it rather than stored.
struct EqlbCtx {
    int ncands = 0;
    Transfers transfer;
    double elim_lb = 0;
    double quota_lb = 0;
    double no_quota_lb = 0;
    RoundMasks nq_cons_added;
    CandSet winners;
    int round = 0;
};

// Per-round summaries shared by all children of an expanded node (-prec_et).
// Quota-prefix mode uses only 'tallies'; the other mode uses the four sums
// of RoundTallies in stvtree.py.
struct RoundTallies {
    std::vector<double> tallies;
    std::vector<double> ub_first;
    std::vector<double> ub_present;
    std::vector<double> elb_gain;
    std::vector<double> slb_first;
};

using SharedRoundTallies = std::shared_ptr<const RoundTallies>;

// Position of each candidate within the first 'len' rounds of a prefix;
// -1 where the candidate is not among them.
std::vector<int> gone_positions(std::span<const Cand> order_c, std::size_t len, int ncands);

// Value of ballot b once the rounds in 'gone' have run, and the last round
// in which it moved (calc_tallies_q_prefix).
struct QValue {
    double value;
    int move_r;
};
QValue calc_tallies_q_prefix(std::span<const Pref> prefs, double votes, std::span<const Cand> gone,
                             std::span<const int> gone_pos, const CandSet& winners,
                             std::span<const double> tv_lo, std::span<const int> qround);

// Seating lower bound, elimination lower bound and upper bound on the value
// of a ballot once the rounds in 'gone' have run (calc_tallies).
struct Valuation {
    double slb;
    double elb;
    double ub;
};

// Prepared state for calc_tallies over one 'gone' list.
struct CalcTalliesPlan {
    std::span<const Cand> gone;
    std::vector<int> pos;         // position in gone, or -1
    std::vector<char> is_winner;  // per position in gone
    std::size_t final_block = 0;  // first position of the trailing seatings
    std::vector<double> tv_lo;
    std::vector<double> tv_hi;
    std::vector<char> has_tv;
};
CalcTalliesPlan plan_calc_tallies(std::span<const Cand> gone, const CandSet& winners,
                                  const Transfers& transfer, int ncands);
Valuation calc_tallies(std::span<const Pref> prefs, double votes, const CalcTalliesPlan& plan);

// Quota round (order_q[c][0]) per candidate; a large value where c has none.
std::vector<int> quota_rounds(const OrderQ& q, int ncands);

struct PrefixRef {
    std::span<const Cand> order_c;
    std::span<const int> order_a;
    const OrderQ* order_q;
};

EqlbCtx compute_eqlb_stv26_qprefix(const EqlbCtx& in, const BoundInputs& bi, const PrefixRef& p,
                                   const RoundTallies* elim_tallies, bool transfers_only);

EqlbCtx compute_eqlb_stv26(const EqlbCtx& in, const BoundInputs& bi, const PrefixRef& p,
                           const RoundTallies* precomputed, bool transfers_only);

EqlbCtx compute_eqlb_bst19(const EqlbCtx& in, const BoundInputs& bi, const PrefixRef& p);

// Round tallies for the children of a node whose walk stands at ctx.round.
RoundTallies compute_round_tallies_q_prefix(const EqlbCtx& ctx, const BoundInputs& bi,
                                            std::span<const Cand> order_c, const OrderQ& q);
RoundTallies compute_round_tallies(const EqlbCtx& ctx, const BoundInputs& bi,
                                   std::span<const Cand> order_c);

} // namespace marginstv
