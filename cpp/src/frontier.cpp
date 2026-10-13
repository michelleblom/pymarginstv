#include "marginstv/frontier.hpp"

#include <algorithm>
#include <cstring>
#include <limits>

namespace marginstv {

namespace {
// Subsumption tolerance on distances.
constexpr double kEpsilon = 0.9;
} // namespace

TreeNode::TreeNode(std::vector<Cand> oc, std::vector<int> oa, OrderQ oq, EqlbCtx ctx,
                   DispCache dc, PyNum d, PyNum dub)
    : order_c(oc.begin(), oc.end()), order_a(oa.begin(), oa.end()), order_q(std::move(oq)),
      dist(d), dist_ub(dub), eqlbctx(std::move(ctx)), disp_cache(std::move(dc)),
      sig(outcome_signature(oc, oa, order_q)) {}

std::string TreeNode::str() const {
    std::vector<std::vector<Cand>> quotas(order_c.size());
    for (const auto& q : order_q) {
        quotas[static_cast<std::size_t>(std::max(q.hi, 0))].push_back(q.c);
    }
    std::string out;
    for (std::size_t r = 0; r < order_c.size(); ++r) {
        std::string action = order_a[r] == 0 ? "e" : "s";
        if (!quotas[r].empty()) {
            action += " ( ";
            for (const auto c : quotas[r]) {
                action += std::to_string(c) + " ";
            }
            action += ")";
        }
        out += std::to_string(order_c[r]) + action + " ";
    }
    out += "with distance " + dist.str() + "/" + dist_ub.str();
    return out;
}

std::size_t SignatureHash::operator()(const Signature& s) const noexcept {
    std::size_t h = 0;
    std::memcpy(&h, s.data(), sizeof h);
    return h;
}

PyNum Frontier::lower_bound() const {
    if (nodes_.empty()) {
        return PyNum::real(std::numeric_limits<double>::infinity());
    }
    return nodes_.begin()->first;
}

std::vector<NodePtr> Frontier::pop(std::size_t number) {
    std::vector<NodePtr> out;
    while (out.size() < number && !nodes_.empty()) {
        auto it = nodes_.begin();
        out.push_back(std::move(it->second));
        nodes_.erase(it);
    }
    return out;
}

void Frontier::unregister(const TreeNode& node) {
    const auto it = sig_dists_.find(node.sig);
    if (it == sig_dists_.end()) {
        return;
    }
    auto& dl = it->second;
    const auto d = node.dist.as_double();
    const auto pos = std::lower_bound(dl.begin(), dl.end(), d);
    if (pos != dl.end() && *pos == d) {
        dl.erase(pos);
    }
    if (dl.empty()) {
        sig_dists_.erase(it);
    }
}

void Frontier::prune(const PyNum& upperbound, Logger& log) {
    if (nodes_.empty()) {
        return;
    }
    auto first = nodes_.begin();
    std::size_t kept = 0;
    while (first != nodes_.end() && first->first < upperbound) {
        ++first;
        ++kept;
    }
    for (auto it = first; it != nodes_.end(); ++it) {
        if (kept > 0) {
            log.line("Pruning " + it->second->str());
        }
        unregister(*it->second);
    }
    nodes_.erase(first, nodes_.end());
}

bool Frontier::insert(NodePtr node, bool lse) {
    const auto d = node->dist.as_double();
    if (!nodes_.empty()) {
        const auto it = sig_dists_.find(node->sig);
        if (it != sig_dists_.end() && !it->second.empty()) {
            const auto& dl = it->second;
            if (lse) {
                if (d >= dl.front() - kEpsilon) {
                    ++ignore_cntr_;
                    return false;
                }
            } else {
                const auto pos = std::lower_bound(dl.begin(), dl.end(), d - kEpsilon);
                if (pos != dl.end() && *pos <= d + kEpsilon) {
                    ++ignore_cntr_;
                    return false;
                }
            }
        }
    }

    node->id = idcntr_++;
    auto& dl = sig_dists_[node->sig];
    dl.insert(std::upper_bound(dl.begin(), dl.end(), d), d);
    auto key = node->dist;
    nodes_.emplace(key, std::move(node));
    return true;
}

std::string Frontier::str() const {
    std::string out = "--------------------------------------------------\n";
    out += "FRONTIER (" + std::to_string(nodes_.size()) + " nodes)\n";
    if (nodes_.size() > 10) {
        auto it = nodes_.begin();
        for (int i = 0; i < 5; ++i, ++it) {
            out += it->second->str() + '\n';
        }
        out += "...\n";
        auto tail = nodes_.end();
        std::advance(tail, -5);
        for (; tail != nodes_.end(); ++tail) {
            out += tail->second->str() + '\n';
        }
    } else {
        for (const auto& [k, n] : nodes_) {
            out += n->str() + '\n';
        }
    }
    out += "--------------------------------------------------\n";
    return out;
}

} // namespace marginstv
