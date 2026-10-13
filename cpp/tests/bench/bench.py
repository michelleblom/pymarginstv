"""
Speed and memory comparison: Python and C++ on the same machine, same
flags, same wall-time budget.

For each program it records nodes expanded, frontier nodes popped, the
lower and upper bounds reached, and peak resident memory summed over the
whole process tree (the Python's -pc workers are separate processes).

Usage:
  python3 bench.py --data FedAus19/FederalSenate2019VIC.json --seats 6 --ub 37843 \
      --flags "-lse -eqlbc -dlbc -useqprefix -nominlps -prec_et" --seconds 600
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))


def tree_rss_kb(root: int) -> int:
    """Resident memory of a process and all its descendants, in KB."""
    out = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,rss="], capture_output=True,
                         text=True).stdout
    children: dict[int, list[int]] = {}
    rss: dict[int, int] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) != 3:
            continue
        pid, ppid, kb = int(parts[0]), int(parts[1]), int(parts[2])
        children.setdefault(ppid, []).append(pid)
        rss[pid] = kb
    total, stack = 0, [root]
    while stack:
        p = stack.pop()
        total += rss.get(p, 0)
        stack.extend(children.get(p, []))
    return total


def summarise(log: str) -> dict:
    batches = 0
    popped = 0
    lb = ub = "?"
    with open(log) as f:
        for line in f:
            if line.startswith("EXPANDING NODE"):
                popped += 1
            elif line.startswith("Lower bound "):
                m = re.match(r"Lower bound (\S+), upper bound (\S+)", line)
                if m:
                    lb, ub = m.group(1), m.group(2)
            elif line.startswith("Time elapsed"):
                batches += 1
    return {"popped": popped, "steps": max(batches - 1, 0), "lb": lb, "ub": ub}


def run(cmd: list[str], seconds: int) -> tuple[float, int]:
    start = time.monotonic()
    proc = subprocess.Popen(cmd, cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    peak = 0
    while proc.poll() is None:
        peak = max(peak, tree_rss_kb(proc.pid))
        time.sleep(1.0)
        if time.monotonic() - start > seconds * 3 + 600:
            proc.kill()
    return time.monotonic() - start, peak


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="path under the shared data folder")
    ap.add_argument("--seats", required=True)
    ap.add_argument("--ub", default=None)
    ap.add_argument("--flags", required=True)
    ap.add_argument("--seconds", type=int, default=600)
    ap.add_argument("--pc", default="15")
    ap.add_argument("--threads", default="0", help="C++ thread counts, comma separated")
    ap.add_argument("--skip-python", action="store_true")
    args = ap.parse_args()

    data = os.path.join(REPO, "..", "stv-rla", "data", args.data)
    common = ["-d", data, "-s", args.seats, "-pc", args.pc, "-g", "0.01", "-agap", "0",
              "-m", "-limit", str(args.seconds)] + shlex.split(args.flags)
    if args.ub:
        common += ["-ub", args.ub]

    out = tempfile.mkdtemp(prefix="marginstv_bench_")
    rows = []
    if not args.skip_python:
        log = os.path.join(out, "python.log")
        secs, peak = run([sys.executable, "pymarginstv.py"] + common + ["-log", log],
                         args.seconds)
        rows.append(("python", secs, peak, summarise(log)))
    for t in args.threads.split(","):
        log = os.path.join(out, f"cpp_t{t}.log")
        cmd = [os.path.join(REPO, "cpp", "build", "marginstv")] + common + ["-log", log]
        if t != "0":
            cmd += ["-threads", t]
        secs, peak = run(cmd, args.seconds)
        rows.append((f"c++ threads={t}", secs, peak, summarise(log)))

    print(f"{args.data} {args.flags} -pc {args.pc}, budget {args.seconds}s (logs in {out})")
    for name, secs, peak, s in rows:
        print(f"  {name:16} ran {secs:7.1f}s  peak memory {peak / 1024 / 1024:6.2f} GB  "
              f"steps {s['steps']:6}  nodes expanded {s['popped']:7}  "
              f"bounds {s['lb']}--{s['ub']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
