// Set iteration order, against CPython's.

#include "golden.hpp"

#include "marginstv/pyset.hpp"

#include <catch2/catch_test_macros.hpp>

using namespace marginstv;

TEST_CASE("set iteration order matches CPython 3.9", "[unit][pyset]") {
    const auto doc = golden::load_json_gz(golden::path("units.json.gz"));
    std::size_t checked = 0;
    for (const auto item : doc.root["set_order"].get_array()) {
        PySetOrder s;
        for (const auto c : golden::ints(item["comprehension"].value())) {
            s.add(c);
        }
        CHECK(s.order() == golden::ints(item["order_after_comprehension"].value()));

        auto t = s.copy();
        t.add(static_cast<int>(item["then_copy_add"].get_int64().value()));
        CHECK(t.order() == golden::ints(item["order_after_copy_add"].value()));
        ++checked;
    }
    CHECK(checked == 2000);
}
