#include "marginstv/options.hpp"

#include <functional>
#include <map>
#include <stdexcept>

namespace marginstv {

Options parse_options(const std::vector<std::string>& argv) {
    Options o;
    const std::map<std::string, bool*> flags = {
        {"-m", &o.merge},          {"-nopccap", &o.nopccap},     {"-dlb", &o.dlb},
        {"-dlbc", &o.dlbc},        {"-lse", &o.lse},             {"-eqlb", &o.eqlb},
        {"-eqlbc", &o.eqlbc},      {"-prec_et", &o.prec_et},     {"-nominlps", &o.nominlps},
        {"-allminlps", &o.allminlps}, {"-just_sim", &o.just_sim}, {"-useqprefix", &o.useqprefix},
        {"-evalpara", &o.evalpara}, {"--evalpara", &o.evalpara}, {"-sumq", &o.sumq},
        {"-multielim", &o.multielim}, {"-sumnq", &o.sumnq},
    };
    const std::map<std::string, std::function<void(const std::string&)>> values = {
        {"-d", [&](const std::string& v) { o.data = v; }},
        {"-s", [&](const std::string& v) { o.seats = std::stoi(v); }},
        {"-g", [&](const std::string& v) { o.gap = std::stod(v); }},
        {"-agap", [&](const std::string& v) { o.agap = std::stoi(v); }},
        {"-t", [&](const std::string& v) { o.time = std::stoi(v); }},
        {"-thard", [&](const std::string& v) { o.thard = std::stoi(v); }},
        {"-pc", [&](const std::string& v) { o.pc = std::stoi(v); }},
        {"-limit", [&](const std::string& v) { o.limit = std::stoi(v); }},
        {"-displayname", [&](const std::string& v) { o.displayname = v; }},
        {"-ub", [&](const std::string& v) { o.ub = std::stoll(v); }},
        {"-log", [&](const std::string& v) { o.log = v; }},
        {"-threads", [&](const std::string& v) { o.threads = std::stoi(v); }},
    };

    for (std::size_t i = 0; i < argv.size(); ++i) {
        const auto& a = argv[i];
        if (const auto f = flags.find(a); f != flags.end()) {
            *f->second = true;
            continue;
        }
        if (const auto v = values.find(a); v != values.end()) {
            if (i + 1 >= argv.size()) {
                throw std::invalid_argument("argument " + a + ": expected one argument");
            }
            v->second(argv[++i]);
            continue;
        }
        throw std::invalid_argument("unrecognized arguments: " + a);
    }
    if (o.data.empty()) {
        throw std::invalid_argument("-d is required");
    }
    if (o.pc < 1) {
        throw std::invalid_argument("-pc must be at least 1");
    }
    return o;
}

} // namespace marginstv
