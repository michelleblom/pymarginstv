#pragma once

// Election data: candidates, ballots and per-pair ballot summaries, and the
// readers for the three input formats (.txt, .json, .blt).

#include <cstdint>
#include <span>
#include <string>
#include <vector>

namespace marginstv {

// Candidate number in the range 0..N-1 (an index, not the id in the file).
using Cand = int;

// One stored preference.
using Pref = std::uint16_t;

struct Candidate {
    Cand num = 0;
    std::int64_t id = 0;
    std::string name;
    std::int64_t fp_votes = 0; // first preference votes
};

// Every ballot type and its vote count, laid out flat: all rankings in one
// array, in file order. Read-only once loaded and shared by every thread.
class BallotStore {
  public:
    void add(std::int64_t votes, std::span<const Cand> prefs);

    [[nodiscard]] std::size_t size() const { return votes_.size(); }
    [[nodiscard]] std::int64_t votes(std::size_t b) const { return votes_[b]; }
    [[nodiscard]] std::span<const Pref> prefs(std::size_t b) const {
        return {prefs_.data() + offsets_[b], offsets_[b + 1] - offsets_[b]};
    }

    void shrink_to_fit();

  private:
    std::vector<Pref> prefs_;
    std::vector<std::size_t> offsets_{0};
    std::vector<std::int64_t> votes_;
};

// Ballot summaries over the whole election, used by the displacement bound
// for the outcome prefixes of length one.
//   mentions[x]      votes on ballots that rank x
//   above[x][y]      votes on ballots that rank x above y
//   reassign[x][y]   votes on ballots ranking x first and y second
struct BallotMetadata {
    explicit BallotMetadata(int n)
        : ncand(n), mentions(static_cast<std::size_t>(n)),
          above(static_cast<std::size_t>(n) * static_cast<std::size_t>(n)),
          reassign(static_cast<std::size_t>(n) * static_cast<std::size_t>(n)) {}

    int ncand;
    std::vector<std::int64_t> mentions;
    std::vector<std::int64_t> above;
    std::vector<double> reassign;

    void count(std::int64_t votes, std::span<const Cand> prefs);
};

struct Election {
    std::vector<Candidate> candidates;
    BallotStore ballots;
    BallotMetadata metadata{0};
};

// Read a data file, choosing the reader by extension as the Python does.
// Messages the Python readers print go to stdout as well.
Election read_election(const std::string& path);

} // namespace marginstv
