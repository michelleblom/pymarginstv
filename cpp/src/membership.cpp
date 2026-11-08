#include "marginstv/membership.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <map>

namespace marginstv {

namespace {

constexpr double kInf = std::numeric_limits<double>::infinity();

// Smallest c with sum of max(0, a - (c - excess)) over gaps at most
// c - deficit, and c >= deficit (shared_lift_lb in membership.py).
double shared_lift_lb(std::vector<double> gaps, double excess, double deficit) {
    std::vector<double> pos;
    for (const auto g : gaps) {
        if (g > 0) {
            pos.push_back(g);
        }
    }
    std::stable_sort(pos.begin(), pos.end(), std::greater<>());
    double best = deficit;
    double total = 0.0;
    double m = 0;
    for (const auto g : pos) {
        m += 1;
        total += g;
        best = std::max(best, (total + m * excess + deficit) / (m + 1));
    }
    return best;
}

// Smallest c for which the additions keeping the OUT candidates above the top
// IN tally plus x's own lift total at most c - deficit (end_lb in
// membership.py), by bisection.
double end_lb(const std::vector<double>& gaps, double own, double need, double excess,
              double deficit) {
    auto fits = [&](double c) {
        if (c < excess || c < deficit) {
            return false;
        }
        const auto low = c - excess;
        double lift = 0;
        for (const auto a : gaps) {
            lift += std::max(0.0, a - low);
        }
        return lift + std::max({0.0, own - low, need}) <= c - deficit;
    };
    double top = std::max({0.0, need, own, excess, deficit});
    for (const auto a : gaps) {
        top = std::max(top, a);
    }
    double hi = top * 3 + excess + deficit + 1.0;
    if (!fits(hi)) {
        return kInf;
    }
    double lo = 0.0;
    if (fits(lo)) {
        return 0.0;
    }
    while (hi - lo > 1e-3 * std::max(1.0, hi)) {
        const auto mid = (lo + hi) / 2;
        if (fits(mid)) {
            hi = mid;
        } else {
            lo = mid;
        }
    }
    return hi;
}

} // namespace

RunState::RunState(int ncand, double quota, int seats_left, std::vector<Cand> standing,
                   const std::vector<std::vector<Cand>>& prefs, const std::vector<double>& values)
    : ncand_(ncand), quota_(quota), seats_left_(seats_left), standing_(std::move(standing)) {
    // Identical rankings move together from here on: merge them, keeping
    // the order in which each first appears.
    std::map<std::vector<Cand>, std::size_t> index;
    for (std::size_t b = 0; b < prefs.size(); ++b) {
        if (prefs[b].empty()) {
            continue;
        }
        const auto [it, fresh] = index.emplace(prefs[b], rows_.size());
        if (fresh) {
            rows_.push_back(prefs[b]);
            w_.push_back(0.0);
        }
        w_[it->second] += values[b];
    }
    t0_.assign(static_cast<std::size_t>(ncand_), 0.0);
    for (std::size_t r = 0; r < rows_.size(); ++r) {
        t0_[static_cast<std::size_t>(rows_[r][0])] += w_[r];
    }
    order_ = standing_;
    std::stable_sort(order_.begin(), order_.end(), [&](Cand a, Cand b) {
        return -t0_[static_cast<std::size_t>(a)] < -t0_[static_cast<std::size_t>(b)];
    });
}

std::vector<double> RunState::tmax(const std::vector<char>& out) const {
    std::vector<double> t(static_cast<std::size_t>(ncand_), 0.0);
    for (std::size_t r = 0; r < rows_.size(); ++r) {
        for (const auto c : rows_[r]) {
            t[static_cast<std::size_t>(c)] += w_[r];
            if (out[static_cast<std::size_t>(c)] != 0) {
                break; // c is the row's first OUT candidate
            }
        }
    }
    return t;
}

void RunState::tmin_flow(const std::vector<char>& in, std::vector<double>& tmin,
                         std::vector<double>& flow) const {
    const auto n = static_cast<std::size_t>(ncand_);
    tmin.assign(n, 0.0);
    flow.assign(n * n, 0.0);
    for (std::size_t r = 0; r < rows_.size(); ++r) {
        const auto& row = rows_[r];
        std::size_t h = 0;
        while (h < row.size() && in[static_cast<std::size_t>(row[h])] != 0) {
            ++h;
        }
        if (h == row.size()) {
            continue;
        }
        const auto x = static_cast<std::size_t>(row[h]);
        tmin[x] += w_[r];
        for (std::size_t j = 0; j < h; ++j) {
            flow[static_cast<std::size_t>(row[j]) * n + x] += w_[r];
        }
    }
}

double RunState::lb(const std::vector<Cand>& in, const std::vector<Cand>& out, double floor,
                    double deficit, bool sumnq, bool elimnq, int depth) const {
    const auto q = quota_;
    if (static_cast<int>(standing_.size()) - static_cast<int>(in.size()) < seats_left_) {
        return kInf; // few
    }
    std::vector<char> out_mask(static_cast<std::size_t>(ncand_), 0);
    for (const auto d : out) {
        out_mask[static_cast<std::size_t>(d)] = 1;
    }
    std::vector<char> in_mask(static_cast<std::size_t>(ncand_), 0);
    for (const auto c : in) {
        in_mask[static_cast<std::size_t>(c)] = 1;
    }
    const auto tm = tmax(out_mask);
    auto at = [](const std::vector<double>& v, Cand c) { return v[static_cast<std::size_t>(c)]; };

    double best = deficit;
    std::vector<std::pair<Cand, double>> gaps; // in candidate order
    double excess = 0.0;
    if (!in.empty()) {
        // Q: nobody holds a quota when the first elimination happens.
        double most = -kInf;
        double over_sum = 0.0;
        for (const auto c : standing_) {
            const auto e = at(t0_, c) - q;
            most = std::max(most, e);
            if (e > 0) {
                over_sum += e;
            }
        }
        best = std::max(best, most);
        if (sumnq) {
            best = std::max(best, over_sum);
        }
        double top = -kInf;
        for (const auto c : in) {
            top = std::max(top, at(t0_, c));
        }
        if (!out.empty()) {
            std::vector<double> gv;
            for (const auto d : out) {
                gaps.emplace_back(d, top - at(tm, d));
                gv.push_back(top - at(tm, d));
            }
            if (elimnq) {
                for (const auto d : out) {
                    excess += std::max(0.0, at(t0_, d) - q);
                }
            }
            best = std::max(best, shared_lift_lb(gv, excess, deficit)); // E+
            // E+ again for IN's largest candidates l, with l still standing.
            std::vector<Cand> by_tally = in;
            std::stable_sort(by_tally.begin(), by_tally.end(), [&](Cand a, Cand b) {
                const auto ta = at(t0_, a);
                const auto tb = at(t0_, b);
                return -ta < -tb || (-ta == -tb && a < b);
            });
            const auto k = std::min<std::size_t>(by_tally.size(),
                                                 static_cast<std::size_t>(std::max(depth, 0)));
            for (std::size_t li = 0; li < k; ++li) {
                const auto l = by_tally[li];
                auto mask_l = out_mask;
                mask_l[static_cast<std::size_t>(l)] = 1;
                const auto tl = tmax(mask_l);
                std::vector<double> gl;
                for (const auto d : out) {
                    gl.push_back(at(t0_, l) - at(tl, d));
                }
                best = std::max(best, shared_lift_lb(gl, excess, deficit));
            }
            // M, only when it could raise the bound.
            bool try_m = false;
            for (const auto x : out) {
                if (at(tm, x) - q > std::max(best, floor)) {
                    try_m = true;
                    break;
                }
            }
            if (try_m) {
                std::vector<double> tmin;
                std::vector<double> flow;
                tmin_flow(in_mask, tmin, flow);
                const auto n = static_cast<std::size_t>(ncand_);
                for (const auto x : out) {
                    double fmax = -kInf;
                    for (const auto l : in) {
                        fmax = std::max(fmax, flow[static_cast<std::size_t>(l) * n +
                                                   static_cast<std::size_t>(x)]);
                    }
                    best = std::max(best, at(tmin, x) - fmax - q);
                }
            }
        }
    }
    if (static_cast<int>(out.size()) > seats_left_) { // S+
        double least = kInf;
        for (const auto x : standing_) {
            if (in_mask[static_cast<std::size_t>(x)] != 0) {
                continue;
            }
            std::vector<double> others;
            double own = -kInf;
            for (const auto& [d, a] : gaps) {
                if (d == x) {
                    own = a;
                } else {
                    others.push_back(a);
                }
            }
            least = std::min(least, end_lb(others, own, q - at(tm, x), excess, deficit));
        }
        best = std::max(best, least);
    }
    return best;
}

void RunState::disp_costs(const CandSet& reported) const {
    std::call_once(disp_once_, [&] {
        const auto n = static_cast<std::size_t>(ncand_);
        std::vector<double> present(n, 0.0);
        for (std::size_t r = 0; r < rows_.size(); ++r) {
            for (const auto c : rows_[r]) {
                present[static_cast<std::size_t>(c)] += w_[r];
            }
        }
        // above[r][y]: rows ranking r above y.
        std::vector<std::vector<double>> above(n);
        for (const auto r : standing_) {
            auto& row_above = above[static_cast<std::size_t>(r)];
            row_above.assign(n, 0.0);
            for (std::size_t b = 0; b < rows_.size(); ++b) {
                bool seen = false;
                for (const auto c : rows_[b]) {
                    if (seen) {
                        row_above[static_cast<std::size_t>(c)] += w_[b];
                    } else if (c == r) {
                        seen = true;
                    }
                }
            }
        }
        disp_winner_.assign(n, 0);
        disp_any_winner_ = false;
        for (const auto c : standing_) {
            if (reported.test(c)) {
                disp_winner_[static_cast<std::size_t>(c)] = 1;
                disp_any_winner_ = true;
            }
        }
        const auto need = static_cast<int>(standing_.size()) - seats_left_;
        disp_cost_.assign(n, std::numeric_limits<double>::quiet_NaN());
        for (const auto l : standing_) {
            if (reported.test(l)) {
                continue;
            }
            const auto li = static_cast<std::size_t>(l);
            std::vector<double> dps;
            double disp = kInf;
            for (const auto r : standing_) {
                if (r == l) {
                    continue;
                }
                const auto ri = static_cast<std::size_t>(r);
                const auto dp = std::max(0.0, 0.5 * (t0_[ri] - (present[li] - above[ri][li])));
                dps.push_back(dp);
                if (reported.test(r)) {
                    disp = std::min(disp, dp);
                }
            }
            std::sort(dps.begin(), dps.end());
            double left_end = 0.0;
            if (need > 0 && !dps.empty()) {
                const auto upto = std::min<std::size_t>(dps.size(), static_cast<std::size_t>(need));
                left_end = dps[0];
                for (std::size_t i = 0; i < upto; ++i) {
                    left_end = std::max(left_end, dps[i]);
                }
            }
            const auto quota_cost = std::max(0.0, quota_ - present[li]);
            disp_cost_[li] = std::max(disp, std::min(quota_cost, left_end));
        }
    });
}

double RunState::dlb(const std::vector<Cand>& in, const CandSet& reported, bool changed) const {
    if (changed) {
        return 0.0;
    }
    disp_costs(reported);
    if (!disp_any_winner_) {
        return 0.0;
    }
    for (const auto c : in) {
        if (disp_winner_[static_cast<std::size_t>(c)] != 0) {
            return 0.0;
        }
    }
    std::vector<char> in_mask(static_cast<std::size_t>(ncand_), 0);
    for (const auto c : in) {
        in_mask[static_cast<std::size_t>(c)] = 1;
    }
    double least = kInf;
    for (const auto l : standing_) {
        const auto li = static_cast<std::size_t>(l);
        if (std::isnan(disp_cost_[li]) || in_mask[li] != 0) {
            continue;
        }
        least = std::min(least, disp_cost_[li]);
    }
    return least;
}

} // namespace marginstv
