#include "marginstv/distance.hpp"

#include "marginstv/pyexpr.hpp"
#include "marginstv/pyset.hpp"

#include <scip/cons_linear.h>
#include <scip/cons_nonlinear.h>
#include <scip/expr_product.h>
#include <scip/expr_sum.h>
#include <scip/expr_var.h>
#include <scip/scip.h>
#include <scip/scipdefplugins.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <fstream>
#include <map>
#include <mutex>
#include <stdexcept>
#include <string>

namespace marginstv {

namespace {

constexpr double kEpsilon = 0.0001;

void check(SCIP_RETCODE rc, const char* what) {
    if (rc != SCIP_OKAY) {
        throw std::runtime_error(std::string("SCIP call failed: ") + what);
    }
}

#define CHECK_SCIP(call) check((call), #call)

// ---------------------------------------------------------------- event handlers

struct HandlerData {
    double upperbound = 0;
    long ncalls = 0;
};

SCIP_DECL_EVENTCOPY(eventCopyNoop) {
    (void)scip;
    (void)eventhdlr;
    return SCIP_OKAY;
}

SCIP_DECL_EVENTINIT(eventInitBestSol) {
    return SCIPcatchEvent(scip, SCIP_EVENTTYPE_BESTSOLFOUND, eventhdlr, nullptr, nullptr);
}

SCIP_DECL_EVENTEXIT(eventExitBestSol) {
    return SCIPdropEvent(scip, SCIP_EVENTTYPE_BESTSOLFOUND, eventhdlr, nullptr, -1);
}

// Stop once ceil(primal) == ceil(dual): the integer optimum is known.
SCIP_DECL_EVENTEXEC(eventExecBestSol) {
    (void)eventhdlr;
    (void)event;
    (void)eventdata;
    const auto primal = SCIPgetPrimalbound(scip);
    const auto dual = SCIPgetDualbound(scip);
    if (std::ceil(primal) == std::ceil(dual)) {
        return SCIPinterruptSolve(scip);
    }
    return SCIP_OKAY;
}

SCIP_DECL_EVENTINIT(eventInitNodeSolved) {
    return SCIPcatchEvent(scip, SCIP_EVENTTYPE_NODESOLVED, eventhdlr, nullptr, nullptr);
}

SCIP_DECL_EVENTEXIT(eventExitNodeSolved) {
    return SCIPdropEvent(scip, SCIP_EVENTTYPE_NODESOLVED, eventhdlr, nullptr, -1);
}

// Stop once the dual bound alone prunes the prefix; checked every 64th node.
SCIP_DECL_EVENTEXEC(eventExecNodeSolved) {
    (void)event;
    (void)eventdata;
    auto* data = reinterpret_cast<HandlerData*>(SCIPeventhdlrGetData(eventhdlr));
    ++data->ncalls;
    if ((data->ncalls & 63) != 0) {
        return SCIP_OKAY;
    }
    if (std::ceil(SCIPgetDualbound(scip)) >= data->upperbound) {
        return SCIPinterruptSolve(scip);
    }
    return SCIP_OKAY;
}

// ---------------------------------------------------------------- model wrapper

// One SCIP instance, set up as pyscipopt's Model("STVDISTANCE") is, with
// variables numbered in creation order (pyscipopt orders terms by that).
// The headers this file was compiled with must describe the library that
// was linked; a mismatch would silently change solver behaviour.
void check_library_version() {
    static const bool ok = SCIPmajorVersion() == SCIP_VERSION_MAJOR &&
                           SCIPminorVersion() == SCIP_VERSION_MINOR &&
                           SCIPtechVersion() == SCIP_VERSION_PATCH;
    if (!ok) {
        throw std::runtime_error("linked SCIP library is " + std::to_string(SCIPmajorVersion()) +
                                 "." + std::to_string(SCIPminorVersion()) + "." +
                                 std::to_string(SCIPtechVersion()) +
                                 ", but the build used headers for another version");
    }
}

class ScipModel {
  public:
    ScipModel() {
        check_library_version();
        CHECK_SCIP(SCIPcreate(&scip_));
        CHECK_SCIP(SCIPincludeDefaultPlugins(scip_));
        CHECK_SCIP(SCIPcreateProbBasic(scip_, "STVDISTANCE"));
    }
    ~ScipModel() {
        if (scip_ != nullptr) {
            SCIPfree(&scip_);
        }
    }
    ScipModel(const ScipModel&) = delete;
    ScipModel& operator=(const ScipModel&) = delete;
    ScipModel(ScipModel&&) = delete;
    ScipModel& operator=(ScipModel&&) = delete;

