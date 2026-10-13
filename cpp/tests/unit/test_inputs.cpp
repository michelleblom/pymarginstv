// Readers and the simulated count, against the Python.

#include "golden.hpp"

#include "marginstv/blake2b.hpp"
#include "marginstv/election.hpp"
#include "marginstv/simulate.hpp"

#include <catch2/catch_test_macros.hpp>

#include <cstdio>
#include <filesystem>
#include <fstream>
#include <sstream>

using namespace marginstv;

namespace {

std::string data_path(const std::string& name) {
    if (name.starts_with("repo:")) {
        return std::string(MARGINSTV_REPO_DIR) + "/" + name.substr(5);
    }
    return std::string(MARGINSTV_DATA_DIR) + "/" + name;
}

std::string ballots_digest(const BallotStore& ballots) {
    std::vector<std::uint8_t> bytes;
    auto put = [&](std::uint64_t v, int nbytes) {
        for (int k = 0; k < nbytes; ++k) {
            bytes.push_back(static_cast<std::uint8_t>(v >> (8 * k)));
        }
    };
    for (std::size_t b = 0; b < ballots.size(); ++b) {
        const auto prefs = ballots.prefs(b);
        put(static_cast<std::uint64_t>(ballots.votes(b)), 8);
        put(prefs.size(), 2);
        for (const auto p : prefs) {
            put(p, 2);
        }
    }
    const auto d = blake2b(bytes, 16);
    std::string out;
    char buf[3];
    for (const auto x : d) {
        std::snprintf(buf, sizeof buf, "%02x", x);
        out += buf;
    }
    return out;
}

// Expected Python str() of a golden number.
std::string py_str(simdjson::dom::element e) {
    if (golden::is_float(e)) {
        return py_float_repr(golden::num(e));
    }
    return std::to_string(e.get_int64().value());
}

} // namespace

TEST_CASE("readers and simulation match the Python", "[unit][inputs]") {
    const auto doc = golden::load_json_gz(golden::path("inputs.json.gz"));
    for (const auto item : doc.root.get_array()) {
        const std::string file(item["file"].get_string().value());
        const auto seats = static_cast<int>(item["seats"].get_int64().value());
        DYNAMIC_SECTION(file) {
            const auto e = read_election(data_path(file));
            const auto n = e.candidates.size();
            REQUIRE(n == item["ncands"].get_uint64().value());
            REQUIRE(e.ballots.size() == item["nballots"].get_uint64().value());
            CHECK(ballots_digest(e.ballots) == std::string(item["ballots_digest"].get_string().value()));

            const auto ids = golden::ints(item["cand_ids"].value());
            const auto fp = golden::nums(item["fp_votes"].value());
            for (std::size_t c = 0; c < n; ++c) {
                CHECK(e.candidates[c].id == ids[c]);
                CHECK(static_cast<double>(e.candidates[c].fp_votes) == fp[c]);
            }
            const auto mentions = golden::nums(item["mentions"].value());
            for (std::size_t c = 0; c < n; ++c) {
                CHECK(static_cast<double>(e.metadata.mentions[c]) == mentions[c]);
            }
            std::size_t x = 0;
            for (const auto row : item["above"].get_array()) {
                std::size_t y = 0;
                for (const auto v : row.get_array()) {
                    CHECK(static_cast<double>(e.metadata.above[x * n + y]) == golden::num(v));
                    CHECK(e.metadata.reassign[x * n + y] ==
                          golden::num(item["reassign"].at(x).at(y).value()));
                    ++y;
                }
                ++x;
            }

            const auto tmp = std::filesystem::temp_directory_path() / "marginstv_sim_test.log";
            Outcome out;
            {
                Logger log(tmp.string());
                out = simulate_stv(e, seats, log);
            }
            std::ifstream in(tmp);
            std::stringstream text;
            text << in.rdbuf();
            CHECK(text.str() == std::string(item["sim_log"].get_string().value()));

            CHECK(out.quota == item["quota"].get_int64().value());
            CHECK(out.total_votes.str() == py_str(item["totvotes"].value()));
            CHECK(out.order_c == golden::ints(item["order_c"].value()));
            CHECK(out.order_a == golden::ints(item["order_a"].value()));
            CHECK(out.winners == golden::ints(item["winners"].value()));
            for (const auto pair : item["tallies"]["dict"].get_array()) {
                const auto c = static_cast<std::size_t>(pair.at(0).get_int64().value());
                const auto t = golden::nums(pair.at(1).value());
                for (std::size_t r = 0; r < t.size(); ++r) {
                    CHECK(out.tallies[c * n + r] == t[r]);
                }
            }
            CHECK(compute_weub(e, out).str() == py_str(item["weub"].value()));
            CHECK(compute_simple_ub(e, out).str() == py_str(item["simple_ub"].value()));
        }
    }
}
