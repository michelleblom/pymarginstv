"""
Prototype: best-first search with membership branching and lower bounds.

Starts at the node where the reported count's opening seatings are done.
Each run of eliminations between seatings is searched by deciding, for one
candidate at a time (largest tally first), whether it is eliminated in the
run (IN) or still standing when the run ends (OUT). A node stands for
every run that eliminates all of IN and none of OUT, in any order.

Every node carries a lower bound on the changed ballots any election in
its family needs: the largest, over the node's path, of the checks of
membership_two_level.py turned into numbers. With c changed ballots every
tally at the start of a run moves by at most c, value removed totals at
most c and value added totals at most c. With top the largest starting
tally in IN, a_d = top - Tmax(d) for d in OUT, and T0 the tallies at the
start of the run:

  Q   IN not empty: max T0 - quota (someone already holds a quota).
  E+  IN and OUT not empty: max over m of (sum of the m largest positive
      a_d) / (m + 1). When the IN candidate with tally top is eliminated
      every OUT candidate holds at least as much; it can be lowered by
      under c and the additions shared among the OUT candidates total
      under c. Its m = 1 case is the pairwise bound a_d / 2.
  M   x in OUT: Tmin(x) - F(x) - quota, x's least tally before the run's
      last elimination less the quota.
  S+  more OUT candidates than seats left: the smallest c for which some
      x outside IN can reach the quota at the run's end, the additions
      that lift x sharing c with those keeping OUT above top.
  few IN leaves fewer than seats-left candidates: impossible.

A fully decided run R ends by seating x (bound quota - T_R(x)), or by
seating everyone left when exactly seats-left remain. A complete outcome
whose winners differ from the reported ones ends the search: every node
left has a bound at least as large, so the margin, over elections that
follow the opening seatings, is at least that bound. Elections that do
not follow the opening need at least the opening's cost X(P), so the
reported lower bound is min(X(P), the search's bound).

Run from the repository root:
    python3 membership_prototype/membership_search.py [-contest PATH]
        [-seats N] [-limit SECONDS] [-report SECONDS]
"""
import argparse
import heapq
import itertools
import math
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from measure_batch_seeding import load, Count, forced_profile
from utils import simulate_stv, compute_simple_ub, compute_weub
from membership_proto import Node
from membership_two_level import Level


def shared_lift_lb(gaps):
    """
        Smallest c with sum of max(0, a - c) over gaps at most c: the best
        of (sum of the m largest positive gaps) / (m + 1) over m.
    """
    best, total, m = 0.0, 0.0, 0
    for g in sorted((g for g in gaps if g > 0), reverse=True):
        m += 1
        total += g
        best = max(best, total / (m + 1))
    return best


def end_lb(gaps, own, need):
    """
        Smallest c >= 0 with sum of max(0, a - c) over gaps, plus
        max(0, own - c, need), at most c. own is x's own gap to top
        (-inf when x is not in OUT) and need = quota - Tmax(x). The left
        side falls and the right side rises with c, so bisect.
    """
    def fits(c):
        lift = sum(max(0.0, a - c) for a in gaps)
        return lift + max(0.0, own - c, need) <= c
    hi = max([0.0, need, own] + list(gaps)) * 2 + 1.0
    if not fits(hi):
        return math.inf
    lo = 0.0
    if fits(lo):
        return 0.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if fits(mid):
            hi = mid
        else:
            lo = mid
    return hi


class LBLevel(Level):
    """ A run of eliminations whose checks return lower bounds. """

    # Best-first search revisits the same IN and OUT sets in no fixed
    # order, so keep many: a Tmax is one tally per candidate, a Tmin with
    # its flows one table of them.
    TM_KEEP = 20000
    TF_KEEP = 500

    def tmax(self, OUT):
        key = frozenset(OUT)
        store = self.__dict__.setdefault("_tm", {})
        t = store.get(key)
        if t is None:
            self.tm_cache = {}            # the parent's own small cache
            t = Level.tmax(self, OUT)
            store[key] = t
            while len(store) > self.TM_KEEP:
                store.pop(next(iter(store)))
        return t

    def tmin_flow(self, IN):
        key = frozenset(IN)
        store = self.__dict__.setdefault("_tf", {})
        v = store.get(key)
        if v is None:
            self.tf_cache = {}
            v = Level.tmin_flow(self, IN)
            store[key] = v
            while len(store) > self.TF_KEEP:
                store.pop(next(iter(store)))
        return v

    def lb(self, IN, OUT, floor):
        """
            Lower bound on the changed ballots any run in (IN, OUT) needs;
            inf when none is possible. floor is the bound the node already
            has, which lets the costly M check be skipped when it cannot
            raise it.
        """
        q, t0 = self.nd.quota, self.t0
        if len(self.hopeful) - len(IN) < self.seats_left:
            return math.inf                                       # few
        tm = self.tmax(OUT)
        best = 0.0
        gaps = {}
        if IN:
            best = max(best, max(t0[c] for c in self.hopeful) - q)  # Q
            top = max(t0[c] for c in IN)
            if OUT:
                gaps = {d: top - tm[d] for d in OUT}
                best = max(best, shared_lift_lb(gaps.values()))    # E+
                # M can only exceed tm[x] - quota, so skip it below floor.
                if any(tm[x] - q > max(best, floor) for x in OUT):
                    tmin, F = self.tmin_flow(IN)
                    rows = list(IN)
                    for x in OUT:
                        best = max(best, tmin[x] - F[rows, x].max() - q)
        if len(OUT) > self.seats_left:                             # S+
            best = max(best, min(end_lb(
                [a for d, a in gaps.items() if d != x],
                gaps.get(x, -math.inf), q - tm[x])
                for x in self.hopeful if x not in IN))
        return best

    def after_seating(self, R, x, tr):
        """ The next run, once R is gone and x is seated. """
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
        return LBLevel(nd, w, gone, self.seats_left - 1, self.k)