    [[nodiscard]] SCIP* get() const { return scip_; }

    void include_handlers(double upperbound) {
        CHECK_SCIP(SCIPincludeEventhdlr(
            scip_, "terminate_at_integer_solution",
            "Event handler that terminates solving when ceil(primal) == ceil(dual)", eventCopyNoop,
            nullptr, eventInitBestSol, eventExitBestSol, nullptr, nullptr, nullptr, eventExecBestSol,
            reinterpret_cast<SCIP_EVENTHDLRDATA*>(&best_data_)));
        prune_data_.upperbound = upperbound;
        CHECK_SCIP(SCIPincludeEventhdlr(
            scip_, "terminate_on_pruning_bound",
            "Event handler that terminates solving when ceil(dual) reaches the caller's pruning "
            "threshold",
            eventCopyNoop, nullptr, eventInitNodeSolved, eventExitNodeSolved, nullptr, nullptr,
            nullptr, eventExecNodeSolved, reinterpret_cast<SCIP_EVENTHDLRDATA*>(&prune_data_)));
    }

    // Model.addVar: binaries have their bounds clipped to [0, 1].
    Expr add_var(const std::string& name, bool binary, double lb, double ub) {
        if (binary) {
            ub = std::min(ub, 1.0);
            lb = std::max(lb, 0.0);
        }
        SCIP_VAR* var = nullptr;
        CHECK_SCIP(SCIPcreateVarBasic(scip_, &var, name.c_str(), lb, ub, 0.0,
                                      binary ? SCIP_VARTYPE_BINARY : SCIP_VARTYPE_CONTINUOUS));
        CHECK_SCIP(SCIPaddVar(scip_, var));
        vars_.push_back(var);
        CHECK_SCIP(SCIPreleaseVar(scip_, &var));
        return Expr::var(static_cast<int>(vars_.size()) - 1);
    }

    [[nodiscard]] SCIP_VAR* var(int index) const { return vars_[static_cast<std::size_t>(index)]; }
    [[nodiscard]] std::size_t nvars() const { return vars_.size(); }

    // Model.addCons via createConsFromExpr, named "c<n>".
    void add_cons(const ExprCons& c) {
        const auto name = "c" + std::to_string(SCIPgetNConss(scip_) + 1);
        const auto inf = SCIPinfinity(scip_);
        const auto lhs = c.lhs ? *c.lhs : -inf;
        const auto rhs = c.rhs ? *c.rhs : inf;
        const auto& terms = c.expr.terms();
        const auto deg = c.expr.degree();
        SCIP_CONS* cons = nullptr;

        if (deg <= 1) {
            std::vector<SCIP_VAR*> vs;
            std::vector<SCIP_Real> cs;
            for (const auto& [t, coef] : terms) {
                vs.push_back(var(t.at(0)));
                cs.push_back(coef);
            }
            CHECK_SCIP(SCIPcreateConsLinear(scip_, &cons, name.c_str(), static_cast<int>(vs.size()),
                                            vs.data(), cs.data(), lhs, rhs, TRUE, TRUE, TRUE, TRUE,
                                            TRUE, FALSE, FALSE, FALSE, FALSE, FALSE));
        } else if (deg <= 2) {
            CHECK_SCIP(SCIPcreateConsQuadraticNonlinear(scip_, &cons, name.c_str(), 0, nullptr,
                                                        nullptr, 0, nullptr, nullptr, nullptr, lhs,
                                                        rhs, TRUE, TRUE, TRUE, TRUE, TRUE, FALSE,
                                                        FALSE, FALSE, FALSE));
            for (const auto& [t, coef] : terms) {
                if (t.size() == 1) {
                    CHECK_SCIP(SCIPaddLinearVarNonlinear(scip_, cons, var(t[0]), coef));
                } else {
                    SCIP_EXPR* ve[2] = {nullptr, nullptr};
                    SCIP_EXPR* prod = nullptr;
                    CHECK_SCIP(SCIPcreateExprVar(scip_, &ve[0], var(t[0]), nullptr, nullptr));
                    CHECK_SCIP(SCIPcreateExprVar(scip_, &ve[1], var(t[1]), nullptr, nullptr));
                    CHECK_SCIP(SCIPcreateExprProduct(scip_, &prod, 2, ve, 1.0, nullptr, nullptr));
                    CHECK_SCIP(SCIPaddExprNonlinear(scip_, cons, prod, coef));
                    CHECK_SCIP(SCIPreleaseExpr(scip_, &prod));
                    CHECK_SCIP(SCIPreleaseExpr(scip_, &ve[1]));
                    CHECK_SCIP(SCIPreleaseExpr(scip_, &ve[0]));
                }
            }
        } else {
            std::vector<SCIP_EXPR*> monomials(terms.size(), nullptr);
            std::vector<SCIP_Real> coefs(terms.size());
            for (std::size_t i = 0; i < terms.size(); ++i) {
                std::vector<SCIP_VAR*> vs;
                for (const auto v : terms[i].first) {
                    vs.push_back(var(v));
                }
                CHECK_SCIP(SCIPcreateExprMonomial(scip_, &monomials[i], static_cast<int>(vs.size()),
                                                  vs.data(), nullptr, nullptr, nullptr));
                coefs[i] = terms[i].second;
            }
            SCIP_EXPR* sum = nullptr;
            CHECK_SCIP(SCIPcreateExprSum(scip_, &sum, static_cast<int>(terms.size()),
                                         monomials.data(), coefs.data(), 0.0, nullptr, nullptr));
            CHECK_SCIP(SCIPcreateConsNonlinear(scip_, &cons, name.c_str(), sum, lhs, rhs, TRUE, TRUE,
                                               TRUE, TRUE, TRUE, FALSE, FALSE, FALSE, FALSE));
            CHECK_SCIP(SCIPreleaseExpr(scip_, &sum));
            for (auto& m : monomials) {
                CHECK_SCIP(SCIPreleaseExpr(scip_, &m));
            }
        }
        CHECK_SCIP(SCIPaddCons(scip_, cons));
        CHECK_SCIP(SCIPreleaseCons(scip_, &cons));
    }

