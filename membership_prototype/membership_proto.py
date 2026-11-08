"""
Prototype: branch on membership of the current elimination run.

At a node P (here: the reported count's opening seatings, by default on
NSW 19), each search node is (IN, OUT): IN are eliminated before the next
seating, OUT still stand at it, the rest are undecided. It stands for every
run R with IN <= R and R disjoint from OUT, in any order.

A node is pruned when no run in it is possible with fewer than k changed
ballots (every tally at P moves by at most k):

  E  some c in IN and d in OUT with T0(c) - Tmax(d) > 2k:
     c's tally when eliminated is at least T0(c), its tally at P;
     d's is at most Tmax(d), its tally with everyone outside OUT gone.
  Q  IN is not empty but some candidate has T0 - k >= quota at P, so the
     next step must be a seating.
  S  nobody can be seated when the run ends (Tmax(x) + k < quota for every
     x outside IN) and more than seats-left candidates must stand.
  M  some x in OUT reaches the quota before the run's last elimination:
     just before it, x holds at least Tmin(x) - F(x), where Tmin(x) is
     x's tally with IN gone and F(x) the most a single IN candidate could
     still have to pass to x. If that, less k, is at least the quota, the
     run would have ended earlier.

Reports, for each k: how many candidates are forced at the root, a capped
depth-first count of nodes, and a random-probe (Knuth) estimate of the
number of fully decided runs.

Run from the repository root:
    python3 <this file> [-data DIR] [-contest PATH] [-seats N]
        [-fracs F ...] [-probes N] [-cap N]
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


class Node:
    """ Ballots at the base node P, in flat arrays for fast tallies. """

    def __init__(self, ct):
        self.quota = ct.quota
        self.seats_left = ct.seats_left
        self.hopeful = np.array(ct.hopeful)
        self.ncand = ct.ncand
        lens = np.array([len(p) for p in ct.prefs])
        self.start = np.concatenate(([0], np.cumsum(lens)[:-1]))
        self.flat = np.fromiter((c for p in ct.prefs for c in p), \
            dtype=np.int16, count=int(lens.sum()))
        self.seg = np.repeat(np.arange(len(lens)), lens)
        self.w = np.array(ct.weight)
        self.idx = np.arange(len(self.flat))
        self.big = len(self.flat)
        self.t0 = self.first_tally(np.zeros(self.ncand, dtype=bool))

    def first_pos(self, mask):
        """ Per ballot, the flat index of its first candidate in mask. """
        hit = np.where(mask[self.flat], self.idx, self.big)
        return np.minimum.reduceat(hit, self.start)

    def first_tally(self, gone):
        """ Tallies with the candidates in 'gone' removed. """
        p = self.first_pos(~gone)
        ok = p < self.big
        return np.bincount(self.flat[p[ok]], weights=self.w[ok], \
            minlength=self.ncand)

    def tmin_flow(self, gone):
        """
            Tmin: tallies with the candidates in 'gone' removed. F[l, x]:
            value of the ballots that x holds then and that rank l (in
            'gone') above x.
        """
        p = self.first_pos(~gone)
        ok = p < self.big
        holder = np.where(ok, self.flat[np.where(ok, p, 0)], -1)
        tmin = np.bincount(holder[ok], weights=self.w[ok], \
            minlength=self.ncand)
        before = self.idx < np.where(ok, p, 0)[self.seg]
        x = holder[self.seg[before]]
        pair = self.flat[before].astype(np.int64) * self.ncand + x
        F = np.bincount(pair, weights=self.w[self.seg[before]], \
            minlength=self.ncand * self.ncand).reshape(self.ncand, self.ncand)
        return tmin, F

    def tmax(self, out):
        """
            Tmax for every candidate: for d in OUT, the value of ballots
            whose first OUT candidate is d; for d outside OUT, the value of
            ballots ranking d above every OUT candidate.
        """
        p = self.first_pos(out)
        before = self.idx < np.where(p < self.big, p, self.big)[self.seg]
        t = np.bincount(self.flat[before], weights=self.w[self.seg[before]], \
            minlength=self.ncand)
        ok = p < self.big
        t += np.bincount(self.flat[p[ok]], weights=self.w[ok], \
            minlength=self.ncand)
        return t


def pruned(nd, IN, OUT, tm, k, tmin_flow=None):
    """ True when no run in (IN, OUT) is possible with fewer than k changes. """
    q = nd.quota
    if IN:
        if max(nd.t0[c] for c in IN) - k >= q or \
            max(nd.t0[c] for c in nd.hopeful) - k >= q:
            return True                                           # Q
        if OUT and max(nd.t0[c] for c in IN) - \
            min(tm[d] for d in OUT) > 2 * k:
            return True                                           # E
    if IN and OUT and tmin_flow is not None:
        tmin, F = tmin_flow(IN)
        rows = list(IN)
        for x in OUT:
            if tmin[x] - F[rows, x].max() - k >= q:
                return True                                       # M
    can_seat = any(tm[x] + k >= q for x in nd.hopeful if x not in IN)
    if not can_seat and len(OUT) > nd.seats_left:
        return True                                               # S
    return False


class Search:
    def __init__(self, nd, k, order):
        self.nd, self.k, self.order = nd, k, order
        self.tm_cache = {}
        self.tf_cache = {}
        self.evals = 0

    def tm(self, OUT):
        key = frozenset(OUT)
        if key not in self.tm_cache:
            mask = np.zeros(self.nd.ncand, dtype=bool)
            mask[list(OUT)] = True
            self.tm_cache[key] = self.nd.tmax(mask)
            if len(self.tm_cache) > 64:
                self.tm_cache.pop(next(iter(self.tm_cache)))
        return self.tm_cache[key]

    def tf(self, IN):
        key = frozenset(IN)
        if key not in self.tf_cache:
            mask = np.zeros(self.nd.ncand, dtype=bool)
            mask[list(IN)] = True
            self.tf_cache[key] = self.nd.tmin_flow(mask)
            if len(self.tf_cache) > 64:
                self.tf_cache.pop(next(iter(self.tf_cache)))
        return self.tf_cache[key]

    def ok(self, IN, OUT):
        self.evals += 1
        return not pruned(self.nd, IN, OUT, self.tm(OUT), self.k, self.tf)

    def children(self, IN, OUT, i):
        c = self.order[i]
        out = []
        if self.ok(IN | {c}, OUT):
            out.append((IN | {c}, OUT))
        if self.ok(IN, OUT | {c}):
            out.append((IN, OUT | {c}))
        return out

    def forced_at_root(self):
        """ Candidates one of whose branches is pruned with nothing else set. """
        n_in = n_out = 0
        for c in self.order:
            a = self.ok({c}, set())
            b = self.ok(set(), {c})
            n_in += (not b) and a
            n_out += (not a) and b
        return n_in, n_out

    def dfs(self, cap):
        """ Nodes visited depth first, stopping after cap. """
        stack = [(set(), set(), 0)]
        seen = leaves = 0
        while stack and seen < cap:
            IN, OUT, i = stack.pop()
            seen += 1
            if i == len(self.order):
                leaves += 1
                continue
            for a, b in self.children(IN, OUT, i):
                stack.append((a, b, i + 1))
        return seen, leaves, bool(stack)

    def knuth(self, probes, rng):
        """
            Random probes from the root; along a probe the product of the
            numbers of surviving children estimates the number of fully
            decided runs, and its running sum the number of nodes.
        """
        leaves, nodes = [], []
        for _ in range(probes):
            IN, OUT, prod, tot = set(), set(), 1.0, 1.0
            for i in range(len(self.order)):
                ch = self.children(IN, OUT, i)
                if not ch:
                    prod = 0.0
                    break
                prod *= len(ch)
                tot += prod
                IN, OUT = rng.choice(ch)
            leaves.append(prod)
            nodes.append(tot)
        return sum(leaves) / probes, sum(nodes) / probes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-data", default="../stv-rla/data")
    ap.add_argument("-contest", default="FedAus19/FederalSenate2019NSW.json")
    ap.add_argument("-seats", type=int, default=6)
    ap.add_argument("-fracs", nargs="*", type=float, \
        default=[1, 1/4, 1/16, 1/64])
    ap.add_argument("-probes", type=int, default=20)
    ap.add_argument("-cap", type=int, default=2000)
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
    order = sorted(nd.hopeful.tolist(), key=lambda c: -nd.t0[c])
    print(f"{a.contest}: UB {ub}, quota {q}, {len(order)} standing, "
          f"{nd.seats_left} seats left, {len(nd.flat)} preference entries",
          flush=True)
    print(f"  candidates with T0 > 2*UB: "
          f"{sum(nd.t0[c] > 2 * ub for c in order)}", flush=True)

    for f in a.fracs:
        k = ub * f
        t = time.time()
        s = Search(nd, k, order)
        fin, fout = s.forced_at_root()
        seen, leaves, more = s.dfs(a.cap)
        est_leaves, est_nodes = s.knuth(a.probes, random.Random(1))
        free = sum(nd.t0[c] <= 2 * k for c in order)
        print(f"  k={k:.0f} ({f:g} UB): forced at root IN {fin} OUT {fout}; "
              f"T0 <= 2k: {free}; DFS {seen} nodes, {leaves} full runs"
              f"{' (cap hit)' if more else ''}; estimated full runs "
              f"{est_leaves:.3g}, nodes {est_nodes:.3g}; "
              f"{s.evals} checks, {time.time() - t:.0f}s", flush=True)


if __name__ == "__main__":
    main()
