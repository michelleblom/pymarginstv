#pragma once

// -membership: lower bounds for a run of eliminations that is still open
// (RunState in membership.py). A node stands for every run that eliminates
// all of IN and none of OUT, in any order; the bounds use the ballots at
// the start of the run, where every ballot sits with its first standing
// candidate.

#include "marginstv/cand_set.hpp"
#include "marginstv/election.hpp"

#include <cstdint>
#include <mutex>
#include <optional>
#include <span>
#include <vector>

namespace marginstv {

class RunState {
  public:
    // standing: candidates standing at the run's start, in candidate order;
    // prefs/values: each live ballot's ranking over them and its value, in
    // ballot order. Identical rankings are merged.
    RunState(int ncand, double quota, int seats_left, std::vector<Cand> standing,
             const std::vector<std::vector<Cand>>& prefs, const std::vector<double>& values);

    [[nodiscard]] const std::vector<double>& t0() const { return t0_; }
    // Decision order: largest tally at the run's start first.
    [[nodiscard]] const std::vector<Cand>& order() const { return order_; }
    [[nodiscard]] const std::vector<Cand>& standing() const { return standing_; }

    // Lower bound for the family (IN, OUT): the checks Q, E+, M and S+;
    // infinity when IN leaves too few standing. Sets are given in
    // candidate order.
    [[nodiscard]] double lb(const std::vector<Cand>& in, const std::vector<Cand>& out,
                            double floor, double deficit, bool sumnq, bool elimnq,
                            int depth) const;

    // Displacement bound tightened by IN (dlb in membership.py).
    [[nodiscard]] double dlb(const std::vector<Cand>& in, const CandSet& reported,
                             bool changed) const;

    // The no-quota bounds worked back over the seatings before the run, set
    // once by the search (which has the walk's context).
    template <class F>
    double nq(F&& compute) const {
        std::call_once(nq_once_, [&] { nq_ = compute(); });
        return nq_;
    }

  private:
    [[nodiscard]] std::vector<double> tmax(const std::vector<char>& out) const;
    void tmin_flow(const std::vector<char>& in, std::vector<double>& tmin,
                   std::vector<double>& flow) const;
    void disp_costs(const CandSet& reported) const;

    int ncand_;
    double quota_;
    int seats_left_;
    std::vector<Cand> standing_;
    std::vector<std::vector<Cand>> rows_;
    std::vector<double> w_;
    std::vector<double> t0_;
    std::vector<Cand> order_;

    mutable std::once_flag disp_once_;
    mutable std::vector<char> disp_winner_; // reported winners standing
    mutable bool disp_any_winner_ = false;
    mutable std::vector<double> disp_cost_; // per reported loser; NaN otherwise
    mutable std::once_flag nq_once_;
    mutable double nq_ = 0.0;
};

} // namespace marginstv