    // Model.setObjective(expr, "minimize") for a linear expression.
    void set_objective(const Expr& objective) {
        const auto expr = Expr().add(objective);
        CHECK_SCIP(SCIPaddOrigObjoffset(scip_, -SCIPgetOrigObjoffset(scip_)));
        auto* const* orig = SCIPgetOrigVars(scip_);
        const auto norig = SCIPgetNOrigVars(scip_);
        for (int i = 0; i < norig; ++i) {
            CHECK_SCIP(SCIPchgVarObj(scip_, orig[i], 0.0));
        }
        if (expr.constant() != 0.0) {
            CHECK_SCIP(SCIPaddOrigObjoffset(scip_, expr.constant()));
        }
        for (const auto& [t, coef] : expr.terms()) {
            if (!t.empty()) {
                CHECK_SCIP(SCIPchgVarObj(scip_, var(t.at(0)), coef));
            }
        }
        CHECK_SCIP(SCIPsetObjsense(scip_, SCIP_OBJSENSE_MINIMIZE));
    }

  private:
    SCIP* scip_ = nullptr;
    std::vector<SCIP_VAR*> vars_;
    HandlerData best_data_;
    HandlerData prune_data_;
};

std::string status_name(SCIP_STATUS s) {
    switch (s) {
    case SCIP_STATUS_OPTIMAL: return "optimal";
    case SCIP_STATUS_TIMELIMIT: return "timelimit";
    case SCIP_STATUS_INFEASIBLE: return "infeasible";
    case SCIP_STATUS_UNBOUNDED: return "unbounded";
    case SCIP_STATUS_USERINTERRUPT: return "userinterrupt";
    case SCIP_STATUS_INFORUNBD: return "inforunbd";
    case SCIP_STATUS_NODELIMIT: return "nodelimit";
    case SCIP_STATUS_TOTALNODELIMIT: return "totalnodelimit";
    case SCIP_STATUS_STALLNODELIMIT: return "stallnodelimit";
    case SCIP_STATUS_GAPLIMIT: return "gaplimit";
    case SCIP_STATUS_MEMLIMIT: return "memlimit";
    case SCIP_STATUS_SOLLIMIT: return "sollimit";
    case SCIP_STATUS_BESTSOLLIMIT: return "bestsollimit";
    case SCIP_STATUS_RESTARTLIMIT: return "restartlimit";
    case SCIP_STATUS_PRIMALLIMIT: return "primallimit";
    case SCIP_STATUS_DUALLIMIT: return "duallimit";
    default: return "unknown";
    }
}

// ---------------------------------------------------------------- ballot classes

struct Classes {
    std::vector<std::vector<Cand>> prefs;
    std::vector<std::int64_t> votes;
};

// Votes of every ballot, gathered into its equivalence class (reduce_ballots).
Classes reduce_ballots(const BoundInputs& bi, std::span<const Cand> order_c,
                       std::span<const Cand> remainder, std::span<const Cand> merge_map) {
    Classes cl;
    cl.prefs = equivalence_classes(order_c, remainder);
    cl.votes.assign(cl.prefs.size(), 0);

    const auto n = static_cast<std::size_t>(bi.ncands);
    std::vector<int> candpos(n, 0);
    for (std::size_t i = 0; i < order_c.size(); ++i) {
        candpos[static_cast<std::size_t>(order_c[i])] = static_cast<int>(i);
    }
    std::vector<int> rem_index(n, -1);
    for (std::size_t k = 0; k < remainder.size(); ++k) {
        if (rem_index[static_cast<std::size_t>(remainder[k])] < 0) {
            rem_index[static_cast<std::size_t>(remainder[k])] = static_cast<int>(k);
        }
    }
    const auto full = (std::uint64_t{1} << order_c.size()) - 1; // number of prefix-only classes

    const auto& ballots = bi.election->ballots;
    for (std::size_t b = 0; b < ballots.size(); ++b) {
        const auto prefs = ballots.prefs(b);
        auto np = merge_map[prefs[0]];
        std::uint64_t mask = 0;
        int tail = -1; // remainder index of a final remaining candidate
        if (rem_index[static_cast<std::size_t>(np)] >= 0) {
            tail = rem_index[static_cast<std::size_t>(np)];
        } else {
            auto i = candpos[static_cast<std::size_t>(np)];
            mask |= std::uint64_t{1} << i;
            for (std::size_t k = 1; k < prefs.size(); ++k) {
                np = merge_map[prefs[k]];
                const auto j = candpos[static_cast<std::size_t>(np)];
                if (rem_index[static_cast<std::size_t>(np)] < 0 && ((mask >> j) & 1U) != 0 &&
                    order_c[static_cast<std::size_t>(j)] == np) {
                    continue; // already seen
                }
                if (rem_index[static_cast<std::size_t>(np)] >= 0) {
                    tail = rem_index[static_cast<std::size_t>(np)];
                    break;
                }
                if (j < i) {
                    continue;
                }
                i = j;
                mask |= std::uint64_t{1} << j;
            }
        }
        const auto id = tail < 0 ? mask - 1
                                 : full + static_cast<std::uint64_t>(tail) * (full + 1) + mask;
        cl.votes[id] += ballots.votes(b);
    }
    return cl;
}

// ---------------------------------------------------------------- shared setup

struct Setup {
    std::vector<Cand> order_c;
    std::vector<int> order_a;
    std::vector<Cand> cands; // full prefix + remaining, before trimming
    std::vector<Cand> rem;   // remaining after trimming to the last round
    int R = 0;
};

Setup trim_to_last_round(const DistanceProblem& p) {
    Setup s;
    s.order_c.assign(p.order_c.begin(), p.order_c.end());
    s.order_a.assign(p.order_a.begin(), p.order_a.end());
    s.R = static_cast<int>(s.order_c.size());
    s.cands = s.order_c;
    s.cands.insert(s.cands.end(), p.rem.begin(), p.rem.end());
    s.rem.assign(p.rem.begin(), p.rem.end());
    if (p.last_round < s.R - 1) {
        s.rem.insert(s.rem.end(), s.order_c.begin() + p.last_round + 1, s.order_c.end());
        s.order_c.resize(static_cast<std::size_t>(p.last_round + 1));
        s.order_a.resize(static_cast<std::size_t>(p.last_round + 1));
        s.R = p.last_round + 1;
    }
    return s;
}

void configure(ScipModel& m, const DistanceProblem& p, const DistanceSettings& s) {
    auto* scip = m.get();
    CHECK_SCIP(SCIPsetEmphasis(scip, SCIP_PARAMEMPHASIS_OPTIMALITY, TRUE));
    SCIPsetMessagehdlrQuiet(scip, TRUE);
    CHECK_SCIP(SCIPsetBoolParam(scip, "separating/closecuts/separelint", FALSE));
    CHECK_SCIP(SCIPsetCharParam(scip, "benders/default/cutstrengthenintpoint", 'i'));
    m.include_handlers(p.upperbound.as_double());
    if (p.isleaf) {
        CHECK_SCIP(SCIPsetRealParam(scip, "limits/time", s.leaf_time_limit));
        CHECK_SCIP(SCIPsetRealParam(scip, "limits/gap", 0.0));
    } else {
        CHECK_SCIP(SCIPsetRealParam(scip, "limits/time", s.time_limit));
        CHECK_SCIP(SCIPsetRealParam(scip, "limits/gap", s.gap));
    }
}

std::vector<double> reachable_votes(const Classes& cl, int n) {
    std::vector<double> reach(static_cast<std::size_t>(n), 0.0);
    for (std::size_t k = 0; k < cl.prefs.size(); ++k) {
        CandSet seen(n);
        for (const auto p : cl.prefs[k]) {
            if (p < n && !seen.test(p)) {
                seen.set(p);
                reach[static_cast<std::size_t>(p)] += static_cast<double>(cl.votes[k]);
            }
        }
    }
    return reach;
}

// Variables and tally expressions of one model, indexed by (candidate, round).
class Grid {
  public:
    Grid() = default;
    Grid(int n, int rounds)
        : rounds_(rounds),
          cells_(static_cast<std::size_t>(n) * static_cast<std::size_t>(rounds)) {}

