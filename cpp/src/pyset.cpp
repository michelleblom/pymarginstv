#include "marginstv/pyset.hpp"

// Follows Objects/setobject.c in CPython 3.9.6. Keys are non-negative ints,
// whose hash is the int itself, and sets here never have keys removed, so
// there are no deleted-slot markers to handle.

namespace marginstv {

namespace {
constexpr std::size_t kMinSize = 8;
constexpr std::size_t kLinearProbes = 9;
constexpr std::size_t kPerturbShift = 5;
} // namespace

PySetOrder::PySetOrder() : table_(kMinSize), mask_(kMinSize - 1) {}

void PySetOrder::insert_clean(std::vector<Slot>& table, std::size_t mask, std::int64_t key) {
    auto perturb = static_cast<std::size_t>(key);
    auto i = static_cast<std::size_t>(key) & mask;
    while (true) {
        if (table[i].key < 0) {
            table[i].key = key;
            return;
        }
        if (i + kLinearProbes <= mask) {
            for (std::size_t j = 1; j <= kLinearProbes; ++j) {
                if (table[i + j].key < 0) {
                    table[i + j].key = key;
                    return;
                }
            }
        }
        perturb >>= kPerturbShift;
        i = (i * 5 + 1 + perturb) & mask;
    }
}

void PySetOrder::resize(std::size_t minused) {
    auto newsize = kMinSize;
    while (newsize <= minused) {
        newsize <<= 1;
    }
    std::vector<Slot> fresh(newsize);
    const auto newmask = newsize - 1;
    for (const auto& slot : table_) {
        if (slot.key >= 0) {
            insert_clean(fresh, newmask, slot.key);
        }
    }
    table_ = std::move(fresh);
    mask_ = newmask;
}

void PySetOrder::add(int key) {
    const auto k = static_cast<std::int64_t>(key);
    auto i = static_cast<std::size_t>(k) & mask_;
    auto perturb = static_cast<std::size_t>(k);
    while (true) {
        const auto probes = (i + kLinearProbes <= mask_) ? kLinearProbes : 0;
        for (std::size_t j = 0; j <= probes; ++j) {
            auto& slot = table_[i + j];
            if (slot.key < 0) {
                slot.key = k;
                ++fill_;
                ++used_;
                if (fill_ * 5 < mask_ * 3) {
                    return;
                }
                resize(used_ > 50000 ? used_ * 2 : used_ * 4);
                return;
            }
            if (slot.key == k) {
                return;
            }
        }
        perturb >>= kPerturbShift;
        i = (i * 5 + 1 + perturb) & mask_;
    }
}

PySetOrder PySetOrder::copy() const {
    // set_merge into a new, empty set.
    PySetOrder out;
    if (used_ == 0) {
        return out;
    }
    if ((out.fill_ + used_) * 5 >= out.mask_ * 3) {
        out.resize((out.used_ + used_) * 2);
    }
    if (out.mask_ == mask_) {
        // Same table size and no deleted slots: slots are copied as they are.
        out.table_ = table_;
    } else {
        for (const auto& slot : table_) {
            if (slot.key >= 0) {
                insert_clean(out.table_, out.mask_, slot.key);
            }
        }
    }
    out.fill_ = used_;
    out.used_ = used_;
    return out;
}

PySetOrder PySetOrder::unpickled() const {
    PySetOrder out;
    for (const auto k : order()) {
        out.add(k);
    }
    return out;
}

bool PySetOrder::contains(int key) const {
    for (const auto& slot : table_) {
        if (slot.key == key) {
            return true;
        }
    }
    return false;
}

std::vector<int> PySetOrder::order() const {
    std::vector<int> out;
    out.reserve(used_);
    for (const auto& slot : table_) {
        if (slot.key >= 0) {
            out.push_back(static_cast<int>(slot.key));
        }
    }
    return out;
}

} // namespace marginstv
