#include "marginstv/search.hpp"

#include "marginstv/pyset.hpp"

#include <tbb/parallel_for.h>
#include <tbb/parallel_invoke.h>

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <limits>
#include <set>

namespace marginstv {

namespace {

double wall_seconds() {
    return std::chrono::duration<double>(std::chrono::system_clock::now().time_since_epoch()).count();
}

std::vector<Cand> to_cands(const std::vector<Pref>& v) { return {v.begin(), v.end()}; }

// max(0, ceil(max(elim_lb, quota_lb, no_quota_lb)))
PyNum eqlb_value(const EqlbCtx& ctx) {
    const auto m = std::max({ctx.elim_lb, ctx.quota_lb, ctx.no_quota_lb});
    return py_max(PyNum::integer(0), py_ceil(m));
}

bool needs_transfers(const Options& o) { return o.dlb || o.dlbc || o.prec_et; }

// The elimination/quota bound in the configured mode, or BST19 plus a walk
// for transfer values when something downstream reads them.
EqlbCtx run_eqlb(const SearchInputs& in, const EqlbCtx& start, const PrefixRef& p,
                 const RoundTallies* tallies) {
    const auto& o = *in.options;
    if (o.eqlb || o.eqlbc) {
        return o.useqprefix
                   ? compute_eqlb_stv26_qprefix(start, in.bounds, p, tallies, false, o.sumq,
                                                o.multielim, o.sumnq, o.elimnq)
                   : compute_eqlb_stv26(start, in.bounds, p, tallies, false, o.sumq, o.multielim);
    }
    auto ctx = compute_eqlb_bst19(start, in.bounds, p);
    if (needs_transfers(o)) {
        const auto t = o.useqprefix
                           ? compute_eqlb_stv26_qprefix(start, in.bounds, p, tallies, true)
                           : compute_eqlb_stv26(start, in.bounds, p, tallies, true);
        ctx.transfer = t.transfer;
    }
    return ctx;
}

DispCache run_disp(const SearchInputs& in, const DispCache& dc, const PrefixRef& p,
                   std::span<const Cand> rem, const Transfers& transfer) {
    return in.options->useqprefix
               ? compute_disp_lb_stv26_q_prefix(dc, in.bounds, p, in.winner_set, rem, transfer)
               : compute_disp_lb_stv26(dc, in.bounds, p, in.winner_set, rem, transfer);
}

DistanceResult solve(const SearchInputs& in, std::span<const Cand> order_c,
                     std::span<const int> order_a, std::span<const Cand> rem,
                     const CandSet& winners, const OrderQ& order_q, std::span<const Cand> merge_map,
                     std::span<const Cand> supers, const PyNum& upperbound, int last_round,
                     const PyNum& lowerbound, bool isleaf) {
    DistanceProblem p;
    p.order_c = order_c;
    p.order_a = order_a;
    p.rem = rem;
    p.winners = &winners;
    p.order_q = &order_q;
    p.merge_map = merge_map;
    p.supers = supers;
    p.upperbound = upperbound;
    p.last_round = last_round;
    p.lowerbound = lowerbound;
    p.isleaf = isleaf;
    return solve_stvdistance(in.bounds, in.tot_ballots, p, in.distance);
}

std::vector<Cand> identity_map(int n) {
    std::vector<Cand> m(static_cast<std::size_t>(n));
    for (int c = 0; c < n; ++c) {
        m[static_cast<std::size_t>(c)] = c;
    }
    return m;
}

} // namespace

EqlbCtx blank_eqlb(int ncands) {
    EqlbCtx ctx;
    ctx.ncands = ncands;
    ctx.winners = CandSet(ncands);
    return ctx;
}

DispCache blank_disp(int ncands) {
    DispCache dc;
    dc.ncands = ncands;
    dc.winners = CandSet(ncands);
    return dc;
}

// ---------------------------------------------------------------- initial nodes

InitialResult eval_child_initial(const SearchInputs& in, std::vector<Cand> order_c,
                                 std::vector<int> order_a, OrderQ order_q, const CandSet& winners,
                                 std::vector<Cand> rem, const PyNum& running_ub) {
    const auto& o = *in.options;
    const auto n = in.bounds.ncands;
    const PrefixRef p{order_c, order_a, &order_q};

    const auto orig_prefix =
        order_c[0] == in.full_order_c.at(0) && order_a[0] == in.full_order_a.at(0);

    InitialResult res;
    res.eqlbctx = run_eqlb(in, blank_eqlb(n), p, nullptr);
    res.eqlb = eqlb_value(res.eqlbctx);
    if (orig_prefix) {
        res.eqlb = PyNum::integer(0);
    }
    res.disp_cache = disp_cache_from_metadata(in.bounds);
    res.order_c = order_c;
    res.order_a = order_a;
    res.order_q = order_q;

    if (res.eqlb >= running_ub) {
        res.lb = res.eqlb;
        res.dlb = PyNum::integer(0);
        res.dist = res.eqlb;
        res.dist_ub = res.eqlb;
        return res;
    }

    res.dlb = PyNum::integer(0);
    if (o.dlb || o.dlbc) {
        res.disp_cache = run_disp(in, res.disp_cache, p, rem, res.eqlbctx.transfer);
        res.dlb = res.disp_cache.lowerbound;
    }
    res.lb = py_max(res.dlb, res.eqlb);

    // Initial nodes are internal, so they are solved only under -allminlps.
    const auto skipsolve = o.nominlps || !o.allminlps;
    if (res.lb >= running_ub || skipsolve) {
        res.dist = res.lb;
        res.dist_ub = res.lb;
        return res;
    }

    const auto merge_map = identity_map(n);
    const auto r = solve(in, order_c, order_a, rem, winners, order_q, merge_map, {}, running_ub, 0,
                         res.lb, false);
    res.dist = r.dist;
    res.dist_ub = r.dist_ub;
    res.solved = true;
    return res;
}

// ---------------------------------------------------------------- expansion

Expansion generate_children(const SearchInputs& in, const TreeNode& node, const PyNum& running_ub) {
    const auto& o = *in.options;
    const auto n = in.bounds.ncands;
    const auto forder_c = to_cands(node.order_c);
    const std::vector<int> forder_a(node.order_a.begin(), node.order_a.end());
    const auto& forder_q = node.order_q;

    std::vector<Cand> frem;
    CandSet placed(n);
    for (const auto c : forder_c) {
        placed.set(c);
    }
    for (int c = 0; c < n; ++c) {
        if (!placed.test(c)) {
            frem.push_back(c);
        }
    }
    // derive_winners: a set comprehension over the prefix. With -pc above 1
    // and node-level parallelism the Python builds it in the main process
    // and pickles it to a worker, which rebuilds it in iteration order; its
    // iteration order then decides the quota map's order (get_order_q).
    PySetOrder fwinners;
    for (std::size_t i = 0; i < forder_c.size(); ++i) {
        if (forder_a[i] == 1) {
            fwinners.add(forder_c[i]);
        }
    }
    if (o.pc > 1 && !o.evalpara) {
        fwinners = fwinners.unpickled();
    }

    Expansion ex;
    ex.eqlbctx = node.eqlbctx;
    ex.disp_cache = node.disp_cache;

    // Work shared by all children, run side by side.
    tbb::parallel_invoke(
        [&] {
            if (!o.dlbc) {
                return;
            }
            ex.disp_cache =
                o.useqprefix
                    ? update_disp_cache_q_prefix(node.disp_cache, in.bounds, forder_c, forder_q,
                                                 frem, node.eqlbctx.transfer)
                    : update_disp_cache(node.disp_cache, in.bounds, forder_c, forder_a, frem,
                                        node.eqlbctx.transfer);
        },
        [&] {
            if (!(o.prec_et && o.eqlbc)) {
                return;
            }
            ex.elim_tallies =
                o.useqprefix
                    ? compute_round_tallies_q_prefix(node.eqlbctx, in.bounds, forder_c, forder_q)
                    : compute_round_tallies(node.eqlbctx, in.bounds, forder_c);
        });

    for (const auto r : frem) {
        for (int act = 0; act < 2; ++act) {
            auto node_order_c = forder_c;
            node_order_c.push_back(r);
            std::vector<Cand> rem;
            for (const auto c : frem) {
                if (c != r) {
                    rem.push_back(c);
                }
            }

            auto set_winners = fwinners.copy(); // set(fwinners)
            if (act == 1) {
                set_winners.add(r);
            }
            CandSet node_winners(n);
            for (const auto w : set_winners.order()) {
                node_winners.set(w);
            }
            if (node_winners == in.winner_set) {
                continue; // the reported outcome
            }

            auto node_order_a = forder_a;
            node_order_a.push_back(act);
            int seats_filled = 0;
            for (const auto a : node_order_a) {
                seats_filled += a;
            }

            auto new_rem = rem;
            const auto nrem = static_cast<int>(rem.size());
            bool isleaf = false;
            if (seats_filled > in.bounds.seats) {
                continue;
            }
            if (seats_filled == in.bounds.seats) {
                node_order_c.insert(node_order_c.end(), rem.begin(), rem.end());
                node_order_a.insert(node_order_a.end(), rem.size(), 0);
                new_rem.clear();
                isleaf = true;
            } else if (in.bounds.seats - seats_filled == nrem) {
                // Are the remaining seats exactly the remaining original winners?
                CandSet missing(n);
                for (const auto w : in.full_order_c) {
                    if (in.winner_set.test(w) && !node_winners.test(w)) {
                        missing.set(w);
                    }
                }
                CandSet rem_set(n);
                for (const auto c : rem) {
                    rem_set.set(c);
                }
                if (missing == rem_set) {
                    continue;
                }
                isleaf = true;
            }

            auto add_child = [&](OrderQ q) {
                ChildSpec spec;
                spec.parent_dist = node.dist;
                spec.order_c = node_order_c;
                spec.order_a = node_order_a;
                spec.order_q = std::move(q);
                spec.winners = node_winners;
                spec.rem = new_rem;
                spec.isleaf = isleaf;
                spec.running_ub = running_ub;
                ex.children.push_back(std::move(spec));
            };

            if (act == 0) {
                add_child(forder_q);
            } else if (o.useqprefix) {
                // One child per round in which r could first hold a quota.
                const auto lenf = static_cast<int>(forder_a.size());
                auto minqr = lenf;
                if (forder_a.back() == 1) {
                    minqr = find_q(forder_q, forder_c.back())->lo;
                }
                for (auto i = lenf; i >= minqr; --i) {
                    auto q = forder_q;
                    q.push_back({r, i, i});
                    add_child(std::move(q));
                }
            } else {
                const auto last = compute_last_round(node_order_c, node_order_a, in.bounds.seats, n);
                add_child(get_order_q(node_order_a, last, set_winners.order(), node_order_c));
            }
        }
    }
    return ex;
}

ChildResult eval_child(const SearchInputs& in, const Expansion& ex, const ChildSpec& spec) {
    const auto& o = *in.options;
    const auto n = in.bounds.ncands;
    const PrefixRef p{spec.order_c, spec.order_a, &spec.order_q};
    const RoundTallies* tallies = ex.elim_tallies ? &*ex.elim_tallies : nullptr;

    const auto start_ctx = o.eqlbc ? ex.eqlbctx : blank_eqlb(n);
    const auto start_disp = o.dlbc ? ex.disp_cache : blank_disp(n);

    ChildResult res;
    res.isleaf = spec.isleaf;
    res.order_c = spec.order_c;
    res.order_a = spec.order_a;
    res.order_q = spec.order_q;
    res.eqlbctx = run_eqlb(in, start_ctx, p, tallies);
    res.eqlb = eqlb_value(res.eqlbctx);

    if (res.eqlb >= spec.running_ub) {
        res.disp_cache = blank_disp(n);
        res.lb = res.eqlb;
        res.dlb = PyNum::integer(0);
        res.dist = res.eqlb;
        res.dist_ub = res.eqlb;
        return res;
    }

    if (o.dlb || o.dlbc) {
        res.disp_cache = run_disp(in, start_disp, p, spec.rem, res.eqlbctx.transfer);
        res.dlb = res.disp_cache.lowerbound;
    } else {
        res.disp_cache = start_disp;
        res.dlb = PyNum::integer(0);
    }

    const auto lowerbound = py_max(res.eqlb, py_max(res.dlb, spec.parent_dist));
    res.lb = lowerbound;

    // Solve a leaf always, an internal node only under -allminlps, and
    // nothing under -nominlps.
    const auto skipsolve = o.nominlps || !(o.allminlps || spec.isleaf);
    if (lowerbound >= spec.running_ub || skipsolve) {
        res.dist = lowerbound;
        res.dist_ub = lowerbound;
        return res;
    }

    DistanceResult r;
    if (o.merge) {
        const auto m = merge_outcome(spec.order_c, spec.order_a, spec.order_q, spec.rem, n);
        const auto last = compute_last_round(m.order_c, m.order_a, in.bounds.seats,
                                             static_cast<int>(m.order_c.size() + spec.rem.size()));
        r = solve(in, m.order_c, m.order_a, spec.rem, spec.winners, m.order_q, m.merge_map,
                  m.supers, spec.running_ub, last, lowerbound, spec.isleaf);
    } else {
        const auto last = compute_last_round(spec.order_c, spec.order_a, in.bounds.seats, n);
        const auto merge_map = identity_map(n);
        r = solve(in, spec.order_c, spec.order_a, spec.rem, spec.winners, spec.order_q, merge_map,
                  {}, spec.running_ub, last, lowerbound, spec.isleaf);
    }
    res.dist = r.dist;
    res.dist_ub = r.dist_ub;
    res.solved = true;
    return res;
}

// ---------------------------------------------------------------- the search

namespace {

class Search {
  public:
    Search(const SearchInputs& in, PyNum upperbound, Logger& log)
        : in_(in), o_(*in.options), log_(log), running_ub_(upperbound) {}

