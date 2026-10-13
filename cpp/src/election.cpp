#include "marginstv/election.hpp"

#include <simdjson.h>

#include <fstream>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

namespace marginstv {

void BallotStore::add(std::int64_t votes, std::span<const Cand> prefs) {
    for (const auto p : prefs) {
        if (p < 0 || p > std::numeric_limits<Pref>::max()) {
            throw std::runtime_error("candidate number out of range");
        }
        prefs_.push_back(static_cast<Pref>(p));
    }
    offsets_.push_back(prefs_.size());
    votes_.push_back(votes);
}

void BallotStore::shrink_to_fit() {
    prefs_.shrink_to_fit();
    offsets_.shrink_to_fit();
    votes_.shrink_to_fit();
}

void BallotMetadata::count(std::int64_t votes, std::span<const Cand> prefs) {
    const auto n = static_cast<std::size_t>(ncand);
    for (std::size_t i = 0; i < prefs.size(); ++i) {
        const auto x = static_cast<std::size_t>(prefs[i]);
        mentions[x] += votes;
        for (std::size_t j = i + 1; j < prefs.size(); ++j) {
            above[x * n + static_cast<std::size_t>(prefs[j])] += votes;
        }
    }
    if (prefs.size() > 1) {
        reassign[static_cast<std::size_t>(prefs[0]) * n + static_cast<std::size_t>(prefs[1])] +=
            static_cast<double>(votes);
    }
}

namespace {

std::string_view strip(std::string_view s) {
    const auto* ws = " \t\n\r\f\v";
    const auto b = s.find_first_not_of(ws);
    if (b == std::string_view::npos) {
        return {};
    }
    const auto e = s.find_last_not_of(ws);
    return s.substr(b, e - b + 1);
}

std::vector<std::string_view> split(std::string_view s, char sep) {
    std::vector<std::string_view> out;
    std::size_t start = 0;
    while (true) {
        const auto pos = s.find(sep, start);
        if (pos == std::string_view::npos) {
            out.push_back(s.substr(start));
            return out;
        }
        out.push_back(s.substr(start, pos - start));
        start = pos + 1;
    }
}

std::vector<std::string_view> split_whitespace(std::string_view s) {
    std::vector<std::string_view> out;
    std::size_t i = 0;
    while (i < s.size()) {
        while (i < s.size() && std::isspace(static_cast<unsigned char>(s[i])) != 0) {
            ++i;
        }
        const auto start = i;
        while (i < s.size() && std::isspace(static_cast<unsigned char>(s[i])) == 0) {
            ++i;
        }
        if (i > start) {
            out.push_back(s.substr(start, i - start));
        }
    }
    return out;
}

// Python int() of a string: surrounding whitespace allowed.
std::int64_t to_int(std::string_view s) {
    const auto t = strip(s);
    std::size_t used = 0;
    const auto v = std::stoll(std::string(t), &used);
    if (used != t.size()) {
        throw std::runtime_error("invalid integer: " + std::string(t));
    }
    return v;
}

std::vector<std::string> read_lines(const std::string& path) {
    std::ifstream in(path);
    if (!in) {
        throw std::runtime_error("cannot open " + path);
    }
    std::vector<std::string> lines;
    std::string line;
    while (std::getline(in, line)) {
        lines.push_back(line);
    }
    return lines;
}

void add_ballot(Election& e, std::int64_t votes, const std::vector<Cand>& prefs) {
    e.ballots.add(votes, prefs);
    e.candidates[static_cast<std::size_t>(prefs[0])].fp_votes += votes;
    e.metadata.count(votes, prefs);
}

Election read_txt(const std::string& path) {
    Election e;
    const auto lines = read_lines(path);
    const bool us_version = path.ends_with(".us");

    std::unordered_map<std::int64_t, Cand> cid2num;
    for (const auto tok : split(strip(lines.at(0)), ',')) {
        const auto id = to_int(tok);
        const auto num = static_cast<Cand>(e.candidates.size());
        e.candidates.push_back({num, id, std::to_string(id), 0});
        cid2num[id] = num;
    }
    const auto ncands = static_cast<int>(e.candidates.size());
    e.metadata = BallotMetadata(ncands);

    std::vector<Cand> prefs;
    for (std::size_t i = us_version ? 2 : 5; i < lines.size(); ++i) {
        const auto line = strip(lines[i]);
        auto toks = split(line, ':');
        for (auto& t : toks) {
            t = strip(t);
        }
        // Python takes toks[0][1:-1]: the text inside the brackets.
        auto inner = toks[0];
        inner = inner.size() >= 2 ? inner.substr(1, inner.size() - 2) : std::string_view{};
        prefs.clear();
        for (const auto p : split(inner, ',')) {
            if (!p.empty()) {
                prefs.push_back(cid2num.at(to_int(p)));
            }
        }
        if (prefs.empty()) {
            continue;
        }
        for (const auto p : prefs) {
            if (p == ncands) {
                std::cout << "Invalid canidate number in preferences\n";
            }
        }
        add_ballot(e, to_int(toks.at(1)), prefs);
    }
    return e;
}

Election read_blt(const std::string& path) {
    Election e;
    std::vector<std::string> lines;
    for (const auto& raw : read_lines(path)) {
        const auto s = strip(raw);
        if (!s.empty()) {
            lines.emplace_back(s);
        }
    }

    const auto head = split_whitespace(lines.at(0));
    if (head.size() != 2) {
        throw std::runtime_error("bad .blt header");
    }
    const auto ncands = static_cast<int>(to_int(head[0]));

    std::size_t split_idx = 0;
    while (split_idx < lines.size() && lines[split_idx] != "0") {
        ++split_idx;
    }
    if (split_idx == lines.size()) {
        throw std::runtime_error("no end-of-ballots line in .blt file");
    }

    std::unordered_map<std::int64_t, Cand> cid2num;
    for (int i = 0; i < ncands && split_idx + 1 + static_cast<std::size_t>(i) < lines.size();
         ++i) {
        e.candidates.push_back({i, i + 1, lines[split_idx + 1 + static_cast<std::size_t>(i)], 0});
        cid2num[i + 1] = i;
    }
    e.metadata = BallotMetadata(static_cast<int>(e.candidates.size()));

    std::vector<Cand> prefs;
    for (std::size_t i = 1; i < split_idx; ++i) {
        const auto toks = split_whitespace(lines[i]);
        prefs.clear();
        for (std::size_t t = 1; t + 1 < toks.size(); ++t) {
            prefs.push_back(cid2num.at(to_int(toks[t])));
        }
        add_ballot(e, to_int(toks.at(0)), prefs);
    }
    return e;
}

std::int64_t json_int(simdjson::dom::element el) {
    if (el.is_int64()) {
        return el.get_int64().value();
    }
    if (el.is_uint64()) {
        return static_cast<std::int64_t>(el.get_uint64().value());
    }
    if (el.is_string()) {
        return to_int(el.get_string().value());
    }
    if (el.is_double()) {
        return static_cast<std::int64_t>(el.get_double().value());
    }
    throw std::runtime_error("expected an integer in JSON data");
}

// A missing key, raised as Python's KeyError would be.
struct MissingKey : std::runtime_error {
    using std::runtime_error::runtime_error;
};

simdjson::dom::element at_key(simdjson::dom::element el, const char* key) {
    simdjson::dom::element out;
    if (el.at_key(key).get(out) != simdjson::SUCCESS) {
        throw MissingKey(key);
    }
    return out;
}

Election read_json(const std::string& path) {
    Election e;
    simdjson::dom::parser parser;
    const simdjson::dom::element data = parser.load(path);

    const auto meta = at_key(data, "metadata");
    for (const auto cand : at_key(meta, "candidates").get_array()) {
        const auto num = static_cast<Cand>(e.candidates.size());
        e.candidates.push_back({num, num, std::string(at_key(cand, "name").get_string().value()), 0});
    }
    e.metadata = BallotMetadata(static_cast<int>(e.candidates.size()));

    std::unordered_map<std::int64_t, std::vector<Cand>> groups;
    try {
        std::int64_t pid = 0;
        for (const auto party : at_key(meta, "parties").get_array()) {
            std::vector<Cand> members;
            for (const auto c : at_key(party, "candidates").get_array()) {
                members.push_back(static_cast<Cand>(json_int(c)));
            }
            groups[pid++] = std::move(members);
        }
    } catch (const MissingKey&) {
        std::cout << "No parties or bad data in party lists for candidates.\n";
    }

    std::vector<Cand> prefs;
    try {
        for (const auto atl : at_key(data, "atl").get_array()) {
            const auto n = json_int(at_key(atl, "n"));
            prefs.clear();
            for (const auto g : at_key(atl, "parties").get_array()) {
                const auto it = groups.find(json_int(g));
                if (it == groups.end()) {
                    throw MissingKey("party");
                }
                prefs.insert(prefs.end(), it->second.begin(), it->second.end());
            }
            add_ballot(e, n, prefs);
        }
    } catch (const MissingKey&) {
        std::cout << "No ATL votes or bad data listing ATL parties.\n";
    }

    try {
        for (const auto btl : at_key(data, "btl").get_array()) {
            const auto n = json_int(at_key(btl, "n"));
            prefs.clear();
            for (const auto c : at_key(btl, "candidates").get_array()) {
                prefs.push_back(static_cast<Cand>(json_int(c)));
            }
            add_ballot(e, n, prefs);
        }
    } catch (const MissingKey&) {
        std::cout << "No BTL votes or bad data listing BTL candidates.\n";
    }
    return e;
}

} // namespace

Election read_election(const std::string& path) {
    Election e;
    if (path.ends_with(".blt")) {
        e = read_blt(path);
    } else if (path.ends_with(".json")) {
        e = read_json(path);
    } else {
        e = read_txt(path);
    }
    e.ballots.shrink_to_fit();
    return e;
}

} // namespace marginstv
