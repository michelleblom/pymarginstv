"""
Diagnoses where the membership-branching tree grows: random probes as in
membership_two_level.py, recording at every decision which checks pruned
a child, and for each run the candidates still standing at its end.

Run from the repository root:
    python3 <this file> [-contest PATH] [-frac F] [-probes N] [-seed N]
"""
import argparse
import math
import os
import random
import sys
import time
from collections import Counter

import numpy as np

sys.path.insert(0, os.getcwd())

from measure_batch_seeding import load, Count
from utils import simulate_stv, compute_simple_ub, compute_weub
from membership_proto import Node
from membership_two_level import Level


class DiagLevel(Level):
    """ Level whose check also says which test pruned. """

    def why(self, IN, OUT):
        q, k, t0 = self.nd.quota, self.k, self.t0
        if len(self.hopeful) - len(IN) < self.seats_left:
            return "few"
        tm = self.tmax(OUT)
        if IN:
            if max(t0[c] for c in self.hopeful) - k >= q:
                return "Q"
            if OUT and max(t0[c] for c in IN) - \
                min(tm[d] for d in OUT) > 2 * k:
                return "E"
            if OUT:
                tmin, F = self.tmin_flow(IN)
                rows = list(IN)
                for x in OUT:
                    if tmin[x] - F[rows, x].max() - k >= q:
                        return "M"
        can = [x for x in self.hopeful if x not in IN and tm[x] + k >= q]
        if not can and len(OUT) > self.seats_left:
            return "S"
        return None

    def after_seating(self, R, x, tr):
        nxt = super().after_seating(R, x, tr)
        return DiagLevel(nxt.nd, nxt.w, nxt.gone, nxt.seats_left, nxt.k)


def probe(level, rng):
    """ One random path, with a record of every decision and run. """
    prod, nodes = 1.0, 1.0
    runs = []
    while True:
        IN, OUT = set(), set()
        steps = []
        for c in level.order:
            opts = [(IN | {c}, OUT), (IN, OUT | {c})]
            reasons = [level.why(*o) for o in opts]
            ch = [o for o, r in zip(opts, reasons) if r is None]
            tm = level.tmax(OUT)
            seaters = [x for x in level.hopeful \
                if x not in IN and tm[x] + level.k >= level.nd.quota]
            steps.append((c, level.t0[c], len(ch), reasons, len(IN), \
                len(OUT), seaters))
            if not ch:
                runs.append((level, steps, IN, OUT, []))
                return 0.0, nodes, runs
            prod *= len(ch)
            nodes += prod
            IN, OUT = rng.choice(ch)
        ends, tr = level.endings(IN)
        runs.append((level, steps, IN, OUT, ends))
        if not ends:
            return 0.0, nodes, runs
        prod *= len(ends)
        nodes += prod
        end = rng.choice(ends)
        if end[0] == "all" or level.seats_left == 1:
            return prod, nodes, runs
        level = level.after_seating(IN, end[1], tr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-data", default="../stv-rla/data")
    ap.add_argument("-contest", default="FedAus19/FederalSenate2019VIC.json")
    ap.add_argument("-seats", type=int, default=6)
    ap.add_argument("-frac", type=float, default=0.5)
    ap.add_argument("-probes", type=int, default=40)
    ap.add_argument("-seed", type=int, default=2)
    a = ap.parse_args()

    cands, ballots = load(f"{a.data}/{a.contest}")
    names = [c.id for c in cands]
    oc, oa, w = [], [], []
    q, tal, _ = simulate_stv(ballots, cands, a.seats, oc, oa, w)
    ub = math.ceil(min(compute_weub(cands, w, oc, oa, tal), \
        compute_simple_ub(cands, q, w)))
    v = 0
    while oa[v] == 1:
        v += 1
    ct = Count(ballots, len(cands), q, a.seats)
    for _ in range(v):
        ct.step()
    nd = Node(ct.contest(0))
    k = ub * a.frac
    print(f"{a.contest}: UB {ub}, k {k:.0f}, quota {q}, "
          f"{len(nd.hopeful)} standing, {nd.seats_left} seats left; "
          f"reported winners {[names[c] for c in w]}", flush=True)

    root0 = DiagLevel(nd, nd.w, np.zeros(nd.ncand, dtype=bool), \
        nd.seats_left, k)
    top = root0.order[:15]
    print("  largest tallies at the node: " + ", ".join(
        f"{names[c]} {root0.t0[c]:.0f}" for c in top), flush=True)

    rng = random.Random(a.seed)
    t = time.time()
    two_way = Counter()       # candidate -> paths where both branches lived
    for i in range(a.probes):
        root = DiagLevel(nd, nd.w, np.zeros(nd.ncand, dtype=bool), \
            nd.seats_left, k)
        o, n, runs = probe(root, rng)
        print(f"probe {i}: nodes {n:.3g}, outcomes {o:.3g}, "
              f"{time.time() - t:.0f}s", flush=True)
        for r, (lv, steps, IN, OUT, ends) in enumerate(runs):
            free = [s for s in steps if s[2] == 2]
            for s in free:
                two_way[(r, names[s[0]])] += 1
            pr = Counter(x for s in steps for x in s[3] if x)
            standing = [c for c in lv.hopeful if c not in IN]
            print(f"  run {r}: {len(lv.hopeful)} standing -> "
                  f"{len(standing)} left; 2-way decisions {len(free)}; "
                  f"pruned by {dict(pr)}; endings "
                  f"{[e[0] if e[0] == 'all' else names[e[1]] for e in ends]}",
                  flush=True)
            print("    left standing: " + ", ".join(
                f"{names[c]} {lv.t0[c]:.0f}" for c in
                sorted(standing, key=lambda c: -lv.t0[c])), flush=True)
            if free:
                first = free[0]
                print(f"    first 2-way decision: {names[first[0]]} "
                      f"(T0 {first[1]:.0f}) with IN {first[4]}, OUT "
                      f"{first[5]}; could reach quota then: "
                      f"{[names[x] for x in first[6]][:6]}", flush=True)
                tail = [s for s in free if s[1] < 2 * k]
                print(f"    2-way decisions on candidates with T0 < 2k: "
                      f"{len(tail)} (could reach quota at the last one: "
                      f"{[names[x] for x in free[-1][6]][:6]})", flush=True)

    print("candidates most often left undecided-both-ways (run, name): "
          f"{two_way.most_common(20)}", flush=True)


if __name__ == "__main__":
    main()
