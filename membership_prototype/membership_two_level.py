"""
Prototype: size of the membership-branching tree from the node where the
reported count's opening seatings are done (NSW 19 by default) to complete
outcomes, through every remaining seat.

Each level is one run of eliminations between seatings, searched by
IN/OUT membership with the checks of membership_proto.py (E, Q, S, M).
Check E+ shares the budget across OUT candidates: when the IN candidate
c* with the largest tally is eliminated, every OUT candidate d needs at
least T0(c*) - k, and the changed ballots can add under k in total, so
the sum of max(0, T0(c*) - k - Tmax(d)) over d in OUT must be at most k.

With -splus the run-must-end check shares the budget too: the lifts that
keep OUT candidates above c* plus the lift that takes some x to the quota
must total at most k. -order bigup decides candidates over 2k largest
first, then the rest smallest first.

A fully decided run R ends by:
  - seating x, for each x outside R with T_R(x) + k >= quota, where T_R(x)
    is x's tally once R is gone; x's ballots then carry on at transfer
    value max(0, T_R(x) - quota) / T_R(x), and the next level starts; or
  - seating everyone left, when exactly seats-left candidates remain.

Random probes from the root (Knuth's estimator) give the expected number
of complete outcomes and of tree nodes across all levels.

Run from the repository root:
    python3 <this file> [-fracs F ...] [-probes N] [-seed N]
"""
import argparse
import math
import os
import random
import sys
import time

import numpy as np

sys.path.insert(0, os.getcwd())

from measure_batch_seeding import load, Count
from utils import simulate_stv, compute_simple_ub, compute_weub
from membership_proto import Node


class Level:
    """
        One run of eliminations: the ballots' current values w, the
        candidates gone before it, and the seats left.
    """

    def __init__(self, nd, w, gone, seats_left, k, order_mode="desc", \
        splus=False):
        self.nd, self.w, self.gone, self.seats_left, self.k = \
            nd, w, gone, seats_left, k
        self.order_mode, self.splus = order_mode, splus
        self.hopeful = [c for c in nd.hopeful.tolist() if not gone[c]]
        self.t0 = self.tally(gone)
        # desc: largest tally first. bigup: candidates over 2k largest
        # first, then the rest smallest first, so small candidates are
        # settled while the big decisions are known.
        self.order = sorted(self.hopeful, key=lambda c: -self.t0[c])
        if order_mode == "bigup":
            big = [c for c in self.order if self.t0[c] >= 2 * k]
            small = [c for c in reversed(self.order) if self.t0[c] < 2 * k]
            self.order = big + small
        self.tm_cache, self.tf_cache = {}, {}
        self.checks = 0

    def mask(self, cands):
        m = self.gone.copy()
        m[list(cands)] = True
        return m

    def holders(self, gone):
        """ Per ballot, the flat index of its first candidate not gone. """
        return self.nd.first_pos(~gone)

    def tally(self, gone):
        nd = self.nd
        p = self.holders(gone)
        ok = p < nd.big
        return np.bincount(nd.flat[p[ok]], weights=self.w[ok], \
            minlength=nd.ncand)

    def tmax(self, OUT):
        key = frozenset(OUT)
        if key not in self.tm_cache:
            nd = self.nd
            out = np.zeros(nd.ncand, dtype=bool)
            out[list(OUT)] = True
            # Ballots still live at this level: some standing candidate.
            live = self.holders(self.gone) < nd.big
            p = nd.first_pos(out)
            lim = np.where((p < nd.big) & live, p, np.where(live, nd.big, 0))
            before = nd.idx < lim[nd.seg]
            t = np.bincount(nd.flat[before], weights=self.w[nd.seg[before]], \
                minlength=nd.ncand)
            ok = (p < nd.big) & live
            t += np.bincount(nd.flat[p[ok]], weights=self.w[ok], \
                minlength=nd.ncand)
            self.tm_cache = {key: t} if len(self.tm_cache) > 64 \
                else {**self.tm_cache, key: t}
        return self.tm_cache[key]

    def tmin_flow(self, IN):
        key = frozenset(IN)
        if key not in self.tf_cache:
            nd = self.nd
            gone = self.mask(IN)
            p = self.holders(gone)
            ok = p < nd.big
            holder = np.where(ok, nd.flat[np.where(ok, p, 0)], -1)
            tmin = np.bincount(holder[ok], weights=self.w[ok], \
                minlength=nd.ncand)
            # Ballots that a candidate in IN held at this level's start.
            p0 = self.holders(self.gone)
            start = np.where(p0 < nd.big, p0, nd.big)
            before = (nd.idx >= start[nd.seg]) & \
                (nd.idx < np.where(ok, p, 0)[nd.seg])
            x = holder[nd.seg[before]]
            pair = nd.flat[before].astype(np.int64) * nd.ncand + x
            F = np.bincount(pair, weights=self.w[nd.seg[before]], \
                minlength=nd.ncand * nd.ncand).reshape(nd.ncand, nd.ncand)
            self.tf_cache = {key: (tmin, F)} if len(self.tf_cache) > 64 \
                else {**self.tf_cache, key: (tmin, F)}
        return self.tf_cache[key]

    def ok(self, IN, OUT):
        """ False when no run in (IN, OUT) is possible with < k changes. """
        self.checks += 1
        q, k, t0 = self.nd.quota, self.k, self.t0
        if len(self.hopeful) - len(IN) < self.seats_left:
            return False                       # too few left for the seats
        tm = self.tmax(OUT)
        if IN:
            if max(t0[c] for c in self.hopeful) - k >= q:
                return False                                      # Q
            if OUT and max(t0[c] for c in IN) - \
                min(tm[d] for d in OUT) > 2 * k:
                return False                                      # E
            # Shared budget: when c*, the IN candidate with the largest
            # T0, is eliminated, every OUT candidate holds at least as
            # much. Fewer than k changes take under k from c* and add
            # under k in total across the OUT candidates.
            if OUT:
                top = max(t0[c] for c in IN) - k
                if sum(max(0.0, top - tm[d]) for d in OUT) > k:
                    return False                                  # E+
            if OUT:
                tmin, F = self.tmin_flow(IN)
                rows = list(IN)
                for x in OUT:
                    if tmin[x] - F[rows, x].max() - k >= q:
                        return False                              # M
        if self.splus and len(OUT) > self.seats_left:
            # S+: the run must end with someone x reaching the quota. The
            # ballots added to keep the OUT candidates above c* stay with
            # them to the end of the run, so they cannot also lift x: the
            # lifts share the budget.
            top = max(t0[c] for c in IN) - k if IN else -math.inf
            lift = {d: max(0.0, top - tm[d]) for d in OUT}
            total = sum(lift.values())
            if not any(total - lift.get(x, 0.0) + max(lift.get(x, 0.0), \
                q - tm[x]) <= k for x in self.hopeful if x not in IN):
                return False                                      # S+
            return True
        can_seat = any(tm[x] + k >= q for x in self.hopeful if x not in IN)
        if not can_seat and len(OUT) > self.seats_left:
            return False                                          # S
        return True

    def endings(self, R):
        """ Ways a fully decided run R can end: ('seat', x) or ('all',). """
        left = [c for c in self.hopeful if c not in R]
        out = []
        if len(left) == self.seats_left:
            out.append(("all",))
        tr = self.tally(self.mask(R))
        out += [("seat", x) for x in left if tr[x] + self.k >= self.nd.quota]
        return out, tr

    def after_seating(self, R, x, tr):
        """ The next level, once R is gone and x is seated. """
        nd = self.nd
        gone = self.mask(R)
        p = self.holders(gone)
        ok = p < nd.big
        held = np.zeros(len(self.w), dtype=bool)
        held[ok] = nd.flat[p[ok]] == x
        tv = max(0.0, tr[x] - nd.quota) / tr[x] if tr[x] > 0 else 0.0
        w = self.w.copy()
        w[held] *= tv
        gone[x] = True
        return Level(nd, w, gone, self.seats_left - 1, self.k, \
            self.order_mode, self.splus)


