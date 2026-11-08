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
  -sumq   winners seated under the quota leave a shortfall the additions
          must cover; it adds up along the path and every bound below is
          at least the sum, with the additions in E+ and S+ cut by it.
          (Transfer values of such winners are already 0.)
  -sumnq  Q adds up everyone's excess over the quota.
  -elimnq E+ and S+: removals bringing OUT candidates under the quota
          cannot also lower the top IN candidate.
  D   the displacement bound at the start of the run (see disp_costs),
      over the reported losers not in IN; 0 once the outcome has changed
      (a reported loser seated, or a reported winner in IN), and impossible
      when every standing reported loser is in IN.

A fully decided run R ends when some set of candidates holds the quota:
the search branches on that set (adding quota - T_R(z) for each under it,
and T_R(y) - quota for each left out who is over it) and on which of them
is seated first; or by seating everyone left when exactly seats-left
remain. Ballots then pass over the candidates holding the quota, as STV
does, and those candidates are seated next, with no eliminations, keeping
the ballots they held when they reached it. A complete outcome
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


def expand_ranges(starts, ends, owners):
    """
        Every flat index in [start, end) for each pair, with the owner
        (ballot) of each, as arrays.
    """
    lens = np.maximum(ends - starts, 0)
    total = int(lens.sum())
    if total == 0:
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64)
    offsets = np.cumsum(lens) - lens
    pos = np.arange(total) - np.repeat(offsets, lens) + np.repeat(starts, lens)
    return pos, np.repeat(owners, lens)


def prepare(nd):
    """
        Adds to a Node, once: where each ballot's entries end, and each
        candidate's entries (flat indices, in ballot order).
    """
    nd.ends = np.append(nd.start[1:], len(nd.flat)).astype(np.int64)
    order = np.argsort(nd.flat, kind="stable")
    counts = np.bincount(nd.flat, minlength=nd.ncand)
    cuts = np.cumsum(counts)[:-1]
    nd.by_cand = np.split(order.astype(np.int64), cuts)
    return nd


def merged_contest(ct):
    """
        The node's ballots with identical remaining rankings merged (their
        values summed). Identical rankings move together from here on, so
        every tally is unchanged.
    """
    total = {}
    for p, w in zip(ct.prefs, ct.weight):
        total[p] = total.get(p, 0.0) + w
    ct.prefs = list(total)
    ct.weight = [total[p] for p in ct.prefs]
    return ct


def shared_lift_lb(gaps, excess=0.0, deficit=0.0):
    """
        Smallest c with sum of max(0, a - (c - excess)) over gaps at most
        c - deficit, and c >= deficit: the IN candidate with the largest
        tally can be lowered by c less the removals used to bring OUT
        candidates under the quota (excess), and the additions shared
        among the OUT candidates total c less the earlier winners'
        shortfalls (deficit). The best of (sum of the m largest positive
        gaps + m * excess + deficit) / (m + 1) over m >= 0.
    """
    best, total, m = deficit, 0.0, 0
    for g in sorted((g for g in gaps if g > 0), reverse=True):
        m += 1
        total += g
        best = max(best, (total + m * excess + deficit) / (m + 1))
    return best


def end_lb(gaps, own, need, excess=0.0, deficit=0.0):
    """
        Smallest c with the additions keeping the OUT candidates above the
        largest IN tally (each gap a closed down to a - (c - excess)) plus
        x's own lift, max(0, own - (c - excess), need), at most c -
        deficit. own is x's gap to that tally (-inf when x is not in OUT)
        and need = quota - Tmax(x). The left side falls and the right
        side rises with c, so bisect.
    """
    def fits(c):
        if c < excess or c < deficit:
            return False
        low = c - excess
        lift = sum(max(0.0, a - low) for a in gaps)
        return lift + max(0.0, own - low, need) <= c - deficit
    hi = max([0.0, need, own, excess, deficit] + list(gaps)) * 3 + \
        excess + deficit + 1.0
    if not fits(hi):
        return math.inf
    lo = 0.0
    if fits(lo):
        return 0.0
    # Bounds are reported to whole votes; stop well short of that.
    while hi - lo > 1e-3 * max(1.0, hi):
        mid = (lo + hi) / 2
        if fits(mid):
            hi = mid
        else:
            lo = mid
    return hi


