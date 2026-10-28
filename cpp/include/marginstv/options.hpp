#pragma once

// Command line, with the same flags and defaults as pymarginstv.py.

#include <optional>
#include <string>
#include <vector>

namespace marginstv {

struct Options {
    std::string data;                 // -d
    int seats = 0;                    // -s
    double gap = 0.01;                // -g
    int agap = 1;                     // -agap
    bool merge = false;               // -m
    int time = 100;                   // -t
    int thard = 150;                  // -thard
    int pc = 1;                       // -pc: frontier nodes expanded per step
    bool nopccap = false;             // -nopccap: accepted; threads share memory
    int limit = 10000;                // -limit
    bool dlb = false;                 // -dlb
    bool dlbc = false;                // -dlbc
    bool lse = false;                 // -lse
    bool eqlb = false;                // -eqlb
    bool eqlbc = false;               // -eqlbc
    bool prec_et = false;             // -prec_et
    bool nominlps = false;            // -nominlps
    bool allminlps = false;           // -allminlps
    bool just_sim = false;            // -just_sim
    std::optional<std::string> displayname; // -displayname
    std::optional<long long> ub;      // -ub
    bool useqprefix = false;          // -useqprefix
    bool sumq = false;                // -sumq: add up quota shortfalls
    bool multielim = false;           // -multielim: several-candidate elimination bound
    bool sumnq = false;               // -sumnq: add up excesses over the quota
    // -evalpara: both levels of parallelism always run here, but the flag
    // still decides one set order the Python logs (see generate_children).
    bool evalpara = false;
    std::string log;                  // -log
    int threads = 0;                  // -threads: 0 = all cores
};

// Throws std::invalid_argument with a message on a bad command line.
Options parse_options(const std::vector<std::string>& argv);

} // namespace marginstv
