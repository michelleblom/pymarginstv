#pragma once

// One pass over every ballot type that adds per-ballot values into totals.
//
// Floating-point addition depends on order, and the totals must equal the
// Python program's bit for bit, so additions happen in ballot order. The
// costly part of a pass is working out each ballot's value, and ballots are
// independent of each other, so on large elections that part runs in
// parallel over a block of ballots; then the block's values are added in
// ballot order. Small elections skip the split.

#include <tbb/blocked_range.h>
#include <tbb/parallel_for.h>

#include <algorithm>
#include <cstddef>
#include <vector>

namespace marginstv {

// Ballot count below which a pass runs straight through on one thread.
inline constexpr std::size_t kParallelPassMinBallots = 20000;

// Ballots handled per block in a parallel pass.
inline constexpr std::size_t kPassBlock = 16384;

// compute(b, rec) fills rec for ballot b and returns false to skip it.
// add(b, rec) adds a kept ballot's values into the totals, in ballot order.
template <class Record, class Compute, class Add>
void ordered_ballot_pass(std::size_t nballots, Compute&& compute, Add&& add) {
    if (nballots < kParallelPassMinBallots) {
        Record rec{};
        for (std::size_t b = 0; b < nballots; ++b) {
            if (compute(b, rec)) {
                add(b, rec);
            }
        }
        return;
    }

    std::vector<Record> recs(kPassBlock);
    std::vector<char> keep(kPassBlock);
    for (std::size_t start = 0; start < nballots; start += kPassBlock) {
        const auto len = std::min(kPassBlock, nballots - start);
        tbb::parallel_for(tbb::blocked_range<std::size_t>(0, len, 512),
                          [&](const tbb::blocked_range<std::size_t>& r) {
                              for (auto i = r.begin(); i != r.end(); ++i) {
                                  keep[i] = compute(start + i, recs[i]) ? 1 : 0;
                              }
                          });
        for (std::size_t i = 0; i < len; ++i) {
            if (keep[i] != 0) {
                add(start + i, recs[i]);
            }
        }
    }
}

} // namespace marginstv
