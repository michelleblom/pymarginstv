// The C++ MINLP models must be the models the Python gives SCIP: same
// variables, constraints, term order, coefficients, parameters and
// objective limit. Each recorded Python solve is rebuilt here and SCIP's
// written form of both is compared. Solving them must also give the same
// result.

#include "../unit/golden.hpp"

#include "marginstv/distance.hpp"
#include "marginstv/election.hpp"
#include "marginstv/simulate.hpp"

#include <catch2/catch_test_macros.hpp>
#include <tbb/parallel_for.h>

#include <atomic>
#include <memory>

#include <filesystem>
#include <fstream>
#include <sstream>

using namespace marginstv;

namespace {

std::string slurp(const std::string& path) {
    std::ifstream in(path);
    std::stringstream s;
    s << in.rdbuf();
    return s.str();
}

PyNum decode_num(simdjson::dom::element e) {
    if (golden::is_float(e)) {
        return PyNum::real(golden::num(e));
    }
    return PyNum::integer(static_cast<PyInt>(golden::num(e)));
}

std::optional<PyNum> decode_opt(simdjson::dom::element e) {
    if (e.is_null()) {
        return std::nullopt;
    }
    return decode_num(e);
}

OrderQ decode_q(simdjson::dom::element e) {
    OrderQ q;
    for (const auto pair : e["dict"].get_array()) {
        const auto rng = golden::ints(pair.at(1).value());
        q.push_back({static_cast<int>(pair.at(0).get_int64().value()), rng[0], rng[1]});
    }
    return q;
}

struct Case {
    std::string name;
    std::vector<std::string> argv;
};

std::string arg_after(const std::vector<std::string>& argv, const std::string& flag) {
    for (std::size_t i = 0; i + 1 < argv.size(); ++i) {
        if (argv[i] == flag) {
            return argv[i + 1];
        }
    }
    return {};
}

bool has_flag(const std::vector<std::string>& argv, const std::string& flag) {
    return std::find(argv.begin(), argv.end(), flag) != argv.end();
}

} // namespace

TEST_CASE("MINLP models match the Python's", "[scip][models]") {
    const auto dir = std::filesystem::path(golden::path(""));
    std::vector<std::filesystem::path> files;
    for (const auto& f : std::filesystem::directory_iterator(dir)) {
        const auto name = f.path().filename().string();
        if (name.find("_minlp") != std::string::npos && name.ends_with(".jsonl.gz")) {
            files.push_back(f.path());
        }
    }
    std::sort(files.begin(), files.end());
    REQUIRE(!files.empty());

    const auto out_dir = std::filesystem::temp_directory_path() / "marginstv_models";
    std::filesystem::create_directories(out_dir);
    std::size_t compared = 0;

    for (const auto& file : files) {
        const auto stem = file.filename().string().substr(0, file.filename().string().size() - 9);
        golden::JsonLines lines(file.string());
        simdjson::dom::element rec;
        REQUIRE(lines.next(rec));
        std::vector<std::string> argv;
        for (const auto a : rec["argv"].get_array()) {
            argv.emplace_back(a.get_string().value());
        }
        const auto election = read_election(arg_after(argv, "-d"));
        BoundInputs bi;
        bi.election = &election;
        bi.ncands = static_cast<int>(election.candidates.size());
        bi.seats = std::stoi(arg_after(argv, "-s"));
        for (const auto& c : election.candidates) {
            bi.fp.push_back(static_cast<double>(c.fp_votes));
        }
        DistanceSettings settings;
        settings.qprefix = has_flag(argv, "-useqprefix");

        while (lines.next(rec)) {
            if (std::string(rec["kind"].get_string().value()) != "solve") {
                continue;
            }
            const auto in = rec["inputs"].get_array();
            const auto order_c = golden::ints(in.at(0).value());
            const auto order_a = golden::ints(in.at(1).value());
            const auto rem = golden::ints(in.at(2).value());
            CandSet winners(bi.ncands);
            for (const auto w : golden::set_items(in.at(3).value())) {
                winners.set(w);
            }
            const auto order_q = decode_q(in.at(4).value());
            std::vector<Cand> merge_map(static_cast<std::size_t>(bi.ncands));
            for (const auto pair : in.at(5)["dict"].get_array()) {
                merge_map[static_cast<std::size_t>(pair.at(0).get_int64().value())] =
                    static_cast<Cand>(pair.at(1).get_int64().value());
            }
            const auto supers = golden::ints(in.at(6).value());
            const auto tot = decode_num(in.at(7).value());
            bi.quota = static_cast<std::int64_t>(golden::num(in.at(8).value()));

            DistanceProblem p;
            p.order_c = order_c;
            p.order_a = order_a;
            p.rem = rem;
            p.winners = &winners;
            p.order_q = &order_q;
            p.merge_map = merge_map;
            p.supers = supers;
            p.upperbound = decode_num(in.at(9).value());
            p.last_round = static_cast<int>(golden::num(in.at(10).value()));
            p.lowerbound = decode_num(in.at(11).value());
            p.isleaf = rec["isleaf"].get_bool().value();

            const auto model = std::string(rec["model"].get_string().value());
            const auto py_stem = (dir / (stem + "_models") / model).string();
            const auto cpp_stem = (out_dir / (stem + "_" + model)).string();
            const auto py_cip = py_stem.substr(0, py_stem.size() - 4);

            ModelDump dump{cpp_stem.substr(0, cpp_stem.size() - 4), true, 0};
            const auto result = solve_stvdistance(bi, tot, p, settings, &dump);

            INFO(stem << " " << model);
            CHECK(slurp(dump.stem + ".cip") == slurp(py_cip + ".cip"));
            CHECK(slurp(dump.stem + ".set") == slurp(py_cip + ".set"));
            CHECK(dump.objlimit == std::strtod(slurp(py_cip + ".objlimit").c_str(), nullptr));

            const auto expected = rec["result"].get_array();
            CHECK(result.feasible == expected.at(0).get_bool().value());
            const auto dist = decode_opt(expected.at(1).value());
            const auto dist_ub = decode_opt(expected.at(2).value());
            CHECK(result.dist.has_value() == dist.has_value());
            if (dist && result.dist) {
                CHECK(result.dist->str() == dist->str());
                CHECK(result.dist_ub->str() == dist_ub->str());
            }
            ++compared;
        }
    }
    CHECK(compared > 500);
}

