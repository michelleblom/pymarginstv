#include "marginstv/pyexpr.hpp"

namespace marginstv {

std::size_t TermHash::operator()(const Term& t) const noexcept {
    std::size_t h = 1469598103934665603ULL;
    for (const auto v : t) {
        h ^= static_cast<std::size_t>(v) + 0x9e3779b97f4a7c15ULL + (h << 6) + (h >> 2);
    }
    return h;
}

namespace {

// Term.__mul__: merge two sorted variable lists, taking the left one first
// on a tie.
Term term_mul(const Term& a, const Term& b) {
    if (a.empty()) {
        return b;
    }
    if (b.empty()) {
        return a;
    }
    Term out;
    out.reserve(a.size() + b.size());
    std::size_t i = 0;
    std::size_t j = 0;
    while (i < a.size() && j < b.size()) {
        if (a[i] <= b[j]) {
            out.push_back(a[i++]);
        } else {
            out.push_back(b[j++]);
        }
    }
    while (i < a.size()) {
        out.push_back(a[i++]);
    }
    while (j < b.size()) {
        out.push_back(b[j++]);
    }
    return out;
}

const Term kConst{};

} // namespace

Expr::Expr() { slot(kConst) = 0.0; }

Expr Expr::var(int index) {
    Expr e(true);
    e.slot(Term{index}) = 1.0;
    return e;
}

double& Expr::slot(const Term& t) {
    const auto it = index_.find(t);
    if (it != index_.end()) {
        return terms_[it->second].second;
    }
    index_.emplace(t, terms_.size());
    terms_.emplace_back(t, 0.0);
    return terms_.back().second;
}

const double* Expr::find(const Term& t) const {
    const auto it = index_.find(t);
    return it == index_.end() ? nullptr : &terms_[it->second].second;
}

Expr Expr::add(const Expr& o) const {
    Expr out = *this;
    out.iadd(o);
    return out;
}

Expr Expr::add_num(double c) const {
    Expr out = *this;
    // terms[CONST] = terms.get(CONST, 0.0) + c
    const auto* cur = out.find(kConst);
    const auto base = cur != nullptr ? *cur : 0.0;
    out.slot(kConst) = base + c;
    return out;
}

void Expr::iadd(const Expr& o) {
    for (const auto& [t, c] : o.terms_) {
        const auto* cur = find(t);
        const auto base = cur != nullptr ? *cur : 0.0;
        slot(t) = base + c;
    }
}

Expr Expr::mul(const Expr& o) const {
    Expr out(true);
    for (const auto& [t1, c1] : terms_) {
        for (const auto& [t2, c2] : o.terms_) {
            auto child = term_mul(t1, t2);
            const auto coef = c1 * c2;
            const auto* old = out.find(child);
            if (old != nullptr) {
                const auto v = *old + coef;
                out.slot(child) = v;
            } else {
                out.slot(child) = coef;
            }
        }
    }
    return out;
}

Expr Expr::mul_num(double c) const {
    Expr out(true);
    for (const auto& [t, v] : terms_) {
        out.slot(t) = v * c;
    }
    return out;
}

Expr Expr::neg() const {
    Expr out(true);
    for (const auto& [t, v] : terms_) {
        out.slot(t) = -v;
    }
    return out;
}

double Expr::constant() const {
    const auto* c = find(kConst);
    return c != nullptr ? *c : 0.0;
}

void Expr::normalize() {
    std::vector<std::pair<Term, double>> kept;
    kept.reserve(terms_.size());
    for (auto& [t, c] : terms_) {
        if (c != 0.0) {
            kept.emplace_back(std::move(t), c);
        }
    }
    terms_ = std::move(kept);
    index_.clear();
    for (std::size_t i = 0; i < terms_.size(); ++i) {
        index_.emplace(terms_[i].first, i);
    }
}

std::size_t Expr::degree() const {
    std::size_t d = 0;
    for (const auto& [t, c] : terms_) {
        d = std::max(d, t.size());
    }
    return d;
}

ExprCons make_cons(Expr expr, std::optional<double> lhs, std::optional<double> rhs) {
    // ExprCons.normalize(): c = expr[CONST]; expr -= c; expr.normalize();
    // lhs -= c; rhs -= c.
    const auto c = expr.constant();
    ExprCons out{expr.sub_num(c), lhs, rhs};
    out.expr.normalize();
    if (out.lhs) {
        *out.lhs -= c;
    }
    if (out.rhs) {
        *out.rhs -= c;
    }
    return out;
}

ExprCons le(const Expr& a, const Expr& b) { return make_cons(a.sub(b), std::nullopt, 0.0); }
ExprCons le(const Expr& a, double b) { return make_cons(a, std::nullopt, b); }
ExprCons ge(const Expr& a, const Expr& b) { return make_cons(a.sub(b), 0.0, std::nullopt); }
ExprCons ge(const Expr& a, double b) { return make_cons(a, b, std::nullopt); }
ExprCons eq(const Expr& a, const Expr& b) { return make_cons(a.sub(b), 0.0, 0.0); }
ExprCons eq(const Expr& a, double b) { return make_cons(a, b, b); }

void ExprSlot::iadd(const Expr& e) {
    if (!expr_) {
        // 0 + e: int.__add__ declines, so e.__radd__(0) runs: e + 0.
        expr_ = e.add_num(0.0);
    } else {
        expr_->iadd(e);
    }
}

ExprCons eq(const Expr& a, const ExprSlot& b) {
    if (b.is_zero_int()) {
        return eq(a, 0.0);
    }
    return eq(a, b.expr());
}

} // namespace marginstv
