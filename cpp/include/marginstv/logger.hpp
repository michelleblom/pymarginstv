#pragma once

// The run log. Only the coordinating thread writes to it, so lines appear
// in the same order as the Python program's.

#include <fstream>
#include <string>
#include <string_view>

namespace marginstv {

class Logger {
  public:
    Logger() = default;
    explicit Logger(const std::string& path);

    [[nodiscard]] bool active() const { return out_.is_open(); }

    // Writes text followed by a newline, as Python's print() does.
    void line(std::string_view text);

    // Writes text with no newline.
    void raw(std::string_view text);

    void flush();

  private:
    std::ofstream out_;
};

} // namespace marginstv
