#include "marginstv/simulate.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <optional>
#include <string>

namespace marginstv {

namespace {

struct Weighted {
    std::size_t ballot;
    PyNum weight;
};

struct SimCandidate {
    const Candidate* info = nullptr;
    PyNum votes = PyNum::integer(0);
    std::vector<Weighted> held;
    bool standing = true;
    int seat = -1;
    std::optional<PyNum> surplus; // empty: no quota yet (Python's -1)
};

class Count {
  public:
    Count(const Election& e, Logger& log) : e_(e), log_(log) {
        for (const auto& c : e.candidates) {
            SimCandidate sc;
            sc.info = &c;
            cands_.push_back(std::move(sc));
        }
    }

    Outcome run(int seats);

  private:
    [[nodiscard]] std::string label(const SimCandidate& c) const {
        return std::to_string(c.info->id) + ", " + c.info->name;
    }

    // First candidate after cnum on the ballot who is standing without a quota.
    [[nodiscard]] int next_candidate(std::size_t ballot, Cand cnum) const;

    // Ordered by surplus, largest first; ties keep the newcomer first.
    static void insert_surplus(std::vector<SimCandidate*>& list, SimCandidate* c) {
        for (std::size_t i = 0; i < list.size(); ++i) {
            if (*c->surplus >= *list[i]->surplus) {
                list.insert(list.begin() + static_cast<std::ptrdiff_t>(i), c);
                return;
            }
        }
        list.push_back(c);
    }

    void transfer(std::vector<std::vector<Weighted>>& moving, const std::string& from,
                  bool log_all);
    void distribute_surplus(SimCandidate& elect);
    void eliminate(SimCandidate& out);
    void record_tallies(int r);

