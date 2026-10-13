// Python number printing, against Python's own output.

#include "golden.hpp"

#include "marginstv/pynum.hpp"

#include <catch2/catch_test_macros.hpp>

#include <cstdlib>
#include <string>

using namespace marginstv;

TEST_CASE("floats print as Python prints them", "[unit][pyformat]") {
    const auto doc = golden::load_json_gz(golden::path("units.json.gz"));
    std::size_t checked = 0;
    for (const auto item : doc.root["float_str"].get_array()) {
        const std::string hex(item.at(0).get_string().value());
        const auto v = std::strtod(hex.c_str(), nullptr);
        INFO("value " << hex);
        CHECK(py_float_repr(v) == std::string(item.at(1).get_string().value()));
        CHECK(py_fixed(v, 2) == std::string(item.at(2).get_string().value()));
        ++checked;
    }
    CHECK(checked > 3000);
}

TEST_CASE("ints and mixed arithmetic follow Python", "[unit][pyformat]") {
    CHECK(PyNum::integer(5).str() == "5");
    CHECK(PyNum::real(5).str() == "5.0");
    CHECK(PyNum::integer(static_cast<PyInt>(1e20)).str() == "100000000000000000000");
    CHECK((PyNum::integer(2) + PyNum::real(0.5)).str() == "2.5");
    CHECK(true_div(PyNum::integer(1), PyNum::integer(2)).str() == "0.5");
    // max keeps the first argument on a tie, deciding int vs float.
    CHECK(py_max(PyNum::integer(0), PyNum::real(0.0)).str() == "0");
    CHECK(py_max(PyNum::real(0.0), PyNum::integer(0)).str() == "0.0");
    CHECK(py_list_str({1, 2, 3}) == "[1, 2, 3]");
    CHECK(py_list_str({}) == "[]");
}
