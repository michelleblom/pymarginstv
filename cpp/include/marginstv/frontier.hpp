#pragma once

// Search tree nodes and the frontier of unexpanded nodes (TreeNode and
// Frontier in stvtree.py).

#include "marginstv/bounds_disp.hpp"
#include "marginstv/bounds_eqlb.hpp"
#include "marginstv/logger.hpp"
#include "marginstv/prefix.hpp"
#include "marginstv/pynum.hpp"

#include <cstdint>
#include <map>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

namespace marginstv {

struct TreeNode {
    TreeNode(std::vector<Cand> order_c, std::vector<int> order_a, OrderQ order_q, EqlbCtx eqlbctx,
             DispCache disp_cache, PyNum dist, PyNum dist_ub);

    std::uint64_t id = 0;
    std::vector<Pref> order_c;
    std::vector<std::uint8_t> order_a;
    OrderQ order_q;
    PyNum dist;
    PyNum dist_ub;
    EqlbCtx eqlbctx;
    DispCache disp_cache;
    Signature sig;

    [[nodiscard]] std::vector<Cand> order_c_list() const { return {order_c.begin(), order_c.end()}; }
    [[nodiscard]] std::vector<int> order_a_list() const { return {order_a.begin(), order_a.end()}; }

    // Python str(TreeNode): "3e 7s ( 7 ) with distance 0/0".
    [[nodiscard]] std::string str() const;
};

using NodePtr = std::unique_ptr<TreeNode>;

struct PyNumLess {
    bool operator()(const PyNum& a, const PyNum& b) const { return a < b; }
};

struct SignatureHash {
    std::size_t operator()(const Signature& s) const noexcept;
};

class Frontier {
  public:
    [[nodiscard]] std::size_t size() const { return nodes_.size(); }
    [[nodiscard]] PyNum lower_bound() const;

    // Removes and returns up to 'number' nodes with the smallest distance.
    std::vector<NodePtr> pop(std::size_t number);

    // Drops every node whose distance is at least 'upperbound'.
    void prune(const PyNum& upperbound, Logger& log);

    // Inserts a node unless an equivalent node already covers it.
    // Returns false when the node was subsumed.
    bool insert(NodePtr node, bool lse);

    [[nodiscard]] std::string str() const;

    [[nodiscard]] std::uint64_t ignore_count() const { return ignore_cntr_; }
    [[nodiscard]] std::uint64_t agg_prune_count() const { return agg_prune_cntr_; }

  private:
    void unregister(const TreeNode& node);

    // Ordered by distance; equal distances keep insertion order.
    std::multimap<PyNum, NodePtr, PyNumLess> nodes_;
    // Distances of every node inserted and not pruned, per signature.
    std::unordered_map<Signature, std::vector<double>, SignatureHash> sig_dists_;
    std::uint64_t idcntr_ = 0;
    std::uint64_t ignore_cntr_ = 0;
    std::uint64_t agg_prune_cntr_ = 0;
};

} // namespace marginstv
