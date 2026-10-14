#include "marginstv/bounds_eqlb.hpp"

#include "marginstv/ballot_pass.hpp"

#include <algorithm>
#include <climits>
#include <stdexcept>

namespace marginstv {

// ---------------------------------------------------------------- helpers

const TransferValue* Transfers::find(Cand c) const {
    for (const auto& t : items_) {
        if (t.c == c) {
            return &t;
        }
    }
    return nullptr;
}

void Transfers::set(Cand c, double lo, double hi) {
    for (auto& t : items_) {
        if (t.c == c) {
            t.lo = lo;
            t.hi = hi;
            return;
        }
    }
    items_.push_back({c, lo, hi});
}

std::vector<double> Transfers::dense_lo(int ncands) const {
    std::vector<double> out(static_cast<std::size_t>(ncands), 0.0);
    for (const auto& t : items_) {
        out[static_cast<std::size_t>(t.c)] = t.lo;
    }
    return out;
}

std::vector<double> Transfers::dense_hi(int ncands) const {
    std::vector<double> out(static_cast<std::size_t>(ncands), 0.0);
    for (const auto& t : items_) {
        out[static_cast<std::size_t>(t.c)] = t.hi;
    }
    return out;
}

CandSet RoundMasks::get(int round) const {
    const auto r = static_cast<std::size_t>(round);
    return r < rounds_.size() ? rounds_[r] : CandSet{};
}

void RoundMasks::merge(int round, const CandSet& add) {
    const auto r = static_cast<std::size_t>(round);
    if (r >= rounds_.size()) {
        rounds_.resize(r + 1);
    }
    rounds_[r].merge(add);
}

std::vector<int> gone_positions(std::span<const Cand> order_c, std::size_t len, int ncands) {
    std::vector<int> pos(static_cast<std::size_t>(ncands), -1);
    for (std::size_t i = 0; i < len && i < order_c.size(); ++i) {
        pos[static_cast<std::size_t>(order_c[i])] = static_cast<int>(i);
    }
    return pos;
}

std::vector<int> quota_rounds(const OrderQ& q, int ncands) {
    std::vector<int> out(static_cast<std::size_t>(ncands), INT_MAX);
    for (const auto& e : q) {
        out[static_cast<std::size_t>(e.c)] = e.lo;
    }
    return out;
}

namespace {

// The candidates processed so far in a walk, kept three ways as the
// Python keeps gone, gone_set and gone_pos.
struct Gone {
    Gone(std::span<const Cand> order_c, int len, int ncands)
        : list(order_c.begin(), order_c.begin() + len), set(ncands),
          pos(static_cast<std::size_t>(ncands), -1) {
        for (int i = 0; i < len; ++i) {
            set.set(list[static_cast<std::size_t>(i)]);
            pos[static_cast<std::size_t>(list[static_cast<std::size_t>(i)])] = i;
        }
    }
    void push(Cand c) {
        pos[static_cast<std::size_t>(c)] = static_cast<int>(list.size());
        list.push_back(c);
        set.set(c);
    }

    std::vector<Cand> list;
    CandSet set;
    std::vector<int> pos;
};

double py_max0(double v) { return v > 0 ? v : 0.0; }

// Per-thread scratch for calc_tallies' set of skipped seated candidates.
struct SeenStamps {
    std::vector<std::uint32_t> stamp;
    std::uint32_t gen = 0;