    struct Cell {
        std::optional<Expr> vcr;
        std::optional<Expr> qcr;
        std::optional<Expr> nqcr;
        ExprSlot tally;
    };

    Cell& at(Cand c, int r) {
        return cells_.at(static_cast<std::size_t>(c) * static_cast<std::size_t>(rounds_) +
                         static_cast<std::size_t>(r));
    }
    const Expr& vcr(Cand c, int r) {
        const auto& v = at(c, r).vcr;
        if (!v) {
            throw std::runtime_error("missing tally variable");
        }
        return *v;
    }

  private:
    int rounds_ = 0;
    std::vector<Cell> cells_;
};

// What both model variants share.
struct ModelState {
    Setup st;
    Classes cl;
    std::vector<int> candpos;
    std::vector<Cand> nonsupers; // in Python set iteration order
    CandSet nonsuper_set;
    CandSet rem_set;
    std::vector<double> reach;
    Grid grid;
    std::map<int, Expr> tvalue;
};

void build_nonsupers(ModelState& ms, std::span<const Cand> supers, int n) {
    CandSet super_set(n);
    for (const auto c : supers) {
        super_set.set(c);
    }
    PySetOrder order;
    ms.nonsuper_set = CandSet(n);
    for (const auto c : ms.st.cands) {
        if (!super_set.test(c)) {
            order.add(c);
            ms.nonsuper_set.set(c);
        }
    }
    ms.nonsupers = order.order();
    ms.rem_set = CandSet(n);
    for (const auto c : ms.st.rem) {
        ms.rem_set.set(c);
    }
}

// Tally variable bounds that hold in every elimination order.
std::pair<double, double> tally_bounds(const ModelState& ms, const BoundInputs& bi, Cand c, int r,
                                       double ub, double tot) {
    if (r == 0 && ms.nonsuper_set.test(c)) {
        const auto fp = bi.fp[static_cast<std::size_t>(c)];
        const auto low = fp - ub;
        return {low > 0.0 ? low : 0.0, std::min(tot, fp + ub)};
    }
    return {0.0, std::min(tot, ms.reach[static_cast<std::size_t>(c)] + ub)};
}

void add_round_constraints(ScipModel& m, ModelState& ms, const BoundInputs& bi,
                           const DistanceProblem& p, bool qprefix, int last_seating_block_start) {
    const auto quota = static_cast<double>(bi.quota);
    const auto& oc = ms.st.order_c;
    const auto& oa = ms.st.order_a;
    const auto pos = [&ms](Cand c) { return ms.candpos[static_cast<std::size_t>(c)]; };
    for (int r = 0; r <= p.last_round; ++r) {
        const auto ce = oc[static_cast<std::size_t>(r)];
        if (oa[static_cast<std::size_t>(r)] == 0) {
            // Nobody holds a quota in an elimination round, and the
            // eliminated candidate has the smallest tally.
            for (const auto c : ms.nonsupers) {
                if (pos(c) >= r) {
                    m.add_cons(le(ms.grid.vcr(c, r), quota - kEpsilon));
                }
            }
            if (ms.nonsuper_set.test(ce)) {
                for (const auto co : ms.nonsupers) {
                    if (ce != co && pos(co) > r) {
                        m.add_cons(le(ms.grid.vcr(ce, r), ms.grid.vcr(co, r)));
                    }
                }
            }
            continue;
        }

        if (qprefix) {
            for (const auto co : ms.nonsupers) {
                if (const auto* q = find_q(*p.order_q, co)) {
                    const auto rq = q->hi;
                    if (rq == r) {
                        m.add_cons(ge(ms.grid.vcr(co, r), quota));
                    } else if (r < last_seating_block_start && rq > r) {
                        m.add_cons(le(ms.grid.vcr(co, r), quota - kEpsilon));
                    }
                } else if (r < last_seating_block_start && pos(co) > r) {
                    m.add_cons(le(ms.grid.vcr(co, r), quota - kEpsilon));
                }
            }
        } else if (const auto& q = ms.grid.at(ce, r).qcr) {
            CHECK_SCIP(SCIPchgVarLb(m.get(), m.var(q->terms().at(0).first.at(0)), 1.0));
        }

        // The first candidate seated after an elimination has the highest tally.
        if (r == 0 || oa[static_cast<std::size_t>(r - 1)] == 0) {
            for (const auto co : ms.nonsupers) {
                if (ce != co && pos(co) > r) {
                    m.add_cons(ge(ms.grid.vcr(ce, r), ms.grid.vcr(co, r)));
                }
            }
        }

        if (r != p.last_round) {
            const auto tv = m.add_var("tv(" + std::to_string(r) + ")", false, 0, 1.0);
            ms.tvalue.emplace(r, tv);
            const auto& v = ms.grid.vcr(ce, r);
            m.add_cons(le(tv.sub_num(kEpsilon).mul(v), v.sub_num(quota)));
            m.add_cons(ge(tv.add_num(kEpsilon).mul(v), v.sub_num(quota)));
        }
    }
}

// distribute_ballots_t in stvdistance.py (quota rounds as ranges).
void distribute_ranges(ModelState& ms, const DistanceProblem& p, const std::vector<Cand>& prefs,
                       int rstart, Cand bw, int cp_bw, std::size_t wi, Expr value) {
    std::optional<Cand> with = bw;
    auto last = bw;
    auto cp = cp_bw;
    auto withindex = wi;
    const auto lballot = prefs.size();
    ms.grid.at(bw, rstart).tally.iadd(value);

    for (int r = rstart; r < ms.st.R; ++r) {
        if (!with) {
            continue;
        }
        if (last != *with) {
            ms.grid.at(*with, r).tally.iadd(value);
            last = *with;
        }
        if (r == p.last_round) {
            break;
        }
        if (cp == r && p.winners->test(*with)) {
            value = value.mul(ms.tvalue.at(r));
        }
        if (!ms.rem_set.test(*with) && cp <= r) {
            ++withindex;
            while (withindex < lballot) {
                with = prefs[withindex];
                cp = ms.candpos[static_cast<std::size_t>(*with)];
                if (cp <= r) {
                    ++withindex;
                    continue;
                }
                if (p.winners->test(*with)) {
                    if (const auto* q = find_q(*p.order_q, *with)) {
                        if (q->hi < r) {
                            ++withindex;
                            continue;
                        }
                        if (q->lo < r) {
                            // The candidate may or may not hold a quota by
                            // now: follow both possibilities.
                            const auto nbv = value.mul(*ms.grid.at(*with, r).nqcr);
                            distribute_ranges(ms, p, prefs, r + 1, *with, cp, withindex, nbv);
                            value = value.mul(*ms.grid.at(*with, r).qcr);
                            ++withindex;
                            continue;
                        }
                    }
                }
                break;
            }
            if (withindex == lballot) {
                with.reset();
            }
        }
    }
}

// distribute_ballots_t in stvdistance-qprefix.py (exact quota rounds).
void distribute_qprefix(ModelState& ms, const DistanceProblem& p, const std::vector<Cand>& prefs,
                        Cand bw, int cp_bw, Expr value) {
    std::optional<Cand> with = bw;
    auto last = bw;
    auto cp = cp_bw;
    std::size_t withindex = 0;
    const auto lballot = prefs.size();
    ms.grid.at(bw, 0).tally.iadd(value);

    for (int r = 0; r < ms.st.R; ++r) {
        if (!with) {
            continue;
        }
        if (last != *with) {
            ms.grid.at(*with, r).tally.iadd(value);
            last = *with;
        }
        if (r == p.last_round) {
            break;
        }
        if (cp == r && p.winners->test(*with)) {
            value = value.mul(ms.tvalue.at(r));
        }
        if (!ms.rem_set.test(*with) && cp <= r) {
            ++withindex;
            while (withindex < lballot) {
                with = prefs[withindex];
                cp = ms.candpos[static_cast<std::size_t>(*with)];
                if (cp <= r) {
                    ++withindex;
                    continue;
                }
                if (p.winners->test(*with)) {
                    const auto* q = find_q(*p.order_q, *with);
                    if (q != nullptr && q->hi < r) {
                        ++withindex;
                        continue;
                    }
                }
                break;
            }
            if (withindex == lballot) {
                with.reset();
            }
        }
    }
}

void write_sidecar(const DistanceSettings& s, const DistanceProblem& p, const ModelState& ms,
                   SCIP* scip, const PyNum& dual, const PyNum& primal,
                   std::chrono::steady_clock::time_point t_start) {
    static std::mutex sidecar_mutex;
    const auto wall =
        std::chrono::duration<double>(std::chrono::steady_clock::now() - t_start).count();
    std::string line = status_name(SCIPgetStatus(scip)) + "," +
                       py_fixed(SCIPgetSolvingTime(scip), 2) + "," + py_fixed(wall, 2) + "," +
                       std::to_string(SCIPgetNNodes(scip)) + "," + dual.str() + "," + primal.str() +
                       "," + p.upperbound.str() + "," + p.lowerbound.str() + "," +
                       (p.isleaf ? "1" : "0") + "," + std::to_string(ms.st.order_c.size()) + ",";
    for (std::size_t i = 0; i < ms.st.order_c.size(); ++i) {
        line += (i > 0 ? "|" : "") + std::to_string(ms.st.order_c[i]);
    }
    line += ",";
    for (std::size_t i = 0; i < ms.st.order_a.size(); ++i) {
        line += (i > 0 ? "|" : "") + std::to_string(ms.st.order_a[i]);
    }
    const std::lock_guard<std::mutex> lock(sidecar_mutex);
    std::ofstream out(s.sidecar_path, std::ios::app);
    if (out) {
        out << line << '\n';
    }
}

DistanceResult build_and_solve(const BoundInputs& bi, const PyNum& tot_ballots,
                               const DistanceProblem& p, const DistanceSettings& s,
                               ModelDump* dump) {
    const auto t_start = std::chrono::steady_clock::now();
    const auto n = bi.ncands;
    const auto quota = static_cast<double>(bi.quota);
    const auto ub = p.upperbound.as_double();
    const auto tot = tot_ballots.as_double();

    ModelState ms;
    ms.st = trim_to_last_round(p);
    const auto R = ms.st.R;

    int last_seating_block_start = n;
    if (s.qprefix && ms.st.order_a.back() == 1) {
        for (auto i = static_cast<int>(ms.st.order_c.size()) - 1; i >= 0; --i) {
            if (ms.st.order_a[static_cast<std::size_t>(i)] == 1) {
                last_seating_block_start = i;
            } else {
                break;
            }
        }
    }

    ms.cl = reduce_ballots(bi, ms.st.order_c, ms.st.rem, p.merge_map);

    ScipModel m;
    configure(m, p, s);

    // Position in the trimmed prefix; R + 1 for candidates still standing.
    ms.candpos.assign(static_cast<std::size_t>(n), R + 1);
    if (s.qprefix) {
        for (const auto c : ms.st.cands) {
            const auto it = std::find(ms.st.order_c.begin(), ms.st.order_c.end(), c);
            if (it != ms.st.order_c.end()) {
                ms.candpos[static_cast<std::size_t>(c)] =
                    static_cast<int>(it - ms.st.order_c.begin());
            }
        }
    } else {
        for (std::size_t i = 0; i < ms.st.order_c.size(); ++i) {
            ms.candpos[static_cast<std::size_t>(ms.st.order_c[i])] = static_cast<int>(i);
        }
    }
    build_nonsupers(ms, p.supers, n);
    ms.reach = reachable_votes(ms.cl, n);
    ms.grid = Grid(n, R);

    CandSet in_order_c(n);
    for (const auto c : ms.st.order_c) {
        in_order_c.set(c);
    }

    // Tally variables, and in range mode the quota indicators of winners.
    for (const auto c : ms.st.cands) {
        const auto pos = ms.candpos[static_cast<std::size_t>(c)];
        for (int r = 0; r < R; ++r) {
            if (pos < r) {
                break;
            }
            const auto [vlb, vub] = tally_bounds(ms, bi, c, r, ub, tot);
            auto& cell = ms.grid.at(c, r);
            cell.vcr = m.add_var("vcr(" + std::to_string(c) + "," + std::to_string(r) + ")", false,
                                 vlb, vub);
            if (r > 0) {
                cell.tally.iadd(*ms.grid.at(c, r - 1).vcr);
            }
            if (!s.qprefix && p.winners->test(c) && in_order_c.test(c)) {
                const auto suffix = "(" + std::to_string(c) + "," + std::to_string(r) + ")";
                const auto inf = SCIPinfinity(m.get());
                cell.qcr = m.add_var("qcr" + suffix, true, 0.0, inf);
                cell.nqcr = m.add_var("nqcr" + suffix, true, 0.0, inf);
                m.add_cons(eq(*cell.nqcr, cell.qcr->rsub_num(1.0)));
                m.add_cons(ge(*cell.vcr, cell.qcr->mul_num(quota)));
                m.add_cons(le(*cell.vcr,
                              cell.nqcr->mul_num(quota - kEpsilon).add(cell.qcr->mul_num(tot))));
            }
        }
    }

    add_round_constraints(m, ms, bi, p, s.qprefix, last_seating_block_start);

    // Ballot classes: changes allowed to each, and where each one's votes go.
    Expr sum_ps;
    Expr sum_ms;
    bool sums_started = false;
    for (std::size_t k = 0; k < ms.cl.prefs.size(); ++k) {
        const auto votes = static_cast<double>(ms.cl.votes[k]);
        const auto num = std::to_string(k);
        auto ps = m.add_var("ps(" + num + ")", false, 0, ub);
        auto msv = m.add_var("ms(" + num + ")", false, 0, std::min(ub, votes));
        auto ys = m.add_var("ys(" + num + ")", false, 0, std::min(tot, votes + ub));
        if (!sums_started) {
            sum_ps = ps.add_num(0.0); // Python: 0 + ps
            sum_ms = msv.add_num(0.0);
            sums_started = true;
        } else {
            sum_ps.iadd(ps);
            sum_ms.iadd(msv);
        }
        m.add_cons(eq(ys, ps.add_num(votes).sub(msv)));

        const auto& prefs = ms.cl.prefs[k];
        const auto bw = prefs[0];
        const auto cp = ms.candpos[static_cast<std::size_t>(bw)];
        if (s.qprefix) {
            distribute_qprefix(ms, p, prefs, bw, cp, ys);
        } else {
            distribute_ranges(ms, p, prefs, 0, bw, cp, 0, ys);
        }
    }

    m.add_cons(eq(sum_ps, sum_ms));

    for (const auto c : ms.st.cands) {
        const auto pos = ms.candpos[static_cast<std::size_t>(c)];
        const auto upto = std::min(p.last_round + 1, pos + 1);
        for (int r = 0; r < upto; ++r) {
            auto& cell = ms.grid.at(c, r);
            m.add_cons(eq(*cell.vcr, cell.tally));
        }
    }

    CHECK_SCIP(SCIPsetObjlimit(m.get(), ub));
    m.add_cons(ge(sum_ps, p.lowerbound.as_double()));
    m.set_objective(sum_ps);

    if (dump != nullptr) {
        CHECK_SCIP(SCIPwriteOrigProblem(m.get(), (dump->stem + ".cip").c_str(), nullptr, FALSE));
        CHECK_SCIP(SCIPwriteParams(m.get(), (dump->stem + ".set").c_str(), FALSE, TRUE));
        dump->objlimit = SCIPgetObjlimit(m.get());
        if (!dump->solve) {
            return {};
        }
    }

    CHECK_SCIP(SCIPsolve(m.get()));

    const auto status = SCIPgetStatus(m.get());
    const auto dual = py_max(PyNum::integer(0), py_ceil(SCIPgetDualbound(m.get())));
    const auto primal_raw = SCIPgetPrimalbound(m.get());
    const auto primal = primal_raw < ub - 1e-9
                            ? py_max(PyNum::integer(0), py_ceil(primal_raw))
                            : PyNum::integer(static_cast<PyInt>(SCIPinfinity(m.get())));

    if (!s.qprefix && !s.sidecar_path.empty()) {
        write_sidecar(s, p, ms, m.get(), dual, primal, t_start);
    }

    if (status == SCIP_STATUS_INFEASIBLE || status == SCIP_STATUS_INFORUNBD) {
        return {false, std::nullopt, std::nullopt};
    }
    return {true, dual, primal};
}

} // namespace

DistanceResult solve_stvdistance(const BoundInputs& bi, const PyNum& tot_ballots,
                                 const DistanceProblem& p, const DistanceSettings& s,
                                 ModelDump* dump) {
    return build_and_solve(bi, tot_ballots, p, s, dump);
}

std::vector<std::vector<Cand>> equivalence_classes(std::span<const Cand> order_c,
                                                   std::span<const Cand> remainder) {
    const auto n = order_c.size();
    const auto full = (std::uint64_t{1} << n) - 1;
    std::vector<std::vector<Cand>> first;
    first.reserve(full);
    for (std::uint64_t m = 1; m <= full; ++m) {
        std::vector<Cand> prefs;
        for (std::size_t i = 0; i < n; ++i) {
            if (((m >> i) & 1U) != 0) {
                prefs.push_back(order_c[i]);
            }
        }
        first.push_back(std::move(prefs));
    }
    std::vector<std::vector<Cand>> out = first;
    for (const auto r : remainder) {
        out.push_back({r});
        for (const auto& f : first) {
            auto with_r = f;
            with_r.push_back(r);
            out.push_back(std::move(with_r));
        }
    }
    return out;
}

} // namespace marginstv