class LBLevel(Level):
    """
        A run of eliminations whose checks return lower bounds.

        hold is each ballot's holder (a flat index, or big for an
        exhausted ballot). It is tracked rather than read off the ranking,
        because ballots pass over candidates who already hold the quota.
        queued is the candidates who hold the quota and wait to be seated;
        while any do, nothing can be eliminated, and they keep exactly the
        ballots they held when they reached the quota.
    """

    def __init__(self, nd, w, gone, seats_left, k, hold=None, \
        queued=frozenset()):
        self.nd, self.w, self.gone, self.seats_left, self.k = \
            nd, w, gone, seats_left, k
        self.order_mode, self.splus = "desc", False
        self.queued = frozenset(queued)
        self.hopeful = [c for c in nd.hopeful.tolist() if not gone[c]]
        self.hold = self.holders(gone) if hold is None else hold
        ok = self.hold < nd.big
        self.t0 = np.bincount(nd.flat[self.hold[ok]], weights=w[ok], \
            minlength=nd.ncand)
        self.order = sorted(self.hopeful, key=lambda c: -self.t0[c])
        self.tm_cache, self.tf_cache = {}, {}
        self.checks = 0

    # Best-first search revisits the same IN and OUT sets in no fixed
    # order. A Tmax is one tally per candidate and is kept for many OUT
    # sets; the per-ballot positions behind it (one per ballot) only for
    # the most recent, from which a child's are updated rather than
    # recomputed. The same for Tmin and its flows over IN sets.
    TM_KEEP = 20000
    POS_KEEP = 48
    TF_KEEP = 48

    def _start(self):
        """
            Per run, computed once: each ballot's holder at the run's start
            (a flat index, or big) and whether it is still live.
        """
        st = self.__dict__.get("_st")
        if st is None:
            p0 = self.hold
            st = (p0, p0 < self.nd.big)
            self._st = st
        return st

    @staticmethod
    def _lru_put(store, key, value, keep):
        store[key] = value
        while len(store) > keep:
            store.pop(next(iter(store)))

    def tmax(self, OUT):
        """
            Tmax per candidate: for d in OUT the value of the ballots whose
            first OUT candidate is d; for d outside OUT the value of the
            ballots ranking d above every OUT candidate. Updated from the
            positions of OUT less one candidate when they are kept.
        """
        key = frozenset(OUT)
        tms = self.__dict__.setdefault("_tm", {})
        t = tms.get(key)
        if t is not None:
            return t
        poss = self.__dict__.setdefault("_pos", {})
        nd = self.nd
        _, live = self._start()
        for c in key:
            parent = key - {c}
            if parent in poss and parent in tms:
                p, t = self._add_out(poss[parent], tms[parent], c, live)
                break
        else:
            out = np.zeros(nd.ncand, dtype=bool)
            out[list(key)] = True
            p = nd.first_pos(out)
            lim = np.where(live, np.where(p < nd.big, p, nd.big), 0)
            before = nd.idx < lim[nd.seg]
            t = np.bincount(nd.flat[before], weights=self.w[nd.seg[before]], \
                minlength=nd.ncand)
            ok = (p < nd.big) & live
            t += np.bincount(nd.flat[p[ok]], weights=self.w[ok], \
                minlength=nd.ncand)
        self._lru_put(tms, key, t, self.TM_KEEP)
        self._lru_put(poss, key, p, self.POS_KEEP)
        return t

    def _add_out(self, p_parent, t_parent, c, live):
        """
            Positions and Tmax once c joins OUT. Only live ballots ranking
            c ahead of their first OUT candidate change: the candidates
            between c and that candidate lose the ballot, that candidate
            stops being its first OUT, and c, counted before, counts now as
            its first OUT.
        """
        nd = self.nd
        ent = nd.by_cand[c]
        b = nd.seg[ent]
        sel = live[b] & (ent < p_parent[b])
        ent, b = ent[sel], b[sel]
        old = p_parent[b]
        end = np.where(old < nd.big, old, nd.ends[b])
        pos, bb = expand_ranges(ent + 1, end, b)
        t = t_parent.copy()
        if len(pos):
            t -= np.bincount(nd.flat[pos], weights=self.w[bb], \
                minlength=nd.ncand)
        had = old < nd.big
        if had.any():
            t -= np.bincount(nd.flat[old[had]], weights=self.w[b[had]], \
                minlength=nd.ncand)
        p = p_parent.copy()
        p[b] = ent
        return p, t

    def tmin_flow(self, IN):
        """
            Tmin: tallies with IN gone. F[l, x]: value of the ballots x
            holds then that rank l above x since the run's start. Updated
            from IN less one candidate when kept.
        """
        key = frozenset(IN)
        tfs = self.__dict__.setdefault("_tf", {})
        v = tfs.get(key)
        if v is not None:
            return v[1], v[2]
        nd = self.nd
        p0, live = self._start()
        gone = self.mask(key)
        for c in key:
            parent = key - {c}
            if parent in tfs:
                h, tmin, F = self._add_in(*tfs[parent], c, gone, p0)
                break
        else:
            h = self.holders(gone)
            ok = h < nd.big
            holder = np.where(ok, nd.flat[np.where(ok, h, 0)], -1)
            tmin = np.bincount(holder[ok], weights=self.w[ok], \
                minlength=nd.ncand)
            start = np.where(p0 < nd.big, p0, nd.big)
            before = (nd.idx >= start[nd.seg]) & \
                (nd.idx < np.where(ok, h, 0)[nd.seg])
            x = holder[nd.seg[before]]
            pair = nd.flat[before].astype(np.int64) * nd.ncand + x
            F = np.bincount(pair, weights=self.w[nd.seg[before]], \
                minlength=nd.ncand * nd.ncand).reshape(nd.ncand, nd.ncand)
        self._lru_put(tfs, key, (h, tmin, F), self.TF_KEEP)
        return tmin, F

    def _add_in(self, h_parent, tmin_parent, F_parent, c, gone, p0):
        """
            Holders, Tmin and F once c joins IN. Only the ballots c holds
            move, to their next candidate not gone, and that candidate's
            column of F gains their whole span since the run's start.
        """
        nd = self.nd
        ok = h_parent < nd.big
        moved = np.nonzero(ok)[0]
        moved = moved[nd.flat[h_parent[moved]] == c]
        pos = h_parent[moved] + 1
        end = nd.ends[moved]
        active = pos < end
        while active.any():
            act = np.nonzero(active)[0]
            step = gone[nd.flat[pos[act]]]
            pos[act[step]] += 1
            active[act[~step]] = False
            active &= pos < end
        new_h = np.where(pos < end, pos, nd.big)
        h = h_parent.copy()
        h[moved] = new_h
        tmin = tmin_parent.copy()
        tmin[c] = 0.0
        has = new_h < nd.big
        x = nd.flat[new_h[has]]
        tmin += np.bincount(x, weights=self.w[moved[has]], minlength=nd.ncand)
        F = F_parent.copy()
        F[:, c] = 0.0                     # c holds nothing now
        span, bb = expand_ranges(p0[moved[has]], new_h[has], moved[has])
        if len(span):
            pair = nd.flat[span].astype(np.int64) * nd.ncand + nd.flat[h[bb]]
            F += np.bincount(pair, weights=self.w[bb], \
                minlength=nd.ncand * nd.ncand).reshape(nd.ncand, nd.ncand)
        return h, tmin, F

    def disp_costs(self, reported):
        """
            Displacement bound at the start of this run (as
            compute_disp_lb_STV26_q_prefix in stvtree.py computes it for the
            prefix ending with the last seating). Returns (W, costs): W is
            the reported winners still standing and costs[l] the bound
            for reported loser l being the one who wins:

              max(displacement, min(quota_cost, left_at_end_cost))

            where, with min_r[r] r's tally now, present[l] the value of the
            ballots on which l still stands and above[r][l] those that rank
            r above l, dp(r) = max(0, (min_r[r] - (present[l] -
            above[r][l])) / 2) is the cost of l outlasting r;
            displacement is the least dp(r) over reported winners r,
            quota_cost = quota - present[l], and left_at_end_cost the
            largest of the (standing - seats left) smallest dp(r).
            Computed once per run.
        """
        cached = self.__dict__.get("_disp")
        if cached is not None:
            return cached
        nd = self.nd
        standing = np.zeros(nd.ncand, dtype=bool)
        standing[self.hopeful] = True
        _, live = self._start()
        keep = standing[nd.flat] & live[nd.seg]
        flat, seg, idx = nd.flat[keep], nd.seg[keep], nd.idx[keep]
        w = self.w[seg]
        present = np.bincount(flat, weights=w, minlength=nd.ncand)
        above = {}
        for r in self.hopeful:
            at = np.full(len(self.w), nd.big, dtype=np.int64)
            hit = flat == r
            at[seg[hit]] = idx[hit]
            after = idx > at[seg]
            above[r] = np.bincount(flat[after], weights=w[after], \
                minlength=nd.ncand)
        W = [c for c in self.hopeful if c in reported]
        losers = [c for c in self.hopeful if c not in reported]
        nleft = len(self.hopeful)
        costs = {}
        for l in losers:
            dps, disp = [], math.inf
            for r in self.hopeful:
                if r == l:
                    continue
                dp = max(0.0, 0.5 * (self.t0[r] - (present[l] - above[r][l])))
                dps.append(dp)
                if r in reported:
                    disp = min(disp, dp)
            dps.sort()
            need = nleft - self.seats_left
            left_end = max(dps[:need]) if need > 0 else 0.0
            quota_cost = max(0.0, self.nd.quota - present[l])
            costs[l] = max(disp, min(quota_cost, left_end))
        self._disp = (set(W), costs)
        return self._disp

    def dlb(self, IN, reported, changed):
        """
            Displacement bound for the family (IN, OUT): 0 once the outcome
            has changed (a reported loser seated, or a reported winner in
            IN); inf when every standing reported loser is in IN; otherwise
            the least cost over the reported losers not in IN.
        """
        if changed:
            return 0.0
        W, costs = self.disp_costs(reported)
        if W & IN or not W:
            return 0.0
        left = [costs[l] for l in costs if l not in IN]
        return min(left) if left else math.inf

    def lb(self, IN, OUT, floor, deficit=0.0, opts=None):
        """
            Lower bound on the changed ballots any run in (IN, OUT) needs;
            inf when none is possible. floor is the bound the node already
            has, which lets the costly M check be skipped when it cannot
            raise it. deficit is the earlier winners' summed shortfall under
            the quota (-sumq), which the additions cannot also cover. opts
            holds the -sumnq and -elimnq switches.
        """
        q, t0 = self.nd.quota, self.t0
        sumnq = opts is not None and opts.sumnq
        elimnq = opts is not None and opts.elimnq
        if len(self.hopeful) - len(IN) < self.seats_left:
            return math.inf                                       # few
        tm = self.tmax(OUT)
        best = deficit
        gaps = {}
        excess = 0.0
        if IN:
            # Q: nobody holds a quota when the first elimination happens.
            # -sumnq: one removed ballot lowers one candidate at a time, so
            # the excesses add up.
            over = [t0[c] - q for c in self.hopeful]
            best = max(best, max(over))
            if sumnq:
                best = max(best, sum(e for e in over if e > 0))
            top = max(t0[c] for c in IN)
            if OUT:
                gaps = {d: top - tm[d] for d in OUT}
                # -elimnq: OUT candidates over the quota at the run's start
                # are over it when the top IN candidate goes, and bringing
                # them under uses removals that cannot also lower it.
                if elimnq:
                    excess = sum(max(0.0, t0[d] - q) for d in OUT)
                best = max(best, shared_lift_lb(gaps.values(), excess, \
                    deficit))                                      # E+
                # M can only exceed tm[x] - quota, so skip it below floor.
                if any(tm[x] - q > max(best, floor) for x in OUT):
                    tmin, F = self.tmin_flow(IN)
                    rows = list(IN)
                    for x in OUT:
                        best = max(best, tmin[x] - F[rows, x].max() - q)
        if len(OUT) > self.seats_left:                             # S+
            best = max(best, min(end_lb(
                [a for d, a in gaps.items() if d != x],
                gaps.get(x, -math.inf), q - tm[x], excess, deficit)
                for x in self.hopeful if x not in IN))
        return best

    def after_run(self, R):
        """
            Tallies and holders once the run R is gone. Eliminations happen
            only when nobody holds the quota, so then every ballot sits with
            its first candidate still standing.
        """
        if not R:
            return self.t0, self.hold
        assert not self.queued
        h = self.holders(self.mask(R))
        ok = h < self.nd.big
        t = np.bincount(self.nd.flat[h[ok]], weights=self.w[ok], \
            minlength=self.nd.ncand)
        return t, h

    def after_seating(self, R, x, H):
        """
            The next run, once R is gone and x is seated while the
            candidates in H hold the quota (x among them). x's ballots move
            on at its transfer value to their next candidate that is
            neither gone nor holding the quota (utils.next_candidate); the
            others in H keep their ballots and wait to be seated.
        """
        nd = self.nd
        tr, h = self.after_run(R)
        gone = self.mask(R)
        gone[x] = True
        skip = gone.copy()
        skip[list(H)] = True
        ok = h < nd.big
        moved = np.nonzero(ok)[0]
        moved = moved[nd.flat[h[moved]] == x]
        tv = max(0.0, tr[x] - nd.quota) / tr[x] if tr[x] > 0 else 0.0
        w = self.w.copy()
        w[moved] *= tv
        pos = h[moved] + 1
        end = nd.ends[moved]
        active = pos < end
        while active.any():
            act = np.nonzero(active)[0]
            step = skip[nd.flat[pos[act]]]
            pos[act[step]] += 1
            active[act[~step]] = False
            active &= pos < end
        hold = h.copy()
        hold[moved] = np.where(pos < end, pos, nd.big)
        return LBLevel(nd, w, gone, self.seats_left - 1, self.k, hold, \
            frozenset(H) - {x})


