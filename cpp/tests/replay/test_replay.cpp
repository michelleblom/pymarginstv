// Replays the Python's recorded search steps through the C++ functions.
//
// dump_golden.py recorded every call to eval_child_initial,
// generate_children and eval_child in short Python runs covering every
// bound configuration. Each call's inputs go to the C++ counterpart here and
// every output field must match exactly: bounds, transfer values, no-quota
// masks, displacement summaries, the children generated, and the round
// tallies they share.

#include "../unit/golden.hpp"

#include "marginstv/search.hpp"

#include <catch2/catch_test_macros.hpp>

#include <filesystem>
#include <sstream>

using namespace marginstv;

namespace {

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

// An int that may be stored as {"int": "0x..."}: its set bits.
CandSet decode_mask(simdjson::dom::element e, int n) {
    CandSet s(n);
    if (e.is_int64()) {
        const auto v = static_cast<std::uint64_t>(e.get_int64().value());
        for (int b = 0; b < 64; ++b) {
            if (((v >> b) & 1U) != 0) {
                s.set(b);
            }
        }
        return s;
    }
    const std::string hex(e["int"].get_string().value());
    int bit = 0;
    for (auto i = hex.size(); i-- > 2;) {
        const auto ch = hex[i];
        const int d = ch <= '9' ? ch - '0' : (ch | 0x20) - 'a' + 10;
        for (int k = 0; k < 4; ++k, ++bit) {
            if (((d >> k) & 1) != 0) {
                s.set(bit);
            }
        }
    }
    return s;
}

CandSet decode_set(simdjson::dom::element e, int n) {
    CandSet s(n);
    for (const auto c : golden::set_items(e)) {
        s.set(c);
    }
    return s;
}

OrderQ decode_q(simdjson::dom::element e) {
    OrderQ q;
    for (const auto pair : e["dict"].get_array()) {
        const auto rng = golden::ints(pair.at(1).value());
        q.push_back({static_cast<int>(pair.at(0).get_int64().value()), rng[0], rng[1]});
    }
    return q;
}

EqlbCtx decode_eqlb(simdjson::dom::element e, int n) {
    EqlbCtx ctx;
    ctx.ncands = n;
    for (const auto pair : e["transfer"]["dict"].get_array()) {
        const auto tv = golden::nums(pair.at(1).value());
        ctx.transfer.set(static_cast<Cand>(pair.at(0).get_int64().value()), tv[0], tv[1]);
    }
    ctx.elim_lb = golden::num(e["elim_lb"].value());
    ctx.quota_lb = golden::num(e["quota_lb"].value());
    ctx.no_quota_lb = golden::num(e["no_quota_lb"].value());
    int r = 0;
    for (const auto m : e["nq_cons_added"].get_array()) {
        const auto mask = decode_mask(m, n);
        if (!mask.empty()) {
            ctx.nq_cons_added.merge(r, mask);
        }
        ++r;
    }
    ctx.winners = decode_set(e["winners"].value(), n);
    ctx.round = static_cast<int>(e["round"].get_int64().value());
    return ctx;
}

// A summary array: a numpy array, a (nested) list, or None.
SharedArray decode_array(simdjson::dom::element e, bool& was_list) {
    if (e.is_null()) {
        return nullptr;
    }
    std::vector<double> out;
    if (e.is_object()) {
        out = golden::nums(e["nd"].value());
    } else {
        was_list = true;
        for (const auto v : e.get_array()) {
            if (v.is_array()) {
                for (const auto x : v.get_array()) {
                    out.push_back(golden::num(x));
                }
            } else {
                out.push_back(golden::num(v));
            }
        }
    }
    return std::make_shared<const std::vector<double>>(std::move(out));
}

DispCache decode_disp(simdjson::dom::element e, int n) {
    DispCache dc;
    dc.ncands = n;
    dc.new_winner = e["new_winner"].get_bool().value();
    dc.winners = decode_set(e["winners"].value(), n);
    bool lists = false;
    dc.above = decode_array(e["above"].value(), lists);
    dc.present = decode_array(e["present"].value(), lists);
    dc.curtally = decode_array(e["curtally"].value(), lists);
    dc.reassign = decode_array(e["reassign"].value(), lists);
    dc.from_metadata_lists = lists;
    dc.start = static_cast<int>(e["start"].get_int64().value());
    dc.lowerbound = decode_num(e["lowerbound"].value());
    return dc;
}

std::optional<RoundTallies> decode_tallies(simdjson::dom::element e) {
    if (e.is_null()) {
        return std::nullopt;
    }
    RoundTallies rt;
    if (e.is_array()) {
        rt.tallies = golden::nums(e);
    } else {
        rt.ub_first = golden::nums(e["ub_first"].value());
        rt.ub_present = golden::nums(e["ub_present"].value());
        rt.elb_gain = golden::nums(e["elb_gain"].value());
        rt.slb_first = golden::nums(e["slb_first"].value());
    }
    return rt;
}

void check_eqlb(const EqlbCtx& got, const EqlbCtx& want, int n) {
    CHECK(got.elim_lb == want.elim_lb);
    CHECK(got.quota_lb == want.quota_lb);
    CHECK(got.no_quota_lb == want.no_quota_lb);
    CHECK(got.round == want.round);
    CHECK(got.winners == want.winners);
    CHECK(got.transfer.items().size() == want.transfer.items().size());
    for (const auto& t : want.transfer.items()) {
        const auto* g = got.transfer.find(t.c);
        REQUIRE(g != nullptr);
        CHECK(g->lo == t.lo);
        CHECK(g->hi == t.hi);
    }
    for (int r = 0; r < n; ++r) {
        CHECK(got.nq_cons_added.get(r) == want.nq_cons_added.get(r));
    }
}

void check_array(const SharedArray& got, const SharedArray& want) {
    CHECK(static_cast<bool>(got) == static_cast<bool>(want));
    if (got && want) {
        CHECK(*got == *want);
    }
}

void check_disp(const DispCache& got, const DispCache& want) {
    CHECK(got.new_winner == want.new_winner);
    CHECK(got.winners == want.winners);
    CHECK(got.start == want.start);
    CHECK(got.lowerbound.str() == want.lowerbound.str());
    check_array(got.above, want.above);
    check_array(got.present, want.present);
    check_array(got.curtally, want.curtally);
    check_array(got.reassign, want.reassign);
}

void check_tallies(const std::optional<RoundTallies>& got, const std::optional<RoundTallies>& want) {
    CHECK(got.has_value() == want.has_value());
    if (got && want) {
        CHECK(got->tallies == want->tallies);
        CHECK(got->ub_first == want->ub_first);
        CHECK(got->ub_present == want->ub_present);
        CHECK(got->elb_gain == want->elb_gain);
        CHECK(got->slb_first == want->slb_first);
    }
}

std::string str_opt(const std::optional<PyNum>& v) { return v ? v->str() : "None"; }

// Everything a recorded run needs: the election, its count and options.
struct Run {
    Options options;
    Election election;
    Outcome outcome;
    SearchInputs in;
};

std::unique_ptr<Run> make_run(const std::vector<std::string>& argv) {
    auto run = std::make_unique<Run>();
    run->options = parse_options(argv);
    run->election = read_election(run->options.data);
    {
        const auto tmp = std::filesystem::temp_directory_path() / "marginstv_replay_sim.log";
        Logger log(tmp.string());
        run->outcome = simulate_stv(run->election, run->options.seats, log);
    }
    auto& in = run->in;
    in.election = &run->election;
    in.options = &run->options;
    in.bounds.election = &run->election;
    in.bounds.ncands = static_cast<int>(run->election.candidates.size());
    in.bounds.quota = run->outcome.quota;
    in.bounds.seats = run->options.seats;
    for (const auto& c : run->election.candidates) {
        in.bounds.fp.push_back(static_cast<double>(c.fp_votes));
    }
    in.tot_ballots = run->outcome.total_votes;
    in.winner_set = CandSet(in.bounds.ncands);
    for (const auto w : run->outcome.winners) {
        in.winner_set.set(w);
    }
    in.full_order_c = run->outcome.order_c;
    in.full_order_a = run->outcome.order_a;
    in.distance.qprefix = run->options.useqprefix;
    return run;
}

} // namespace

