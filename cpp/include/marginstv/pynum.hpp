#pragma once

// Numbers and text formatting that behave exactly like Python's.
//
// The log prints values with Python's str(). Python prints an int and a
// float of equal value differently ("5" vs "5.0"), so values that reach the
// log carry whether they are an int or a float, and arithmetic on them
// follows Python's rules for mixing the two.

#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

namespace marginstv {

// Wide enough for the largest int the Python program prints: SCIP's
// infinity (1e20) converted to an int.
using PyInt = __int128;

class PyNum {
  public:
    PyNum() = default;

    static PyNum integer(PyInt v) {
        PyNum n;
        n.is_int_ = true;
        n.i_ = v;
        return n;
    }

    static PyNum real(double v) {
        PyNum n;
        n.is_int_ = false;
        n.d_ = v;
        return n;
    }

    [[nodiscard]] bool is_int() const { return is_int_; }
    [[nodiscard]] PyInt as_int() const { return is_int_ ? i_ : static_cast<PyInt>(d_); }
    [[nodiscard]] double as_double() const { return is_int_ ? static_cast<double>(i_) : d_; }

    // Python str() of the value.
    [[nodiscard]] std::string str() const;

  private:
    bool is_int_ = true;
    PyInt i_ = 0;
    double d_ = 0.0;
};

PyNum operator+(const PyNum& a, const PyNum& b);
PyNum operator-(const PyNum& a, const PyNum& b);
PyNum operator*(const PyNum& a, const PyNum& b);
// Python true division: always a float.
PyNum true_div(const PyNum& a, const PyNum& b);

// Numeric comparisons, as Python compares an int with a float.
bool operator<(const PyNum& a, const PyNum& b);
bool operator==(const PyNum& a, const PyNum& b);
inline bool operator>(const PyNum& a, const PyNum& b) { return b < a; }
inline bool operator<=(const PyNum& a, const PyNum& b) { return !(b < a); }
inline bool operator>=(const PyNum& a, const PyNum& b) { return !(a < b); }
inline bool operator!=(const PyNum& a, const PyNum& b) { return !(a == b); }

// Python's max(a, b) and min(a, b): on a tie the first argument is kept,
// which decides whether the result is an int or a float.
inline PyNum py_max(const PyNum& a, const PyNum& b) { return b > a ? b : a; }
inline PyNum py_min(const PyNum& a, const PyNum& b) { return b < a ? b : a; }

// Python's math.ceil: always an int.
PyNum py_ceil(double v);

// Python str()/repr() of a float: shortest digits that read back exactly.
std::string py_float_repr(double v);

// Python's "{:.Nf}".format(v).
std::string py_fixed(double v, int decimals);

// Python str() of an int.
std::string py_int_str(PyInt v);

// Python str() of a list of ints: "[1, 2, 3]".
std::string py_list_str(const std::vector<int>& values);

// Python str() of a bool.
inline std::string_view py_bool(bool b) { return b ? "True" : "False"; }

} // namespace marginstv
