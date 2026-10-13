"""
Run the C++ program on reference runs and compare its logs with Python's.

Each selected run is repeated at every thread count given with --threads.
Every log must match the reference (see compare_log.py), which also means
the logs at different thread counts match each other.

For a reference that stopped on its time limit, the C++ run is stopped as
soon as its log is longer than the reference, then compared as a prefix.

Usage examples:
  python3 run_e2e.py --tier quick
  python3 run_e2e.py --tier full --threads 1,4,15
  python3 run_e2e.py --filter Canal --threads 15
  python3 run_e2e.py --manifest extra_runs.csv --tier full
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
import time

from compare_log import TIME_LINE, compare

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))

# Tiers by how long Python took on the reference machine (seconds).
TIER_LIMITS = {"quick": 60.0, "medium": 1800.0, "full": float("inf")}


def kept_line_count(path: str) -> int:
    with open(path) as f:
        return sum(1 for line in f if not TIME_LINE.match(line))


def resolve_data(datafile: str, data_dir: str) -> str:
    """Reference rows name data under the shared data folder unless marked
    as living in this repository."""
    if datafile.startswith("repo:"):
        return os.path.join(REPO, datafile[len("repo:"):])
    return os.path.join(data_dir, datafile)


def build_command(binary: str, row: dict, data_dir: str, log: str,
                  threads: int, lift_limit: bool) -> list[str]:
    """
        With lift_limit, the run's own -limit is raised out of reach: the
        reference stopped on its time limit, and the candidate must be free
        to run past the point the reference reached. The runner stops it.
    """
    cmd = [binary, "-d", resolve_data(row["datafile"], data_dir),
           "-s", row["seats"], "-log", log, "-displayname", "x"]
    flags = shlex.split(row["flags"])
    if lift_limit and "-limit" in flags:
        flags[flags.index("-limit") + 1] = "1000000000"
    cmd += flags
    if row["ub"] not in ("", "-"):
        cmd += ["-ub", row["ub"]]
    if threads > 0:
        cmd += ["-threads", str(threads)]
    return cmd


def run_until_past(cmd: list[str], log: str, target_lines: int,
                   wall_timeout: float) -> tuple[str, float]:
    """
        Run cmd. Stop it early once the log holds more than target_lines
        non-time lines (target_lines < 0 means never stop early).
        Returns (how it ended, seconds).
    """
    start = time.monotonic()
    with open(log + ".stdout", "w") as out:
        proc = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT)

    seen = 0
    offset = 0
    pending = ""
    while True:
        try:
            proc.wait(timeout=1.0)
            return f"exit {proc.returncode}", time.monotonic() - start
        except subprocess.TimeoutExpired:
            pass

        if time.monotonic() - start > wall_timeout:
            proc.kill()
            proc.wait()
            return "wall timeout", time.monotonic() - start

        if target_lines >= 0 and os.path.exists(log):
            with open(log) as f:
                f.seek(offset)
                chunk = f.read()
                offset = f.tell()
            lines = (pending + chunk).split("\n")
            pending = lines.pop()
            seen += sum(1 for line in lines if not TIME_LINE.match(line))
            if seen > target_lines:
                proc.terminate()
                proc.wait()
                return "stopped past reference", time.monotonic() - start


def masked_stdout(path: str) -> list[str]:
    """Stdout lines, with the summary CSV's two time columns blanked."""
    out = []
    with open(path) as f:
        for line in f:
            fields = line.rstrip("\n").split(", ")
            if len(fields) >= 15:
                fields[9] = fields[10] = "<time>"
            out.append(", ".join(fields))
    return out


def read_solves(path: str) -> list[list[str]]:
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [line.rstrip("\n").split(",") for line in f if line.strip()]


def same_solves(a_path: str, b_path: str) -> bool:
    """
        MINLP sidecars match when every solve reached the same bounds, and,
        except where a solve ran into its time limit on either side, the
        same status and node count. A solve near its time limit can stop on
        the clock in one run and finish just in time in the other: which one
        happens depends on machine speed, not on the program. Time columns
        are ignored and row order is free, as parallel solves finish in any
        order.
    """
    a, b = read_solves(a_path), read_solves(b_path)
    bounds = lambda rows: sorted(",".join(r[4:]) for r in rows)
    if bounds(a) != bounds(b):
        return False
    clocked = {",".join(r[4:]) for r in a + b if r[0] == "timelimit"}
    full = lambda rows: sorted(",".join([r[0], r[3]] + r[4:]) for r in rows
                               if ",".join(r[4:]) not in clocked)
    return full(a) == full(b)


