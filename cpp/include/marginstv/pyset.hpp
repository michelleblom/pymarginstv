#pragma once

// The order in which CPython 3.9 iterates a set of small non-negative ints.
//
// The Python program sometimes builds a set of candidate numbers and then
// loops over it, and that order reaches the log (quota maps built by
// get_order_q) or the MINLP model (constraints added per candidate). A set
// iterates in hash-table slot order, which depends on the table size and on
// the order of insertion, so this class replays CPython's table exactly:
// same sizes, same probing, same resizing.

#include <cstdint>
#include <vector>

namespace marginstv {

class PySetOrder {
  public:
    PySetOrder();

    // set.add(key) / a set comprehension adding keys one by one.
    void add(int key);

    // set(other): a new set copied from another set.
    [[nodiscard]] PySetOrder copy() const;

    // The set after a pickle round trip, as when the Python sends it to a
    // worker process: a new set with the keys added in iteration order.
    [[nodiscard]] PySetOrder unpickled() const;

    [[nodiscard]] bool contains(int key) const;
    [[nodiscard]] std::size_t size() const { return used_; }

    // Keys in iteration order.
    [[nodiscard]] std::vector<int> order() const;

  private:
    struct Slot {
        std::int64_t key = -1; // -1: empty
    };

    void resize(std::size_t minused);
    static void insert_clean(std::vector<Slot>& table, std::size_t mask, std::int64_t key);

    std::vector<Slot> table_;
    std::size_t mask_;
    std::size_t fill_ = 0;
    std::size_t used_ = 0;
};

} // namespace marginstv