    std::uint32_t next(std::size_t n) {
        if (stamp.size() < n) {
            stamp.assign(n, 0);
            gen = 0;
        }
        if (++gen == 0) {
            std::fill(stamp.begin(), stamp.end(), 0);
            gen = 1;
        }
        return gen;
    }
};

thread_local SeenStamps tls_seen;

// First preference on the ballot not yet processed, or -1.
int first_standing(std::span<const Pref> prefs, const CandSet& gone) {
    for (const auto p : prefs) {
        if (!gone.test(p)) {
            return p;
        }
    }
    return -1;
}

} // namespace

QValue calc_tallies_q_prefix(std::span<const Pref> prefs, double votes, std::span<const Cand> gone,
                             std::span<const int> gone_pos, const CandSet& winners,
                             std::span<const double> tv_lo, std::span<const int> qround) {
    auto value = votes;
    std::size_t bidx = 0;
    std::size_t eidx = 0;
    int move_r = -1;
    const auto nprefs = prefs.size();
    const auto ngone = gone.size();
    while (bidx < nprefs && eidx < ngone) {
        const auto bp = static_cast<Cand>(prefs[bidx]);
        const auto pos = gone_pos[static_cast<std::size_t>(bp)];
        if (pos >= 0 && static_cast<std::size_t>(pos) < eidx) {
            ++bidx;
            continue;
        }
        const auto ep = gone[eidx];
        if (!winners.test(ep)) {
            if (bp == ep) {
                move_r = static_cast<int>(eidx);
            }
            ++eidx;
        } else if (bidx > 0 && qround[static_cast<std::size_t>(bp)] <= move_r) {
            ++bidx;
        } else if (bp == ep) {
            value *= tv_lo[static_cast<std::size_t>(bp)];
            move_r = static_cast<int>(eidx);
            ++eidx;
            ++bidx;
        } else {
            ++eidx;
        }
    }
    return {value, move_r};
}

CalcTalliesPlan plan_calc_tallies(std::span<const Cand> gone, const CandSet& winners,
                                  const Transfers& transfer, int ncands) {
    CalcTalliesPlan plan;
    plan.gone = gone;
    plan.pos.assign(static_cast<std::size_t>(ncands), -1);
    plan.is_winner.resize(gone.size());
    for (std::size_t i = 0; i < gone.size(); ++i) {
        plan.pos[static_cast<std::size_t>(gone[i])] = static_cast<int>(i);
        plan.is_winner[i] = winners.test(gone[i]) ? 1 : 0;
    }
    plan.final_block = gone.size();
    while (plan.final_block > 0 && plan.is_winner[plan.final_block - 1] != 0) {
        --plan.final_block;
    }
    plan.tv_lo = transfer.dense_lo(ncands);
    plan.tv_hi = transfer.dense_hi(ncands);
    plan.has_tv.assign(static_cast<std::size_t>(ncands), 0);
    for (const auto& t : transfer.items()) {
        plan.has_tv[static_cast<std::size_t>(t.c)] = 1;
    }
    return plan;
}

Valuation calc_tallies(std::span<const Pref> prefs, double votes, const CalcTalliesPlan& plan) {
    auto slb = votes;
    auto elb = votes;
    auto ub = votes;
    const auto gen = tls_seen.next(plan.pos.size());
    auto& seen = tls_seen.stamp;

    std::size_t bidx = 0;
    std::size_t eidx = 0;
    bool seat_block = false;
    const auto ngone = plan.gone.size();
    while (bidx < prefs.size() && eidx < ngone) {
        const auto bp = static_cast<std::size_t>(prefs[bidx]);
        const auto ep = static_cast<std::size_t>(plan.gone[eidx]);
        const auto bpos = plan.pos[bp];
        if (plan.is_winner[eidx] == 0) {
            ++eidx;
        } else if (bpos >= 0 && static_cast<std::size_t>(bpos) < eidx &&
                   plan.is_winner[static_cast<std::size_t>(bpos)] == 0) {
            seat_block = false;
            ++bidx;
        } else if (bp == ep) {
            if (plan.has_tv[bp] == 0) {
                throw std::runtime_error("seated candidate has no transfer value");
            }
            elb *= plan.tv_lo[bp];
            if (eidx >= plan.final_block) {
                slb *= 0;
            } else {
                slb *= plan.tv_lo[bp];
            }
            if (!seat_block) {
                ub *= plan.tv_hi[bp];
            }
            seat_block = true;
            ++eidx;
            ++bidx;
        } else if (seen[bp] == gen) {
            ++bidx;
        } else {
            seen[ep] = gen;
            ++eidx;
        }
    }
    return {slb, elb, ub};
}

// ---------------------------------------------------------------- quota-prefix mode

namespace {

struct QPlan {
    std::vector<double> tv_lo;
    std::vector<int> qround;
};

// Round tallies when every ballot sits with its first standing candidate.
std::vector<double> round_tallies_q(const BoundInputs& bi, const Gone& gone,
                                    const CandSet& winners, const QPlan& plan) {
    const auto& ballots = bi.election->ballots;
    std::vector<double> tallies(static_cast<std::size_t>(bi.ncands), 0.0);
    struct Rec {
        int first;
        double value;
    };
    ordered_ballot_pass<Rec>(
        ballots.size(),
        [&](std::size_t b, Rec& rec) {
            const auto prefs = ballots.prefs(b);
            rec.first = first_standing(prefs, gone.set);
            if (rec.first < 0) {
                return false;
            }
            rec.value = calc_tallies_q_prefix(prefs, static_cast<double>(ballots.votes(b)),
                                              gone.list, gone.pos, winners, plan.tv_lo,
                                              plan.qround)
                            .value;
            return true;
        },
        [&](std::size_t, const Rec& rec) { tallies[static_cast<std::size_t>(rec.first)] += rec.value; });
    return tallies;
}

// The candidate a ballot is credited to when ballots that last moved at or
// after a candidate's quota round skip that candidate.
struct Credit {
    int target;
    double value;
};

// Shared by the seating rounds of the bound and by backcompute_nq_bound:
// skips gone candidates; a candidate with a quota round at or before the
// ballot's last move is passed over; otherwise the ballot stops there.
Credit credit_ballot(std::span<const Pref> prefs, double votes, const Gone& gone,
                     std::span<const int> gone_pos, const CandSet& winners, const QPlan& plan) {
    bool valued = false;
    QValue qv{0, -1};
    for (const auto p : prefs) {
        if (gone.set.test(p)) {
            continue;
        }
        if (!valued) {
            qv = calc_tallies_q_prefix(prefs, votes, gone.list, gone_pos, winners, plan.tv_lo,
                                       plan.qround);
            valued = true;
        }
        if (plan.qround[p] <= qv.move_r) {
            continue;
        }
        return {p, qv.value};
    }
    return {-1, 0};
}

std::vector<double> credited_tallies(const BoundInputs& bi, const Gone& gone,
                                     std::span<const int> gone_pos, const CandSet& winners,
                                     const QPlan& plan) {
    const auto& ballots = bi.election->ballots;
    std::vector<double> tallies(static_cast<std::size_t>(bi.ncands), 0.0);
    ordered_ballot_pass<Credit>(
        ballots.size(),
        [&](std::size_t b, Credit& rec) {
            rec = credit_ballot(ballots.prefs(b), static_cast<double>(ballots.votes(b)), gone,
                                gone_pos, winners, plan);
            return rec.target >= 0;
        },
        [&](std::size_t, const Credit& rec) {
            tallies[static_cast<std::size_t>(rec.target)] += rec.value;
        });
    return tallies;
}

// No-quota bound for the seating at round i, worked out after the walk
// (backcompute_nq_bound). Returns the bound and the candidates it covers.
std::pair<double, CandSet> backcompute_nq_bound(int i, const EqlbCtx& walked, const BoundInputs& bi,
                                                std::span<const Cand> order_c, const OrderQ& q,
                                                std::span<const int> walked_pos) {
    const Gone gone(order_c, i, bi.ncands);
    const auto already = walked.nq_cons_added.get(i);
    std::vector<Cand> rem_qs;
    for (const auto& e : q) {
        if (!gone.set.test(e.c) && e.lo > i && !already.test(e.c)) {
            rem_qs.push_back(e.c);
        }
    }
    CandSet added(bi.ncands);
    double nqlb = 0;
    if (rem_qs.empty()) {
        return {nqlb, added};
    }

    std::vector<double> tallies;
    if (i == 0) {
        tallies = bi.fp;
    } else {
        const QPlan plan{walked.transfer.dense_lo(bi.ncands), quota_rounds(q, bi.ncands)};
        tallies = credited_tallies(bi, gone, walked_pos, walked.winners, plan);
    }
    for (const auto c : rem_qs) {
        nqlb = std::max(nqlb, tallies[static_cast<std::size_t>(c)] - static_cast<double>(bi.quota));
        added.set(c);
    }
    return {nqlb, added};
}

} // namespace

RoundTallies compute_round_tallies_q_prefix(const EqlbCtx& ctx, const BoundInputs& bi,
                                            std::span<const Cand> order_c, const OrderQ& q) {
    const Gone gone(order_c, ctx.round, bi.ncands);
    const QPlan plan{ctx.transfer.dense_lo(bi.ncands), quota_rounds(q, bi.ncands)};
    RoundTallies rt;
    rt.tallies = round_tallies_q(bi, gone, ctx.winners, plan);
    return rt;
}

EqlbCtx compute_eqlb_stv26_qprefix(const EqlbCtx& in, const BoundInputs& bi, const PrefixRef& p,
                                   const RoundTallies* elim_tallies, bool transfers_only,
                                   bool sumq) {
    EqlbCtx out = in;
    const auto start = in.round;
    Gone gone(p.order_c, start, bi.ncands);
    const auto& q = *p.order_q;
    const auto n = bi.ncands;
    const auto quota = static_cast<double>(bi.quota);
    const auto pxlen = static_cast<int>(p.order_c.size());
    const auto qround = quota_rounds(q, n);

    for (int i = start; i < pxlen; ++i) {
        const auto ce = p.order_c[static_cast<std::size_t>(i)];
        const auto cei = static_cast<std::size_t>(ce);

        if (p.order_a[static_cast<std::size_t>(i)] == 0) {
            if (transfers_only) {
                gone.push(ce);
                continue;
            }
            std::vector<double> computed;
            const std::vector<double>* tallies = nullptr;
            if (i == 0) {
                tallies = &bi.fp;
            } else if (i == start && elim_tallies != nullptr) {
                tallies = &elim_tallies->tallies;
            } else {
                const QPlan plan{out.transfer.dense_lo(n), qround};
                computed = round_tallies_q(bi, gone, out.winners, plan);
                tallies = &computed;
            }
            const auto& t = *tallies;
            out.no_quota_lb = std::max(out.no_quota_lb, py_max0(t[cei] - quota));
            CandSet mask = out.nq_cons_added.get(i);
            for (int c = 0; c < n; ++c) {
                if (gone.set.test(c) || c == ce) {
                    continue;
                }
                const auto ci = static_cast<std::size_t>(c);
                out.elim_lb = std::max(out.elim_lb, py_max0(0.5 * (t[cei] - t[ci])));
                out.no_quota_lb = std::max(out.no_quota_lb, py_max0(t[ci] - quota));
                mask.set(c);
            }
            out.nq_cons_added.merge(i, mask);
        } else {
            // The precomputed round tallies stand in for the ballot walk when
            // every standing candidate with a quota round reaches it no
            // earlier than this round (see the Python for the argument).
            bool reuse = i > 0 && i == start && elim_tallies != nullptr;
            if (reuse) {
                const auto* ceq = find_q(q, ce);
                reuse = ceq != nullptr && ceq->lo == i;
                for (const auto& e : q) {
                    if (reuse && !gone.set.test(e.c) && e.lo < i) {
                        reuse = false;
                    }
                }
            }

            std::vector<double> computed;
            const std::vector<double>* max_tallies = nullptr;
            if (i == 0) {
                max_tallies = &bi.fp;
            } else if (reuse) {
                max_tallies = &elim_tallies->tallies;
            } else {
                const QPlan plan{out.transfer.dense_lo(n), qround};
                computed = credited_tallies(bi, gone, gone.pos, out.winners, plan);
                max_tallies = &computed;
            }
            const auto& mt = *max_tallies;

            if (!transfers_only) {
                double shortfall = 0;
                for (int c = 0; c < n; ++c) {
                    if (gone.set.test(c)) {
                        continue;
                    }
                    const auto* cq = find_q(q, c);
                    if (cq != nullptr && cq->lo <= i) {
                        const auto need = quota - mt[static_cast<std::size_t>(c)];
                        out.quota_lb = std::max(out.quota_lb, need);
                        shortfall += py_max0(need);
                    }
                }

                // -sumq: votes changed to lift a short candidate to the quota
                // are used up there, so shortfalls of different candidates add.
                if (sumq) {
                    out.quota_lb = std::max(out.quota_lb, out.deficit_sum + shortfall);
                }
            }

            if (find_q(q, ce) != nullptr) {
                out.winners.set(ce);
                const auto cmax = mt[cei];
                const auto value = quota > cmax ? quota : cmax;
                const auto tv = (value - quota) / value;
                out.transfer.set(ce, tv, tv);

                if (sumq && !transfers_only) {
                    out.deficit_sum += py_max0(quota - cmax);
                }

                if (!transfers_only) {
                    double displacement_cost = 0;
                    if (gone.list.empty()) {
                        bool any = false;
                        double fp_others_max = 0;
                        for (int c = 0; c < n; ++c) {
                            if (gone.set.test(c) || c == ce) {
                                continue;
                            }
                            const auto v = bi.fp[static_cast<std::size_t>(c)];
                            if (!any || v > fp_others_max) {
                                fp_others_max = v;
                                any = true;
                            }
                        }
                        displacement_cost = py_max0(0.5 * (fp_others_max - cmax));
                    }
                    out.quota_lb = std::max({out.quota_lb, quota - cmax, displacement_cost});
                }
            }
        }
        gone.push(ce);
    }

    // Coming out of a seating block into eliminations: work back over the
    // block, adding the no-quota bounds that are now unambiguous.
    int lastseat = pxlen - 1;
    while (lastseat >= 0 && p.order_a[static_cast<std::size_t>(lastseat)] == 0) {
        --lastseat;
    }
    if (!transfers_only && lastseat >= 0 && lastseat < pxlen - 1 &&
        (pxlen == n || (lastseat >= 1 && p.order_a[static_cast<std::size_t>(lastseat - 1)] == 1))) {
        for (int j = lastseat; j >= 0 && p.order_a[static_cast<std::size_t>(j)] == 1; --j) {
            const auto [nqlb, nqs] = backcompute_nq_bound(j, out, bi, p.order_c, q, gone.pos);
            out.no_quota_lb = std::max(out.no_quota_lb, nqlb);
            out.nq_cons_added.merge(j, nqs);
        }
    }

    out.round = pxlen;
    return out;
}

// ---------------------------------------------------------------- range mode

RoundTallies compute_round_tallies(const EqlbCtx& ctx, const BoundInputs& bi,
                                   std::span<const Cand> order_c) {
    const Gone gone(order_c, ctx.round, bi.ncands);
    const auto plan = plan_calc_tallies(gone.list, ctx.winners, ctx.transfer, bi.ncands);
    const auto& ballots = bi.election->ballots;
    const auto n = static_cast<std::size_t>(bi.ncands);
    RoundTallies rt;
    rt.ub_first.assign(n, 0.0);
    rt.ub_present.assign(n, 0.0);
    rt.elb_gain.assign(n, 0.0);
    rt.slb_first.assign(n, 0.0);

    struct Rec {
        int first;
        Valuation v;
    };
    ordered_ballot_pass<Rec>(
        ballots.size(),
        [&](std::size_t b, Rec& rec) {
            const auto prefs = ballots.prefs(b);
            rec.first = first_standing(prefs, gone.set);
            if (rec.first < 0) {
                return false;
            }
            rec.v = calc_tallies(prefs, static_cast<double>(ballots.votes(b)), plan);
            return true;
        },
        [&](std::size_t b, const Rec& rec) {
            const auto f = static_cast<std::size_t>(rec.first);
            rt.ub_first[f] += rec.v.ub;
            rt.slb_first[f] += rec.v.slb;
            const auto prefs = ballots.prefs(b);
            if (prefs[0] != rec.first) {
                rt.elb_gain[f] += rec.v.elb;
            }
            for (const auto p : prefs) {
                if (!gone.set.test(p)) {
                    rt.ub_present[p] += rec.v.ub;
                }
            }
        });
    return rt;
}

EqlbCtx compute_eqlb_stv26(const EqlbCtx& in, const BoundInputs& bi, const PrefixRef& p,
                           const RoundTallies* precomputed, bool transfers_only, bool sumq) {
    EqlbCtx out = in;
    const auto start = in.round;
    Gone gone(p.order_c, start, bi.ncands);
    const auto& q = *p.order_q;
    const auto n = bi.ncands;
    const auto quota = static_cast<double>(bi.quota);
    const auto pxlen = static_cast<int>(p.order_c.size());
    const auto& ballots = bi.election->ballots;

    for (int i = start; i < pxlen; ++i) {
        const auto ce = p.order_c[static_cast<std::size_t>(i)];
        const auto cei = static_cast<std::size_t>(ce);

        if (p.order_a[static_cast<std::size_t>(i)] == 0) {
            if (transfers_only) {
                gone.push(ce);
                continue;
            }
            auto min_ce = bi.fp[cei];
            // max_others: candidate -> upper bound on their tally.
            std::vector<double> max_others(static_cast<std::size_t>(n), 0.0);
            std::vector<char> in_others(static_cast<std::size_t>(n), 0);
            if (i == 0) {
                for (int c = 0; c < n; ++c) {
                    if (c != ce) {
                        in_others[static_cast<std::size_t>(c)] = 1;
                        max_others[static_cast<std::size_t>(c)] = bi.fp[static_cast<std::size_t>(c)];
                    }
                }
            } else if (i == start && precomputed != nullptr) {
                for (int c = 0; c < n; ++c) {
                    if (!gone.set.test(c) && c != ce) {
                        in_others[static_cast<std::size_t>(c)] = 1;
                        max_others[static_cast<std::size_t>(c)] =
                            precomputed->ub_first[static_cast<std::size_t>(c)];
                    }
                }
                min_ce += precomputed->elb_gain[cei];
            } else {
                for (int c = 0; c < n; ++c) {
                    if (!gone.set.test(c) && c != ce) {
                        in_others[static_cast<std::size_t>(c)] = 1;
                    }
                }
                const auto plan = plan_calc_tallies(gone.list, out.winners, out.transfer, n);
                struct Rec {
                    int first;
                    double elb;
                    double ub;
                };
                ordered_ballot_pass<Rec>(
                    ballots.size(),
                    [&](std::size_t b, Rec& rec) {
                        const auto prefs = ballots.prefs(b);
                        rec.first = first_standing(prefs, gone.set);
                        if (rec.first < 0) {
                            return false;
                        }
                        if (rec.first == ce && prefs[0] == ce) {
                            return false; // first preferences are in fp already
                        }
                        const auto v =
                            calc_tallies(prefs, static_cast<double>(ballots.votes(b)), plan);
                        rec.elb = v.elb;
                        rec.ub = v.ub;
                        return true;
                    },
                    [&](std::size_t, const Rec& rec) {
                        if (rec.first != ce) {
                            max_others[static_cast<std::size_t>(rec.first)] += rec.ub;
                        } else {
                            min_ce += rec.elb;
                        }
                    });
            }
            for (int c = 0; c < n; ++c) {
                if (in_others[static_cast<std::size_t>(c)] != 0) {
                    out.elim_lb = std::max(
                        out.elim_lb, py_max0(0.5 * (min_ce - max_others[static_cast<std::size_t>(c)])));
                }
            }
        } else if (find_q(q, ce) != nullptr) {
            double lb_value = 0;
            double ub_value = 0;
            if (i == 0) {
                lb_value = bi.fp[cei];
                ub_value = lb_value;
            } else if (i == start && precomputed != nullptr) {
                lb_value = precomputed->slb_first[cei];
                ub_value = p.order_a[static_cast<std::size_t>(i - 1)] == 1
                               ? precomputed->ub_present[cei]
                               : precomputed->ub_first[cei];
            } else {
                const bool ambiguous = i >= 1 && p.order_a[static_cast<std::size_t>(i - 1)] == 1;
                const auto plan = plan_calc_tallies(gone.list, out.winners, out.transfer, n);
                struct Rec {
                    bool first_is_ce;
                    double slb;
                    double ub;
                };
                ordered_ballot_pass<Rec>(
                    ballots.size(),
                    [&](std::size_t b, Rec& rec) {
                        const auto prefs = ballots.prefs(b);
                        const auto first = first_standing(prefs, gone.set);
                        if (first < 0) {
                            return false;
                        }
                        rec.first_is_ce = first == ce;
                        bool counts = rec.first_is_ce;
                        if (!counts && ambiguous) {
                            for (const auto x : prefs) {
                                if (x == ce) {
                                    counts = true;
                                    break;
                                }
                            }
                        }
                        if (!counts) {
                            return false;
                        }
                        const auto v =
                            calc_tallies(prefs, static_cast<double>(ballots.votes(b)), plan);
                        rec.slb = v.slb;
                        rec.ub = v.ub;
                        return true;
                    },
                    [&](std::size_t, const Rec& rec) {
                        if (rec.first_is_ce) {
                            lb_value += rec.slb;
                        }
                        // Ambiguous rounds credit every ballot still ranking ce.
                        ub_value += rec.ub;
                    });
            }

            out.winners.set(ce);
            const auto cmax = ub_value;
            lb_value = quota > lb_value ? quota : lb_value;
            ub_value = lb_value > ub_value ? lb_value : ub_value;
            out.transfer.set(ce, (lb_value - quota) / lb_value, (ub_value - quota) / ub_value);

            if (!transfers_only) {
                double displacement_cost = 0;
                if (gone.list.empty()) {
                    bool any = false;
                    double fp_others_max = 0;
                    for (int c = 0; c < n; ++c) {
                        if (gone.set.test(c) || c == ce) {
                            continue;
                        }
                        const auto v = bi.fp[static_cast<std::size_t>(c)];
                        if (!any || v > fp_others_max) {
                            fp_others_max = v;
                            any = true;
                        }
                    }
                    displacement_cost = py_max0(0.5 * (fp_others_max - cmax));
                }
                out.quota_lb = std::max({out.quota_lb, quota - cmax, displacement_cost});
            }

            // -sumq: shortfalls of winners seated by quota add up.
            if (sumq && !transfers_only) {
                out.deficit_sum += py_max0(quota - cmax);
                out.quota_lb = std::max(out.quota_lb, out.deficit_sum);
            }
        }
        gone.push(ce);
    }

    EqlbCtx result;
    result.ncands = n;
    result.transfer = std::move(out.transfer);
    result.elim_lb = out.elim_lb;
    result.quota_lb = out.quota_lb;
    result.no_quota_lb = 0;
    result.winners = std::move(out.winners);
    result.round = pxlen;
    result.deficit_sum = out.deficit_sum;
    return result;
}

EqlbCtx compute_eqlb_bst19(const EqlbCtx& in, const BoundInputs& bi, const PrefixRef& p) {
    auto elim_lb = in.elim_lb;
    auto quota_lb = in.quota_lb;
    auto winners = in.winners;
    const auto start = in.round;
    Gone gone(p.order_c, start, bi.ncands);
    const auto& q = *p.order_q;
    const auto n = bi.ncands;
    const auto quota = static_cast<double>(bi.quota);
    const auto pxlen = static_cast<int>(p.order_c.size());
    const auto& ballots = bi.election->ballots;

    for (int i = start; i < pxlen; ++i) {
        const auto ce = p.order_c[static_cast<std::size_t>(i)];
        const auto cei = static_cast<std::size_t>(ce);

        if (p.order_a[static_cast<std::size_t>(i)] == 0) {
            auto min_ce = bi.fp[cei];
            std::vector<double> max_others(static_cast<std::size_t>(n), 0.0);
            std::vector<char> in_others(static_cast<std::size_t>(n), 0);
            if (i == 0) {
                for (int c = 0; c < n; ++c) {
                    if (c != ce) {
                        in_others[static_cast<std::size_t>(c)] = 1;
                        max_others[static_cast<std::size_t>(c)] = bi.fp[static_cast<std::size_t>(c)];
                    }
                }
            } else {
                for (int c = 0; c < n; ++c) {
                    if (!gone.set.test(c) && c != ce) {
                        in_others[static_cast<std::size_t>(c)] = 1;
                    }
                }
                // Vote counts are whole numbers, so these sums are exact in
                // any order.
                for (std::size_t b = 0; b < ballots.size(); ++b) {
                    const auto prefs = ballots.prefs(b);
                    int first = -1;
                    bool through_winner = false;
                    for (const auto x : prefs) {
                        if (first < 0 && !gone.set.test(x)) {
                            first = x;
                        }
                        if (winners.test(x)) {
                            through_winner = true;
                        }
                    }
                    if (first < 0) {
                        continue;
                    }
                    const auto votes = static_cast<double>(ballots.votes(b));
                    if (first != ce) {
                        max_others[static_cast<std::size_t>(first)] += votes;
                    } else if (prefs[0] != ce && !through_winner) {
                        min_ce += votes;
                    }
                }
            }
            for (int c = 0; c < n; ++c) {
                if (in_others[static_cast<std::size_t>(c)] != 0) {
                    elim_lb = std::max(
                        elim_lb, py_max0(0.5 * (min_ce - max_others[static_cast<std::size_t>(c)])));
                }
            }
        } else {
            winners.set(ce);
            if (find_q(q, ce) != nullptr) {
                double cmax = 0;
                if (i == 0) {
                    cmax = bi.fp[cei];
                } else {
                    for (std::size_t b = 0; b < ballots.size(); ++b) {
                        if (first_standing(ballots.prefs(b), gone.set) == ce) {
                            cmax += static_cast<double>(ballots.votes(b));
                        }
                    }
                }
                quota_lb = std::max(quota_lb, quota - cmax);
            }
        }
        gone.push(ce);
    }

    EqlbCtx result;
    result.ncands = n;
    result.elim_lb = elim_lb;
    result.quota_lb = quota_lb;
    result.no_quota_lb = 0;
    result.winners = std::move(winners);
    result.round = pxlen;
    return result;
}

} // namespace marginstv