def compare_side_outputs(log: str, reference: str) -> tuple[bool, str]:
    """
        Compare stdout and the MINLP sidecar where the reference has them.
        Only meaningful for runs that finished: a run stopped early has a
        partial sidecar and no summary line.
    """
    if os.path.exists(reference + ".stdout") and \
            masked_stdout(log + ".stdout") != masked_stdout(reference + ".stdout"):
        return False, "stdout differs"
    if os.path.exists(reference + ".solves.csv") and \
            not same_solves(log + ".solves.csv", reference + ".solves.csv"):
        return False, "MINLP sidecar (.solves.csv) differs"
    return True, ""


def main() -> int:
    keep_awake()
    ap = argparse.ArgumentParser()
    ap.add_argument("--binary", default=os.path.join(REPO, "cpp", "build", "marginstv"))
    ap.add_argument("--manifest", default=os.path.join(HERE, "reference_runs.csv"))
    ap.add_argument("--refs", default=None,
                    help="folder holding the reference logs "
                         "(default: 15PC_logs, or the manifest's own folder)")
    ap.add_argument("--data-dir", default=os.path.join(REPO, "..", "stv-rla", "data"))
    ap.add_argument("--out", default=os.path.join(REPO, "cpp", "build", "e2e_out"))
    ap.add_argument("--tier", choices=list(TIER_LIMITS), default="quick")
    ap.add_argument("--filter", default=None, help="regex on the log name")
    ap.add_argument("--threads", default="0",
                    help="comma separated thread counts; 0 = program default")
    ap.add_argument("--wall-timeout", type=float, default=4 * 3600)
    ap.add_argument("--local-refs", default=os.path.join(HERE, "local_refs"),
                    help="folder of references regenerated by the Python on this "
                         "machine (make_local_refs.py); used in place of the original "
                         "when present")
    args = ap.parse_args()

    refs = args.refs
    if refs is None:
        refs = os.path.join(REPO, "15PC_logs") \
            if os.path.basename(args.manifest) == "reference_runs.csv" \
            else os.path.dirname(os.path.abspath(args.manifest))

    with open(args.manifest) as f:
        rows = list(csv.DictReader(f))

    limit = TIER_LIMITS[args.tier]
    pattern = re.compile(args.filter) if args.filter else None
    selected = [r for r in rows
                if float(r["python_seconds"] or "inf") <= limit
                and (pattern is None or pattern.search(r["log"]))]

    thread_counts = [int(t) for t in args.threads.split(",")]
    os.makedirs(args.out, exist_ok=True)

    failures = 0
    for row in selected:
        reference = os.path.join(refs, row["log"])
        local = os.path.join(args.local_refs, row["log"])
        source = "reference"
        if os.path.exists(local):
            reference, source = local, "local reference"
        prefix = row["status"] != "converged"
        target = kept_line_count(reference) if prefix else -1

        for threads in thread_counts:
            log = os.path.join(args.out, f"{row['log']}.t{threads}")
            for stale in (log, log + ".stdout", log + ".solves.csv"):
                if os.path.exists(stale):
                    os.remove(stale)

            cmd = build_command(args.binary, row, args.data_dir, log, threads,
                                lift_limit=prefix)
            ended, seconds = run_until_past(cmd, log, target, args.wall_timeout)

            if not os.path.exists(log):
                ok, message = False, f"no log written ({ended})"
            else:
                with open(log) as c, open(reference) as r:
                    ok, message = compare(c, r, prefix)
                if ok and not prefix:
                    side_ok, side_message = compare_side_outputs(log, reference)
                    if not side_ok:
                        ok, message = False, side_message

            sidecar = log + ".solves.csv"
            if os.path.exists(sidecar):
                with open(sidecar) as sf:
                    limited = sum(1 for line in sf if line.startswith("timelimit"))
                if limited:
                    message += f" [warning: {limited} MINLP solves hit their time limit]"

            failures += 0 if ok else 1
            py = row["python_seconds"] or "?"
            print(f"{'PASS' if ok else 'FAIL'} {row['log']} threads={threads} "
                  f"[{source}; {ended}, {seconds:.1f}s vs python {py}s] {message}",
                  flush=True)

    print(f"\n{len(selected) * len(thread_counts) - failures} passed, "
          f"{failures} failed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
