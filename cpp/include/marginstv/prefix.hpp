#pragma once

// Outcome prefixes: the order in which candidates are seated or eliminated
// at the start of a count, and the helpers that work on them.

#include "marginstv/election.hpp"

#include <array>
#include <cstdint>
#include <span>
#include <string>
#include <vector>

namespace marginstv {

// The rounds (earliest, latest) in which a seated candidate could first
// hold a quota. With -useqprefix the two are equal and give the round at
// whose start the candidate holds a quota (0 = on first preferences).
// Otherwise they follow get_order_q (-1 = on first preferences).
struct QEntry {
    Cand c;
    int lo;
    int hi;
};

// Quota rounds in insertion order, as the Python dict iterates them.
using OrderQ = std::vector<QEntry>;

const QEntry* find_q(const OrderQ& q, Cand c);

// Python str() of the quota map: "{3: (-1, 0), 5: (7, 7)}".
std::string order_q_str(const OrderQ& q);

// The round up to which constraints are formed for a prefix.
int compute_last_round(std::span<const Cand> order_c, std::span<const int> order_a, int seats,
                       int ncands);

// Quota round ranges for the winners seated at or before last_round,
// in the order the winners set is given (Python set iteration order).
OrderQ get_order_q(std::span<const int> order_a, int last_round,
                   std::span<const Cand> winners_in_set_order, std::span<const Cand> order_c);

// A prefix with runs of eliminated candidates merged into one candidate,
// for a smaller MINLP.
struct MergedOutcome {
    std::vector<Cand> order_c;
    std::vector<int> order_a;
    OrderQ order_q;
    std::vector<Cand> merge_map; // merge_map[c]: c's candidate in the merged prefix
    std::vector<Cand> supers;    // the merged candidates
};

MergedOutcome merge_outcome(std::span<const Cand> order_c, std::span<const int> order_a,
                            const OrderQ& order_q, std::span<const Cand> rem, int ncands);

// 16 byte digest identifying a prefix up to reordering of eliminations
// between seatings (see outcome_signature in stvtree.py).
using Signature = std::array<std::uint8_t, 16>;

std::vector<std::uint8_t> canonical_outcome(std::span<const Cand> order_c,
                                            std::span<const int> order_a, const OrderQ& order_q);
Signature outcome_signature(std::span<const Cand> order_c, std::span<const int> order_a,
                            const OrderQ& order_q);

} // namespace marginstv
