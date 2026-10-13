#include "marginstv/bounds_disp.hpp"

#include "marginstv/ballot_pass.hpp"

#include <tbb/parallel_for.h>

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace marginstv {

namespace {

// Per-ballot values for the summary build.
//   cur   value added to curtally (and reassign) for the first standing x
//   pres  value added to present and above
struct DispRec {
    double cur = 0;
    double pres = 0;
    bool add_cur = true;
    bool add_reassign = true;
};

struct DispArrays {
    std::vector<double> curtally;
    std::vector<double> present;
    std::vector<double> above;
    std::vector<double> reassign;
};

void collect_standing(std::span<const Pref> prefs, const CandSet& rem, std::vector<int>& out) {
    out.clear();
    for (const auto p : prefs) {
        if (rem.test(p)) {
            out.push_back(p);
        }
    }
}

// Adds one ballot's values into the rows [lo, hi) of every summary.
void add_ballot_rows(const std::vector<int>& pres, const DispRec& rec, int lo, int hi, int n,
                     DispArrays& a) {
    const auto un = static_cast<std::size_t>(n);
    const auto c = pres[0];
    if (c >= lo && c < hi) {
        if (rec.add_cur) {
            a.curtally[static_cast<std::size_t>(c)] += rec.cur;
        }
        if (rec.add_reassign && pres.size() > 1) {
            a.reassign[static_cast<std::size_t>(c) * un + static_cast<std::size_t>(pres[1])] +=
                rec.cur;
        }
    }
    for (std::size_t i = 0; i < pres.size(); ++i) {
        const auto x = pres[i];
        if (x < lo || x >= hi) {
            continue;
        }
        a.present[static_cast<std::size_t>(x)] += rec.pres;
        auto* row = a.above.data() + static_cast<std::size_t>(x) * un;
        for (auto j = i + 1; j < pres.size(); ++j) {
            row[pres[j]] += rec.pres;
        }
    }
}

// One pass over the ballots building the four summaries over the
// candidates in 'rem'. Values are worked out per ballot in parallel; each
// summary row is then owned by one task, which adds into it in ballot order.
template <class Compute>
DispArrays build_disp(const BoundInputs& bi, std::span<const Cand> rem, Compute&& compute) {
    const auto n = bi.ncands;
    const auto un = static_cast<std::size_t>(n);
    const auto& ballots = bi.election->ballots;
    CandSet rem_set(n);
    for (const auto c : rem) {
        rem_set.set(c);
    }

    DispArrays a;
    a.curtally.assign(un, 0.0);
    a.present.assign(un, 0.0);
    a.above.assign(un * un, 0.0);
    a.reassign.assign(un * un, 0.0);

    const auto nb = ballots.size();
    if (nb < kParallelPassMinBallots) {
        std::vector<int> pres;
        DispRec rec;
        for (std::size_t b = 0; b < nb; ++b) {
            collect_standing(ballots.prefs(b), rem_set, pres);
            if (pres.empty()) {
                continue;
            }
            compute(b, pres[0], rec);
            add_ballot_rows(pres, rec, 0, n, n, a);
        }
        return a;
    }

    const auto parts = std::min(n, 16);
    std::vector<DispRec> recs(kPassBlock);
    std::vector<char> keep(kPassBlock);
    for (std::size_t start = 0; start < nb; start += kPassBlock) {
        const auto len = std::min(kPassBlock, nb - start);
        tbb::parallel_for(tbb::blocked_range<std::size_t>(0, len, 512),
                          [&](const tbb::blocked_range<std::size_t>& r) {
                              std::vector<int> pres;
                              for (auto i = r.begin(); i != r.end(); ++i) {
                                  collect_standing(ballots.prefs(start + i), rem_set, pres);
                                  keep[i] = pres.empty() ? 0 : 1;
                                  if (!pres.empty()) {
                                      compute(start + i, pres[0], recs[i]);
                                  }
                              }
                          });
        tbb::parallel_for(0, parts, [&](int part) {
            const auto lo = part * n / parts;
            const auto hi = (part + 1) * n / parts;
            std::vector<int> pres;
            for (std::size_t i = 0; i < len; ++i) {
                if (keep[i] == 0) {
                    continue;
                }
                collect_standing(ballots.prefs(start + i), rem_set, pres);
                add_ballot_rows(pres, recs[i], lo, hi, n, a);
            }
        });
    }
    return a;
}

SharedArray share(std::vector<double>&& v) {
    return std::make_shared<const std::vector<double>>(std::move(v));
}

DispCache with_arrays(DispCache dc, DispArrays&& a) {
    dc.curtally = share(std::move(a.curtally));
    dc.present = share(std::move(a.present));
    dc.above = share(std::move(a.above));
    dc.reassign = share(std::move(a.reassign));
    dc.from_metadata_lists = false;
    return dc;
}

DispCache without_arrays(DispCache dc) {
    dc.above.reset();
    dc.present.reset();
    dc.curtally.reset();
    dc.reassign.reset();
    dc.from_metadata_lists = false;
    return dc;
}

CandSet seated_in(const PrefixRef& p, int n) {
    CandSet s(n);
    for (std::size_t i = 0; i < p.order_c.size(); ++i) {
        if (p.order_a[i] == 1) {
            s.set(p.order_c[i]);
        }
    }
    return s;
}

// Has the prefix changed who won? Scans from the cache's start round.
bool changes_winners(const DispCache& dc, const PrefixRef& p, const CandSet& winner_set) {
    if (dc.new_winner) {
        return true;
    }
    for (auto i = static_cast<std::size_t>(dc.start); i < p.order_c.size(); ++i) {
        const auto c = p.order_c[i];
        if (p.order_a[i] == 1) {
            if (!winner_set.test(c)) {
                return true;
            }
        } else if (winner_set.test(c)) {
            return true;
        }
    }
    return false;
}

// The bound itself, from the four summaries at this prefix.
PyNum displacement_bound(const BoundInputs& bi, std::span<const Cand> rem,
                         const std::vector<Cand>& og_losers, const CandSet& og_winners, int sleft,
                         std::span<const double> min_r, std::span<const double> present,
                         std::span<const double> above) {
    const auto un = static_cast<std::size_t>(bi.ncands);
    const auto nleft = static_cast<int>(rem.size());
    const auto quota = static_cast<double>(bi.quota);
    constexpr auto inf = std::numeric_limits<double>::infinity();

    auto lowerbound = inf;
    std::vector<double> costs;
    for (const auto ogl : og_losers) {
        auto displacement_cost = inf;
        costs.clear();
        const auto max_ogl = present[static_cast<std::size_t>(ogl)];
        for (const auto r : rem) {
            if (r == ogl) {
                continue;
            }
            const auto max_l_r =
                max_ogl - above[static_cast<std::size_t>(r) * un + static_cast<std::size_t>(ogl)];
            const auto diff = 0.5 * (min_r[static_cast<std::size_t>(r)] - max_l_r);
            const auto dp = diff > 0.0 ? diff : 0.0;
            costs.push_back(dp);
            if (og_winners.test(r)) {
                displacement_cost = std::min(displacement_cost, dp);
            }
        }
        const auto qdiff = quota - max_ogl;
        const auto quota_cost = qdiff > 0 ? qdiff : 0.0;
        std::sort(costs.begin(), costs.end());
        // ogl must outlast nleft - sleft candidates.
        const auto k =
            std::min(static_cast<std::size_t>(std::max(nleft - sleft, 0)), costs.size());
        if (k == 0) {
            throw std::runtime_error("displacement bound: no candidates to outlast");
        }
        const auto left_at_end_cost =
            *std::max_element(costs.begin(), costs.begin() + static_cast<std::ptrdiff_t>(k));
        lowerbound = std::min(lowerbound,
                              std::max(displacement_cost, std::min(quota_cost, left_at_end_cost)));
    }
    return py_ceil(lowerbound - 1e-4);
}

struct Standing {
    std::vector<Cand> og_losers;
    CandSet og_winners;
    std::size_t n_og_winners = 0;
};

Standing split_standing(std::span<const Cand> rem, const CandSet& winner_set, int n) {
    Standing s;
    s.og_winners = CandSet(n);
    for (const auto c : rem) {
        if (winner_set.test(c)) {
            s.og_winners.set(c);
            ++s.n_og_winners;
        } else {
            s.og_losers.push_back(c);
        }
    }
    return s;
}

int seats_left(const BoundInputs& bi, const PrefixRef& p) {
    int filled = 0;
    for (const auto a : p.order_a) {
        filled += a;
    }
    return bi.seats - filled;
}

std::vector<double> incremental_min_r(const DispCache& dc, Cand ce) {
    // See DispCache::from_metadata_lists.
    if (dc.from_metadata_lists) {
        return *dc.curtally;
    }
    const auto un = static_cast<std::size_t>(dc.ncands);
    std::vector<double> out(*dc.curtally);
    const auto* row = dc.reassign->data() + static_cast<std::size_t>(ce) * un;
    for (std::size_t i = 0; i < un; ++i) {
        out[i] += row[i];
    }
    return out;
}

DispArrays build_q(const BoundInputs& bi, std::span<const Cand> gone, std::span<const int> gone_pos,
                   const CandSet& winners, const OrderQ& q, std::span<const Cand> rem,
                   const Transfers& transfer) {
    const auto tv_lo = transfer.dense_lo(bi.ncands);
    const auto qround = quota_rounds(q, bi.ncands);
    const auto& ballots = bi.election->ballots;
    return build_disp(bi, rem, [&](std::size_t b, int c, DispRec& rec) {
        const auto v = calc_tallies_q_prefix(ballots.prefs(b), static_cast<double>(ballots.votes(b)),
                                             gone, gone_pos, winners, tv_lo, qround);
        rec.cur = v.value;
        rec.pres = v.value;
        const auto in_q = find_q(q, c) != nullptr;
        rec.add_cur = !in_q || qround[static_cast<std::size_t>(c)] > v.move_r;
        rec.add_reassign = !in_q;
    });
}

DispArrays build_ranges(const BoundInputs& bi, std::span<const Cand> gone, const CandSet& winners,
                        std::span<const Cand> rem, const Transfers& transfer) {
    const auto plan = plan_calc_tallies(gone, winners, transfer, bi.ncands);
    const auto& ballots = bi.election->ballots;
    return build_disp(bi, rem, [&](std::size_t b, int, DispRec& rec) {
        const auto v = calc_tallies(ballots.prefs(b), static_cast<double>(ballots.votes(b)), plan);
        rec.cur = v.elb;
        rec.pres = v.ub;
        rec.add_cur = true;
        rec.add_reassign = true;
    });
}

} // namespace

DispCache disp_cache_from_metadata(const BoundInputs& bi) {
    const auto& m = bi.election->metadata;
    DispCache dc;
    dc.ncands = bi.ncands;
    dc.winners = CandSet(bi.ncands);
    dc.above = share(std::vector<double>(m.above.begin(), m.above.end()));
    dc.present = share(std::vector<double>(m.mentions.begin(), m.mentions.end()));
    dc.curtally = share(std::vector<double>(bi.fp));
    dc.reassign = share(std::vector<double>(m.reassign));
    dc.from_metadata_lists = true;
    return dc;
}

// ---------------------------------------------------------------- quota-prefix mode

DispCache update_disp_cache_q_prefix(const DispCache& dc, const BoundInputs& bi,
                                     std::span<const Cand> order_c, const OrderQ& q,
                                     std::span<const Cand> rem, const Transfers& transfer) {
    if (dc.new_winner || dc.reassign) {
        return dc;
    }
    const auto gone_pos = gone_positions(order_c, static_cast<std::size_t>(dc.start), bi.ncands);
    return with_arrays(dc, build_q(bi, order_c, gone_pos, dc.winners, q, rem, transfer));
}

DispCache compute_disp_lb_stv26_q_prefix(const DispCache& dc, const BoundInputs& bi,
                                         const PrefixRef& p, const CandSet& winner_set,
                                         std::span<const Cand> rem, const Transfers& transfer) {
    if (changes_winners(dc, p, winner_set)) {
        auto out = without_arrays(dc);
        out.new_winner = true;
        out.lowerbound = PyNum::integer(0);
        return out;
    }
    const auto st = split_standing(rem, winner_set, bi.ncands);
    const auto sleft = seats_left(bi, p);
    if (sleft == static_cast<int>(rem.size()) || st.og_losers.empty() || st.n_og_winners == 0) {
        auto out = without_arrays(dc);
        out.lowerbound = PyNum::integer(0);
        return out;
    }

    const auto winners = seated_in(p, bi.ncands);
    const auto norder = static_cast<int>(p.order_c.size());

    DispCache out;
    out.ncands = bi.ncands;
    out.new_winner = false;
    out.winners = winners;
    out.start = norder;

    if (p.order_a.back() == 0 && dc.complete()) {
        const auto min_r = incremental_min_r(dc, p.order_c.back());
        out.lowerbound = displacement_bound(bi, rem, st.og_losers, st.og_winners, sleft, min_r,
                                            *dc.present, *dc.above);
        return out; // summaries rebuilt by update_disp_cache_q_prefix
    }

    const auto gone_pos = gone_positions(p.order_c, p.order_c.size(), bi.ncands);
    auto a = build_q(bi, p.order_c, gone_pos, winners, *p.order_q, rem, transfer);
    out.lowerbound = displacement_bound(bi, rem, st.og_losers, st.og_winners, sleft, a.curtally,
                                        a.present, a.above);
    return with_arrays(out, std::move(a));
}

// ---------------------------------------------------------------- range mode

DispCache update_disp_cache(const DispCache& dc, const BoundInputs& bi,
                            std::span<const Cand> order_c, std::span<const int> order_a,
                            std::span<const Cand> rem, const Transfers& transfer) {
    if (dc.new_winner || dc.reassign) {
        return dc;
    }
    const PrefixRef p{order_c, order_a, nullptr};
    const auto winners = seated_in(p, bi.ncands);
    return with_arrays(dc, build_ranges(bi, order_c, winners, rem, transfer));
}

DispCache compute_disp_lb_stv26(const DispCache& dc, const BoundInputs& bi, const PrefixRef& p,
                                const CandSet& winner_set, std::span<const Cand> rem,
                                const Transfers& transfer) {
    if (changes_winners(dc, p, winner_set)) {
        auto out = without_arrays(dc);
        out.new_winner = true;
        out.lowerbound = PyNum::integer(0);
        return out;
    }
    const auto st = split_standing(rem, winner_set, bi.ncands);
    const auto sleft = seats_left(bi, p);
    if (sleft == static_cast<int>(rem.size()) || st.og_losers.empty() || st.n_og_winners == 0) {
        auto out = without_arrays(dc);
        out.lowerbound = PyNum::integer(0);
        return out;
    }

    const auto winners = seated_in(p, bi.ncands);
    DispCache out;
    out.ncands = bi.ncands;
    out.new_winner = false;
    out.winners = winners;
    out.start = static_cast<int>(p.order_c.size());

    if (p.order_a.back() == 0 && dc.complete()) {
        const auto min_r = incremental_min_r(dc, p.order_c.back());
        out.lowerbound = displacement_bound(bi, rem, st.og_losers, st.og_winners, sleft, min_r,
                                            *dc.present, *dc.above);
        return out; // summaries rebuilt by update_disp_cache
    }

    auto a = build_ranges(bi, p.order_c, winners, rem, transfer);
    out.lowerbound = displacement_bound(bi, rem, st.og_losers, st.og_winners, sleft, a.curtally,
                                        a.present, a.above);
    return with_arrays(out, std::move(a));
}

} // namespace marginstv
