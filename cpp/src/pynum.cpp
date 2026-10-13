#include "marginstv/pynum.hpp"

#include <array>
#include <charconv>
#include <cmath>
#include <cstdio>
#include <stdexcept>
#include <string>

namespace marginstv {

std::string py_int_str(PyInt v) {
    if (v == 0) {
        return "0";
    }
    const auto negative = v < 0;
    std::string digits;
    while (v != 0) {
        const auto d = static_cast<int>(v % 10);
        digits.push_back(static_cast<char>('0' + (negative ? -d : d)));
        v /= 10;
    }
    if (negative) {
        digits.push_back('-');
    }
    return {digits.rbegin(), digits.rend()};
}

std::string py_float_repr(double v) {
    if (std::isnan(v)) {
        return "nan";
    }
    if (std::isinf(v)) {
        return v < 0 ? "-inf" : "inf";
    }

    // Shortest round-trip digits in scientific form, e.g. "1.2345e+02".
    std::array<char, 64> buf{};
    const auto [end, ec] = std::to_chars(buf.data(), buf.data() + buf.size(), v,
                                         std::chars_format::scientific);
    if (ec != std::errc{}) {
        throw std::runtime_error("float formatting failed");
    }
    const std::string_view sci(buf.data(), static_cast<std::size_t>(end - buf.data()));

    std::string out;
    std::size_t pos = 0;
    if (sci[pos] == '-') {
        out.push_back('-');
        ++pos;
    }
    const auto epos = sci.find('e');
    std::string digits;
    for (auto i = pos; i < epos; ++i) {
        if (sci[i] != '.') {
            digits.push_back(sci[i]);
        }
    }
    const auto exponent = std::stoi(std::string(sci.substr(epos + 1)));

    // Python places the decimal point after 'decpt' digits.
    const auto decpt = exponent + 1;
    const auto ndigits = static_cast<int>(digits.size());

    if (decpt <= -4 || decpt > 16) {
        out.push_back(digits[0]);
        if (ndigits > 1) {
            out.push_back('.');
            out.append(digits, 1);
        }
        const auto e = decpt - 1;
        out.push_back('e');
        out.push_back(e < 0 ? '-' : '+');
        const auto mag = std::to_string(std::abs(e));
        if (mag.size() < 2) {
            out.push_back('0');
        }
        out += mag;
    } else if (decpt <= 0) {
        out += "0.";
        out.append(static_cast<std::size_t>(-decpt), '0');
        out += digits;
    } else if (decpt >= ndigits) {
        out += digits;
        out.append(static_cast<std::size_t>(decpt - ndigits), '0');
        out += ".0";
    } else {
        out.append(digits, 0, static_cast<std::size_t>(decpt));
        out.push_back('.');
        out.append(digits, static_cast<std::size_t>(decpt));
    }
    return out;
}

std::string py_fixed(double v, int decimals) {
    if (std::isinf(v)) {
        return v < 0 ? "-inf" : "inf";
    }
    if (std::isnan(v)) {
        return "nan";
    }
    std::array<char, 400> buf{};
    std::snprintf(buf.data(), buf.size(), "%.*f", decimals, v);
    return {buf.data()};
}

std::string PyNum::str() const { return is_int_ ? py_int_str(i_) : py_float_repr(d_); }

std::string py_list_str(const std::vector<int>& values) {
    std::string out = "[";
    for (std::size_t i = 0; i < values.size(); ++i) {
        if (i > 0) {
            out += ", ";
        }
        out += std::to_string(values[i]);
    }
    out += "]";
    return out;
}

PyNum operator+(const PyNum& a, const PyNum& b) {
    if (a.is_int() && b.is_int()) {
        return PyNum::integer(a.as_int() + b.as_int());
    }
    return PyNum::real(a.as_double() + b.as_double());
}

PyNum operator-(const PyNum& a, const PyNum& b) {
    if (a.is_int() && b.is_int()) {
        return PyNum::integer(a.as_int() - b.as_int());
    }
    return PyNum::real(a.as_double() - b.as_double());
}

PyNum operator*(const PyNum& a, const PyNum& b) {
    if (a.is_int() && b.is_int()) {
        return PyNum::integer(a.as_int() * b.as_int());
    }
    return PyNum::real(a.as_double() * b.as_double());
}

PyNum true_div(const PyNum& a, const PyNum& b) {
    return PyNum::real(a.as_double() / b.as_double());
}

bool operator<(const PyNum& a, const PyNum& b) {
    if (a.is_int() && b.is_int()) {
        return a.as_int() < b.as_int();
    }
    return a.as_double() < b.as_double();
}

bool operator==(const PyNum& a, const PyNum& b) {
    if (a.is_int() && b.is_int()) {
        return a.as_int() == b.as_int();
    }
    return a.as_double() == b.as_double();
}

PyNum py_ceil(double v) { return PyNum::integer(static_cast<PyInt>(std::ceil(v))); }

} // namespace marginstv
