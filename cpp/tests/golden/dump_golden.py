"""
Record golden data from the Python program for the C++ component tests.

Runs the Python search in-process (-pc 1) with recording wrappers around:

  eval_child_initial  each initial-frontier node: inputs and full result
  generate_children   each expansion: the node, the restored and updated
                      contexts, the shared round tallies, the child specs
  eval_child          each child: inputs and full result
  solve_stvdistance   each MINLP: inputs, result, and the model file SCIP
                      was given (.cip), for an exact model comparison

Every value is stored exactly: floats as hex (float.hex), ints that do not
fit in 53 bits as hex strings, sets in their Python iteration order, dicts
as ordered pairs. Records go to one gzipped JSON-lines file per case.

It also writes unit-level goldens that need no search (number printing, set
iteration order, prefix helpers, signatures, readers, simulation).

Usage: python3 dump_golden.py [--only REGEX] [--max-children N]
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import math
import os
import random
import re
import runpy
import struct
import sys
from array import array
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
DATA = os.path.abspath(os.path.join(REPO, "..", "stv-rla", "data"))
OUT = os.path.join(HERE, "data")

sys.path.insert(0, REPO)

import numpy as np  # noqa: E402

import stvtree  # noqa: E402
import utils  # noqa: E402

BIG = 1 << 53


class StopRecording(Exception):
    """Raised once enough children have been recorded."""


def enc(x: Any) -> Any:
    """Encode a Python value as exact JSON."""
    if x is None or isinstance(x, (bool, np.bool_)):
        return None if x is None else bool(x)
    if isinstance(x, (int, np.integer)):
        x = int(x)
        return x if -BIG < x < BIG else {"int": hex(x)}
    if isinstance(x, (float, np.floating)):
        return {"f": float(x).hex()}
    if isinstance(x, np.ndarray):
        return {"nd": [enc(v) for v in x.ravel().tolist()], "shape": list(x.shape)}
    if isinstance(x, (bytes, bytearray)):
        return list(x)
    if isinstance(x, array):
        return list(x)
    if isinstance(x, stvtree.TreeNode):
        return {"type": "TreeNode", "sig": x.sig.hex(), "order_c": x.order_c,
                "order_a": x.order_a, "order_q": enc(x.order_q),
                "dist": enc(x.dist), "dist_ub": enc(x.dist_ub),
                "eqlbctx": enc(x.eqlbctx), "disp_cache": enc(x.disp_cache)}
    if isinstance(x, tuple) and hasattr(x, "_fields"):
        return {"type": type(x).__name__,
                **{k: enc(getattr(x, k)) for k in x._fields}}
    if isinstance(x, (list, tuple)):
        return [enc(v) for v in x]
    if isinstance(x, (set, frozenset)):
        return {"set": [enc(v) for v in x]}   # iteration order kept
    if isinstance(x, dict):
        return {"dict": [[enc(k), enc(v)] for k, v in x.items()]}
    raise TypeError(f"cannot encode {type(x)}")


class Recorder:
    def __init__(self, path: str, max_children: int) -> None:
        self.out = gzip.open(path, "wt")
        self.max_children = max_children
        self.children = 0
        self.solves = 0
        self.model_dir = path[:-len(".jsonl.gz")] + "_models"

    def write(self, kind: str, **fields: Any) -> None:
        self.out.write(json.dumps({"kind": kind, **fields}) + "\n")

    def close(self) -> None:
        self.out.close()


def recording_model_class() -> type:
    """
        A pyscipopt Model that writes the problem it is about to solve to a
        file first. pyscipopt's Model is a compiled class whose methods
        cannot be replaced, so the model modules are handed this subclass
        through their imported name instead.
    """
    import pyscipopt

    class RecordingModel(pyscipopt.Model):
        next_file = ""

        def optimize(self) -> Any:
            self.writeProblem(RecordingModel.next_file, trans=False, verbose=False)
            self.writeParams(RecordingModel.next_file[:-4] + ".set",
                             comments=False, onlychanged=True, verbose=False)
            with open(RecordingModel.next_file[:-4] + ".objlimit", "w") as f:
                f.write(float(self.getObjlimit()).hex() + "\n")
            return super().optimize()

    return RecordingModel


RecordingModel: Any = None


def install(rec: Recorder) -> None:
    """Wrap the stvtree functions so each call is recorded."""
    global RecordingModel
    if RecordingModel is None:
        RecordingModel = recording_model_class()
    for module in ("stvdistance", "stvdistance-qprefix"):
        sys.modules[module].Model = RecordingModel
    orig_initial = stvtree.eval_child_initial
    orig_generate = stvtree.generate_children
    orig_child = stvtree.eval_child
    orig_solve = stvtree.solve_stvdistance

    def eval_child_initial(*a: Any) -> Any:
        inputs = enc(a)
        result = orig_initial(*a)
        rec.write("initial", inputs=inputs, result=enc(result))
        return result

    def generate_children(fnode_data: Any, running_ub: Any) -> Any:
        inputs = enc((fnode_data, running_ub))
        specs = orig_generate(fnode_data, running_ub)
        # Every spec shares the restored/updated contexts and round tallies,
        # so they are written once here and children refer to them by index.
        shared = enc(specs[0][1:3] + (specs[0][10],)) if specs else None
        rec.write("generate", inputs=inputs, shared=shared,
                  children=[enc((s[0],) + s[3:10]) for s in specs])
        return specs

    def eval_child(*a: Any) -> Any:
        if rec.children >= rec.max_children:
            raise StopRecording()
        inputs = enc(a)
        result = orig_child(*a)
        rec.write("child", inputs=inputs, result=enc(result))
        rec.children += 1
        return result

    def solve_stvdistance(*a: Any, **k: Any) -> Any:
        os.makedirs(rec.model_dir, exist_ok=True)
        model_file = os.path.join(rec.model_dir, f"solve_{rec.solves:05d}.cip")
        RecordingModel.next_file = model_file
        result = orig_solve(*a, **k)

        # candidates, ballots and args are run-wide; leave them out.
        keep = (2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14)
        rec.write("solve", index=rec.solves, model=os.path.basename(model_file),
                  inputs=[enc(a[i]) for i in keep],
                  isleaf=enc(a[15] if len(a) > 15 else k.get("isleaf", False)),
                  result=enc(result))
        rec.solves += 1
        return result

    stvtree.eval_child_initial = eval_child_initial
    stvtree.generate_children = generate_children
    stvtree.eval_child = eval_child
    stvtree.solve_stvdistance = solve_stvdistance


def record_search(name: str, argv: list[str], max_children: int) -> None:
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name + ".jsonl.gz")
    rec = Recorder(path, max_children)
    rec.write("run", argv=argv)

    saved = (stvtree.eval_child_initial, stvtree.generate_children,
             stvtree.eval_child, stvtree.solve_stvdistance)
    install(rec)
    old_argv = sys.argv
    sys.argv = ["pymarginstv.py"] + argv + ["-log", os.devnull]
    try:
        runpy.run_path(os.path.join(REPO, "pymarginstv.py"), run_name="__main__")
    except StopRecording:
        pass
    except SystemExit:
        pass
    finally:
        sys.argv = old_argv
        (stvtree.eval_child_initial, stvtree.generate_children,
         stvtree.eval_child, stvtree.solve_stvdistance) = saved
        rec.close()
    print(f"{name}: {rec.children} children, {rec.solves} solves", flush=True)


# ---------------------------------------------------------------- unit goldens

def float_cases(rng: random.Random) -> list[float]:
    vals = [0.0, -0.0, 1.0, 0.5, 0.1, 1e16, 1e15, 9999999999999998.0, 1e-4,
            1e-5, 123456789.0, 1 / 3, 2 / 3, 1e300, 5e-324, math.inf, -math.inf,
            0.517638020887403, 15859.393683948258, 35171.39368394826,
            0.3138424821002387]
    for _ in range(3000):
        kind = rng.randrange(4)
        if kind == 0:
            vals.append(rng.uniform(0, 1))
        elif kind == 1:
            vals.append(rng.uniform(0, 1e6) * rng.choice([1, 1e-3, 1e3]))
        elif kind == 2:
            vals.append(float(rng.randrange(0, 10 ** rng.randrange(1, 18))))
        else:
            vals.append(rng.random() * 10 ** rng.randrange(-8, 22))
    return vals


def dump_units() -> None:
    rng = random.Random(20261009)
    os.makedirs(OUT, exist_ok=True)
    units: dict[str, Any] = {}

    # Python str() of floats, the format every log value goes through.
    units["float_str"] = [[v.hex(), str(v), "{:.2f}".format(v)]
                          for v in float_cases(rng)]

    # Set iteration order: sequences of adds, copies, comprehensions.
    sets = []
    for _ in range(2000):
        n = rng.randrange(1, 12)
        top = rng.choice([8, 16, 40, 90, 160])
        ops = [rng.randrange(top) for _ in range(n)]
        s = {c for c in ops[:-1]}          # derive_winners builds it this way
        t = set(s)                         # generate_children copies it
        t.add(ops[-1])                     # then adds the new winner
        sets.append({"comprehension": ops[:-1], "then_copy_add": ops[-1],
                     "order_after_comprehension": list(s),
                     "order_after_copy_add": list(t)})
    units["set_order"] = sets

    # Larger sets built by comprehension over a candidate ordering, as the
    # MINLP builds its set of non-merged candidates.
    big = []
    for _ in range(500):
        n = rng.randrange(1, 170)
        perm = list(range(n))
        rng.shuffle(perm)
        drop = set(rng.sample(perm, rng.randrange(0, max(1, n // 3))))
        s = {c for c in perm if c not in drop}
        big.append({"adds": [c for c in perm if c not in drop], "order": list(s)})
    units["set_big"] = big

    # Prefix helpers on random prefixes.
    prefix_cases = []
    for _ in range(1500):
        ncands = rng.randrange(3, 30)
        seats = rng.randrange(1, min(7, ncands))
        perm = list(range(ncands))
        rng.shuffle(perm)
        plen = rng.randrange(1, ncands + 1)
        order_c = perm[:plen]
        order_a = [0] * plen
        for i in rng.sample(range(plen), min(seats, rng.randrange(0, plen + 1))):
            order_a[i] = 1
        rem = perm[plen:]
        last = stvtree.compute_last_round(order_c, order_a, seats, ncands)
        winners = {c for i, c in enumerate(order_c) if order_a[i] == 1}
        idx = {c: i for i, c in enumerate(order_c)}
        order_q = utils.get_order_q(order_a, last, winners, idx)
        qp = {c: (i, i) for i, c in enumerate(order_c) if order_a[i] == 1}
        m = utils.merge_outcome(order_c, order_a, order_q, rem)
        prefix_cases.append({
            "ncands": ncands, "seats": seats, "order_c": order_c,
            "order_a": order_a, "rem": rem, "last_round": last,
            "winners_iter": list(winners), "order_q": enc(order_q),
            "merge": enc(m),
            "sig_ranges": stvtree.outcome_signature(order_c, order_a, order_q).hex(),
            "sig_exact": stvtree.outcome_signature(order_c, order_a, qp).hex(),
            "canonical": stvtree._canonical_outcome(order_c, order_a, order_q).hex(),
        })
    units["prefix"] = prefix_cases

    # Equivalence classes for small prefixes (MINLP ballot reduction).
    eq = []
    for _ in range(50):
        n = rng.randrange(1, 7)
        perm = list(range(10))
        rng.shuffle(perm)
        classes, cntr, _ = utils.gen_equivalence_classes(perm[:n], perm[n:n + 3], 10)
        eq.append({"order_c": perm[:n], "rem": perm[n:n + 3], "count": cntr,
                   "classes": [list(c.prefs) for c in classes]})
    units["equivalence_classes"] = eq

    with gzip.open(os.path.join(OUT, "units.json.gz"), "wt") as f:
        json.dump(units, f)
    print("units: written", flush=True)


def dump_inputs() -> None:
    """Reader and simulation goldens for every data file the tests use."""
    files = sorted({
        ("Minneapolis/MPLS-2009-BET_2Seat_ParsedMB.txt", 2),
        ("Minneapolis/MPLS-2017-BET_2Seat_ParsedMB.txt", 2),
        ("Scotland/2007/GCC_07_Langside_ballots.txt", 3),
        ("Scotland/2007/GCC_07_Canal_ballots.txt", 4),
        ("Ireland/DublinWest2002_ballots.txt", 3),
        ("FedAus22/2022ACT.json", 2),
        ("FedAus19/FederalSenate2019NT.json", 2),
        ("FedAus19/FederalSenate2019VIC.json", 6),
        ("repo:paper_example.blt", 3),
    })
    out = []
    for name, seats in files:
        path = os.path.join(REPO, name[5:]) if name.startswith("repo:") \
            else os.path.join(DATA, name)
        if path.endswith(".blt"):
            cands, ballots, *_, meta = utils.read_ballots_blt(path)
        elif path.endswith(".json"):
            cands, ballots, *_, meta = utils.read_ballots_json(path)
        else:
            cands, ballots, *_, meta = utils.read_ballots_txt(path)

        # Digest of every ballot: votes as 8 bytes, ranking length as 2
        # bytes, then each preference as 2 bytes, all little-endian.
        h = hashlib.blake2b(digest_size=16)
        for b in ballots:
            h.update(struct.pack("<qH", b.votes, len(b.prefs)))
            h.update(struct.pack("<%dH" % len(b.prefs), *b.prefs))

        log = io.StringIO()
        order_c: list[int] = []
        order_a: list[int] = []
        winners: list[int] = []
        quota, tallies, tot = utils.simulate_stv(ballots, cands, seats, order_c,
                                                 order_a, winners, log=log)
        weub = utils.compute_weub(cands, winners, order_c, order_a, tallies)
        sub = utils.compute_simple_ub(cands, quota, winners)

        out.append({
            "file": name, "seats": seats, "ncands": len(cands),
            "nballots": len(ballots), "ballots_digest": h.hexdigest(),
            "cand_ids": [c.id for c in cands],
            "fp_votes": [enc(c.fp_votes) for c in cands],
            "mentions": enc(meta.mentions), "above": enc(meta.above),
            "reassign": enc(meta.reassign),
            "quota": quota, "totvotes": enc(tot), "order_c": order_c,
            "order_a": order_a, "winners": winners,
            "tallies": enc(tallies), "weub": enc(weub), "simple_ub": enc(sub),
            "sim_log": log.getvalue(),
        })
        print(f"inputs: {name}", flush=True)

    with gzip.open(os.path.join(OUT, "inputs.json.gz"), "wt") as f:
        json.dump(out, f)


# ------------------------------------------------------------------ the cases

def search_cases() -> list[tuple[str, list[str]]]:
    cases = []
    insts = [("langside", "Scotland/2007/GCC_07_Langside_ballots.txt", "3", "233"),
             ("mpls09", "Minneapolis/MPLS-2009-BET_2Seat_ParsedMB.txt", "2", "2098"),
             ("paper", "repo:paper_example.blt", "3", None)]

    for tag, data, seats, ub in insts:
        path = os.path.join(REPO, data[5:]) if data.startswith("repo:") \
            else os.path.join(DATA, data)
        base = ["-d", path, "-s", seats, "-pc", "1", "-g", "0.01",
                "-agap", "0", "-m", "-lse", "-limit", "100000"]
        if ub:
            base += ["-ub", ub]

        # Every bound configuration, no MINLPs.
        for eq in ("", "-eqlb", "-eqlbc"):
            for d in ("", "-dlb", "-dlbc"):
                for q in ("", "-useqprefix"):
                    for p in ("", "-prec_et"):
                        flags = [f for f in (eq, d, q, p) if f]
                        name = f"{tag}_" + ("_".join(f.strip("-") for f in flags) or "bst19")
                        cases.append((name, base + flags + ["-nominlps"]))

        # MINLP models in both prefix modes, with and without merging.
        for q in ("", "-useqprefix"):
            for m in ("-m", ""):
                args = [a for a in base if a != "-m" or m] + ["-eqlb", "-dlb"]
                if q:
                    args.append(q)
                name = f"{tag}_minlp{'_qprefix' if q else ''}{'' if m else '_nomerge'}"
                cases.append((name, args + ["-allminlps"]))
    return cases


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="regex on case name")
    ap.add_argument("--max-children", type=int, default=400)
    args = ap.parse_args()
    pattern = re.compile(args.only) if args.only else None

    if pattern is None or pattern.search("units"):
        dump_units()
    if pattern is None or pattern.search("inputs"):
        dump_inputs()
    for name, argv in search_cases():
        if pattern is None or pattern.search(name):
            record_search(name, argv, args.max_children)
    return 0


if __name__ == "__main__":
    sys.exit(main())