def probe(level, rng, stats):
    """
        One random path to a complete outcome. Returns (outcomes, nodes):
        the product of branching factors, and the running sum of products.
    """
    prod, nodes = 1.0, 1.0
    while True:
        IN, OUT = set(), set()
        for c in level.order:
            ch = [s for s in ((IN | {c}, OUT), (IN, OUT | {c})) \
                if level.ok(*s)]
            if not ch:
                return 0.0, nodes
            prod *= len(ch)
            nodes += prod
            IN, OUT = rng.choice(ch)
        ends, tr = level.endings(IN)
        stats["runs"].append((len(level.hopeful), len(IN), len(ends)))
        if not ends:
            return 0.0, nodes
        prod *= len(ends)
        nodes += prod
        end = rng.choice(ends)
        if end[0] == "all" or level.seats_left == 1:
            return prod, nodes
        level = level.after_seating(IN, end[1], tr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-data", default="../stv-rla/data")
    ap.add_argument("-contest", default="FedAus19/FederalSenate2019NSW.json")
    ap.add_argument("-seats", type=int, default=6)
    ap.add_argument("-fracs", nargs="*", type=float, default=[0.5])
    ap.add_argument("-probes", type=int, default=30)
    ap.add_argument("-seed", type=int, default=1)
    ap.add_argument("-order", choices=["desc", "bigup"], default="desc")
    ap.add_argument("-splus", action="store_true",
        help="share the budget in the run-must-end check")
    a = ap.parse_args()

    cands, ballots = load(f"{a.data}/{a.contest}")
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
    print(f"{a.contest}: UB {ub}, quota {q}, {len(nd.hopeful)} standing, "
          f"{nd.seats_left} seats left", flush=True)

    for f in a.fracs:
        k = ub * f
        rng = random.Random(a.seed)
        t = time.time()
        outs, nodes, checks = [], [], 0
        stats = {"runs": []}
        for i in range(a.probes):
            root = Level(nd, nd.w, np.zeros(nd.ncand, dtype=bool), \
                nd.seats_left, k, a.order, a.splus)
            o, n = probe(root, rng, stats)
            outs.append(o)
            nodes.append(n)
            print(f"    probe {i}: outcomes {o:.3g}, nodes {n:.3g}, "
                  f"{time.time() - t:.0f}s", flush=True)
        mean_o = sum(outs) / len(outs)
        mean_n = sum(nodes) / len(nodes)
        print(f"  k={k:.0f} ({f:g} UB): estimated complete outcomes "
              f"{mean_o:.3g}, nodes {mean_n:.3g} (median per probe "
              f"{sorted(nodes)[len(nodes) // 2]:.3g}, max {max(nodes):.3g}); "
              f"dead probes {sum(o == 0 for o in outs)}; "
              f"{time.time() - t:.0f}s", flush=True)
        print(f"  runs seen (standing, eliminated, endings): "
              f"{stats['runs'][:12]}", flush=True)


if __name__ == "__main__":
    main()
