#pragma once

// BLAKE2b hash (RFC 7693), unkeyed, with a chosen digest length. Matches
// Python's hashlib.blake2b(data, digest_size=n).

#include <array>
#include <cstdint>
#include <span>
#include <vector>

namespace marginstv {

std::vector<std::uint8_t> blake2b(std::span<const std::uint8_t> data, std::size_t digest_size);

} // namespace marginstv
