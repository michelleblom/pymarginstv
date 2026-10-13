#pragma once

// Polynomial expressions that behave exactly like pyscipopt's Expr.
//
// SCIP's search depends on the order of variables and terms in each
// constraint, and on the exact coefficients. The Python program builds its
// constraints with pyscipopt's operator overloading, which keeps terms in
// insertion order, merges equal terms by adding coefficients, and moves
// constants to the bounds in a particular way. This class repeats each of
// those steps so the C++ model is the same model, term for term.
//
// A term is a product of variables, identified by their creation index
// (Term in pyscipopt keeps them sorted by SCIPvarGetIndex). The empty term
// is the constant.

#include <cstddef>
#include <cstdint>
#include <optional>
#include <unordered_map>
#include <utility>
#include <vector>

namespace marginstv {

using Term = std::vector<int>;

struct TermHash {
    std::size_t operator()(const Term& t) const noexcept;
};

class Expr {
  public:
    // Expr(): only the constant 0.0.
    Expr();
    // A Variable: {Term(v): 1.0}.
    static Expr var(int index);

    // Python operators. 'num' arguments are Python numbers, converted to
    // float as pyscipopt converts them.
    [[nodiscard]] Expr add(const Expr& o) const;  // self + o
    [[nodiscard]] Expr add_num(double c) const;   // self + c
    void iadd(const Expr& o);                     // self += o
    [[nodiscard]] Expr mul(const Expr& o) const;  // self * o
    [[nodiscard]] Expr mul_num(double c) const;   // self * c
    [[nodiscard]] Expr neg() const;               // -self
    [[nodiscard]] Expr sub(const Expr& o) const { return add(o.neg()); }
    [[nodiscard]] Expr sub_num(double c) const { return add_num(-c); }
    [[nodiscard]] Expr rsub_num(double c) const { return mul_num(-1.0).add_num(c); } // c - self

    [[nodiscard]] double constant() const; // self[CONST]
    void normalize();                      // drop zero coefficients
    [[nodiscard]] std::size_t degree() const;

    [[nodiscard]] const std::vector<std::pair<Term, double>>& terms() const { return terms_; }

  private:
    explicit Expr(bool) {}
    double& slot(const Term& t);     // inserts 0.0 at the end if absent
    [[nodiscard]] const double* find(const Term& t) const;

    std::vector<std::pair<Term, double>> terms_;
    std::unordered_map<Term, std::size_t, TermHash> index_;
};

// A constraint lhs <= expr <= rhs after pyscipopt's ExprCons.normalize():
// the constant moved to the bounds and zero terms dropped. A missing bound
// is infinite.
struct ExprCons {
    Expr expr;
    std::optional<double> lhs;
    std::optional<double> rhs;
};

ExprCons make_cons(Expr expr, std::optional<double> lhs, std::optional<double> rhs);

// Python comparisons that build constraints (Expr.__richcmp__).
ExprCons le(const Expr& a, const Expr& b);
ExprCons le(const Expr& a, double b);
ExprCons ge(const Expr& a, const Expr& b);
ExprCons ge(const Expr& a, double b);
ExprCons eq(const Expr& a, const Expr& b);
ExprCons eq(const Expr& a, double b);

// A tally slot that starts as the Python int 0 and becomes an Expr on the
// first addition ('slot += expr').
class ExprSlot {
  public:
    void iadd(const Expr& e);
    [[nodiscard]] bool is_zero_int() const { return !expr_.has_value(); }
    [[nodiscard]] const Expr& expr() const { return *expr_; }

  private:
    std::optional<Expr> expr_;
};

// var == slot, for either state of the slot.
ExprCons eq(const Expr& a, const ExprSlot& b);

} // namespace marginstv
