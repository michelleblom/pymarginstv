#include "golden.hpp"

#include <zlib.h>

#include <cstdlib>
#include <filesystem>
#include <sstream>
#include <stdexcept>

namespace golden {

namespace {

std::string read_gz(const std::string& file) {
    gzFile f = gzopen(file.c_str(), "rb");
    if (f == nullptr) {
        throw std::runtime_error("cannot open " + file);
    }
    std::string out;
    std::vector<char> buf(1 << 20);
    int n = 0;
    while ((n = gzread(f, buf.data(), static_cast<unsigned>(buf.size()))) > 0) {
        out.append(buf.data(), static_cast<std::size_t>(n));
    }
    gzclose(f);
    return out;
}

} // namespace

std::string path(const std::string& name) { return std::string(MARGINSTV_GOLDEN_DIR) + "/" + name; }

bool exists(const std::string& name) { return std::filesystem::exists(path(name)); }

Doc load_json_gz(const std::string& file) {
    Doc d;
    d.parser = std::make_unique<simdjson::dom::parser>();
    const auto text = read_gz(file);
    d.root = d.parser->parse(simdjson::padded_string(text));
    return d;
}

JsonLines::JsonLines(const std::string& file) {
    std::istringstream in(read_gz(file));
    std::string line;
    while (std::getline(in, line)) {
        if (!line.empty()) {
            lines_.push_back(line);
        }
    }
}

bool JsonLines::next(simdjson::dom::element& out) {
    if (at_ >= lines_.size()) {
        return false;
    }
    out = parser_.parse(simdjson::padded_string(lines_[at_++]));
    return true;
}

bool is_float(simdjson::dom::element e) { return e.is_object() && e["f"].error() == simdjson::SUCCESS; }

double num(simdjson::dom::element e) {
    if (e.is_int64()) {
        return static_cast<double>(e.get_int64().value());
    }
    if (e.is_uint64()) {
        return static_cast<double>(e.get_uint64().value());
    }
    if (e.is_bool()) {
        return e.get_bool().value() ? 1.0 : 0.0;
    }
    if (e.is_object()) {
        simdjson::dom::element f;
        if (e["f"].get(f) == simdjson::SUCCESS) {
            const std::string s(f.get_string().value());
            return std::strtod(s.c_str(), nullptr);
        }
        if (e["int"].get(f) == simdjson::SUCCESS) {
            const std::string s(f.get_string().value());
            return std::strtod(s.c_str(), nullptr);
        }
    }
    throw std::runtime_error("not a number in golden data");
}

std::vector<int> ints(simdjson::dom::element e) {
    std::vector<int> out;
    for (const auto v : e.get_array()) {
        out.push_back(static_cast<int>(v.get_int64().value()));
    }
    return out;
}

std::vector<double> nums(simdjson::dom::element e) {
    std::vector<double> out;
    for (const auto v : e.get_array()) {
        out.push_back(num(v));
    }
    return out;
}

std::vector<int> set_items(simdjson::dom::element e) {
    if (e.is_object()) {
        return ints(e["set"].value());
    }
    return ints(e);
}

} // namespace golden