namespace {

// One recorded solve, with everything needed to repeat it.
struct SolveCase {
    std::shared_ptr<const Election> election;
    BoundInputs bi;
    DistanceSettings settings;
    std::vector<Cand> order_c, rem, merge_map, supers;
    std::vector<int> order_a;
    CandSet winners;
    OrderQ order_q;
    PyNum tot, upperbound, lowerbound;
    int last_round = 0;
    bool isleaf = false;
    std::optional<PyNum> dist, dist_ub;
    bool feasible = false;
};

std::vector<SolveCase> load_solves() {
    std::vector<SolveCase> out;
    const auto dir = std::filesystem::path(golden::path(""));
    for (const auto& f : std::filesystem::directory_iterator(dir)) {
        const auto name = f.path().filename().string();
        if (name.find("_minlp") == std::string::npos || !name.ends_with(".jsonl.gz")) {
            continue;
        }
        golden::JsonLines lines(f.path().string());
        simdjson::dom::element rec;
        lines.next(rec);
        std::vector<std::string> argv;
        for (const auto a : rec["argv"].get_array()) {
            argv.emplace_back(a.get_string().value());
        }
        auto election = std::make_shared<const Election>(read_election(arg_after(argv, "-d")));
        while (lines.next(rec)) {
            if (std::string(rec["kind"].get_string().value()) != "solve") {
                continue;
            }
            SolveCase c;
            c.election = election;
            c.bi.election = election.get();
            c.bi.ncands = static_cast<int>(election->candidates.size());
            c.bi.seats = std::stoi(arg_after(argv, "-s"));
            for (const auto& cand : election->candidates) {
                c.bi.fp.push_back(static_cast<double>(cand.fp_votes));
            }
            c.settings.qprefix = has_flag(argv, "-useqprefix");
            const auto in = rec["inputs"].get_array();
            c.order_c = golden::ints(in.at(0).value());
            c.order_a = golden::ints(in.at(1).value());
            c.rem = golden::ints(in.at(2).value());
            c.winners = CandSet(c.bi.ncands);
            for (const auto w : golden::set_items(in.at(3).value())) {
                c.winners.set(w);
            }
            c.order_q = decode_q(in.at(4).value());
            c.merge_map.resize(static_cast<std::size_t>(c.bi.ncands));
            for (const auto pair : in.at(5)["dict"].get_array()) {
                c.merge_map[static_cast<std::size_t>(pair.at(0).get_int64().value())] =
                    static_cast<Cand>(pair.at(1).get_int64().value());
            }
            c.supers = golden::ints(in.at(6).value());
            c.tot = decode_num(in.at(7).value());
            c.bi.quota = static_cast<std::int64_t>(golden::num(in.at(8).value()));
            c.upperbound = decode_num(in.at(9).value());
            c.last_round = static_cast<int>(golden::num(in.at(10).value()));
            c.lowerbound = decode_num(in.at(11).value());
            c.isleaf = rec["isleaf"].get_bool().value();
            const auto want = rec["result"].get_array();
            c.feasible = want.at(0).get_bool().value();
            c.dist = decode_opt(want.at(1).value());
            c.dist_ub = decode_opt(want.at(2).value());
            out.push_back(std::move(c));
        }
    }
    return out;
}

} // namespace

TEST_CASE("MINLP solves give the same results when run concurrently", "[scip][concurrent]") {
    const auto cases = load_solves();
    REQUIRE(cases.size() > 500);
    std::atomic<std::size_t> mismatches{0};
    for (int round = 0; round < 3; ++round) {
        tbb::parallel_for(std::size_t{0}, cases.size(), [&](std::size_t i) {
            const auto& c = cases[i];
            DistanceProblem p;
            p.order_c = c.order_c;
            p.order_a = c.order_a;
            p.rem = c.rem;
            p.winners = &c.winners;
            p.order_q = &c.order_q;
            p.merge_map = c.merge_map;
            p.supers = c.supers;
            p.upperbound = c.upperbound;
            p.last_round = c.last_round;
            p.lowerbound = c.lowerbound;
            p.isleaf = c.isleaf;
            const auto r = solve_stvdistance(c.bi, c.tot, p, c.settings);
            const auto same = r.feasible == c.feasible && r.dist.has_value() == c.dist.has_value() &&
                              (!r.dist || (r.dist->str() == c.dist->str() &&
                                           r.dist_ub->str() == c.dist_ub->str()));
            if (!same) {
                ++mismatches;
            }
        });
    }
    CHECK(mismatches.load() == 0);
}