    const Election& e_;
    Logger& log_;
    std::vector<SimCandidate> cands_;
    Outcome out_;
    std::int64_t quota_ = 0;
};

int Count::next_candidate(std::size_t ballot, Cand cnum) const {
    const auto prefs = e_.ballots.prefs(ballot);
    std::size_t idx = 0;
    while (idx < prefs.size() && prefs[idx] != cnum) {
        ++idx;
    }
    for (auto i = idx + 1; i < prefs.size(); ++i) {
        const auto& c = cands_[prefs[i]];
        if (!c.standing || c.surplus) {
            continue;
        }
        return prefs[i];
    }
    return -1;
}

void Count::transfer(std::vector<std::vector<Weighted>>& moving, const std::string& from,
                     bool log_all) {
    for (auto& cand : cands_) {
        auto total = PyNum::integer(0);
        for (const auto& w : moving[static_cast<std::size_t>(cand.info->num)]) {
            const auto value = w.weight * PyNum::integer(e_.ballots.votes(w.ballot));
            cand.votes = cand.votes + value;
            total = total + value;
            cand.held.push_back(w);
        }
        if (log_all || total > PyNum::integer(0)) {
            log_.line(total.str() + " votes distributed from " + from + " to " + cand.info->name);
        }
    }
}

void Count::distribute_surplus(SimCandidate& elect) {
    elect.standing = false;
    if (*elect.surplus < PyNum::real(0.001)) {
        return;
    }
    const auto tvalue = true_div(*elect.surplus, elect.votes);
    log_.line("Transfer value is " + tvalue.str());

    std::vector<std::vector<Weighted>> moving(cands_.size());
    for (const auto& w : elect.held) {
        const auto next = next_candidate(w.ballot, elect.info->num);
        if (next != -1) {
            moving[static_cast<std::size_t>(next)].push_back({w.ballot, tvalue * w.weight});
        }
    }
    transfer(moving, elect.info->name, true);
    elect.votes = elect.votes - *elect.surplus;
    elect.surplus.reset();
}

void Count::eliminate(SimCandidate& out) {
    out.standing = false;
    std::vector<std::vector<Weighted>> moving(cands_.size());
    for (const auto& w : out.held) {
        const auto next = next_candidate(w.ballot, out.info->num);
        if (next != -1) {
            moving[static_cast<std::size_t>(next)].push_back(w);
        }
    }
    out.votes = PyNum::integer(0);
    transfer(moving, out.info->name, false);
}

void Count::record_tallies(int r) {
    const auto n = static_cast<int>(cands_.size());
    if (r == n - 1) {
        return;
    }
    for (const auto& c : cands_) {
        if (c.standing) {
            out_.tallies[static_cast<std::size_t>(c.info->num * n + r + 1)] = c.votes.as_double();
        }
    }
}

Outcome Count::run(int seats) {
    const auto n = static_cast<int>(cands_.size());
    out_.tallies.assign(static_cast<std::size_t>(n) * static_cast<std::size_t>(n), 0.0);

    // Ballots each candidate holds on first preferences, in file order.
    std::vector<std::vector<std::size_t>> first(cands_.size());
    for (std::size_t b = 0; b < e_.ballots.size(); ++b) {
        first[e_.ballots.prefs(b)[0]].push_back(b);
    }

    auto totvotes = PyNum::integer(0);
    log_.line("First preference tallies: ");
    for (auto& cand : cands_) {
        for (const auto b : first[static_cast<std::size_t>(cand.info->num)]) {
            cand.held.push_back({b, PyNum::integer(1)});
            cand.votes = cand.votes + PyNum::integer(e_.ballots.votes(b));
        }
        out_.tallies[static_cast<std::size_t>(cand.info->num * n)] = cand.votes.as_double();
        totvotes = totvotes + cand.votes;
        log_.line("    Candidate " + std::to_string(cand.info->id) + " " + cand.votes.str());
    }

    quota_ = static_cast<std::int64_t>(1.0 + totvotes.as_double() / (seats + 1.0));
    out_.quota = quota_;
    out_.total_votes = totvotes;
    log_.line("The quota for election is " + std::to_string(quota_));
    const auto quota = PyNum::integer(quota_);

    std::vector<SimCandidate*> surpluses;
    int currseat = 0;
    int r = -1;

    auto seat_candidate = [&](SimCandidate& c) {
        c.seat = currseat++;
        c.standing = false;
        out_.order_c.push_back(c.info->num);
        out_.order_a.push_back(1);
        out_.winners.push_back(c.info->num);
    };

    while (currseat < seats) {
        int standing = 0;
        for (auto& cand : cands_) {
            if (cand.standing) {
                ++standing;
            }
            if (cand.surplus || !cand.standing) {
                continue;
            }
            if (cand.votes >= quota) {
                cand.surplus = py_max(PyNum::integer(0), cand.votes - quota);
                insert_surplus(surpluses, &cand);
            }
        }
        if (standing == 0) {
            break;
        }
        r = std::max(0, r);

        if (standing == seats - currseat) {
            surpluses.clear();
            log_.line("Number of candidates left standing equals number of remaining seats");
            std::vector<SimCandidate*> order;
            for (auto& cand : cands_) {
                if (!cand.standing) {
                    continue;
                }
                auto pos = order.size();
                for (std::size_t i = 0; i < order.size(); ++i) {
                    if (cand.votes > order[i]->votes) {
                        pos = i;
                        break;
                    }
                }
                order.insert(order.begin() + static_cast<std::ptrdiff_t>(pos), &cand);
            }
            for (auto* c : order) {
                log_.line("Candidate " + label(*c) + ", elected (votes " + c->votes.str() + ")");
                seat_candidate(*c);
            }
        }

        if (surpluses.empty()) {
            SimCandidate* lowest = nullptr;
            for (auto& cand : cands_) {
                if (cand.standing) {
                    log_.line("Candidate " + label(cand) + ", has " + cand.votes.str() + " votes");
                    if (lowest == nullptr || cand.votes < lowest->votes) {
                        lowest = &cand;
                    }
                }
            }
            if (lowest != nullptr) {
                out_.order_c.push_back(lowest->info->num);
                out_.order_a.push_back(0);
                log_.line("Candidate " + label(*lowest) + ", eliminated on " +
                          lowest->votes.str() + " votes");
                eliminate(*lowest);

                for (auto& cand : cands_) {
                    if (cand.surplus || !cand.standing) {
                        continue;
                    }
                    log_.line("Candidate " + label(cand) + ", has " + cand.votes.str() + " votes");
                    if (cand.votes >= quota) {
                        cand.surplus = py_max(PyNum::integer(0), cand.votes - quota);
                        surpluses.push_back(&cand);
                        log_.line("Candidate " + label(cand) + ", has a quota.");
                    }
                }
            }
            record_tallies(r);
            ++r;
        } else {
            std::vector<SimCandidate*> new_surpluses;
            while (!surpluses.empty()) {
                auto* elect = surpluses.front();
                surpluses.erase(surpluses.begin());
                seat_candidate(*elect);
                log_.line("Candidate " + label(*elect) + ", elected (votes " +
                          elect->votes.str() + ")");
                if (currseat < seats) {
                    distribute_surplus(*elect);
                }

                std::vector<SimCandidate*> next;
                for (auto& cand : cands_) {
                    if (cand.surplus || !cand.standing) {
                        continue;
                    }
                    if (cand.votes >= quota) {
                        cand.surplus = py_max(PyNum::integer(0), cand.votes - quota);
                        insert_surplus(next, &cand);
                    }
                }
                new_surpluses.insert(new_surpluses.end(), next.begin(), next.end());
                record_tallies(r);
                ++r;
            }
            surpluses = std::move(new_surpluses);
        }

        if (currseat == seats) {
            if (static_cast<int>(out_.order_c.size()) != n) {
                for (const auto& cand : cands_) {
                    if (cand.standing) {
                        out_.order_c.push_back(cand.info->num);
                        out_.order_a.push_back(0);
                    }
                }
            }
            break;
        }
    }
    return out_;
}

} // namespace

Outcome simulate_stv(const Election& election, int seats, Logger& log) {
    Count count(election, log);
    return count.run(seats);
}

PyNum compute_weub(const Election& election, const Outcome& outcome) {
    const auto n = election.candidates.size();
    std::vector<bool> seated(n, false);
    std::size_t nseated = 0;
    for (const auto w : outcome.winners) {
        if (!seated[static_cast<std::size_t>(w)]) {
            seated[static_cast<std::size_t>(w)] = true;
            ++nseated;
        }
    }
    std::vector<bool> standing(n, true);
    auto tally = [&](std::size_t c, std::size_t r) { return outcome.tallies[c * n + r]; };

    auto weub = PyNum::real(std::numeric_limits<double>::infinity());
    for (std::size_t r = 0; r < outcome.order_c.size(); ++r) {
        const auto cnum = static_cast<std::size_t>(outcome.order_c[r]);
        standing[cnum] = false;
        if (nseated == 0) {
            break;
        }
        if (outcome.order_a[r] == 1) {
            seated[cnum] = false;
            --nseated;
            continue;
        }
        const auto ctally = tally(cnum, r);
        for (std::size_t w = 0; w < n; ++w) {
            if (!seated[w]) {
                continue;
            }
            const auto wtally = tally(w, r);
            const auto change = py_ceil(wtally - ctally);
            weub = py_min(weub, change);

            const auto halfless = wtally - 0.5 * change.as_double();
            bool use_half = true;
            for (std::size_t s = 0; s < n; ++s) {
                if (!standing[s] || s == w || s == cnum) {
                    continue;
                }
                if (tally(s, r) < halfless) {
                    use_half = false;
                    break;
                }
            }
            if (use_half) {
                weub = py_min(weub, py_ceil(0.5 * change.as_double()));
            }
        }
    }
    return weub;
}

PyNum compute_simple_ub(const Election& election, const Outcome& outcome) {
    auto sub = PyNum::real(std::numeric_limits<double>::infinity());
    for (const auto& c : election.candidates) {
        if (std::find(outcome.winners.begin(), outcome.winners.end(), c.num) ==
            outcome.winners.end()) {
            sub = py_min(sub, PyNum::integer(outcome.quota - c.fp_votes));
        }
    }
    return sub;
}

} // namespace marginstv
