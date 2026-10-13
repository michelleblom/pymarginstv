// marginstv: lower bound on the margin of victory of an STV election.
// Command line and output follow pymarginstv.py.

#include "marginstv/election.hpp"
#include "marginstv/logger.hpp"
#include "marginstv/options.hpp"
#include "marginstv/search.hpp"
#include "marginstv/simulate.hpp"

#include <tbb/global_control.h>

#include <chrono>
#include <exception>
#include <iostream>
#include <memory>
#include <string>
#include <vector>

using namespace marginstv;

namespace {

double now_seconds() {
    return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch())
        .count();
}

double wall_seconds() {
    return std::chrono::duration<double>(std::chrono::system_clock::now().time_since_epoch())
        .count();
}

int run(const Options& opt) {
    const auto t0_start = now_seconds();
    const auto displayname = opt.displayname.value_or(opt.data);

    std::unique_ptr<tbb::global_control> threads;
    if (opt.threads > 0) {
        threads = std::make_unique<tbb::global_control>(
            tbb::global_control::max_allowed_parallelism, static_cast<std::size_t>(opt.threads));
    }

    Logger log(opt.log);
    const auto election = read_election(opt.data);
    const auto outcome = simulate_stv(election, opt.seats, log);
    const auto& cands = election.candidates;

    if (opt.just_sim) {
        std::string ids = std::to_string(cands[static_cast<std::size_t>(outcome.order_c[0])].id);
        for (std::size_t i = 1; i < cands.size(); ++i) {
            ids += "," + std::to_string(cands[static_cast<std::size_t>(outcome.order_c[i])].id);
        }
        log.line(ids);
        std::string acts = std::to_string(outcome.order_a[0]);
        for (std::size_t i = 1; i < cands.size(); ++i) {
            acts += "," + std::to_string(outcome.order_a[i]);
        }
        log.raw(acts);
        log.flush();
        return 0;
    }

    const auto weub = compute_weub(election, outcome);
    const auto simple_ub = compute_simple_ub(election, outcome);
    auto upper_bound = py_ceil(py_min(weub, simple_ub).as_double());
    const auto external = opt.ub.has_value();
    if (external) {
        upper_bound = py_ceil(py_min(upper_bound, PyNum::integer(*opt.ub)).as_double());
    }
    const auto original_upper_bound = upper_bound;
    log.line("WEUB " + weub.str() + ", simple UB " + simple_ub.str() + ", external UB " +
             (external ? std::to_string(*opt.ub) : std::string("absent")) + ".");
    log.flush();

    SearchInputs in;
    in.election = &election;
    in.options = &opt;
    in.bounds.election = &election;
    in.bounds.ncands = static_cast<int>(cands.size());
    in.bounds.quota = outcome.quota;
    in.bounds.seats = opt.seats;
    for (const auto& c : cands) {
        in.bounds.fp.push_back(static_cast<double>(c.fp_votes));
    }
    in.tot_ballots = outcome.total_votes;
    in.winner_set = CandSet(in.bounds.ncands);
    for (const auto w : outcome.winners) {
        in.winner_set.set(w);
    }
    in.full_order_c = outcome.order_c;
    in.full_order_a = outcome.order_a;
    in.distance.time_limit = opt.time;
    in.distance.leaf_time_limit = opt.thard;
    in.distance.gap = opt.gap;
    in.distance.qprefix = opt.useqprefix;
    in.distance.sidecar_path = opt.log + ".solves.csv";

    const auto tstart = wall_seconds();
    const auto res = treestv(in, upper_bound, log);
    const auto tend = wall_seconds();

    log.line(res.lb.str() + "--" + res.ub.str() + ", " + std::to_string(res.nexps) + ", " +
             std::to_string(res.nsolves) + ", " + std::to_string(res.ignores) + ", " +
             std::to_string(res.agg_prunes));
    log.flush();

    const auto t0_end = now_seconds();
    std::cout << displayname << ", " << cands.size() << ", " << opt.seats << ", " << outcome.quota
              << ", " << original_upper_bound.str() << ", " << res.lb.str() << ", "
              << res.ub.str() << ", " << res.nexps << ", " << res.nsolves << ", "
              << py_float_repr(tend - tstart) << ", " << py_float_repr(t0_end - t0_start) << ", "
              << py_bool(opt.lse) << ", " << py_bool(opt.dlb) << ", " << py_bool(opt.eqlb) << ", "
              << py_bool(opt.dlbc) << ", " << py_bool(opt.eqlbc) << ", " << py_bool(opt.prec_et)
              << ", " << py_bool(opt.useqprefix) << ", " << py_bool(opt.nominlps) << ", "
              << py_bool(external) << '\n';
    return 0;
}

} // namespace

int main(int argc, char** argv) {
    try {
        const auto opt = parse_options(std::vector<std::string>(argv + 1, argv + argc));
        return run(opt);
    } catch (const std::invalid_argument& e) {
        std::cerr << "marginstv: error: " << e.what() << '\n';
        return 2;
    } catch (const std::exception& e) {
        std::cerr << "marginstv: " << e.what() << '\n';
        return 1;
    }
}
