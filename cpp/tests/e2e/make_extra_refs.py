"""
Generate extra reference runs with the Python program, covering options the
15PC_logs set never uses. Writes, into extra_refs/:

  <name>.log              the log
  <name>.log.stdout       stdout and stderr (the summary CSV line)
  <name>.log.solves.csv   MINLP sidecar, when any MINLP was solved
  extra_runs.csv          manifest in the same format as reference_runs.csv

Usage: python3 make_extra_refs.py [--only REGEX] [--data-dir DIR]
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import shlex
import subprocess
import sys
import time

from make_manifest import summarise

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
OUT = os.path.join(HERE, "extra_refs")

LANGSIDE = ("Scotland/2007/GCC_07_Langside_ballots.txt", 3, "233")
NEWLANDS = ("Scotland/2007/GCC_07_Newlands_ballots.txt", 3, "88")
DUBLIN_W = ("Ireland/DublinWest2002_ballots.txt", 3, "366")
MPLS09 = ("Minneapolis/MPLS-2009-BET_2Seat_ParsedMB.txt", 2, "2098")
MPLS17 = ("Minneapolis/MPLS-2017-BET_2Seat_ParsedMB.txt", 2, "16863")
PAPER = ("repo:paper_example.blt", 3, "-")
ACT22 = ("FedAus22/2022ACT.json", 2, "11078")
NT19 = ("FedAus19/FederalSenate2019NT.json", 2, "15890")

BASE = "-g 0.01 -agap 0 -m"

# Current run_experiments.py versions with no log in 15PC_logs.
CURRENT_UNLOGGED = {
    11: "-eqlbc -prec_et",
    12: "-dlbc -prec_et",
    13: "-lse -eqlbc -dlbc -useqprefix -prec_et",
    14: "-lse -eqlbc -dlbc -useqprefix -prec_et -nominlps",
    15: "-lse -useqprefix",
}


def short(flags: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", flags.replace(" ", "_")) or "none"


def planned_runs() -> list[dict]:
    runs: list[dict] = []

    def add(tag: str, inst: tuple[str, int, str], flags: str, limit: int = 600) -> None:
        datafile, seats, ub = inst
        stem = os.path.basename(datafile.removeprefix("repo:")).split(".")[0]
        runs.append({"name": f"{stem}_{tag}", "datafile": datafile,
                     "seats": seats, "ub": ub,
                     "flags": f"{flags} -limit {limit}"})

    # A. Every combination of the bound options, MINLPs off so each run is
    #    quick. Exercises the bounds in every mode the code supports.
    for inst in (LANGSIDE, MPLS09):
        for eq in ("", "-eqlb", "-eqlbc"):
            for d in ("", "-dlb", "-dlbc"):
                for q in ("", "-useqprefix"):
                    for p in ("", "-prec_et"):
                        flags = " ".join(f for f in ("-lse", eq, d, q, p) if f)
                        add(f"grid_{short(flags)}",
                            inst, f"-pc 4 {BASE} {flags} -nominlps")

    # B. Current versions that never produced a 15PC log.
    for inst in (LANGSIDE, NEWLANDS, DUBLIN_W, MPLS17):
        for version, flags in CURRENT_UNLOGGED.items():
            add(f"v{version}", inst, f"-pc 15 {BASE} {flags}")

    # C. Search options.
    v3 = "-lse -eqlb -dlb"
    for inst in (LANGSIDE, MPLS17):
        add("allminlps", inst, f"-pc 4 {BASE} {v3} -allminlps")
        add("allminlps_qprefix", inst, f"-pc 4 {BASE} {v3} -useqprefix -allminlps")
        add("evalpara", inst, f"-pc 4 {BASE} {v3} -evalpara")
        add("pc1", inst, f"-pc 1 {BASE} {v3}")
        add("nomerge", inst, f"-pc 4 -g 0.01 -agap 0 {v3}")
        add("agap1", inst, f"-pc 4 -g 0.01 -m {v3}")
        add("nolse", inst, f"-pc 4 {BASE} -eqlb -dlb")
        add("bst19", inst, f"-pc 4 {BASE} -lse")
    add("noub", (LANGSIDE[0], LANGSIDE[1], "-"), f"-pc 4 {BASE} {v3}")

    # D. .blt input and simulation only.
    add("v3", PAPER, f"-pc 4 {BASE} {v3}")
    add("v14", PAPER, f"-pc 4 {BASE} {CURRENT_UNLOGGED[14]}")
    for inst in (PAPER, MPLS17, LANGSIDE, ACT22, NT19):
        add("justsim", inst, "-just_sim")

    # E. JSON input under search: cut off after a minute, compared as prefix.
    add("v14_60s", ACT22, f"-pc 15 {BASE} {CURRENT_UNLOGGED[14]}", limit=60)
    add("earlier_v10_60s", NT19, f"-pc 15 {BASE} -lse -eqlbc -dlbc -prec_et -nominlps",
        limit=60)

    return runs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="regex on run name")
    ap.add_argument("--data-dir", default=os.path.join(REPO, "..", "stv-rla", "data"))
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    manifest = os.path.join(OUT, "extra_runs.csv")

    existing: dict[str, dict] = {}
    if os.path.exists(manifest):
        with open(manifest) as f:
            existing = {r["log"]: r for r in csv.DictReader(f)}

    pattern = re.compile(args.only) if args.only else None
    for run in planned_runs():
        if pattern and not pattern.search(run["name"]):
            continue

        log = os.path.join(OUT, run["name"] + ".log")
        for stale in (log, log + ".stdout", log + ".solves.csv"):
            if os.path.exists(stale):
                os.remove(stale)

        datafile = run["datafile"]
        data = os.path.join(REPO, datafile[5:]) if datafile.startswith("repo:") \
            else os.path.join(args.data_dir, datafile)
        cmd = [sys.executable, os.path.join(REPO, "pymarginstv.py"), "-d", data,
               "-s", str(run["seats"]), "-log", log, "-displayname", "x"]
        cmd += shlex.split(run["flags"])
        if run["ub"] != "-":
            cmd += ["-ub", run["ub"]]

        start = time.monotonic()
        with open(log + ".stdout", "w") as out:
            subprocess.run(cmd, stdout=out, stderr=subprocess.STDOUT, cwd=REPO)
        seconds = time.monotonic() - start

        status, _, _, _ = summarise(log)
        if "-just_sim" in run["flags"]:
            status = "converged"     # a complete, deterministic log

        existing[run["name"] + ".log"] = {
            "log": run["name"] + ".log", "datafile": datafile,
            "seats": run["seats"], "version": "extra", "mapping": "extra",
            "flags": run["flags"], "ub": run["ub"], "status": status,
            "python_seconds": f"{seconds:.2f}", "bytes": os.path.getsize(log),
        }
        print(f"{status:9} {seconds:7.1f}s {run['name']}", flush=True)

    rows = sorted(existing.values(), key=lambda r: r["log"])
    with open(manifest, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"{len(rows)} runs in {manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
