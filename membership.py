"""
-membership: lower bounds for a run of eliminations that is still open.

Between two seatings the search decides, one candidate at a time, whether
it is eliminated in the current run (IN) or still standing when the run
ends (OUT). A node stands for every run that eliminates all of IN and none
of OUT, in any order. RunState holds the ballots at the start of the run
and gives, for any IN and OUT, a lower bound on the changed ballots every
election in that family needs.

Every check uses the state at the run's start. With c changed ballots
every tally there moves by at most c, the value removed totals at most c
and the value added totals at most c, less the shortfalls of winners
seated under the quota (deficit, -sumq). With T0 the tallies at the run's
start, Tmax(d) d's tally once everyone outside OUT is gone, and top the
largest T0 in IN:

  few  IN leaves fewer than seats-left candidates standing: impossible.
  Q    IN not empty: nobody holds a quota when the first elimination
       happens, so max T0 - quota (-sumnq: the sum of the excesses).
  E+   IN and OUT not empty: when the IN candidate with tally top goes,
       every OUT candidate holds at least as much. For IN's largest few
       candidates l (depth), also with each OUT candidate's tally taken
       while l still stands, which excludes the rows ranking l above it. It can be lowered by
       c less the removals that bring OUT candidates under the quota
       (-elimnq), and the additions shared among the OUT candidates total
       c - deficit.
  M    x in OUT: x's least tally before the run's last elimination less
       the quota, as the run would otherwise have ended earlier.
  S+   more OUT candidates than seats left: someone outside IN must reach
       the quota when the run ends, and the additions that lift them share
       the budget with those keeping OUT above top.
  D    the displacement bound at the run's start (as
       compute_disp_lb_STV26_q_prefix computes it there), over the reported
       losers not in IN: 0 once the outcome has changed, impossible when
       every standing reported loser is in IN.

Within a run nobody holds a quota (the run would end), so every ballot
sits with its first candidate still standing and its value does not
change; that is what lets these be computed from the run's start alone.
"""
from __future__ import annotations

import math
from typing import Iterable, Optional, Sequence

import numpy as np


def _bincount(x: np.ndarray, weights: np.ndarray, minlength: int) -> np.ndarray:
    """ np.bincount with weights, always as floats (also when x is empty). """
    return np.bincount(x, weights=weights, minlength=minlength).astype(float)


def expand_ranges(starts: np.ndarray, ends: np.ndarray, owners: np.ndarray) \
    -> tuple[np.ndarray, np.ndarray]:
    """ Every flat index in [start, end) for each pair, with its owner. """
    lens = np.maximum(ends - starts, 0)
    total = int(lens.sum())
    if total == 0:
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64)
    offsets = np.cumsum(lens) - lens
    pos = np.arange(total) - np.repeat(offsets, lens) + np.repeat(starts, lens)
    return pos, np.repeat(owners, lens)


def shared_lift_lb(gaps: Iterable[float], excess: float = 0.0, \
    deficit: float = 0.0) -> float:
    """
        Smallest c with sum of max(0, a - (c - excess)) over gaps at most
        c - deficit, and c >= deficit: the best of (sum of the m largest
        positive gaps + m * excess + deficit) / (m + 1) over m >= 0.
    """
    best, total, m = deficit, 0.0, 0
    for g in sorted((g for g in gaps if g > 0), reverse=True):
        m += 1
        total += g
        best = max(best, (total + m * excess + deficit) / (m + 1))
    return best


def end_lb(gaps: Sequence[float], own: float, need: float, \
    excess: float = 0.0, deficit: float = 0.0) -> float:
    """
        Smallest c for which the additions keeping the OUT candidates above
        top (each gap a closed down to a - (c - excess)) plus x's own lift,
        max(0, own - (c - excess), need), total at most c - deficit. own is
        x's gap to top (-inf when x is not in OUT), need = quota - Tmax(x).
    """
    def fits(c: float) -> bool:
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
    while hi - lo > 1e-3 * max(1.0, hi):
        mid = (lo + hi) / 2
        if fits(mid):
            hi = mid
        else:
            lo = mid
    return hi


