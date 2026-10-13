"""
Regenerate chosen reference runs with the Python program on this machine.

A few 15PC_logs runs differ from both the Python and the C++ program run
here, because the server that produced them has its own SCIP build, which
lands on slightly different numbers in some MINLP solves. run_e2e.py uses a
log in local_refs/ in place of the original when one exists.

Usage: python3 make_local_refs.py REGEX [--data-dir DIR]
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import shlex
import subprocess
import sys


def keep_awake() -> None:
    """
        On macOS, re-run this script under caffeinate so the machine cannot
        sleep mid-run. SCIP times its solves by the wall clock, sleep
        included, so a nap pushes solves past their time limit and changes
        the log.
    """
    if sys.platform == "darwin" and not os.environ.get("MARGINSTV_AWAKE"):
        os.environ["MARGINSTV_AWAKE"] = "1"
        os.execvp("caffeinate", ["caffeinate", "-i", sys.executable] + sys.argv)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))


def main() -> int:
    keep_awake()
    ap = argparse.ArgumentParser()
    ap.add_argument("pattern", help="regex on the log name")
    ap.add_argument("--data-dir", default=os.path.join(REPO, "..", "stv-rla", "data"))
    args = ap.parse_args()

    out_dir = os.path.join(HERE, "local_refs")
    os.makedirs(out_dir, exist_ok=True)
    pattern = re.compile(args.pattern)
    with open(os.path.join(HERE, "reference_runs.csv")) as f:
        rows = [r for r in csv.DictReader(f) if pattern.search(r["log"])]

    for row in rows:
        if row["status"] != "converged":
            print(f"skip {row['log']}: only converged runs are regenerated")
            continue
        log = os.path.join(out_dir, row["log"])
        cmd = [sys.executable, os.path.join(REPO, "pymarginstv.py"),
               "-d", os.path.join(args.data_dir, row["datafile"]), "-s", row["seats"],
               "-log", log, "-displayname", "x"] + shlex.split(row["flags"])
        if row["ub"] not in ("", "-"):
            cmd += ["-ub", row["ub"]]
        subprocess.run(cmd, cwd=REPO, stdout=subprocess.DEVNULL, check=True)
        print(f"wrote {log}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
