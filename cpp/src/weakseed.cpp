#include "marginstv/weakseed.hpp"

#include "marginstv/ballot_pass.hpp"

#include <algorithm>
#include <cmath>
#include <limits>

namespace marginstv {

namespace {

// Tallies at a node for choosing a split (SplitStats in stvtree.py).
// mpt[r][j]: for order[r] outside the top j, the value of the ballots
// ranking it above every one of the top j. first[r][j]: for order[r] inside
// the top j, the value of the ballots whose highest-ranked top-j candidate
// it is.
struct SplitStats {
    std::vector<Cand> order;
    std::vector<double> lo_tally;
    std::vector<std::vector<double>> mpt;
    std::vector<std::vector<double>> first;
    int seats_left = 0;
};

std::optional<SplitStats> split_stats(const BoundInputs& bi, std::span<const Cand> order_c,
                                      std::span<const int> order_a, const OrderQ& order_q) {
    const auto n = bi.ncands;
    int seated = 0;
    for (const auto a : order_a) {
        seated += a;
    }
    const auto m = bi.seats - seated;
    CandSet gone_set(n);
    for (const auto c : order_c) {
        gone_set.set(c);
    }
    std::vector<Cand> hopeful;
    for (int c = 0; c < n; ++c) {
        if (!gone_set.test(c)) {
            hopeful.push_back(c);
        }
    }
    const auto H = static_cast<int>(hopeful.size());
    if (m <= 0 || H < m + 1) {
        return std::nullopt;
    }

    // Transfer values of the seated candidates in the prefix.
    EqlbCtx blank;
    blank.ncands = n;
    blank.winners = CandSet(n);
    const PrefixRef p{order_c, order_a, &order_q};
    const auto ctx = compute_eqlb_stv26_qprefix(blank, bi, p, nullptr, true);
    const auto gone_pos = gone_positions(order_c, order_c.size(), n);
    const auto tv_lo = ctx.transfer.dense_lo(n);
    const auto qround = quota_rounds(order_q, n);

    // Each ballot's value at the node, and its first standing candidate.
    const auto& ballots = bi.election->ballots;
    struct Rec {
        int first;
        double value;
    };
    std::vector<double> lo_tally(static_cast<std::size_t>(n), 0.0);
    std::vector<double> value(ballots.size(), 0.0);
    std::vector<char> live(ballots.size(), 0);
    ordered_ballot_pass<Rec>(
        ballots.size(),
        [&](std::size_t b, Rec& rec) {
            const auto prefs = ballots.prefs(b);
            rec.first = -1;
            for (const auto c : prefs) {
                if (!gone_set.test(c)) {
                    rec.first = c;
                    break;
                }
            }
            if (rec.first < 0) {
                return false;
            }
            rec.value = calc_tallies_q_prefix(prefs, static_cast<double>(ballots.votes(b)),
                                              order_c, gone_pos, ctx.winners, tv_lo, qround)
                            .value;
            return true;
        },
        [&](std::size_t b, const Rec& rec) {
            lo_tally[static_cast<std::size_t>(rec.first)] += rec.value;
            value[b] = rec.value;
            live[b] = 1;
        });

    // Python's sorted(hopeful, key=-lo_tally): stable, largest first.
    SplitStats st;
    st.order = hopeful;
    std::stable_sort(st.order.begin(), st.order.end(), [&](Cand a, Cand b) {
        return -lo_tally[static_cast<std::size_t>(a)] < -lo_tally[static_cast<std::size_t>(b)];
    });
    std::vector<int> rank(static_cast<std::size_t>(n), -1);
    for (int r = 0; r < H; ++r) {
        rank[static_cast<std::size_t>(st.order[static_cast<std::size_t>(r)])] = r;
    }

    // One pass gives mpt and first for every j, in ballot order.
    const auto Hs = static_cast<std::size_t>(H);
    std::vector<std::vector<double>> mpt_at(Hs, std::vector<double>(Hs + 1, 0.0));
    std::vector<std::vector<double>> first_diff(Hs, std::vector<double>(Hs + 2, 0.0));
    for (std::size_t b = 0; b < ballots.size(); ++b) {
        if (live[b] == 0) {
            continue;
        }
        const auto v = value[b];
        int rmin = H;
        for (const auto c : ballots.prefs(b)) {
            if (gone_set.test(c)) {
                continue;
            }
            const auto rc = rank[static_cast<std::size_t>(c)];
            const auto u = std::min(rc, rmin);
            if (u >= m) {
                mpt_at[static_cast<std::size_t>(rc)][static_cast<std::size_t>(u)] += v;
            }
            if (rc < rmin) {
                const auto lo_j = std::max(rc + 1, m);
                if (lo_j <= rmin) {
                    first_diff[static_cast<std::size_t>(rc)][static_cast<std::size_t>(lo_j)] += v;
                    first_diff[static_cast<std::size_t>(rc)][static_cast<std::size_t>(rmin + 1)] -= v;
                }
                rmin = rc;
                if (rmin < m) {
                    break;
                }
            }
        }
    }

    st.mpt.assign(Hs, std::vector<double>(Hs + 1, 0.0));
    st.first.assign(Hs, std::vector<double>(Hs + 1, 0.0));
    for (std::size_t r = 0; r < Hs; ++r) {
        double acc = 0.0;
        for (int j = H; j >= 0; --j) {
            acc += mpt_at[r][static_cast<std::size_t>(j)];
            st.mpt[r][static_cast<std::size_t>(j)] = acc;
        }
        acc = 0.0;
        for (std::size_t j = 0; j <= Hs; ++j) {
            acc += first_diff[r][j];
            st.first[r][j] = acc;
        }
    }
    st.lo_tally = std::move(lo_tally);
    st.seats_left = m;
    return st;
}

// choose_split in stvtree.py.
std::optional<WeakSplit> choose_split(const SplitStats& st, double quota, const PyNum& running_ub,
                                      double min_k, int max_children) {
    const auto H = static_cast<int>(st.order.size());
    const auto m = st.seats_left;
    const auto max_other =
        static_cast<int>(std::floor(std::log2(static_cast<double>(std::max(1, max_children)))));
    const auto inf = std::numeric_limits<double>::infinity();
    auto at = [](const std::vector<std::vector<double>>& a, int r, int j) {
        return a[static_cast<std::size_t>(r)][static_cast<std::size_t>(j)];
    };

    std::vector<double> x_quota(static_cast<std::size_t>(H + 1), -inf);
    double cap_x = -inf;
    for (int j = m; j < H; ++j) {
        const auto t = st.lo_tally[static_cast<std::size_t>(st.order[static_cast<std::size_t>(j - 1)])];
        std::vector<double> rest;
        for (int r = j; r < H; ++r) {
            rest.push_back(at(st.mpt, r, j));
        }
        std::sort(rest.begin(), rest.end());
        auto first_max = at(st.first, 0, j);
        for (int r = 1; r < j; ++r) {
            first_max = std::max(first_max, at(st.first, r, j));
        }
        x_quota[static_cast<std::size_t>(j)] = std::min(quota - rest.back(), quota - first_max);
        const auto nweak = std::max(1, static_cast<int>(rest.size()) - max_other);
        cap_x = std::max(cap_x, std::min(x_quota[static_cast<std::size_t>(j)],
                                         (t - rest[static_cast<std::size_t>(nweak - 1)]) / 2.0));
    }

    // Python's min(cap_x, running_ub): running_ub only when strictly smaller.
    const auto k = running_ub.as_double() < cap_x ? running_ub : PyNum::real(cap_x);
    const auto kd = k.as_double();
    if (cap_x < min_k || kd <= 0) {
        return std::nullopt;
    }

    bool found = false;
    int best_weak = 0;
    int best_other = 0;
    int best_j = 0;
    double best_x = 0;
    std::vector<int> best_ranks;
    for (int j = m; j < H; ++j) {
        const auto t = st.lo_tally[static_cast<std::size_t>(st.order[static_cast<std::size_t>(j - 1)])];
        std::vector<int> weak;
        for (int r = j; r < H; ++r) {
            if (t - at(st.mpt, r, j) >= 2.0 * kd) {
                weak.push_back(r);
            }
        }
        const auto nother = H - j - static_cast<int>(weak.size());
        if (weak.empty() || nother > max_other) {
            continue;
        }
        auto top = at(st.mpt, weak[0], j);
        for (const auto r : weak) {
            top = std::max(top, at(st.mpt, r, j));
        }
        const auto x = std::min(x_quota[static_cast<std::size_t>(j)], (t - top) / 2.0);
        if (x < kd) {
            continue;
        }
        const auto nw = static_cast<int>(weak.size());
        if (!found || nw > best_weak || (nw == best_weak && -nother > -best_other)) {
            found = true;
            best_weak = nw;
            best_other = nother;
            best_j = j;
            best_x = x;
            best_ranks = weak;
        }
    }
    if (!found) {
        return std::nullopt;
    }

    WeakSplit split;
    split.k = k;
    split.x = best_x;
    split.order = st.order;
    std::vector<char> is_weak(static_cast<std::size_t>(H), 0);
    for (const auto r : best_ranks) {
        is_weak[static_cast<std::size_t>(r)] = 1;
        split.weak.push_back(st.order[static_cast<std::size_t>(r)]);
    }
    for (int r = 0; r < H; ++r) {
        const auto c = st.order[static_cast<std::size_t>(r)];
        if (r < best_j) {
            split.strong.push_back(c);
        } else if (is_weak[static_cast<std::size_t>(r)] == 0) {
            split.other.push_back(c);
        }
    }
    return split;
}

} // namespace

std::optional<WeakSplit> weak_seed_split(const BoundInputs& bi, std::span<const Cand> order_c,
                                         std::span<const int> order_a, const OrderQ& order_q,
                                         const PyNum& running_ub, const PyNum& orig_ub,
                                         double seedf, int max_children) {
    if (!order_a.empty() && order_a.back() != 1) {
        return std::nullopt;
    }
    const auto st = split_stats(bi, order_c, order_a, order_q);
    if (!st) {
        return std::nullopt;
    }
    // Python's min(seedf * orig_ub, running_ub), only ever compared.
    const auto scaled = seedf * orig_ub.as_double();
    const auto min_k = std::min(scaled, running_ub.as_double());
    return choose_split(*st, static_cast<double>(bi.quota), running_ub, min_k, max_children);
}

} // namespace marginstv
