#include "marginstv/logger.hpp"

#include <stdexcept>

namespace marginstv {

Logger::Logger(const std::string& path) : out_(path) {
    if (!out_) {
        throw std::runtime_error("cannot open log file " + path);
    }
}

void Logger::line(std::string_view text) {
    if (out_.is_open()) {
        out_ << text << '\n';
    }
}

void Logger::raw(std::string_view text) {
    if (out_.is_open()) {
        out_ << text;
    }
}

void Logger::flush() {
    if (out_.is_open()) {
        out_.flush();
    }
}

} // namespace marginstv
