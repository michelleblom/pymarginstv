#include "marginstv/search.hpp"

#include "marginstv/pyset.hpp"

#include <tbb/parallel_for.h>
#include <tbb/parallel_invoke.h>

#include <chrono>
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

// The elimination/quota bound in the configured mode, or BST19 plus a walk
// for transfer values when something downstream reads them.
EqlbCtx run_eqlb(const SearchInputs& in, const EqlbCtx& start, const PrefixRef& p,
                 const RoundTallies* tallies) {
    const auto& o = *in.options;
    if (o.eqlb || o.eqlbc) {
        return o.useqprefix
                   ? compute_eqlb_stv26_qprefix(start, in.bounds, p, tallies, false, o.sumq,
                                                o.multielim, o.sumnq)
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