class RunState:
    """
        The ballots at the start of a run: each live ballot's value and its
        ranking over the candidates standing then, with the per-candidate
        quantities the checks need. Tmax and Tmin are kept for many OUT
        and IN sets and updated from the parent's when one candidate is
        added, as -eqlbc and -dlbc carry their state.
    """

    TM_KEEP = 20000
    POS_KEEP = 48
    TF_KEEP = 48

    def __init__(self, ncand: int, quota: float, seats_left: int, \
        standing: Sequence[int], prefs: Sequence[Sequence[int]], \
        values: Sequence[float]) -> None:
        self.ncand = ncand
        self.quota = quota
        self.seats_left = seats_left
        self.standing = list(standing)

        # Identical rankings move together from here on: merge them.
        merged: dict[tuple[int, ...], float] = {}
        for p, v in zip(prefs, values):
            if p:
                key = tuple(p)
                merged[key] = merged.get(key, 0.0) + v
        rows = list(merged)
        lens = np.array([len(p) for p in rows], dtype=np.int64)
        self.start = np.concatenate(([0], np.cumsum(lens)[:-1])).astype(np.int64)
        self.flat = np.fromiter((c for p in rows for c in p), dtype=np.int64, \
            count=int(lens.sum()))
        self.seg = np.repeat(np.arange(len(rows)), lens)
        self.idx = np.arange(len(self.flat), dtype=np.int64)
        self.ends = np.append(self.start[1:], len(self.flat)).astype(np.int64)
        self.big = len(self.flat)
        self.w = np.array([merged[p] for p in rows], dtype=float)
        order = np.argsort(self.flat, kind="stable")
        cuts = np.cumsum(np.bincount(self.flat, minlength=ncand))[:-1]
        self.by_cand = np.split(order.astype(np.int64), cuts)

        # Every row is live and starts with its holder.
        self.t0 = _bincount(self.flat[self.start], weights=self.w, \
            minlength=ncand)
        # Decision order: largest tally first.
        self.order = sorted(self.standing, key=lambda c: -self.t0[c])

        self._tm: dict = {}
        self._pos: dict = {}
        self._tf: dict = {}
        self._disp: Optional[tuple] = None
        # The no-quota bounds worked back over the seatings before the run
        # (set by the search, which has the walk's context).
        self.nq: Optional[float] = None

    # ------------------------------------------------------------ helpers

    @staticmethod
    def _put(store: dict, key, value, keep: int) -> None:
        store[key] = value
        while len(store) > keep:
            store.pop(next(iter(store)))

    def _first_pos(self, mask: np.ndarray) -> np.ndarray:
        """ Per row, the flat index of its first candidate in mask. """
        hit = np.where(mask[self.flat], self.idx, self.big)
        return np.minimum.reduceat(hit, self.start)

    def _mask(self, cands: Iterable[int]) -> np.ndarray:
        m = np.zeros(self.ncand, dtype=bool)
        m[list(cands)] = True
        return m

    # ------------------------------------------------------------ tallies

    def tmax(self, OUT: frozenset) -> np.ndarray:
        """
            For d in OUT the value of the rows whose first OUT candidate is
            d; for d outside OUT the value of the rows ranking d above every
            OUT candidate.
        """
        t = self._tm.get(OUT)
        if t is not None:
            return t
        for c in OUT:
            parent = OUT - {c}
            if parent in self._pos and parent in self._tm:
                p, t = self._add_out(self._pos[parent], self._tm[parent], c)
                break
        else:
            p = self._first_pos(self._mask(OUT))
            lim = np.where(p < self.big, p, self.big)
            before = self.idx < lim[self.seg]
            t = _bincount(self.flat[before], weights=self.w[self.seg[before]], \
                minlength=self.ncand)
            ok = p < self.big
            t += _bincount(self.flat[p[ok]], weights=self.w[ok], \
                minlength=self.ncand)
        self._put(self._tm, OUT, t, self.TM_KEEP)
        self._put(self._pos, OUT, p, self.POS_KEEP)
        return t

    def _add_out(self, p_parent: np.ndarray, t_parent: np.ndarray, c: int):
        """
            Rows ranking c ahead of their first OUT candidate change: the
            candidates between c and that one lose the row, that one stops
            being its first OUT, and c (counted before) counts as its first.
        """
        ent = self.by_cand[c]
        b = self.seg[ent]
        sel = ent < p_parent[b]
        ent, b = ent[sel], b[sel]
        old = p_parent[b]
        end = np.where(old < self.big, old, self.ends[b])
        pos, bb = expand_ranges(ent + 1, end, b)
        t = t_parent.copy()
        if len(pos):
            t -= _bincount(self.flat[pos], weights=self.w[bb], \
                minlength=self.ncand)
        had = old < self.big
        if had.any():
            t -= _bincount(self.flat[old[had]], weights=self.w[b[had]], \
                minlength=self.ncand)
        p = p_parent.copy()
        p[b] = ent
        return p, t

    def tmin_flow(self, IN: frozenset) -> tuple[np.ndarray, np.ndarray]:
        """
            Tmin: tallies with IN gone. F[l, x]: value of the rows x holds
            then that rank l above x.
        """
        v = self._tf.get(IN)
        if v is not None:
            return v[1], v[2]
        gone = self._mask(IN)
        for c in IN:
            parent = IN - {c}
            if parent in self._tf:
                h, tmin, F = self._add_in(*self._tf[parent], c, gone)
                break
        else:
            h = self._first_pos(~gone)
            ok = h < self.big
            holder = np.where(ok, self.flat[np.where(ok, h, 0)], -1)
            tmin = _bincount(holder[ok], weights=self.w[ok], \
                minlength=self.ncand)
            before = self.idx < np.where(ok, h, 0)[self.seg]
            x = holder[self.seg[before]]
            pair = self.flat[before] * self.ncand + x
            F = _bincount(pair, weights=self.w[self.seg[before]], \
                minlength=self.ncand * self.ncand).reshape(self.ncand, \
                self.ncand)
        self._put(self._tf, IN, (h, tmin, F), self.TF_KEEP)
        return tmin, F

    def _add_in(self, h_parent, tmin_parent, F_parent, c, gone):
        """
            Only the rows c holds move, to their next candidate not gone;
            that candidate's column of F gains their whole span.
        """
        ok = h_parent < self.big
        moved = np.nonzero(ok)[0]
        moved = moved[self.flat[h_parent[moved]] == c]
        pos = h_parent[moved] + 1
        end = self.ends[moved]
        active = pos < end
        while active.any():
            act = np.nonzero(active)[0]
            step = gone[self.flat[pos[act]]]
            pos[act[step]] += 1
            active[act[~step]] = False
            active &= pos < end
        new_h = np.where(pos < end, pos, self.big)
        h = h_parent.copy()
        h[moved] = new_h
        tmin = tmin_parent.copy()
        tmin[c] = 0.0
        has = new_h < self.big
        tmin += _bincount(self.flat[new_h[has]], weights=self.w[moved[has]], \
            minlength=self.ncand)
        F = F_parent.copy()
        F[:, c] = 0.0
        span, bb = expand_ranges(self.start[moved[has]], new_h[has], moved[has])
        if len(span):
            pair = self.flat[span] * self.ncand + self.flat[h[bb]]
            F += _bincount(pair, weights=self.w[bb], \
                minlength=self.ncand * self.ncand).reshape(self.ncand, \
                self.ncand)
        return h, tmin, F

    # ------------------------------------------------------------ bounds

    def lb(self, IN: frozenset, OUT: frozenset, floor: float, \
        deficit: float = 0.0, sumnq: bool = False, \
        elimnq: bool = False, depth: int = 0) -> float:
        """
            Lower bound for the family (IN, OUT): the checks Q, E+, M and
            S+ (inf for few). floor is the node's bound already, which
            lets M, the costly one, be skipped when it cannot raise it.
        """
        q, t0 = self.quota, self.t0
        if len(self.standing) - len(IN) < self.seats_left:
            return math.inf                                       # few
        tm = self.tmax(OUT)
        best = deficit
        gaps: dict[int, float] = {}
        excess = 0.0
        if IN:
            over = [t0[c] - q for c in self.standing]
            best = max(best, max(over))                            # Q
            if sumnq:
                best = max(best, sum(e for e in over if e > 0))
            top = max(t0[c] for c in IN)
            if OUT:
                gaps = {d: top - tm[d] for d in OUT}
                if elimnq:
                    excess = sum(max(0.0, t0[d] - q) for d in OUT)
                best = max(best, shared_lift_lb(gaps.values(), excess, \
                    deficit))                                      # E+
                # E+ again for IN's largest candidates l: while l stands,
                # an OUT candidate cannot hold the rows ranking l above it.
                for l in sorted(IN, key=lambda c: -t0[c])[:depth]:
                    tl = self.tmax(OUT | {l})
                    best = max(best, shared_lift_lb([t0[l] - tl[d] \
                        for d in OUT], excess, deficit))
                if any(tm[x] - q > max(best, floor) for x in OUT):
                    tmin, F = self.tmin_flow(IN)
                    rows = list(IN)
                    for x in OUT:                                  # M
                        best = max(best, tmin[x] - F[rows, x].max() - q)
        if len(OUT) > self.seats_left:                             # S+
            best = max(best, min(end_lb(
                [a for d, a in gaps.items() if d != x],
                gaps.get(x, -math.inf), q - tm[x], excess, deficit)
                for x in self.standing if x not in IN))
        return best

    def disp_costs(self, reported: set) -> tuple[set, dict]:
        """
            The displacement bound at the run's start, per reported loser l
            who might be the one to win: max(displacement, min(quota_cost,
            left_at_end_cost)), with dp(r) = max(0, (T0[r] - (present[l] -
            above[r][l])) / 2), as compute_disp_lb_STV26_q_prefix.
        """
        if self._disp is not None:
            return self._disp
        present = _bincount(self.flat, weights=self.w[self.seg], \
            minlength=self.ncand)
        above: dict[int, np.ndarray] = {}
        wseg = self.w[self.seg]
        for r in self.standing:
            at = np.full(len(self.w), self.big, dtype=np.int64)
            ent = self.by_cand[r]
            at[self.seg[ent]] = ent
            after = self.idx > at[self.seg]
            above[r] = _bincount(self.flat[after], weights=wseg[after], \
                minlength=self.ncand)
        W = {c for c in self.standing if c in reported}
        need = len(self.standing) - self.seats_left
        costs: dict[int, float] = {}
        for l in self.standing:
            if l in reported:
                continue
            dps, disp = [], math.inf
            for r in self.standing:
                if r == l:
                    continue
                dp = max(0.0, 0.5 * (self.t0[r] - (present[l] - above[r][l])))
                dps.append(dp)
                if r in reported:
                    disp = min(disp, dp)
            dps.sort()
            left_end = max(dps[:need]) if need > 0 else 0.0
            quota_cost = max(0.0, self.quota - present[l])
            costs[l] = max(disp, min(quota_cost, left_end))
        self._disp = (W, costs)
        return self._disp

    def dlb(self, IN: frozenset, reported: set, changed: bool) -> float:
        """
            0 once the outcome has changed (a reported loser seated, or a
            reported winner in IN); inf when every standing reported loser
            is in IN; otherwise the least cost over the losers not in IN.
        """
        if changed:
            return 0.0
        W, costs = self.disp_costs(reported)
        if not W or W & IN:
            return 0.0
        left = [costs[l] for l in costs if l not in IN]
        return min(left) if left else math.inf
