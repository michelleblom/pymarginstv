"""
Build reference_runs.csv: one row per log in 15PC_logs, giving everything
needed to rerun it (data file, seats, flags, upper bound) and how it ended.

Usage: python3 make_manifest.py [--logs DIR] [--out FILE]
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, REPO)

import run_experiments as rx  # noqa: E402

# Flags per version in the current run_experiments.py (Scotland, Ireland,
# Minneapolis references). Version 10 is omitted: it never produced a log.
CURRENT_MAPPING = {
    3: "-lse -eqlb -dlb",
    4: "-dlb -eqlb",
    5: "-eqlb -lse",
    6: "-eqlb",
    7: "-dlb",
    8: "-lse -eqlbc -dlbc -prec_et",
    9: "-dlbc -eqlbc -prec_et",
    11: "-eqlbc -prec_et",
    12: "-dlbc -prec_et",
    13: "-lse -eqlbc -dlbc -useqprefix -prec_et",
    14: "-lse -eqlbc -dlbc -useqprefix -prec_et -nominlps",
    15: "-lse -useqprefix",
}
CURRENT_LIMIT = 10000

# Flags per version for the FedAus references, which predate the current
# mapping. Each was confirmed by rerunning the Python and matching the log.
EARLIER_MAPPING = {
    9: "-lse -eqlbc -dlbc -useqprefix -nominlps -prec_et",
    10: "-lse -eqlbc -dlbc -prec_et -nominlps",
    11: "-lse -eqlbc -dlbc",
}
EARLIER_LIMIT = 36000

COMMON = "-pc 15 -g 0.01 -agap 0 -m"

LOG_NAME = re.compile(r"^log_(?P<flat>.+)_(?P<version>-?\d+)_15PC\.log$")


def known_datafiles() -> dict[str, tuple[str, int]]:
    """Map each data file's slash-free name to (path under data/, seats)."""
    found: dict[str, tuple[str, int]] = {}
    for value in vars(rx).values():
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, tuple) and len(item) == 2 \
                    and isinstance(item[0], str) and isinstance(item[1], int):
                found[item[0].replace("/", "")] = (item[0], item[1])
    return found


def tail_text(path: str, nbytes: int = 4096) -> str:
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - nbytes))
        return f.read().decode(errors="replace")


def summarise(path: str) -> tuple[str, str, str, int]:
    """
        Return (status, external upper bound, python seconds, seats) for one
        log. Seats are counted from the simulated count's "elected" lines.
    """
    ub = ""
    seats = 0
    with open(path) as f:
        for line in f:
            if re.match(r"Candidate .*, elected \(votes ", line):
                seats += 1
            if line.startswith("WEUB"):
                m = re.search(r"external UB (\S+)\.$", line.strip())
                ub = m.group(1) if m else ""
                break

    tail = tail_text(path)
    # converged: search finished. timelimit: stopped on -limit, ending with
    # the summary line. cut: the process was killed mid-run.
    last = tail.rstrip("\n").split("\n")[-1]
    if "MARGIN LB:" in tail:
        status = "converged"
    elif re.match(r"^\S+--\S+, \d+, \d+, \d+, \d+$", last):
        status = "timelimit"
    else:
        status = "cut"

    seconds = ""
    times = re.findall(r"Time (?:to finish:|elapsed) ([0-9.]+)s", tail)
    if times:
        seconds = times[-1]

    return status, ("-" if ub == "absent" else ub), seconds, seats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", default=os.path.join(REPO, "15PC_logs"))
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__),
                                                  "reference_runs.csv"))
    args = ap.parse_args()

    datafiles = known_datafiles()
    rows = []
    problems = []

    for name in sorted(os.listdir(args.logs)):
        m = LOG_NAME.match(name)
        if not m:
            continue
        flat, version = m.group("flat"), int(m.group("version"))

        path = os.path.join(args.logs, name)
        status, ub, seconds, log_seats = summarise(path)

        if flat in datafiles:
            datafile, seats = datafiles[flat]
            if seats != log_seats:
                problems.append(f"{name}: run_experiments seats {seats} != "
                                f"seats elected in log {log_seats}")
        else:
            # Not listed in run_experiments.py: recover the path from the
            # flattened name and take seats from the log.
            m2 = re.match(r"^(FedAus\d+)(.+)$", flat)
            if not m2:
                problems.append(f"{name}: data file not listed in run_experiments.py")
                continue
            datafile, seats = f"{m2.group(1)}/{m2.group(2)}", log_seats

        earlier = datafile.startswith("FedAus")
        mapping = EARLIER_MAPPING if earlier else CURRENT_MAPPING
        if version not in mapping:
            problems.append(f"{name}: no flags known for version {version}")
            continue

        displayname = rx.displaynames.get(datafile, "")
        expected_ub = rx.ubs.get(displayname)
        if expected_ub is not None and ub not in ("-", str(expected_ub)):
            problems.append(f"{name}: log UB {ub} != run_experiments UB {expected_ub}")

        rows.append({
            "log": name,
            "datafile": datafile,
            "seats": seats,
            "version": version,
            "mapping": "earlier" if earlier else "current",
            "flags": f"{COMMON} -limit {EARLIER_LIMIT if earlier else CURRENT_LIMIT} "
                     f"{mapping[version]}",
            "ub": ub,
            "status": status,
            "python_seconds": seconds,
            "bytes": os.path.getsize(path),
        })

    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"{len(rows)} runs written to {args.out}")
    for p in problems:
        print("WARNING:", p)


if __name__ == "__main__":
    main()
