#include "marginstv/blake2b.hpp"

#include <algorithm>
#include <array>
#include <cstring>
#include <stdexcept>

namespace marginstv {

namespace {

constexpr std::array<std::uint64_t, 8> kIv = {
    0x6a09e667f3bcc908ULL, 0xbb67ae8584caa73bULL, 0x3c6ef372fe94f82bULL, 0xa54ff53a5f1d36f1ULL,
    0x510e527fade682d1ULL, 0x9b05688c2b3e6c1fULL, 0x1f83d9abfb41bd6bULL, 0x5be0cd19137e2179ULL};

constexpr std::array<std::array<std::uint8_t, 16>, 12> kSigma = {{
    {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15},
    {14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3},
    {11, 8, 12, 0, 5, 2, 15, 13, 10, 14, 3, 6, 7, 1, 9, 4},
    {7, 9, 3, 1, 13, 12, 11, 14, 2, 6, 5, 10, 4, 0, 15, 8},
    {9, 0, 5, 7, 2, 4, 10, 15, 14, 1, 11, 12, 6, 8, 3, 13},
    {2, 12, 6, 10, 0, 11, 8, 3, 4, 13, 7, 5, 15, 14, 1, 9},
    {12, 5, 1, 15, 14, 13, 4, 10, 0, 7, 6, 3, 9, 2, 8, 11},
    {13, 11, 7, 14, 12, 1, 3, 9, 5, 0, 15, 4, 8, 6, 2, 10},
    {6, 15, 14, 9, 11, 3, 0, 8, 12, 2, 13, 7, 1, 4, 10, 5},
    {10, 2, 8, 4, 7, 6, 1, 5, 15, 11, 9, 14, 3, 12, 13, 0},
    {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15},
    {14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3},
}};

constexpr std::uint64_t rotr(std::uint64_t x, int n) { return (x >> n) | (x << (64 - n)); }

void mix(std::array<std::uint64_t, 16>& v, int a, int b, int c, int d, std::uint64_t x,
         std::uint64_t y) {
    v[a] = v[a] + v[b] + x;
    v[d] = rotr(v[d] ^ v[a], 32);
    v[c] = v[c] + v[d];
    v[b] = rotr(v[b] ^ v[c], 24);
    v[a] = v[a] + v[b] + y;
    v[d] = rotr(v[d] ^ v[a], 16);
    v[c] = v[c] + v[d];
    v[b] = rotr(v[b] ^ v[c], 63);
}

void compress(std::array<std::uint64_t, 8>& h, const std::uint8_t* block, std::uint64_t count,
              bool last) {
    std::array<std::uint64_t, 16> m{};
    for (int i = 0; i < 16; ++i) {
        std::uint64_t w = 0;
        for (int j = 7; j >= 0; --j) {
            w = (w << 8) | block[i * 8 + j];
        }
        m[i] = w;
    }
    std::array<std::uint64_t, 16> v{};
    for (int i = 0; i < 8; ++i) {
        v[i] = h[i];
        v[i + 8] = kIv[i];
    }
    v[12] ^= count;
    if (last) {
        v[14] = ~v[14];
    }
    for (const auto& s : kSigma) {
        mix(v, 0, 4, 8, 12, m[s[0]], m[s[1]]);
        mix(v, 1, 5, 9, 13, m[s[2]], m[s[3]]);
        mix(v, 2, 6, 10, 14, m[s[4]], m[s[5]]);
        mix(v, 3, 7, 11, 15, m[s[6]], m[s[7]]);
        mix(v, 0, 5, 10, 15, m[s[8]], m[s[9]]);
        mix(v, 1, 6, 11, 12, m[s[10]], m[s[11]]);
        mix(v, 2, 7, 8, 13, m[s[12]], m[s[13]]);
        mix(v, 3, 4, 9, 14, m[s[14]], m[s[15]]);
    }
    for (int i = 0; i < 8; ++i) {
        h[i] ^= v[i] ^ v[i + 8];
    }
}

} // namespace

std::vector<std::uint8_t> blake2b(std::span<const std::uint8_t> data, std::size_t digest_size) {
    if (digest_size == 0 || digest_size > 64) {
        throw std::invalid_argument("blake2b digest size must be 1..64");
    }
    auto h = kIv;
    h[0] ^= 0x01010000ULL ^ digest_size;

    // Every block but the last is compressed as it fills; the last block
    // (possibly the only one, possibly empty) is padded with zeros.
    std::array<std::uint8_t, 128> block{};
    std::uint64_t count = 0;
    std::size_t offset = 0;
    while (data.size() - offset > 128) {
        count += 128;
        compress(h, data.data() + offset, count, false);
        offset += 128;
    }
    const auto rest = data.size() - offset;
    if (rest > 0) {
        std::memcpy(block.data(), data.data() + offset, rest);
    }
    count += rest;
    compress(h, block.data(), count, true);

    std::vector<std::uint8_t> out(digest_size);
    for (std::size_t i = 0; i < digest_size; ++i) {
        out[i] = static_cast<std::uint8_t>(h[i / 8] >> (8 * (i % 8)));
    }
    return out;
}

} // namespace marginstv
