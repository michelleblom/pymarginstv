#include "marginstv/search.hpp"

#include "marginstv/pyset.hpp"
#include "marginstv/membership.hpp"
#include "marginstv/weakseed.hpp"

#include <tbb/parallel_for.h>
#include <tbb/parallel_invoke.h>

#include <chrono>
#include <algorithm>
#include <mutex>
#include <memory>
#include <map>
#include <cmath>
#include <limits>

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

// -membership: how many of a block's (or an open run's IN) largest
// candidates get the bound that keeps them standing while the others go.
constexpr int kMembershipDepth = 3;

// The elimination/quota bound in the configured mode, or BST19 plus a walk
// for transfer values when something downstream reads them.
EqlbCtx run_eqlb(const SearchInputs& in, const EqlbCtx& start, const PrefixRef& p,
                 const RoundTallies* tallies) {
    const auto& o = *in.options;
    if (o.eqlb || o.eqlbc) {
        return o.useqprefix
                   ? compute_eqlb_stv26_qprefix(start, in.bounds, p, tallies, false, o.sumq,
                                                o.multielim, o.sumnq, o.elimnq,
                                                o.membership ? kMembershipDepth : 0)
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

namespace {

// Children of a node expanded with a strong/weak/other split (block_children
// in stvtree.py): one per subset O' of the other candidates, the node's
// prefix followed by the weak candidates and O' eliminated as one block,
// smallest tally first.
void add_block_children(const SearchInputs& in, const TreeNode& node, const WeakSplit& split,
                        const std::vector<Cand>& forder_c, const std::vector<int>& forder_a,
                        const PySetOrder& fwinners, const PyNum& running_ub, Expansion& ex) {
    const auto n = in.bounds.ncands;
    std::vector<int> pos(static_cast<std::size_t>(n), -1);
    for (std::size_t i = 0; i < split.order.size(); ++i) {
        pos[static_cast<std::size_t>(split.order[i])] = static_cast<int>(i);
    }
    const auto start = static_cast<int>(forder_c.size());
    int seated = 0;
    for (const auto a : forder_a) {
        seated += a;
    }
    const auto seats_left = in.bounds.seats - seated;

    CandSet winners(n);
    for (const auto w : fwinners.order()) {
        winners.set(w);
    }
    CandSet missing(n); // winner_set - fwinners
    for (int c = 0; c < n; ++c) {
        if (in.winner_set.test(c) && !winners.test(c)) {
            missing.set(c);
        }
    }

    const auto nother = split.other.size();
    for (std::size_t size = 0; size <= nother; ++size) {
        // itertools.combinations(other, size), in its order.
        std::vector<std::size_t> idx(size);
        for (std::size_t i = 0; i < size; ++i) {
            idx[i] = i;
        }
        while (true) {
            std::vector<Cand> block = split.weak;
            for (const auto i : idx) {
                block.push_back(split.other[i]);
            }
            std::stable_sort(block.begin(), block.end(), [&](Cand a, Cand b) {
                return -pos[static_cast<std::size_t>(a)] < -pos[static_cast<std::size_t>(b)];
            });
            CandSet gone(n);
            for (const auto c : forder_c) {
                gone.set(c);
            }
            for (const auto c : block) {
                gone.set(c);
            }
            std::vector<Cand> rem;
            CandSet rem_set(n);
            for (int c = 0; c < n; ++c) {
                if (!gone.test(c)) {
                    rem.push_back(c);
                    rem_set.set(c);
                }
            }

            // Only seats-left candidates remain: every one is seated.
            const auto isleaf = static_cast<int>(rem.size()) == seats_left;
            if (!(isleaf && missing == rem_set)) { // else the reported outcome
                ChildSpec spec;
                spec.parent_dist = node.dist;
                spec.order_c = forder_c;
                spec.order_c.insert(spec.order_c.end(), block.begin(), block.end());
                spec.order_a = forder_a;
                spec.order_a.insert(spec.order_a.end(), block.size(), 0);
                spec.order_q = node.order_q;
                spec.winners = winners;
                spec.rem = std::move(rem);
                spec.isleaf = isleaf;
                spec.running_ub = running_ub;
                spec.blocks = node.blocks;
                spec.blocks.emplace_back(start, start + static_cast<int>(block.size()));
                spec.cap = split.k;
                ex.children.push_back(std::move(spec));
            }

            // Next combination.
            std::size_t i = size;
            while (i > 0 && idx[i - 1] == nother - size + (i - 1)) {
                --i;
            }
            if (i == 0) {
                break;
            }
            ++idx[i - 1];
            for (auto j = i; j < size; ++j) {
                idx[j] = idx[j - 1] + 1;
            }
        }
    }
}

} // namespace

namespace {

// ---------------------------------------------------------------- -membership

// Where the current run of eliminations starts: after the last seating.
std::size_t run_start_of(std::span<const int> order_a) {
    auto i = order_a.size();
    while (i > 0 && order_a[i - 1] == 0) {
        --i;
    }
    return i;
}

// The prefix decides every seat (a leaf).
bool membership_complete(const SearchInputs& in, std::span<const Cand> order_c,
                         std::span<const int> order_a) {
    int seated = 0;
    for (const auto a : order_a) {
        seated += a;
    }
    return seated == in.bounds.seats ||
           in.bounds.ncands - static_cast<int>(order_c.size()) == in.bounds.seats - seated;
}

// Blocks once their run has closed: a block of one is an ordered elimination.
Blocks closed_blocks(const Blocks& blocks) {
    Blocks out;
    for (const auto& b : blocks) {
        if (b.second - b.first > 1) {
            out.push_back(b);
        }
    }
    return out;
}

bool refinable(const Blocks& blocks) {
    return std::any_of(blocks.begin(), blocks.end(),
                       [](const auto& b) { return b.second - b.first > 1; });
}

// RunState of the most recent runs, keyed by their prefix (run_state in
// stvtree.py), shared by all threads.
std::mutex g_runs_mutex;
std::map<std::vector<int>, std::shared_ptr<const RunState>> g_runs;
std::vector<std::vector<int>> g_runs_order;
constexpr std::size_t kRunsKeep = 8;

std::shared_ptr<const RunState> run_state(const SearchInputs& in, std::span<const Cand> order_c,
                                          std::span<const int> order_a, const OrderQ& order_q,
                                          const EqlbCtx& ctx) {
    std::vector<int> key(order_c.begin(), order_c.end());
    key.push_back(-1);
    key.insert(key.end(), order_a.begin(), order_a.end());
    key.push_back(-2);
    auto sorted_q = order_q;
    std::sort(sorted_q.begin(), sorted_q.end(),
              [](const QEntry& a, const QEntry& b) { return a.c < b.c; });
    for (const auto& e : sorted_q) {
        key.insert(key.end(), {e.c, e.lo, e.hi});
    }
    const std::lock_guard<std::mutex> lock(g_runs_mutex);
    if (const auto it = g_runs.find(key); it != g_runs.end()) {
        return it->second;
    }
    const auto n = in.bounds.ncands;
    CandSet gone(n);
    for (const auto c : order_c) {
        gone.set(c);
    }
    const auto gone_pos = gone_positions(order_c, order_c.size(), n);
    const auto tv_lo = ctx.transfer.dense_lo(n);
    const auto qround = quota_rounds(order_q, n);
    const auto& ballots = in.bounds.election->ballots;
    std::vector<std::vector<Cand>> prefs;
    std::vector<double> values;
    for (std::size_t b = 0; b < ballots.size(); ++b) {
        std::vector<Cand> p;
        for (const auto c : ballots.prefs(b)) {
            if (!gone.test(c)) {
                p.push_back(c);
            }
        }
        if (p.empty()) {
            continue;
        }
        values.push_back(calc_tallies_q_prefix(ballots.prefs(b),
                                               static_cast<double>(ballots.votes(b)), order_c,
                                               gone_pos, ctx.winners, tv_lo, qround)
                             .value);
        prefs.push_back(std::move(p));
    }
    std::vector<Cand> standing;
    for (int c = 0; c < n; ++c) {
        if (!gone.test(c)) {
            standing.push_back(c);
        }
    }
    int seated = 0;
    for (const auto a : order_a) {
        seated += a;
    }
    auto st = std::make_shared<const RunState>(n, static_cast<double>(in.bounds.quota),
                                               in.bounds.seats - seated, std::move(standing),
                                               prefs, values);
    g_runs[key] = st;
    g_runs_order.push_back(key);
    while (g_runs.size() > kRunsKeep) {
        g_runs.erase(g_runs_order.front());
        g_runs_order.erase(g_runs_order.begin());
    }
    return st;
}

// A bound in whole votes: 3.2 means at least 4; infinity stays.
PyNum whole(double x) {
    if (std::isinf(x)) {
        return PyNum::real(x);
    }
    return py_max(PyNum::integer(0), py_ceil(x - 1e-6));
}

// A child whose run is still open (eval_open_run in stvtree.py).
ChildResult eval_open_run(const SearchInputs& in, const Expansion& ex, const ChildSpec& spec) {
    const auto& o = *in.options;
    const auto n = in.bounds.ncands;
    const auto rs = run_start_of(spec.order_a);
    const std::span<const Cand> pc(spec.order_c.data(), rs);
    const std::span<const int> pa(spec.order_a.data(), rs);
    const auto& ctx = ex.eqlbctx;
    const auto st = run_state(in, pc, pa, spec.order_q, ctx);

    std::vector<Cand> in_set(spec.order_c.begin() + static_cast<std::ptrdiff_t>(rs),
                             spec.order_c.end());
    std::sort(in_set.begin(), in_set.end());
    auto out_set = spec.out;
    std::sort(out_set.begin(), out_set.end());
    const auto deficit = o.sumq ? ctx.deficit_sum : 0.0;
    auto fam = st->lb(in_set, out_set, spec.parent_dist.as_double(), deficit, o.sumnq, o.elimnq,
                      kMembershipDepth);
    if (!in_set.empty()) {
        fam = std::max(fam, st->nq([&] {
            return backcompute_seating_run(ctx, in.bounds, pc, pa, spec.order_q, o.sumnq);
        }));
    }
    double dlb = 0.0;
    if (o.dlb || o.dlbc) {
        bool changed = false;
        for (std::size_t i = 0; i < rs; ++i) {
            if (spec.order_a[i] == 1 && !in.winner_set.test(spec.order_c[i])) {
                changed = true;
            }
        }
        dlb = st->dlb(in_set, in.winner_set, changed);
    }

    ChildResult res;
    res.isleaf = false;
    res.eqlbctx = ctx;
    res.disp_cache = blank_disp(n);
    res.order_c = spec.order_c;
    res.order_a = spec.order_a;
    res.order_q = spec.order_q;
    res.eqlb = whole(fam);
    res.dlb = whole(dlb);
    res.lb = py_max(py_max(spec.parent_dist, res.eqlb), res.dlb);
    res.dist = res.lb;
    res.dist_ub = res.lb;
    res.blocks = spec.blocks;
    res.out = spec.out;
    res.need_in = spec.need_in;
    return res;
}

// A complete outcome bounded only by its blocks: split its last block of
// two or more by which candidate went last (refine_children in stvtree.py).
Expansion refine_expansion(const SearchInputs& in, const TreeNode& node,
                           const std::vector<Cand>& forder_c, const std::vector<int>& forder_a,
                           const CandSet& winners, const PyNum& running_ub) {
    const auto n = in.bounds.ncands;
    Expansion ex;
    ex.eqlbctx = blank_eqlb(n);
    ex.disp_cache = blank_disp(n);
    const auto& fb = node.blocks;
    std::size_t k = 0;
    for (std::size_t j = 0; j < fb.size(); ++j) {
        if (fb[j].second - fb[j].first > 1) {
            k = j;
        }
    }
    const auto [s, e] = fb[k];
    Blocks rest;
    for (std::size_t j = 0; j < fb.size(); ++j) {
        if (j != k) {
            rest.push_back(fb[j]);
        }
    }
    CandSet placed(n);
    for (const auto c : forder_c) {
        placed.set(c);
    }
    std::vector<Cand> rem;
    for (int c = 0; c < n; ++c) {
        if (!placed.test(c)) {
            rem.push_back(c);
        }
    }
    for (int li = s; li < e; ++li) {
        const auto l = forder_c[static_cast<std::size_t>(li)];
        std::vector<Cand> oc(forder_c.begin(), forder_c.begin() + s);
        for (int j = s; j < e; ++j) {
            if (forder_c[static_cast<std::size_t>(j)] != l) {
                oc.push_back(forder_c[static_cast<std::size_t>(j)]);
            }
        }
        oc.push_back(l);
        oc.insert(oc.end(), forder_c.begin() + e, forder_c.end());
        auto blocks = rest;
        if (e - 1 - s > 1) {
            blocks.emplace_back(s, e - 1);
        }
        std::sort(blocks.begin(), blocks.end());
        ChildSpec spec;
        spec.parent_dist = node.dist;
        spec.order_c = std::move(oc);
        spec.order_a = forder_a;
        spec.order_q = node.order_q;
        spec.winners = winners;
        spec.rem = rem;
        spec.isleaf = true;
        spec.running_ub = running_ub;
        spec.blocks = std::move(blocks);
        ex.children.push_back(std::move(spec));
    }
    return ex;
}

// Children of a node whose run is open (membership_children in stvtree.py).
Expansion membership_expansion(const SearchInputs& in, const TreeNode& node,
                               const std::vector<Cand>& forder_c,
                               const std::vector<int>& forder_a, const PySetOrder& fwinners,
                               const PyNum& running_ub) {
    const auto& o = *in.options;
    const auto n = in.bounds.ncands;
    CandSet winners(n);
    for (const auto w : fwinners.order()) {
        winners.set(w);
    }
    if (membership_complete(in, forder_c, forder_a)) {
        return refine_expansion(in, node, forder_c, forder_a, winners, running_ub);
    }
    const auto& forder_q = node.order_q;
    const auto& fblocks = node.blocks;
    const auto rs = run_start_of(forder_a);
    const auto st = run_state(in, std::span<const Cand>(forder_c.data(), rs),
                              std::span<const int>(forder_a.data(), rs), forder_q, node.eqlbctx);

    Expansion ex;
    ex.eqlbctx = node.eqlbctx;
    ex.disp_cache = blank_disp(n);
    if (o.prec_et) {
        RoundTallies rt;
        rt.tallies = st->t0();
        ex.elim_tallies = std::move(rt);
    }

    CandSet in_set(n);
    for (std::size_t i = rs; i < forder_c.size(); ++i) {
        in_set.set(forder_c[i]);
    }
    CandSet out_set(n);
    for (const auto d : node.out) {
        out_set.set(d);
    }
    std::vector<Cand> standing;
    for (const auto c : st->standing()) {
        if (!in_set.test(c)) {
            standing.push_back(c);
        }
    }
    int seated = 0;
    for (const auto a : forder_a) {
        seated += a;
    }
    const auto seats_left = in.bounds.seats - seated;
    CandSet missing(n); // winner_set - fwinners
    for (int c = 0; c < n; ++c) {
        if (in.winner_set.test(c) && !winners.test(c)) {
            missing.set(c);
        }
    }
    auto sorted_out = node.out;
    std::sort(sorted_out.begin(), sorted_out.end());

    auto base = [&](std::vector<Cand> oc, std::vector<int> oa, OrderQ oq, CandSet w,
                    std::vector<Cand> rem, bool isleaf, Blocks blocks) {
        ChildSpec spec;
        spec.parent_dist = node.dist;
        spec.order_c = std::move(oc);
        spec.order_a = std::move(oa);
        spec.order_q = std::move(oq);
        spec.winners = std::move(w);
        spec.rem = std::move(rem);
        spec.isleaf = isleaf;
        spec.running_ub = running_ub;
        spec.blocks = std::move(blocks);
        return spec;
    };

    Cand next = -1;
    for (const auto c : st->order()) {
        if (!in_set.test(c) && !out_set.test(c)) {
            next = c;
            break;
        }
    }
    if (next >= 0) {
        const auto c = next;
        Blocks blocks = fblocks;
        if (rs < forder_c.size()) {
            blocks.back().second += 1;
        } else {
            blocks.emplace_back(static_cast<int>(rs), static_cast<int>(rs) + 1);
        }
        std::vector<Cand> rem;
        CandSet rem_set(n);
        for (const auto x : standing) {
            if (x != c) {
                rem.push_back(x);
                rem_set.set(x);
            }
        }
        auto oc = forder_c;
        oc.push_back(c);
        auto oa = forder_a;
        oa.push_back(0);
        if (static_cast<int>(rem.size()) == seats_left) {
            if (!(missing == rem_set)) {
                ex.children.push_back(
                    base(oc, oa, forder_q, winners, rem, true, closed_blocks(blocks)));
            }
        } else if (static_cast<int>(rem.size()) > seats_left) {
            auto spec = base(oc, oa, forder_q, winners, rem, false, blocks);
            spec.out = sorted_out;
            spec.open_run = true;
            ex.children.push_back(std::move(spec));
        }
        auto spec = base(forder_c, forder_a, forder_q, winners, standing, false, fblocks);
        spec.out = sorted_out;
        spec.out.push_back(c);
        std::sort(spec.out.begin(), spec.out.end());
        spec.need_in = true;
        spec.open_run = true;
        ex.children.push_back(std::move(spec));
    }

    if (node.need_in) {
        return ex;
    }

    // Close the run with exactly IN eliminated and seat someone.
    const auto closed = closed_blocks(fblocks);
    for (const auto r : standing) {
        auto node_winners = winners;
        node_winners.set(r);
        if (node_winners == in.winner_set) {
            continue;
        }
        std::vector<Cand> rem;
        for (const auto x : standing) {
            if (x != r) {
                rem.push_back(x);
            }
        }
        auto oc = forder_c;
        oc.push_back(r);
        auto oa = forder_a;
        oa.push_back(1);
        const auto seats_filled = seated + 1;
        auto new_rem = rem;
        bool isleaf = false;
        if (seats_filled > in.bounds.seats) {
            continue;
        }
        if (seats_filled == in.bounds.seats) {
            oc.insert(oc.end(), rem.begin(), rem.end());
            oa.insert(oa.end(), rem.size(), 0);
            new_rem.clear();
            isleaf = true;
        } else if (in.bounds.seats - seats_filled == static_cast<int>(rem.size())) {
            CandSet miss(n);
            for (int c = 0; c < n; ++c) {
                if (in.winner_set.test(c) && !node_winners.test(c)) {
                    miss.set(c);
                }
            }
            CandSet rem_set(n);
            for (const auto x : rem) {
                rem_set.set(x);
            }
            if (miss == rem_set) {
                continue;
            }
            isleaf = true;
        }
        const auto lenf = static_cast<int>(forder_a.size());
        auto minqr = lenf;
        if (!forder_a.empty() && forder_a.back() == 1) {
            minqr = find_q(forder_q, forder_c.back())->lo;
        }
        for (auto i = lenf; i >= minqr; --i) {
            auto q = forder_q;
            q.push_back({r, i, i});
            ex.children.push_back(base(oc, oa, std::move(q), node_winners, new_rem, isleaf, closed));
        }
    }
    return ex;
}

} // namespace

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

    // -membership: the node's run is open; its children decide the next
    // candidate or close the run and seat someone.
    if (o.membership) {
        return membership_expansion(in, node, forder_c, forder_a, fwinners, running_ub);
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

    // -weakseed: expand into blocks of eliminations when a split qualifies.
    if (o.weakseed) {
        if (const auto split = weak_seed_split(in.bounds, forder_c, forder_a, forder_q, running_ub,
                                               in.orig_ub, o.seedf, o.seedmaxchildren)) {
            add_block_children(in, node, *split, forder_c, forder_a, fwinners, running_ub, ex);
            return ex;
        }
    }

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
                spec.blocks = node.blocks;
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
    if (spec.open_run) {
        return eval_open_run(in, ex, spec);
    }
    const auto& o = *in.options;
    const auto n = in.bounds.ncands;
    const PrefixRef p{spec.order_c, spec.order_a, &spec.order_q, &spec.blocks};
    const RoundTallies* tallies = ex.elim_tallies ? &*ex.elim_tallies : nullptr;

    const auto start_ctx = o.eqlbc ? ex.eqlbctx : blank_eqlb(n);
    const auto start_disp = o.dlbc ? ex.disp_cache : blank_disp(n);

    ChildResult res;
    res.isleaf = spec.isleaf;
    res.blocks = spec.blocks;
    res.cap = spec.cap;
    res.out = spec.out;
    res.need_in = spec.need_in;
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

    // -membership: a leaf's ordered eliminations come from refining blocks, so
    // the prefixes just before them were never search nodes. The displacement
    // bound holds at each of them, as at any prefix.
    if (o.membership && spec.isleaf && o.useqprefix && (o.dlb || o.dlbc)) {
        auto padfrom = static_cast<int>(spec.order_a.size());
        if (padfrom == n) {
            while (padfrom > 0 && spec.order_a[static_cast<std::size_t>(padfrom - 1)] == 0) {
                --padfrom;
            }
        }
        std::vector<char> inside(spec.order_c.size(), 0);
        for (const auto& [s, e] : spec.blocks) {
            for (int i = s; i < e; ++i) {
                inside[static_cast<std::size_t>(i)] = 1;
            }
        }
        for (int k = 1; k < padfrom; ++k) {
            const auto ku = static_cast<std::size_t>(k);
            if (spec.order_a[ku] != 0 || inside[ku] != 0) {
                continue;
            }
            CandSet seated_k(n);
            CandSet prefix(n);
            for (std::size_t i = 0; i < ku; ++i) {
                prefix.set(spec.order_c[i]);
                if (spec.order_a[i] == 1) {
                    seated_k.set(spec.order_c[i]);
                }
            }
            OrderQ q_k;
            for (const auto& e : spec.order_q) {
                if (seated_k.test(e.c)) {
                    q_k.push_back(e);
                }
            }
            std::vector<Cand> rem_k;
            for (int c = 0; c < n; ++c) {
                if (!prefix.test(c)) {
                    rem_k.push_back(c);
                }
            }
            Blocks blocks_k;
            for (const auto& b : spec.blocks) {
                if (b.second <= k) {
                    blocks_k.push_back(b);
                }
            }
            const PrefixRef pk{std::span<const Cand>(spec.order_c.data(), ku),
                               std::span<const int>(spec.order_a.data(), ku), &q_k, &blocks_k};
            const auto sub = compute_disp_lb_stv26_q_prefix(blank_disp(n), in.bounds, pk,
                                                            in.winner_set, rem_k,
                                                            res.eqlbctx.transfer);
            res.dlb = py_max(res.dlb, sub.lowerbound);
        }
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
        : in_(in), o_(*in.options), log_(log), running_ub_(upperbound), found_ub_(upperbound) {}

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

    void initial_frontier();
    // Handles one child; returns true when the search has converged.
    bool handle_child(ChildResult& c);

    const SearchInputs& in_;
    const Options& o_;
    Logger& log_;
    Frontier frontier_;
    PyNum running_ub_;
    PyNum running_lb_ = PyNum::integer(0);
    // Smallest budget used by a -weakseed block expansion so far; running_ub_
    // never exceeds it. found_ub_ is the smallest upper bound from the
    // initial bound and leaves, ignoring that cap.
    std::optional<PyNum> block_cap_;
    PyNum found_ub_;
    std::uint64_t nexps_ = 0;
    std::uint64_t nsolves_ = 0;
};

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
    // -membership: the root is a single open run, in place of these.
    for (int cand = 0; cand < n && !o_.membership; ++cand) {
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

    if (o_.membership) {
        frontier_.insert(std::make_unique<TreeNode>(std::vector<Cand>{}, std::vector<int>{},
                                                    OrderQ{}, blank_eqlb(n), blank_disp(n),
                                                    PyNum::integer(0), PyNum::integer(0),
                                                    Blocks{}, std::vector<Cand>{}, false, true),
                         o_.lse);
    }
}

bool Search::handle_child(ChildResult& c) {
    if (c.cap && (!block_cap_ || *c.cap < *block_cap_)) {
        block_cap_ = c.cap;
        log_.line("BLOCK EXPANSION with budget " + c.cap->str());
        if (*c.cap < running_ub_) {
            log_.line("Capping upper bound from " + running_ub_.str() + " to " + c.cap->str());
            running_ub_ = *c.cap;
            if (gap_closed()) {
                return true;
            }
            frontier_.prune(running_ub_, log_);
        }
    }
    if (c.solved) {
        ++nsolves_;
    }
    std::string run_out;
    if (o_.membership) {
        auto sorted_out = c.out;
        std::sort(sorted_out.begin(), sorted_out.end());
        run_out = " OUT " + py_list_str(sorted_out) + (c.need_in ? " needs IN" : "");
    }
    log_.line("EVALUATED " + py_list_str(c.order_c) + "/" + py_list_str(c.order_a) + "/" +
              order_q_str(c.order_q) + " LB " + c.lb.str() + " (D " + c.dlb.str() + " EQ " +
              c.eqlb.str() + ")" + run_out);
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

    if (c.isleaf && o_.membership && refinable(c.blocks)) {
        // A complete outcome bounded only by its blocks goes to the frontier
        // and is refined when it reaches the top.
        log_.line("        LEAF TO REFINE");
        auto node = std::make_unique<TreeNode>(std::move(c.order_c), std::move(c.order_a),
                                               std::move(c.order_q), std::move(c.eqlbctx),
                                               std::move(c.disp_cache), *c.dist, *c.dist_ub,
                                               std::move(c.blocks), std::move(c.out), c.need_in,
                                               true);
        if (!frontier_.insert(std::move(node), o_.lse)) {
            log_.line("        SUBSUMED");
        }
        return false;
    }

    if (c.isleaf) {
        log_.line("        LEAF");
        if (*c.dist < running_ub_) {
            log_.line("Reducing upper bound from " + running_ub_.str() + " to " + c.dist->str());
        }
        running_ub_ = py_min(running_ub_, *c.dist);
        found_ub_ = py_min(found_ub_, *c.dist);
        if (gap_closed()) {
            return true;
        }
        frontier_.prune(running_ub_, log_);
        return false;
    }

    auto node = std::make_unique<TreeNode>(std::move(c.order_c), std::move(c.order_a),
                                           std::move(c.order_q), std::move(c.eqlbctx),
                                           std::move(c.disp_cache), *c.dist, *c.dist_ub,
                                           std::move(c.blocks), std::move(c.out), c.need_in,
                                           o_.membership);
    if (!frontier_.insert(std::move(node), o_.lse)) {
        log_.line("        SUBSUMED");
    }
    return false;
}

SearchResult Search::run() {
    const auto tstart = wall_seconds();

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
    if (block_cap_ && *block_cap_ < found_ub_) {
        log_.line("Block expansions capped the result at " + block_cap_->str() +
                  "; smallest upper bound found " + found_ub_.str() + ".");
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
