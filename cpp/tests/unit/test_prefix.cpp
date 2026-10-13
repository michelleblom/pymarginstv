// Prefix helpers and set orders, against the Python functions.

#include "golden.hpp"

#include "marginstv/prefix.hpp"
#include "marginstv/pyset.hpp"

#include <catch2/catch_test_macros.hpp>

#include <cstdio>
#include <string>

using namespace marginstv;

namespace {

std::string hex(std::span<const std::uint8_t> bytes) {
    std::string out;
    char buf[3];
    for (const auto b : bytes) {
        std::snprintf(buf, sizeof buf, "%02x", b);
        out += buf;
    }
    return out;
}

OrderQ decode_order_q(simdjson::dom::element e) {
    OrderQ q;
    for (const auto pair : e["dict"].get_array()) {
        const auto rng = golden::ints(pair.at(1).value());
        q.push_back({static_cast<int>(pair.at(0).get_int64().value()), rng[0], rng[1]});
    }
    return q;
}

bool same_q(const OrderQ& a, const OrderQ& b) {
    if (a.size() != b.size()) {
        return false;
    }
    for (std::size_t i = 0; i < a.size(); ++i) {
        if (a[i].c != b[i].c || a[i].lo != b[i].lo || a[i].hi != b[i].hi) {
            return false;
        }
    }
    return true;
}

} // namespace

TEST_CASE("large set orders match CPython", "[unit][pyset]") {
    const auto doc = golden::load_json_gz(golden::path("units.json.gz"));
    for (const auto item : doc.root["set_big"].get_array()) {
        PySetOrder s;
        for (const auto c : golden::ints(item["adds"].value())) {
            s.add(c);
        }
        CHECK(s.order() == golden::ints(item["order"].value()));
    }
}

TEST_CASE("prefix helpers match the Python", "[unit][prefix]") {
    const auto doc = golden::load_json_gz(golden::path("units.json.gz"));
    std::size_t checked = 0;
    for (const auto item : doc.root["prefix"].get_array()) {
        const auto ncands = static_cast<int>(item["ncands"].get_int64().value());
        const auto seats = static_cast<int>(item["seats"].get_int64().value());
        const auto order_c = golden::ints(item["order_c"].value());
        const auto order_a = golden::ints(item["order_a"].value());
        const auto rem = golden::ints(item["rem"].value());
        const auto winners = golden::ints(item["winners_iter"].value());

        const auto last = compute_last_round(order_c, order_a, seats, ncands);
        REQUIRE(last == item["last_round"].get_int64().value());

        // The set iteration order recorded from Python, rebuilt here.
        PySetOrder ws;
        for (std::size_t i = 0; i < order_c.size(); ++i) {
            if (order_a[i] == 1) {
                ws.add(order_c[i]);
            }
        }
        CHECK(ws.order() == winners);

        const auto q = get_order_q(order_a, last, winners, order_c);
        CHECK(same_q(q, decode_order_q(item["order_q"].value())));

        const auto m = merge_outcome(order_c, order_a, q, rem, ncands);
        const auto merged = item["merge"].get_array();
        CHECK(m.order_c == golden::ints(merged.at(0).value()));
        CHECK(m.order_a == golden::ints(merged.at(1).value()));
        CHECK(same_q(m.order_q, decode_order_q(merged.at(2).value())));
        for (const auto pair : merged.at(3)["dict"].get_array()) {
            const auto from = pair.at(0).get_int64().value();
            CHECK(m.merge_map[static_cast<std::size_t>(from)] == pair.at(1).get_int64().value());
        }
        CHECK(m.supers == golden::ints(merged.at(4).value()));

        CHECK(hex(canonical_outcome(order_c, order_a, q)) ==
              std::string(item["canonical"].get_string().value()));
        CHECK(hex(outcome_signature(order_c, order_a, q)) ==
              std::string(item["sig_ranges"].get_string().value()));

        OrderQ exact;
        for (std::size_t i = 0; i < order_c.size(); ++i) {
            if (order_a[i] == 1) {
                exact.push_back({order_c[i], static_cast<int>(i), static_cast<int>(i)});
            }
        }
        CHECK(hex(outcome_signature(order_c, order_a, exact)) ==
              std::string(item["sig_exact"].get_string().value()));
        ++checked;
    }
    CHECK(checked == 1500);
}