class Levels:
    """
        Runs reached so far, keyed by the path of (run, seated candidate)
        pairs from the opening node. Building one costs ballot passes and
        a copy of the ballot values, so only the most recent are kept and
        the rest are rebuilt from their parent when needed.
    """

    def __init__(self, root, keep=24):
        self.root, self.keep = root, keep
        self.cache = {(): root}
        self.order = [()]

    def get(self, key):
        if key in self.cache:
            return self.cache[key]
        parent = self.get(key[:-1])
        R, x = key[-1]
        tr = parent.tally(parent.mask(R))
        lvl = parent.after_seating(set(R), x, tr)
        self.cache[key] = lvl
        self.order.append(key)
        while len(self.cache) > self.keep:
            old = self.order.pop(1)       # never the root
            self.cache.pop(old, None)
        return lvl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-data", default="../stv-rla/data")
    ap.add_argument("-contest", default="FedAus19/FederalSenate2019NSW.json")
    ap.add_argument("-seats", type=int, default=6)
    ap.add_argument("-limit", type=float, default=3600)
    ap.add_argument("-report", type=float, default=60)
    a = ap.parse_args()

    cands, ballots = load(f"{a.data}/{a.contest}")
    oc, oa, w = [], [], []
    q, tal, _ = simulate_stv(ballots, cands, a.seats, oc, oa, w)
    ub = math.ceil(min(compute_weub(cands, w, oc, oa, tal), \
        compute_simple_ub(cands, q, w)))
    v = 0
    while oa[v] == 1:
        v += 1
    xp, _ = forced_profile(ballots, len(cands), q, a.seats, oc, oa)
    ct = Count(ballots, len(cands), q, a.seats)
    for _ in range(v):
        ct.step()
    nd = Node(ct.contest(0))
    opening = set(oc[:v])
    reported = set(w)
    print(f"{a.contest}: UB {ub}, quota {q}, opening {v} seatings "
          f"(cost to leave it {xp[v]:.0f}), {len(nd.hopeful)} standing, "
          f"{nd.seats_left} seats left", flush=True)

    root = LBLevel(nd, nd.w, np.zeros(nd.ncand, dtype=bool), \
        nd.seats_left, math.inf)
    levels = Levels(root)

    # Node: (lb, tie, key, IN, OUT, i, seated). key names the run, i is the
    # next candidate to decide, seated the candidates seated since the
    # opening. i == None marks a fully decided run waiting to end.
    tie = itertools.count()
    heap = [(0.0, next(tie), (), frozenset(), frozenset(), 0, ())]
    t0 = time.time()
    last = t0
    pops = 0
    lb = 0.0
    result = None

    def push(bound, key, IN, OUT, i, seated):
        if bound < ub:
            heapq.heappush(heap, (bound, next(tie), key, IN, OUT, i, seated))

    while heap:
        node = heapq.heappop(heap)
        bound, _, key, IN, OUT, i, seated = node
        lb = max(lb, bound)
        pops += 1
        now = time.time()
        if now - last >= a.report:
            bs = sorted(n[0] for n in heap)
            mid = bs[len(bs) // 2] if bs else math.nan
            print(f"  {now - t0:.0f}s: {pops} nodes expanded, lower bound "
                  f"{lb:.1f}, frontier {len(heap)} (bound 0: "
                  f"{sum(b == 0 for b in bs)}, median bound {mid:.0f}), "
                  f"runs cached {len(levels.cache)}", flush=True)
            last = now
        if now - t0 > a.limit:
            break
        if i == "leaf":
            result = bound
            break

        lvl = levels.get(key)
        if i < len(lvl.order):
            c = lvl.order[i]
            for child_in, child_out in ((IN | {c}, OUT), (IN, OUT | {c})):
                b = max(bound, lvl.lb(child_in, child_out, bound))
                push(b, key, child_in, child_out, i + 1, seated)
            continue

        # The run is decided: end it by seating someone.
        left = [c for c in lvl.hopeful if c not in IN]
        tr = lvl.tally(lvl.mask(IN))
        if len(left) == lvl.seats_left:
            winners = opening | set(seated) | set(left)
            if winners != reported:
                push(bound, key, IN, OUT, "leaf", seated)
        for x in left:
            b = max(bound, q - tr[x])
            if lvl.seats_left == 1:
                if opening | set(seated) | {x} != reported:
                    push(b, key, IN, OUT, "leaf", seated + (x,))
            else:
                push(b, key + ((frozenset(IN), x),), frozenset(), \
                    frozenset(), 0, seated + (x,))

    elapsed = time.time() - t0
    if result is not None:
        search = result
        how = "a changed outcome reached"
    elif not heap:
        search = ub
        how = "every family below the UB ruled out"
    else:
        search = lb
        how = "time limit"
    print(f"  stopped after {elapsed:.0f}s ({how}): {pops} nodes expanded, "
          f"search lower bound {search:.1f}", flush=True)
    print(f"  margin lower bound min(opening {xp[v]:.0f}, search "
          f"{search:.1f}) = {min(xp[v], search):.1f}", flush=True)


if __name__ == "__main__":
    main()
