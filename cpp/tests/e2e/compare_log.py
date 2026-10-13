"""
Compare a C++ log with a Python reference log.

Lines that report wall-clock time are skipped on both sides. Two modes:

  exact   (reference run converged): the logs must be identical.
  prefix  (reference run hit its time limit or was killed): every reference
          line, except the final summary line, must appear at the start of
          the candidate. The candidate may continue past that point.

Usage: python3 compare_log.py CANDIDATE REFERENCE [--prefix]
Exit status: 0 match, 1 mismatch, 2 usage or file error.
"""

from __future__ import annotations

import argparse
import itertools
import re
import sys
from typing import Iterator, Optional, TextIO

TIME_LINE = re.compile(r"^Time (elapsed |to finish: |start )")

# Final line of a timed-out run: "lb--ub, nexps, nsolves, ignores, prunes".
SUMMARY_LINE = re.compile(r"^\S+--\S+, \d+, \d+, \d+, \d+$")


def kept_lines(stream: TextIO) -> Iterator[tuple[int, str]]:
    """
        Yield (line number, text) for every line that is not a time line.
        A final line with no line ending was cut off mid-write and is skipped.
    """
    for number, line in enumerate(stream, start=1):
        if not line.endswith("\n"):
            return
        text = line[:-1]
        if not TIME_LINE.match(text):
            yield number, text


def drop_trailing_summary(lines: Iterator[tuple[int, str]]) \
        -> Iterator[tuple[int, str]]:
    """Pass lines through, holding one back so a final summary can be dropped."""
    previous: Optional[tuple[int, str]] = None
    for item in lines:
        if previous is not None:
            yield previous
        previous = item
    if previous is not None and not SUMMARY_LINE.match(previous[1]):
        yield previous


def compare(candidate: TextIO, reference: TextIO, prefix: bool) -> tuple[bool, str]:
    cand = kept_lines(candidate)
    ref = kept_lines(reference)
    if prefix:
        ref = drop_trailing_summary(ref)

    checked = 0
    for c, r in itertools.zip_longest(cand, ref):
        if r is None:
            if prefix:
                return True, f"match: {checked} reference lines found at the " \
                             "start of the candidate"
            return False, f"candidate has extra lines from line {c[0]}:\n  + {c[1]}"
        if c is None:
            return False, f"candidate ends early; reference line {r[0]} missing:\n" \
                          f"  - {r[1]}"
        if c[1] != r[1]:
            return False, f"first difference at candidate line {c[0]}, " \
                          f"reference line {r[0]}:\n  - {r[1]}\n  + {c[1]}"
        checked += 1

    return True, f"match: {checked} lines identical"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("candidate")
    ap.add_argument("reference")
    ap.add_argument("--prefix", action="store_true",
                    help="reference stopped on its time limit")
    args = ap.parse_args()

    try:
        with open(args.candidate) as c, open(args.reference) as r:
            ok, message = compare(c, r, args.prefix)
    except OSError as e:
        print(e, file=sys.stderr)
        return 2

    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
