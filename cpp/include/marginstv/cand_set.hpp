#pragma once

// A set of candidate numbers stored as bits. Used wherever the Python code
// only tests membership, so its iteration order never matters.

#include <bit>
#include <cstdint>
#include <vector>

namespace marginstv {

class CandSet {
  public:
    CandSet() = default;
    explicit CandSet(int n) : words_((static_cast<std::size_t>(n) + 63) / 64, 0) {}

    [[nodiscard]] bool test(int c) const {
        const auto w = static_cast<std::size_t>(c) / 64;
        return w < words_.size() && ((words_[w] >> (static_cast<unsigned>(c) % 64)) & 1U) != 0;
    }
    void set(int c) {
        const auto w = static_cast<std::size_t>(c) / 64;
        if (w >= words_.size()) {
            words_.resize(w + 1, 0);
        }
        words_[w] |= std::uint64_t{1} << (static_cast<unsigned>(c) % 64);
    }
    void merge(const CandSet& other) {
        if (other.words_.size() > words_.size()) {
            words_.resize(other.words_.size(), 0);
        }
        for (std::size_t i = 0; i < other.words_.size(); ++i) {
            words_[i] |= other.words_[i];
        }
    }
    [[nodiscard]] bool empty() const {
        for (const auto w : words_) {
            if (w != 0) {
                return false;
            }
        }
        return true;
    }
    [[nodiscard]] std::size_t count() const {
        std::size_t n = 0;
        for (const auto w : words_) {
            n += static_cast<std::size_t>(std::popcount(w));
        }
        return n;
    }
    [[nodiscard]] const std::vector<std::uint64_t>& words() const { return words_; }

    friend bool operator==(const CandSet& a, const CandSet& b) {
        const auto n = std::max(a.words_.size(), b.words_.size());
        for (std::size_t i = 0; i < n; ++i) {
            const auto x = i < a.words_.size() ? a.words_[i] : 0;
            const auto y = i < b.words_.size() ? b.words_[i] : 0;
            if (x != y) {
                return false;
            }
        }
        return true;
    }

  private:
    std::vector<std::uint64_t> words_;
};

} // namespace marginstv