class Levels:
    """
        Runs reached so far, keyed by the path of (run, seated candidate,
        quota holders) triples from the opening node. Building one costs ballot passes and
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
        R, x, H = key[-1]
        lvl = parent.after_seating(set(R), x, H)
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
    ap.add_argument("-sumq", action="store_true", help="carry the shortfalls "
        "of winners seated under the quota (they take additions)")
    ap.add_argument("-sumnq", action="store_true", help="add up the "
        "excesses over the quota in Q")
    ap.add_argument("-elimnq", action="store_true", help="share removals "
        "between the top IN candidate and OUT candidates over the quota")
    ap.add_argument("-nodlb", action="store_true", help="leave out the "
        "displacement bound")
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
    base = merged_contest(ct.contest(0))
    nd = prepare(Node(base))
    opening = set(oc[:v])
    reported = set(w)
    print(f"{a.contest}: UB {ub}, quota {q}, opening {v} seatings "
          f"(cost to leave it {xp[v]:.0f}), {len(nd.hopeful)} standing, "
          f"{nd.seats_left} seats left, {len(nd.start)} distinct remaining "
          f"rankings; sumq {a.sumq}, sumnq {a.sumnq}, "
          f"elimnq {a.elimnq}, displacement {not a.nodlb}", flush=True)

    if ct.queue:
        sys.exit(f"candidates {ct.queue} hold the quota at the starting "
                 "node; start after they are seated")
    root = LBLevel(nd, nd.w, np.zeros(nd.ncand, dtype=bool), \
        nd.seats_left, math.inf)
    levels = Levels(root)

    # Node: (lb, tie, key, IN, OUT, i, seated). key names the run, i is the
    # next candidate to decide, seated the candidates seated since the
    # opening. i == None marks a fully decided run waiting to end.
    tie = itertools.count()
    heap = [(0.0, next(tie), (), frozenset(), frozenset(), 0, (), 0.0)]
    t0 = time.time()
    last = t0
    pops = 0
    lb = 0.0
    result = None

    def push(bound, key, IN, OUT, i, seated, deficit):
        if bound < ub:
            heapq.heappush(heap, (bound, next(tie), key, IN, OUT, i, seated, \
                deficit))

    while heap:
        node = heapq.heappop(heap)
        bound, _, key, IN, OUT, i, seated, deficit = node
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
        # A reported loser seated on this path has changed the outcome.
        changed = any(x not in reported for x in seated)
        if i != "end" and i < len(lvl.order):
            c = lvl.order[i]
            for child_in, child_out in ((IN | {c}, OUT), (IN, OUT | {c})):
                b = max(bound, lvl.lb(child_in, child_out, bound, deficit, a))
                if not a.nodlb:
                    b = max(b, lvl.dlb(child_in, reported, changed))
                push(b, key, child_in, child_out, i + 1, seated, deficit)
            continue

        # The run is decided (i == "end": empty, as someone waits to be
        # seated). Branch on who holds the quota now: those already
        # waiting, plus any set N of others. Each one in N under the quota
        # needs additions; each over it and left out needs removals. Then
        # seat any one of them.
        tr, _ = lvl.after_run(IN)
        left = [c for c in lvl.hopeful if c not in IN]
        queued = lvl.queued
        if len(left) == lvl.seats_left:
            winners = opening | set(seated) | set(left)
            if winners != reported:
                push(bound, key, IN, OUT, "leaf", seated, deficit)
        over = [y for y in left if y not in queued and tr[y] >= q]
        elig = [z for z in left if z not in queued and q - tr[z] < ub]
        room = lvl.seats_left - len(queued)
        for size in range(min(room, len(elig)) + 1):
            for N in itertools.combinations(elig, size):
                H = queued | frozenset(N)
                if not H:
                    continue
                lift = sum(max(0.0, q - tr[z]) for z in N)
                outs = [tr[y] - q for y in over if y not in N]
                lower = (sum(outs) if a.sumnq else max(outs)) if outs else 0.0
                nxt = deficit + lift if a.sumq else 0.0
                b = max(bound, lift, nxt, lower)
                for x in H:
                    now_seated = seated + (x,)
                    if lvl.seats_left == 1:
                        if opening | set(now_seated) != reported:
                            push(b, key, IN, OUT, "leaf", now_seated, nxt)
                        continue
                    push(b, key + ((frozenset(IN), x, H),), frozenset(), \
                        frozenset(), "end" if len(H) > 1 else 0, \
                        now_seated, nxt)

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