    SearchResult run();

  private:
    void log_frontier() {
        log_.line("Lower bound " + running_lb_.str() + ", upper bound " + running_ub_.str());
        log_.line(frontier_.str());
    }
    [[nodiscard]] bool gap_closed() const {
        return std::fabs((running_ub_ - running_lb_).as_double()) <= o_.agap;
    }
    SearchResult result() const {
        return {running_lb_, running_ub_, nexps_, nsolves_, frontier_.ignore_count(),
                frontier_.agg_prune_count()};
    }

    void dive();
    void initial_frontier();
    // Handles one child; returns true when the search has converged.
    bool handle_child(ChildResult& c);

    const SearchInputs& in_;
    const Options& o_;
    Logger& log_;
    Frontier frontier_;
    PyNum running_ub_;
    PyNum running_lb_ = PyNum::integer(0);
    std::uint64_t nexps_ = 0;
    std::uint64_t nsolves_ = 0;
};

} // namespace

OrderQ reported_quota_rounds(const Outcome& outcome, int ncands) {
    OrderQ q;
    std::optional<int> prev;
    for (std::size_t p = 0; p < outcome.order_c.size(); ++p) {
        if (outcome.order_a[p] == 0) {
            prev.reset();
            continue;
        }
        const auto c = outcome.order_c[p];
        const auto pos = static_cast<int>(p);
        auto r = pos;
        for (int i = prev.value_or(pos); i <= pos; ++i) {
            const auto t = outcome.tallies[static_cast<std::size_t>(c) * static_cast<std::size_t>(ncands) +
                                           static_cast<std::size_t>(i)];
            if (t >= static_cast<double>(outcome.quota)) {
                r = i;
                break;
            }
        }
        q.push_back(QEntry{c, r, r});
        prev = r;
    }
    return q;
}

namespace {

// The leaf the search reaches by following seq_c/seq_a, cut where
// generate_children ends a prefix. A seated candidate takes the quota round
// in want_q (-1: its own round), kept within the rounds the search allows.
// Empty when the leaf elects the reported winners (dive_leaf in stvtree.py).
std::optional<DiveLeaf> dive_leaf(const SearchInputs& in, const std::vector<Cand>& seq_c,
                                  const std::vector<int>& seq_a, const std::vector<int>& want_q) {
    const auto n = in.bounds.ncands;
    const auto seats = in.bounds.seats;
    DiveLeaf leaf{{}, {}, {}, CandSet(n), {}};
    CandSet placed(n);
    int won = 0;
    for (std::size_t k = 0; k < seq_c.size(); ++k) {
        const auto c = seq_c[k];
        const auto p = static_cast<int>(leaf.order_c.size());
        leaf.order_c.push_back(c);
        leaf.order_a.push_back(seq_a[k]);
        placed.set(c);
        if (seq_a[k] == 1) {
            const auto lo = p > 0 && leaf.order_a[static_cast<std::size_t>(p - 1)] == 1
                                ? leaf.order_q.back().lo
                                : p;
            const auto want = want_q[static_cast<std::size_t>(c)];
            const auto r = std::min(std::max(want >= 0 ? want : p, lo), p);
            leaf.order_q.push_back(QEntry{c, r, r});
            leaf.winners.set(c);
            ++won;
        }
        leaf.rem.clear();
        for (int d = 0; d < n; ++d) {
            if (!placed.test(d)) {
                leaf.rem.push_back(d);
            }
        }
        if (won == seats) {
            for (const auto d : leaf.rem) {
                leaf.order_c.push_back(d);
                leaf.order_a.push_back(0);
            }
            leaf.rem.clear();
            break;
        }
        if (seats - won == static_cast<int>(leaf.rem.size())) {
            break;
        }
    }
    auto all = leaf.winners;
    for (const auto d : leaf.rem) {
        all.set(d);
    }
    if (all == in.winner_set) {
        return std::nullopt;
    }
    return leaf;
}

// -dive: how many of the reported outcome's last seats to start a
// continuation before, and how many non-winners to try in each winner's place.
constexpr int kDiveSeats = 4;
constexpr std::size_t kDiveContenders = 3;

// Tallies at the end of a prefix, with the transfer walk over it resumed
// from ctx (dive_tallies in stvtree.py).
std::vector<double> dive_tallies(const SearchInputs& in, EqlbCtx& ctx, const std::vector<Cand>& oc,
                                 const std::vector<int>& oa, const OrderQ& q) {
    if (oc.empty()) {
        return in.bounds.fp;
    }
    const PrefixRef p{oc, oa, &q};
    ctx = compute_eqlb_stv26_qprefix(ctx, in.bounds, p, nullptr, true);
    return compute_round_tallies_q_prefix(ctx, in.bounds, oc, q).tallies;
}

struct DiveSeq {
    std::vector<Cand> order_c;
    std::vector<int> order_a;
    std::vector<int> want_q;
};

// The count continued from a prefix so that only candidates in new_winners
// are seated (dive_continue in stvtree.py).
DiveSeq dive_continue(const SearchInputs& in, const std::vector<Cand>& pc,
                      const std::vector<int>& pa, const OrderQ& pq, const CandSet& new_winners,
                      const std::vector<int>& known_q) {
    const auto n = in.bounds.ncands;
    const auto seats = in.bounds.seats;
    const auto quota = static_cast<double>(in.bounds.quota);
    DiveSeq d{pc, pa, std::vector<int>(static_cast<std::size_t>(n), -1)};
    auto q = pq;
    // A reported winner who already held a quota keeps that round.
    std::vector<int> first_q(static_cast<std::size_t>(n), -1);
    {
        CandSet in_prefix(n);
        for (const auto c : pc) {
            in_prefix.set(c);
        }
        for (int c = 0; c < n; ++c) {
            const auto r = known_q[static_cast<std::size_t>(c)];
            if (new_winners.test(c) && !in_prefix.test(c) && r >= 0 &&
                r < static_cast<int>(pc.size())) {
                first_q[static_cast<std::size_t>(c)] = r;
            }
        }
    }
    auto ctx = blank_eqlb(n);
    while (true) {
        CandSet placed(n);
        for (const auto c : d.order_c) {
            placed.set(c);
        }
        std::vector<Cand> standing;
        for (int c = 0; c < n; ++c) {
            if (!placed.test(c)) {
                standing.push_back(c);
            }
        }
        const auto seated = static_cast<int>(std::count(d.order_a.begin(), d.order_a.end(), 1));
        if (seated == seats || static_cast<int>(standing.size()) == seats - seated) {
            break;
        }
        const auto t = dive_tallies(in, ctx, d.order_c, d.order_a, q);
        const auto p = static_cast<int>(d.order_c.size());
        for (const auto c : standing) {
            const auto ci = static_cast<std::size_t>(c);
            if (first_q[ci] < 0 && t[ci] >= quota) {
                first_q[ci] = p;
            }
        }
        std::optional<Cand> seat;
        for (const auto c : standing) {
            const auto ci = static_cast<std::size_t>(c);
            if (!new_winners.test(c) || first_q[ci] < 0) {
                continue;
            }
            // Largest tally first; on a tie the smaller candidate number.
            if (!seat || t[ci] > t[static_cast<std::size_t>(*seat)]) {
                seat = c;
            }
        }
        if (seat) {
            const auto r = first_q[static_cast<std::size_t>(*seat)];
            d.order_c.push_back(*seat);
            d.order_a.push_back(1);
            q.push_back(QEntry{*seat, r, r});
            continue;
        }
        std::optional<Cand> elim;
        for (const auto c : standing) {
            if (new_winners.test(c)) {
                continue;
            }
            if (!elim || t[static_cast<std::size_t>(c)] < t[static_cast<std::size_t>(*elim)]) {
                elim = c;
            }
        }
        if (!elim) {
            break;
        }
        d.order_c.push_back(*elim);
        d.order_a.push_back(0);
    }
    for (const auto& e : q) {
        d.want_q[static_cast<std::size_t>(e.c)] = e.lo;
    }
    return d;
}

} // namespace

namespace {

// A leaf's order, actions and quota rounds, for spotting repeats.
std::vector<int> dive_key(const DiveLeaf& leaf) {
    std::vector<int> key(leaf.order_c.begin(), leaf.order_c.end());
    key.push_back(-1);
    key.insert(key.end(), leaf.order_a.begin(), leaf.order_a.end());
    key.push_back(-1);
    auto q = leaf.order_q;
    std::sort(q.begin(), q.end(), [](const QEntry& a, const QEntry& b) { return a.c < b.c; });
    for (const auto& e : q) {
        key.push_back(e.c);
        key.push_back(e.lo);
    }
    return key;
}

} // namespace

std::vector<DiveLeaf> dive_leaves(const SearchInputs& in) {
    const auto n = in.bounds.ncands;
    const auto& oc = in.full_order_c;
    const auto& oa = in.full_order_a;
    int last_seat = -1;
    for (std::size_t i = 0; i < oa.size(); ++i) {
        if (oa[i] == 1) {
            last_seat = static_cast<int>(i);
        }
    }
    int j = -1;
    for (int i = 0; i < last_seat; ++i) {
        if (oa[static_cast<std::size_t>(i)] == 0) {
            j = i;
        }
    }
    std::vector<DiveLeaf> leaves;
    if (!in.reported_q) {
        return leaves;
    }
    std::vector<int> want(static_cast<std::size_t>(n), -1);
    for (const auto& e : *in.reported_q) {
        want[static_cast<std::size_t>(e.c)] = e.lo;
    }
    if (j >= 0) {
        const std::vector<Cand> tail(oc.begin() + j, oc.end());
        for (const auto w : tail) {
            if (!in.winner_set.test(w)) {
                continue;
            }
            for (const auto x : tail) {
                if (in.winner_set.test(x)) {
                    continue;
                }
                std::vector<Cand> seq(oc.begin(), oc.begin() + j);
                for (const auto c : tail) {
                    seq.push_back(c == w ? x : c == x ? w : c);
                }
                auto q = want;
                q[static_cast<std::size_t>(x)] = want[static_cast<std::size_t>(w)];
                if (auto leaf = dive_leaf(in, seq, oa, q)) {
                    leaves.push_back(std::move(*leaf));
                }
            }
        }
    }

    // Continuations: follow the reported outcome until k seats are left,
    // then put one of the kDiveContenders non-winners with the largest
    // tallies there in place of one of the remaining winners.
    std::vector<int> seat_pos;
    for (std::size_t i = 0; i < oa.size(); ++i) {
        if (oa[i] == 1) {
            seat_pos.push_back(static_cast<int>(i));
        }
    }
    const auto nseat = static_cast<int>(seat_pos.size());
    const std::vector<int> none(static_cast<std::size_t>(n), -1);
    for (int k = 1; k <= std::min(kDiveSeats, nseat); ++k) {
        const auto t = nseat - k - 1 >= 0 ? seat_pos[static_cast<std::size_t>(nseat - k - 1)] + 1 : 0;
        const std::vector<Cand> pc(oc.begin(), oc.begin() + t);
        const std::vector<int> pa(oa.begin(), oa.begin() + t);
        OrderQ pq;
        CandSet placed(n);
        for (const auto c : pc) {
            placed.set(c);
            for (const auto& e : *in.reported_q) {
                if (e.c == c) {
                    pq.push_back(e);
                }
            }
        }
        auto ctx = blank_eqlb(n);
        const auto tallies = dive_tallies(in, ctx, pc, pa, pq);
        std::vector<Cand> remaining;
        std::vector<Cand> contenders;
        for (int c = 0; c < n; ++c) {
            if (placed.test(c)) {
                continue;
            }
            (in.winner_set.test(c) ? remaining : contenders).push_back(c);
        }
        std::stable_sort(contenders.begin(), contenders.end(), [&](Cand a, Cand b) {
            return tallies[static_cast<std::size_t>(a)] > tallies[static_cast<std::size_t>(b)];
        });
        if (contenders.size() > kDiveContenders) {
            contenders.resize(kDiveContenders);
        }
        for (const auto w : remaining) {
            for (const auto x : contenders) {
                CandSet nw(n);
                for (const auto c : remaining) {
                    if (c != w) {
                        nw.set(c);
                    }
                }
                nw.set(x);
                // With the reported quota rounds kept, and with each round
                // taken from where the continuation first sees the quota.
                for (const auto* known : std::array<const std::vector<int>*, 2>{&want, &none}) {
                    const auto d = dive_continue(in, pc, pa, pq, nw, *known);
                    if (auto leaf = dive_leaf(in, d.order_c, d.order_a, d.want_q)) {
                        leaves.push_back(std::move(*leaf));
                    }
                }
            }
        }
    }

    // The same leaf can come from more than one route: keep the first.
    std::vector<DiveLeaf> unique;
    std::set<std::vector<int>> seen;
    for (auto& leaf : leaves) {
        if (seen.insert(dive_key(leaf)).second) {
            unique.push_back(std::move(leaf));
        }
    }
    return unique;
}

namespace {

// -dive: evaluate the leaves near the reported last seat, and start from the
// cheapest as the upper bound.
// -dive: most improving steps taken from the cheapest dive leaf; how many of
// a leaf's last rounds a step may change; how far an elimination may move.
constexpr int kDiveSteps = 50;
constexpr int kDiveWindow = 14;
constexpr int kDiveReach = 4;

// How many of a leaf's rounds the search decides one by one. A leaf that
// fills the last seat is padded with the rest as eliminations in the same
// step (dive_size in stvtree.py).
int dive_size(const DiveLeaf& leaf) {
    auto size = static_cast<int>(leaf.order_a.size());
    if (leaf.rem.empty()) {
        for (std::size_t i = 0; i < leaf.order_a.size(); ++i) {
            if (leaf.order_a[i] == 1) {
                size = static_cast<int>(i) + 1;
            }
        }
    }
    return size;
}

// The leaves one step from a leaf, changing only its rounds from start on
// (dive_moves in stvtree.py).
std::vector<DiveLeaf> dive_moves(const SearchInputs& in, const DiveLeaf& leaf, int start) {
    const auto n = in.bounds.ncands;
    const auto size = dive_size(leaf);
    const std::vector<Cand> seq_c(leaf.order_c.begin(), leaf.order_c.begin() + size);
    const std::vector<int> seq_a(leaf.order_a.begin(), leaf.order_a.begin() + size);
    std::vector<int> want(static_cast<std::size_t>(n), -1);
    for (const auto& e : leaf.order_q) {
        want[static_cast<std::size_t>(e.c)] = e.lo;
    }
    std::vector<DiveLeaf> moves;
    std::set<std::vector<int>> seen;
    const auto add = [&](const std::vector<Cand>& c, const std::vector<int>& a,
                         const std::vector<int>& q) {
        auto moved = dive_leaf(in, c, a, q);
        if (!moved) {
            return;
        }
        if (seen.insert(dive_key(*moved)).second) {
            moves.push_back(std::move(*moved));
        }
    };
    for (int i = start; i < size; ++i) {
        const auto iu = static_cast<std::size_t>(i);
        if (seq_a[iu] == 1) {
            for (const auto d : {-1, 1}) {
                const auto r = want[static_cast<std::size_t>(seq_c[iu])] + d;
                const auto lo = i > 0 && seq_a[iu - 1] == 1
                                    ? want[static_cast<std::size_t>(seq_c[iu - 1])]
                                    : i;
                if (lo <= r && r <= i) {
                    auto q = want;
                    q[static_cast<std::size_t>(seq_c[iu])] = r;
                    add(seq_c, seq_a, q);
                }
            }
            continue;
        }
        for (int d = -kDiveReach; d <= kDiveReach; ++d) {
            const auto j = i + d;
            if (d == 0 || j < start || j >= size) {
                continue;
            }
            auto c = seq_c;
            auto a = seq_a;
            const auto x = c[iu];
            const auto y = a[iu];
            c.erase(c.begin() + i);
            a.erase(a.begin() + i);
            c.insert(c.begin() + j, x);
            a.insert(a.begin() + j, y);
            add(c, a, want);
        }
    }
    return moves;
}

// A leaf's walk evaluated up to some prefix (DiveState in stvtree.py).
struct DiveState {
    int m = 0;
    EqlbCtx ctx;
    DispCache disp;
    PyNum dist;
    ChildResult res;
};

// A leaf's bound as the search would give it on reaching the leaf: each
// prefix on the way is evaluated as a child of the one before, with the same
// shared work generate_children does. Stops at the first prefix whose bound
// reaches running_ub. start resumes from a prefix already evaluated; with
// stop, the walk ends at that prefix and stores its state in *at
// (dive_walk in stvtree.py).
ChildResult dive_walk(const SearchInputs& in, const DiveLeaf& leaf, const PyNum& running_ub,
                      const DiveState* start = nullptr, int stop = -1,
                      std::optional<DiveState>* at = nullptr) {
    const auto& o = *in.options;
    const auto n = in.bounds.ncands;
    const auto& oc = leaf.order_c;
    const auto& oa = leaf.order_a;
    const auto size = dive_size(leaf);
    // A start at or past the leaf's own end does not apply to it.
    if (start != nullptr && start->m >= size) {
        start = nullptr;
    }

    const auto prefix = [&](int m, bool isleaf) {
        ChildSpec s;
        s.order_c.assign(oc.begin(), oc.begin() + m);
        s.order_a.assign(oa.begin(), oa.begin() + m);
        CandSet placed(n);
        for (const auto c : s.order_c) {
            placed.set(c);
        }
        for (const auto& e : leaf.order_q) {
            if (placed.test(e.c)) {
                s.order_q.push_back(e);
            }
        }
        s.winners = CandSet(n);
        for (std::size_t i = 0; i < s.order_c.size(); ++i) {
            if (s.order_a[i] == 1) {
                s.winners.set(s.order_c[i]);
            }
        }
        for (int c = 0; c < n; ++c) {
            if (!placed.test(c)) {
                s.rem.push_back(c);
            }
        }
        s.isleaf = isleaf;
        s.running_ub = running_ub;
        return s;
    };

    int m0 = 1;
    ChildResult res;
    EqlbCtx ctx;
    DispCache disp;
    PyNum dist;
    ChildSpec parent;
    if (start == nullptr) {
        parent = prefix(1, false);
        auto init = eval_child_initial(in, parent.order_c, parent.order_a, parent.order_q,
                                       parent.winners, parent.rem, running_ub);
        res.lb = init.lb;
        res.dlb = init.dlb;
        res.eqlb = init.eqlb;
        res.dist = init.dist;
        res.dist_ub = init.dist_ub;
        res.solved = init.solved;
        if (size == 1 || !res.dist || *res.dist >= running_ub) {
            return res;
        }
        ctx = std::move(init.eqlbctx);
        disp = std::move(init.disp_cache);
        dist = *res.dist;
    } else {
        m0 = start->m;
        ctx = start->ctx;
        disp = start->disp;
        dist = start->dist;
        res = start->res;
        parent = prefix(m0, false);
    }
    if (stop == m0 && at != nullptr) {
        *at = DiveState{m0, ctx, disp, dist, res};
        return res;
    }

    for (int m = m0 + 1; m <= size; ++m) {
        Expansion ex;
        ex.eqlbctx = ctx;
        ex.disp_cache = o.dlbc ? update_disp_cache_q_prefix(disp, in.bounds, parent.order_c,
                                                            parent.order_q, parent.rem, ctx.transfer)
                               : disp;
        if (o.prec_et && o.eqlbc) {
            ex.elim_tallies =
                compute_round_tallies_q_prefix(ctx, in.bounds, parent.order_c, parent.order_q);
        }
        ChildSpec child;
        if (m == size) {
            child.order_c = oc;
            child.order_a = oa;
            child.order_q = leaf.order_q;
            child.winners = leaf.winners;
            child.rem = leaf.rem;
            child.isleaf = true;
            child.running_ub = running_ub;
        } else {
            child = prefix(m, false);
        }
        child.parent_dist = dist;
        res = eval_child(in, ex, child);
        if (!res.dist || *res.dist >= running_ub) {
            return res;
        }
        dist = *res.dist;
        ctx = res.eqlbctx;
        disp = res.disp_cache;
        parent = std::move(child);
        if (m == stop && at != nullptr) {
            *at = DiveState{m, ctx, disp, dist, res};
            return res;
        }
    }
    return res;
}

ChildResult dive_value(const SearchInputs& in, const DiveLeaf& leaf, const PyNum& running_ub,
                       const DiveState* start = nullptr) {
    return dive_walk(in, leaf, running_ub, start);
}

void Search::dive() {
    const auto leaves = dive_leaves(in_);
    std::vector<ChildResult> results(leaves.size());
    const auto ub = running_ub_;
    tbb::parallel_for(std::size_t{0}, leaves.size(),
                      [&](std::size_t i) { results[i] = dive_value(in_, leaves[i], ub); });
    for (std::size_t i = 0; i < results.size(); ++i) {
        const auto& c = results[i];
        const auto& l = leaves[i];
        if (c.solved) {
            ++nsolves_;
        }
        log_.line("DIVE " + py_list_str(l.order_c) + "/" + py_list_str(l.order_a) + "/" +
                  order_q_str(l.order_q) + " LB " + c.lb.str() + " (D " + c.dlb.str() + " EQ " +
                  c.eqlb.str() + ")");
        if (!c.dist) {
            log_.line("    DISTANCE None/Infeasible");
        } else {
            log_.line("    DISTANCE " + c.dist->str() + "/" + c.dist_ub->str() +
                      ", MINLP used: " + std::string(py_bool(c.solved)));
        }
        if (!c.dist || *c.dist < PyNum::integer(0) || *c.dist >= running_ub_) {
            continue;
        }
        log_.line("Reducing upper bound from " + running_ub_.str() + " to " + c.dist->str());
        running_ub_ = *c.dist;
    }

    // Local improvement from the cheapest leaf: take the cheapest step that
    // lowers its bound, until none does.
    std::optional<std::size_t> best;
    for (std::size_t i = 0; i < results.size(); ++i) {
        const auto& d = results[i].dist;
        if (d && *d >= PyNum::integer(0) && (!best || *d < *results[*best].dist)) {
            best = i;
        }
    }
    if (!best) {
        return;
    }
    auto cur = leaves[*best];
    auto cur_val = *results[*best].dist;
    for (int step = 0; step < kDiveSteps; ++step) {
        // The rounds before the window are the same in every move: their
        // walk is done once.
        const auto first = std::max(1, dive_size(cur) - kDiveWindow);
        std::optional<DiveState> state;
        dive_walk(in_, cur, cur_val, nullptr, first, &state);
        if (!state) {
            break;
        }
        const auto moves = dive_moves(in_, cur, first);
        std::vector<ChildResult> vals(moves.size());
        tbb::parallel_for(std::size_t{0}, moves.size(), [&](std::size_t i) {
            vals[i] = dive_value(in_, moves[i], cur_val, &*state);
        });
        std::optional<std::size_t> pick;
        for (std::size_t i = 0; i < vals.size(); ++i) {
            const auto& d = vals[i].dist;
            if (d && *d < cur_val && (!pick || *d < *vals[*pick].dist)) {
                pick = i;
            }
        }
        if (!pick) {
            break;
        }
        const auto& c = vals[*pick];
        cur = moves[*pick];
        cur_val = *c.dist;
        if (c.solved) {
            ++nsolves_;
        }
        log_.line("DIVE STEP " + py_list_str(cur.order_c) + "/" + py_list_str(cur.order_a) + "/" +
                  order_q_str(cur.order_q) + " LB " + c.lb.str() + " (D " + c.dlb.str() + " EQ " +
                  c.eqlb.str() + ")");
        log_.line("    DISTANCE " + c.dist->str() + "/" + c.dist_ub->str() +
                  ", MINLP used: " + std::string(py_bool(c.solved)));
    }
    if (cur_val < running_ub_) {
        log_.line("Reducing upper bound from " + running_ub_.str() + " to " + cur_val.str());
        running_ub_ = cur_val;
    }
}

void Search::initial_frontier() {
    const auto n = in_.bounds.ncands;
    struct Spec {
        std::vector<Cand> order_c;
        std::vector<int> order_a;
        OrderQ order_q;
        CandSet winners;
        std::vector<Cand> rem;
    };
    std::vector<Spec> specs;
    for (int cand = 0; cand < n; ++cand) {
        std::vector<Cand> rem;
        for (int c = 0; c < n; ++c) {
            if (c != cand) {
                rem.push_back(c);
            }
        }
        for (int act = 0; act < 2; ++act) {
            Spec s{{cand}, {act}, {}, CandSet(n), rem};
            if (act == 1) {
                s.winners.set(cand);
                s.order_q.push_back(o_.useqprefix ? QEntry{cand, 0, 0} : QEntry{cand, -1, -1});
            }
            specs.push_back(std::move(s));
        }
    }

    std::vector<InitialResult> results(specs.size());
    const auto ub = running_ub_;
    tbb::parallel_for(std::size_t{0}, specs.size(), [&](std::size_t i) {
        auto& s = specs[i];
        results[i] = eval_child_initial(in_, s.order_c, s.order_a, s.order_q, s.winners, s.rem, ub);
    });

    for (auto& r : results) {
        if (r.solved) {
            ++nsolves_;
        }
        log_.line("EVALUATING " + py_list_str(r.order_c) + "/" + py_list_str(r.order_a) + " LB " +
                  r.lb.str() + " (D " + r.dlb.str() + " EQ " + r.eqlb.str() + ")");
        if (r.lb < running_ub_) {
            if (!r.dist) {
                log_.line("    DISTANCE None/Infeasible");
            } else {
                log_.line("    DISTANCE " + py_fixed(r.dist->as_double(), 2) + "/" +
                          py_fixed(r.dist_ub->as_double(), 2));
            }
        }
        if (!r.dist || *r.dist >= running_ub_) {
            continue;
        }
        log_.line("        Added to frontier");
        running_lb_ = frontier_.size() > 0 ? frontier_.lower_bound() : *r.dist;
        frontier_.insert(std::make_unique<TreeNode>(std::move(r.order_c), std::move(r.order_a),
                                                    std::move(r.order_q), std::move(r.eqlbctx),
                                                    std::move(r.disp_cache), *r.dist, *r.dist_ub),
                         o_.lse);
    }
}

bool Search::handle_child(ChildResult& c) {
    if (c.solved) {
        ++nsolves_;
    }
    log_.line("EVALUATED " + py_list_str(c.order_c) + "/" + py_list_str(c.order_a) + "/" +
              order_q_str(c.order_q) + " LB " + c.lb.str() + " (D " + c.dlb.str() + " EQ " +
              c.eqlb.str() + ")");
    if (!c.dist) {
        log_.line("    DISTANCE None/Infeasible");
    } else {
        log_.line("    DISTANCE " + c.dist->str() + "/" + c.dist_ub->str() +
                  ", MINLP used: " + std::string(py_bool(c.solved)));
    }

    if (!c.dist || *c.dist >= running_ub_) {
        log_.line("        PRUNED!");
        return false;
    }

    if (c.isleaf) {
        log_.line("        LEAF");
        if (*c.dist < running_ub_) {
            log_.line("Reducing upper bound from " + running_ub_.str() + " to " + c.dist->str());
        }
        running_ub_ = py_min(running_ub_, *c.dist);
        if (gap_closed()) {
            return true;
        }
        frontier_.prune(running_ub_, log_);
        return false;
    }

    auto node = std::make_unique<TreeNode>(std::move(c.order_c), std::move(c.order_a),
                                           std::move(c.order_q), std::move(c.eqlbctx),
                                           std::move(c.disp_cache), *c.dist, *c.dist_ub);
    if (!frontier_.insert(std::move(node), o_.lse)) {
        log_.line("        SUBSUMED");
    }
    return false;
}

SearchResult Search::run() {
    const auto tstart = wall_seconds();

    if (o_.dive) {
        dive();
    }
    initial_frontier();
    log_frontier();

    auto tnow = wall_seconds();
    log_.line("Time elapsed " + py_float_repr(tnow - tstart) + "s");
    log_.flush();
    if (tnow - tstart > o_.limit) {
        log_.line("Time start " + py_float_repr(tstart) + ", now " + py_float_repr(tnow) +
                  ", difference " + py_float_repr(tnow - tstart));
        return result();
    }
    if (frontier_.size() == 0) {
        running_lb_ = running_ub_;
        log_.line("Search space exhausted");
    }

    bool converged = false;
    while (frontier_.size() > 0) {
        running_lb_ = frontier_.lower_bound();
        log_.line("Lower bound " + running_lb_.str() + ", upper bound " + running_ub_.str());
        if (gap_closed()) {
            converged = true;
            break;
        }

        auto fnodes = frontier_.pop(static_cast<std::size_t>(o_.pc));
        ++nexps_;
        for (const auto& fn : fnodes) {
            log_.line("EXPANDING NODE " + fn->str());
        }

        // Expand every popped node, and every child of each, in parallel.
        const auto ub = running_ub_;
        std::vector<Expansion> expansions(fnodes.size());
        std::vector<std::vector<ChildResult>> results(fnodes.size());
        tbb::parallel_for(std::size_t{0}, fnodes.size(), [&](std::size_t i) {
            expansions[i] = generate_children(in_, *fnodes[i], ub);
            const auto& ex = expansions[i];
            results[i].resize(ex.children.size());
            tbb::parallel_for(std::size_t{0}, ex.children.size(), [&](std::size_t j) {
                results[i][j] = eval_child(in_, ex, ex.children[j]);
            });
        });
        fnodes.clear();
        expansions.clear();

        for (auto& group : results) {
            for (auto& c : group) {
                if (handle_child(c)) {
                    converged = true;
                    break;
                }
            }
            if (converged) {
                break;
            }
        }
        results.clear();

        if (!converged && frontier_.size() > 0) {
            const auto old_lb = running_lb_;
            running_lb_ = py_max(running_lb_, frontier_.lower_bound());
            if (old_lb < running_lb_) {
                log_.line("Increasing lower bound from " + old_lb.str() + " to " + running_lb_.str());
            }
            if (gap_closed()) {
                converged = true;
                break;
            }
        }
        if (frontier_.size() == 0) {
            running_lb_ = running_ub_;
            log_.line("Search space exhausted");
        }
        if (converged) {
            break;
        }

        tnow = wall_seconds();
        if (frontier_.size() > 0) {
            log_frontier();
            log_.line("Time elapsed " + py_float_repr(tnow - tstart) + "s");
        }
        log_.flush();
        if (tnow - tstart > o_.limit) {
            return result();
        }
    }

    if (converged || frontier_.size() == 0) {
        log_.line("-------------------------------------------");
        log_.line("MARGIN LB: " + running_lb_.str() + "--" + running_ub_.str() + ", " +
                  std::to_string(nexps_) + " nodes expanded, " + std::to_string(nsolves_) +
                  " solves.");
        log_.line("-------------------------------------------");
    }
    log_.line("Time to finish: " + py_float_repr(wall_seconds() - tstart) + "s");
    return result();
}

} // namespace

SearchResult treestv(const SearchInputs& in, PyNum upperbound, Logger& log) {
    Search s(in, upperbound, log);
    return s.run();
}

} // namespace marginstv
