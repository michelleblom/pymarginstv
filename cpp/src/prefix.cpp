#include "marginstv/prefix.hpp"

#include "marginstv/blake2b.hpp"

#include <algorithm>
#include <stdexcept>
#include <unordered_map>

namespace marginstv {

const QEntry* find_q(const OrderQ& q, Cand c) {
    for (const auto& e : q) {
        if (e.c == c) {
            return &e;
        }
    }
    return nullptr;
}

std::string order_q_str(const OrderQ& q) {
    std::string out = "{";
    for (std::size_t i = 0; i < q.size(); ++i) {
        if (i > 0) {
            out += ", ";
        }
        out += std::to_string(q[i].c) + ": (" + std::to_string(q[i].lo) + ", " +
               std::to_string(q[i].hi) + ")";
    }
    out += "}";
    return out;
}

int compute_last_round(std::span<const Cand> order_c, std::span<const int> order_a, int seats,
                       int ncands) {
    int c_cntr = 0;
    int s_cntr = 0;
    int last_round = 0;
    const auto loc = static_cast<int>(order_c.size());
    for (int r = 0; r < loc; ++r) {
        ++c_cntr;
        if (order_a[static_cast<std::size_t>(r)] == 1) {
            ++s_cntr;
        }
        if (s_cntr == seats) {
            break;
        }
        if (ncands - c_cntr == seats - s_cntr) {
            break;
        }
        ++last_round;
    }
    return std::min(loc - 1, last_round);
}

OrderQ get_order_q(std::span<const int> order_a, int last_round,
                   std::span<const Cand> winners_in_set_order, std::span<const Cand> order_c) {
    OrderQ out;
    for (const auto w : winners_in_set_order) {
        // Python's order_c_index dict maps each candidate to its last index.
        int pos = -1;
        for (std::size_t i = 0; i < order_c.size(); ++i) {
            if (order_c[i] == w) {
                pos = static_cast<int>(i);
            }
        }
        if (pos == -1) {
            throw std::runtime_error("winner missing from outcome prefix");
        }
        if (pos > last_round) {
            continue;
        }
        auto minrq = pos - 1;
        const auto maxrq = pos - 1;
        for (auto r = pos - 1; r >= 0; --r) {
            if (order_a[static_cast<std::size_t>(r)] == 1) {
                --minrq;
            } else {
                break;
            }
        }
        out.push_back({w, minrq, maxrq});
    }
    return out;
}

namespace {

struct MergeState {
    MergedOutcome out;
    std::vector<std::vector<Cand>> segments;
};

void add_elim_sequence(const std::vector<Cand>& seq, MergeState& s, bool merge_all) {
    const auto le = seq.size();
    auto& m = s.out;
    if (merge_all && le > 1) {
        const auto mc = seq[0];
        m.order_c.push_back(mc);
        m.order_a.push_back(0);
        s.segments.push_back(seq);
        m.supers.push_back(mc);
        for (const auto e : seq) {
            m.merge_map[static_cast<std::size_t>(e)] = mc;
        }
    } else if (le < 3) {
        for (const auto e : seq) {
            m.order_c.push_back(e);
            m.order_a.push_back(0);
            m.merge_map[static_cast<std::size_t>(e)] = e;
            s.segments.push_back({e});
        }
    } else {
        auto mc = seq[0];
        m.merge_map[static_cast<std::size_t>(mc)] = mc;
        m.order_c.push_back(mc);
        m.order_a.push_back(0);
        s.segments.emplace_back(seq.begin(), seq.end() - 1);
        m.supers.push_back(mc);
        for (std::size_t i = 0; i + 1 < le; ++i) {
            m.merge_map[static_cast<std::size_t>(seq[i])] = mc;
        }
        mc = seq.back();
        m.merge_map[static_cast<std::size_t>(mc)] = mc;
        s.segments.push_back({mc});
        m.order_c.push_back(mc);
        m.order_a.push_back(0);
    }
}

} // namespace

MergedOutcome merge_outcome(std::span<const Cand> order_c, std::span<const int> order_a,
                            const OrderQ& order_q, std::span<const Cand> rem, int ncands) {
    MergeState s;
    s.out.merge_map.assign(static_cast<std::size_t>(ncands), -1);
    std::vector<Cand> elim_seq;
    for (std::size_t i = 0; i < order_a.size(); ++i) {
        const auto ci = order_c[i];
        if (order_a[i] == 1) {
            if (!elim_seq.empty()) {
                add_elim_sequence(elim_seq, s, true);
                elim_seq.clear();
            }
            s.out.order_c.push_back(ci);
            s.out.order_a.push_back(1);
            s.out.merge_map[static_cast<std::size_t>(ci)] = ci;
            s.segments.push_back({ci});
        } else {
            elim_seq.push_back(ci);
        }
    }
    if (!elim_seq.empty()) {
        add_elim_sequence(elim_seq, s, false);
    }

    // Old round number -> merged round number; -1 stays -1.
    std::unordered_map<int, int> round_conv{{-1, -1}};
    int j = 0;
    for (std::size_t r = 0; r < s.segments.size(); ++r) {
        for (std::size_t k = 0; k < s.segments[r].size(); ++k) {
            round_conv[j++] = static_cast<int>(r);
        }
    }
    for (const auto& q : order_q) {
        s.out.order_q.push_back({q.c, round_conv.at(q.lo), round_conv.at(q.hi)});
    }
    for (const auto r : rem) {
        s.out.merge_map[static_cast<std::size_t>(r)] = r;
    }
    return std::move(s.out);
}

std::vector<std::uint8_t> canonical_outcome(std::span<const Cand> order_c,
                                            std::span<const int> order_a, const OrderQ& order_q) {
    std::vector<std::uint8_t> out;
    auto put = [&out](std::int32_t v) {
        const auto u = static_cast<std::uint32_t>(v);
        for (int k = 0; k < 4; ++k) {
            out.push_back(static_cast<std::uint8_t>(u >> (8 * k)));
        }
    };
    auto emit = [&put](const std::vector<std::int32_t>& values) {
        put(static_cast<std::int32_t>(values.size()));
        for (const auto v : values) {
            put(v);
        }
    };

    std::vector<std::int32_t> block;
    for (std::size_t i = 0; i < order_c.size(); ++i) {
        if (order_a[i] == 1) {
            std::sort(block.begin(), block.end());
            emit(block);
            emit({order_c[i]});
            block.clear();
        } else {
            block.push_back(order_c[i]);
        }
    }
    std::sort(block.begin(), block.end());
    emit(block);

    auto sorted_q = order_q;
    std::sort(sorted_q.begin(), sorted_q.end(),
              [](const QEntry& a, const QEntry& b) { return a.c < b.c; });
    std::vector<std::int32_t> quotas;
    for (const auto& q : sorted_q) {
        quotas.push_back(q.c);
        quotas.push_back(q.lo);
        quotas.push_back(q.hi);
    }
    emit(quotas);
    return out;
}

Signature outcome_signature(std::span<const Cand> order_c, std::span<const int> order_a,
                            const OrderQ& order_q) {
    const auto bytes = canonical_outcome(order_c, order_a, order_q);
    const auto digest = blake2b(bytes, 16);
    Signature sig{};
    std::copy(digest.begin(), digest.end(), sig.begin());
    return sig;
}

} // namespace marginstv
