#pragma once

// The reported STV count: who was seated and eliminated, in which order,
// with the same log text as the Python program. Also the two starting
// upper bounds on the margin.

#include "marginstv/election.hpp"
#include "marginstv/logger.hpp"
#include "marginstv/pynum.hpp"

#include <cstdint>
#include <vector>

namespace marginstv {

struct Outcome {
    std::int64_t quota = 0;
    PyNum total_votes;
    std::vector<Cand> order_c;  // candidate processed in each round
    std::vector<int> order_a;   // 1: seated, 0: eliminated
    std::vector<Cand> winners;  // in seating order
    std::vector<double> tallies; // tallies[c * N + r]: c's tally at the start of round r
};

Outcome simulate_stv(const Election& election, int seats, Logger& log);

// Upper bound from eliminating a winner while others still stand.
PyNum compute_weub(const Election& election, const Outcome& outcome);

// Upper bound from giving a loser a quota on first preferences.
PyNum compute_simple_ub(const Election& election, const Outcome& outcome);

} // namespace marginstv
