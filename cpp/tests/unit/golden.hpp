#pragma once

// Loading the golden data written by tests/golden/dump_golden.py.

#include <simdjson.h>

#include <memory>
#include <string>
#include <vector>

namespace golden {

// Parsed JSON document kept alive with its parser.
struct Doc {
    std::unique_ptr<simdjson::dom::parser> parser;
    simdjson::dom::element root;
};

// Whole gzipped JSON file.
Doc load_json_gz(const std::string& path);

// Each line of a gzipped JSON-lines file, parsed one at a time.
class JsonLines {
  public:
    explicit JsonLines(const std::string& path);
    // False at end of file.
    bool next(simdjson::dom::element& out);

  private:
    std::vector<std::string> lines_;
    std::size_t at_ = 0;
    simdjson::dom::parser parser_;
};

std::string path(const std::string& name);
bool exists(const std::string& name);

// Decoders for dump_golden.py's encoding.
double num(simdjson::dom::element e);            // int or {"f": hex}
bool is_float(simdjson::dom::element e);         // {"f": ...}
std::vector<int> ints(simdjson::dom::element e); // list of ints
std::vector<double> nums(simdjson::dom::element e);
// Python set or list of ints, in stored order.
std::vector<int> set_items(simdjson::dom::element e);

} // namespace golden