TEST_CASE("search steps replay exactly", "[replay]") {
    const auto dir = std::filesystem::path(golden::path(""));
    std::vector<std::filesystem::path> files;
    for (const auto& f : std::filesystem::directory_iterator(dir)) {
        const auto name = f.path().filename().string();
        if (name.ends_with(".jsonl.gz") && name.find("_minlp") == std::string::npos) {
            files.push_back(f.path());
        }
    }
    std::sort(files.begin(), files.end());
    REQUIRE(files.size() >= 100);

    std::size_t initial = 0;
    std::size_t generated = 0;
    std::size_t children = 0;
    for (const auto& file : files) {
        golden::JsonLines lines(file.string());
        simdjson::dom::element rec;
        REQUIRE(lines.next(rec));
        std::vector<std::string> argv;
        for (const auto a : rec["argv"].get_array()) {
            argv.emplace_back(a.get_string().value());
        }
        argv.emplace_back("-log");
        argv.emplace_back("/dev/null");
        const auto run = make_run(argv);
        const auto& in = run->in;
        const auto n = in.bounds.ncands;

        std::size_t index = 0;
        while (lines.next(rec)) {
            const std::string kind(rec["kind"].get_string().value());
            INFO(file.filename().string() << " record " << index++ << " (" << kind << ")");

            if (kind == "initial") {
                const auto a = rec["inputs"].get_array();
                const auto r = eval_child_initial(
                    in, golden::ints(a.at(0).value()), golden::ints(a.at(1).value()),
                    decode_q(a.at(2).value()), decode_set(a.at(3).value(), n),
                    golden::ints(a.at(4).value()), decode_num(a.at(5).value()));
                const auto want = rec["result"].get_array();
                CHECK(r.lb.str() == decode_num(want.at(0).value()).str());
                CHECK(r.dlb.str() == decode_num(want.at(1).value()).str());
                CHECK(r.eqlb.str() == decode_num(want.at(2).value()).str());
                const auto node = want.at(3).value();
                CHECK(str_opt(r.dist) == str_opt(decode_opt(node["dist"].value())));
                CHECK(str_opt(r.dist_ub) == str_opt(decode_opt(node["dist_ub"].value())));
                check_eqlb(r.eqlbctx, decode_eqlb(node["eqlbctx"].value(), n), n);
                check_disp(r.disp_cache, decode_disp(node["disp_cache"].value(), n));
                ++initial;
            } else if (kind == "generate") {
                const auto a = rec["inputs"].get_array();
                const auto fnode = a.at(0).get_array();
                TreeNode node(golden::ints(fnode.at(2).value()), golden::ints(fnode.at(3).value()),
                              decode_q(fnode.at(4).value()), decode_eqlb(fnode.at(0).value(), n),
                              decode_disp(fnode.at(1).value(), n), decode_num(fnode.at(7).value()),
                              decode_num(fnode.at(7).value()));
                const auto ex = generate_children(in, node, decode_num(a.at(1).value()));

                const auto shared = rec["shared"].value();
                const auto want_children = rec["children"].get_array();
                REQUIRE(ex.children.size() == want_children.size());
                if (!shared.is_null()) {
                    const auto s = shared.get_array();
                    check_eqlb(ex.eqlbctx, decode_eqlb(s.at(0).value(), n), n);
                    check_disp(ex.disp_cache, decode_disp(s.at(1).value(), n));
                    check_tallies(ex.elim_tallies, decode_tallies(s.at(2).value()));
                }
                std::size_t k = 0;
                for (const auto wc : want_children) {
                    const auto w = wc.get_array();
                    const auto& c = ex.children[k++];
                    CHECK(c.order_c == golden::ints(w.at(1).value()));
                    CHECK(c.order_a == golden::ints(w.at(2).value()));
                    CHECK(order_q_str(c.order_q) == order_q_str(decode_q(w.at(3).value())));
                    CHECK(c.winners == decode_set(w.at(4).value(), n));
                    CHECK(c.rem == golden::ints(w.at(5).value()));
                    CHECK(c.isleaf == w.at(6).get_bool().value());
                }
                ++generated;
            } else if (kind == "child") {
                const auto a = rec["inputs"].get_array();
                Expansion ex;
                ex.eqlbctx = decode_eqlb(a.at(1).value(), n);
                ex.disp_cache = decode_disp(a.at(2).value(), n);
                ex.elim_tallies = decode_tallies(a.at(10).value());
                ChildSpec spec;
                spec.parent_dist = decode_num(a.at(0).value());
                spec.order_c = golden::ints(a.at(3).value());
                spec.order_a = golden::ints(a.at(4).value());
                spec.order_q = decode_q(a.at(5).value());
                spec.winners = decode_set(a.at(6).value(), n);
                spec.rem = golden::ints(a.at(7).value());
                spec.isleaf = a.at(8).get_bool().value();
                spec.running_ub = decode_num(a.at(9).value());

                const auto r = eval_child(in, ex, spec);
                const auto want = rec["result"].get_array();
                CHECK(r.lb.str() == decode_num(want.at(6).value()).str());
                CHECK(r.dlb.str() == decode_num(want.at(7).value()).str());
                CHECK(r.eqlb.str() == decode_num(want.at(8).value()).str());
                CHECK(str_opt(r.dist) == str_opt(decode_opt(want.at(9).value())));
                CHECK(str_opt(r.dist_ub) == str_opt(decode_opt(want.at(10).value())));
                CHECK(r.solved == want.at(13).get_bool().value());
                check_eqlb(r.eqlbctx, decode_eqlb(want.at(1).value(), n), n);
                check_disp(r.disp_cache, decode_disp(want.at(2).value(), n));
                ++children;
            }
        }
    }
    INFO("replayed " << initial << " initial, " << generated << " expansions, " << children
                     << " children");
    CHECK(initial > 0);
    CHECK(generated > 0);
    CHECK(children > 10000);
}
