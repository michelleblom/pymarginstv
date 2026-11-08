#
#    Copyright (C) 2026  Michelle Blom
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as published
#    by the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
Measures, for each Senate contest, how much of the search Case C seeding
in BATCH_ELIMINATION.md could skip. Nothing here runs the search.

Seeding starts from a base node and splits the candidates still standing
there into strong (S), weak (L) and other (O). Any changed election that
misses every seed node needs at least X changed ballots, so
min(X, result of the search from the seeds) is a lower bound on the
margin. For each budget k (a fraction of the upper bound UB, set by
-fracs) it picks the split with the largest L whose X is at least k.

Two base nodes (-base):

  vs      Every very strong (VS) candidate seated, nothing eliminated.
          Seeds: 2^|O|, times the number of VS seating orders (one when
          vs_order_gap > 2k).

  forced  The end of a forced opening P of the reported count: one that
          any election with fewer than k changes must follow, judged from
          the tallies at each round of P (see Count.cost). Tried at the
          longest forced P and at each forced P that ends just before a
          run of eliminations; the row reports the split that covers the
          most candidates (eliminations in P plus |L|). Seeds: 2^|O|.

Both rely on every tally at the base node moving by at most k when k
ballots change and the election follows the base node's opening. This
assumes exact Gregory transfer values.

Usage: python3 measure_batch_seeding.py [-data DIR] [-csv FILE]
    [-only NAME ...] [-fracs F ...] [-base vs|forced|both]
"""

from __future__ import annotations

import argparse
import math
import time

from typing import Optional

from utils import read_ballots_blt, read_ballots_json, read_ballots_txt, \
    simulate_stv, compute_simple_ub, compute_weub


# (data file, seats, display name, upper bound): the Senate contests of
# run_cpp_experiments.sh, with its bounds. None means min(WEUB, simple UB).
INSTANCES: list[tuple[str, int, str, Optional[int]]] = [
    ("FedAus19/FederalSenate2019ACT.json", 2, "ACT 19", 12939),
    ("FedAus19/FederalSenate2019NT.json", 2, "NT 19", 15890),
    ("FedAus22/2022ACT.json", 2, "ACT 22", 11078),
    ("FedAus22/2022NT.json", 2, "NT 22", 11412),
    ("FedAus25/2025ACT.json", 2, "ACT 25", 23121),
    ("FedAus25/2025NT.json", 2, "NT 25", 13256),
    ("FedAus19/FederalSenate2019NSW.json", 6, "NSW 19", None),
    ("FedAus19/FederalSenate2019QLD.json", 6, "QLD 19", None),
    ("FedAus19/FederalSenate2019TAS.json", 6, "TAS 19", None),
    ("FedAus19/FederalSenate2019VIC.json", 6, "VIC 19", None),
    ("FedAus19/FederalSenate2019WA.json", 6, "WA 19", None),
    ("FedAus22/FederalSenate2022QLD.json", 6, "QLD 22", None),
    ("FedAus22/FederalSenate2022SA.json", 6, "SA 22", None),
    ("FedAus22/FederalSenate2022TAS.json", 6, "TAS 22", None),
    ("FedAus22/FederalSenate2022VIC.json", 6, "VIC 22", None),
    ("FedAus22/FederalSenate2022WA.json", 6, "WA 22", None),
]

INF = math.inf


class Contest:
    """
        Ballots of one contest at a base node.

        prefs[b] is ballot b's ranking over the candidates standing at the
        base node, and weight[b] is its value there (votes times the
        transfer values of the seated piles it sat in). x_base is the
        number of changes needed to avoid reaching the base node.
    """

    def __init__(self, ncand: int, quota: int, prefs: list[tuple[int, ...]], \
        weight: list[float], hopeful: list[int], seats_left: int, \
        x_base: float) -> None:
        self.ncand = ncand
        self.quota = quota
        self.prefs = prefs
        self.weight = weight
        self.hopeful = hopeful
        self.seats_left = seats_left
        self.x_base = x_base
        self.base = self.first_tallies(set(hopeful))

    def first_tallies(self, hopeful: set[int]) -> list[float]:
        """ Tally of each candidate when only 'hopeful' are standing. """
        tally = [0.0]*self.ncand
        for p, w in zip(self.prefs, self.weight):
            for c in p:
                if c in hopeful:
                    tally[c] += w
                    break
        return tally

    def ahead_of(self, blockers: set[int]) -> tuple[list[float], list[float]]:
        """
            For a set of blockers, returns (mpt, first):
            mpt[c]   = value of ballots ranking c above every blocker,
                       for c not a blocker;
            first[s] = value of ballots whose highest blocker is s.
        """
        mpt = [0.0]*self.ncand
        first = [0.0]*self.ncand
        for p, w in zip(self.prefs, self.weight):
            for c in p:
                if c in blockers:
                    first[c] += w
                    break
                mpt[c] += w
        return mpt, first


def build_vs_contest(ballots, ncand: int, quota: int, seats: int, \
    k: float) -> tuple[Contest, dict]:
    """
        Seats candidates over quota by at least k, largest tally first,
        and returns the ballots at the resulting base node, with facts
        about the VS seatings.
    """
    prefs = [tuple(b.prefs) for b in ballots]
    weight = [float(b.votes) for b in ballots]
    seated: set[int] = set()
    vs: list[int] = []
    vs_gaps: list[float] = []
    order_gap = INF
    from_transfers = False
    blocked_by: Optional[int] = None

    while len(vs) < seats:
        tally = [0.0]*ncand
        top = [-1]*len(prefs)
        for b, p in enumerate(prefs):
            for c in p:
                if c not in seated:
                    tally[c] += weight[b]
                    top[b] = c
                    break

        hopeful = [c for c in range(ncand) if c not in seated]
        best = max(hopeful, key=lambda c: tally[c])
        if tally[best] < quota:
            break
        if tally[best] - quota < k:
            blocked_by = best
            break

        rivals = [tally[c] for c in hopeful if c != best and \
            tally[c] >= quota - k]
        if rivals:
            order_gap = min(order_gap, tally[best] - max(rivals))

        if vs:
            from_transfers = from_transfers or \
                any(top[b] == best and p[0] != best for b, p in enumerate(prefs))

        tv = (tally[best] - quota)/tally[best]
        for b in range(len(prefs)):
            if top[b] == best:
                weight[b] *= tv
        seated.add(best)
        vs.append(best)
        vs_gaps.append(tally[best] - quota)

    prefs = [tuple(c for c in p if c not in seated) for p in prefs]
    hopeful = [c for c in range(ncand) if c not in seated]
    ct = Contest(ncand, quota, prefs, weight, hopeful, seats - len(vs), \
        min(vs_gaps, default=INF))
    info = {"vs": len(vs), "vs_gap": min(vs_gaps, default=INF), \
        "from_transfers": from_transfers, "order_gap": order_gap, \
        "blocked_by": blocked_by}
    return ct, info


class Count:
    """
        Replays the reported count with the rules of utils.simulate_stv,
        one seating or elimination per step.

        Candidates who reach the quota join a queue and are seated in
        queue order before anything is eliminated. A batch that reaches
        the quota at the start or after a seating is queued largest
        surplus first; a batch after an elimination is queued in
        candidate number order. A seated candidate's ballots move on at
        (surplus when queued) / (tally when seated).
    """

    def __init__(self, ballots, ncand: int, quota: int, seats: int) -> None:
        self.ncand = ncand
        self.quota = quota
        self.seats = seats
        self.prefs = [tuple(b.prefs) for b in ballots]
        self.weight = [float(b.votes) for b in ballots]
        self.pos = [0]*len(self.prefs)
        self.standing = [True]*ncand
        self.tally = [0.0]*ncand
        self.pile: list[list[int]] = [[] for _ in range(ncand)]
        self.surplus: dict[int, float] = {}
        self.queue: list[int] = []
        self.seated = 0
        self.done = False

        for b, p in enumerate(self.prefs):
            if p:
                self.pile[p[0]].append(b)
                self.tally[p[0]] += self.weight[b]

        # Candidates that joined the queue at the current state, in
        # queue order, and whether that order was set by surplus.
        self.entrants, self.by_surplus = self._enter(True), True

    def _enter(self, by_surplus: bool) -> list[int]:
        new = [c for c in range(self.ncand) if self.standing[c] and \
            c not in self.surplus and self.tally[c] >= self.quota]
        batch: list[int] = []
        for c in new:
            self.surplus[c] = max(0.0, self.tally[c] - self.quota)
            if not by_surplus:
                batch.append(c)
                continue
            # Same tie rule as utils.insert_surplus.
            i = 0
            while i < len(batch) and self.surplus[c] < self.surplus[batch[i]]:
                i += 1
            batch.insert(i, c)
        self.queue.extend(batch)
        return batch

    def _move(self, c: int, factor: float) -> None:
        """ Passes c's ballots to their next standing candidate. """
        for b in self.pile[c]:
            self.weight[b] *= factor
            p = self.prefs[b]
            i = self.pos[b] + 1
            while i < len(p) and not self.standing[p[i]]:
                i += 1
            self.pos[b] = i
            if i < len(p):
                self.pile[p[i]].append(b)
                self.tally[p[i]] += self.weight[b]
        self.pile[c] = []

    def n_standing(self) -> int:
        return sum(self.standing)

    def at_end(self) -> bool:
        """ The count is over, or only seats-left candidates remain. """
        return self.done or \
            self.n_standing() == self.seats - self.seated

    def next_action(self) -> tuple[int, int]:
        """ (candidate, 1 = seat / 0 = eliminate) for the next step. """
        if self.queue:
            return self.queue[0], 1
        hopeful = [c for c in range(self.ncand) if self.standing[c]]
        return min(hopeful, key=lambda c: self.tally[c]), 0

    def cost(self) -> float:
        """
            Changes needed, at this state, for an election that has
            followed the count so far (with the same queue) to take a
            different next step or queue differently here. Each tally can
            move by at most k, so a gap g between two tallies needs g/2.

            - a candidate that joined the queue here stays out: T - q;
            - two neighbours in a batch queued by surplus swap: gap/2;
            - a candidate outside the queue reaches the quota: q - T;
            - before an elimination of e, another c goes instead:
              (T(c) - T(e))/2.
        """
        q = self.quota
        T = self.tally
        x = INF
        for c in self.entrants:
            x = min(x, T[c] - q)
        if self.by_surplus:
            for a, b in zip(self.entrants, self.entrants[1:]):
                x = min(x, (T[a] - T[b])/2)
        hopeful = [c for c in range(self.ncand) if self.standing[c]]
        for c in hopeful:
            if c not in self.surplus:
                x = min(x, q - T[c])
        if not self.queue:
            e, _ = self.next_action()
            for c in hopeful:
                if c != e:
                    x = min(x, (T[c] - T[e])/2)
        return x

    def step(self) -> tuple[int, int]:
        c, a = self.next_action()
        self.standing[c] = False
        if a == 1:
            self.queue.pop(0)
            self.seated += 1
            if self.seated == self.seats:
                self.done = True
            elif self.surplus[c] >= 0.001:
                self._move(c, self.surplus[c]/self.tally[c])
            else:
                self.pile[c] = []
            self.entrants, self.by_surplus = self._enter(True), True
        else:
            self._move(c, 1.0)
            self.entrants, self.by_surplus = self._enter(False), False
        self.tally[c] = 0.0
        return c, a

    def contest(self, x_base: float) -> Contest:
        """ The ballots at this state, as a seeding base node. """
        hopeful = [c for c in range(self.ncand) if self.standing[c]]
        prefs: list[tuple[int, ...]] = []
        weight: list[float] = []
        for b, p in enumerate(self.prefs):
            i = self.pos[b]
            if i >= len(p) or not self.standing[p[i]]:
                continue
            prefs.append(tuple(c for c in p[i:] if self.standing[c]))
            weight.append(self.weight[b])
        return Contest(self.ncand, self.quota, prefs, weight, hopeful, \
            self.seats - self.seated, x_base)


def forced_profile(ballots, ncand: int, quota: int, seats: int, \
    order_c: list[int], order_a: list[int]) -> tuple[list[float], list[int]]:
    """
        Replays the reported count. Returns xp and acts, where xp[n] is the
        cost of leaving the first n steps (the smallest Count.cost over
        their states), and acts[n] is step n's action. Stops where only
        seats-left candidates remain. Checks the replay against order_c.
    """
    ct = Count(ballots, ncand, quota, seats)
    xp = [INF]
    acts: list[int] = []
    while not ct.at_end():
        x = min(xp[-1], ct.cost())
        n = len(acts)
        c, a = ct.step()
        assert (c, a) == (order_c[n], order_a[n]), \
            f"replay differs from simulate_stv at step {n}"
        acts.append(a)
        xp.append(x)
    return xp, acts


def forced_bases(xp: list[float], acts: list[int], k: float) -> list[int]:
    """
        Lengths n of forced openings (xp[n] >= k) to try as base nodes:
        the longest, then each that ends just before a run of
        eliminations, longest first.
    """
    forced = [n for n in range(len(xp)) if xp[n] >= k]
    if not forced:
        return []
    longest = forced[-1]
    out = [longest]
    for n in reversed(forced[:-1]):
        if n < len(acts) and acts[n] == 0 and (n == 0 or acts[n-1] == 1):
            out.append(n)
    return out


def contest_after(ballots, ncand: int, quota: int, seats: int, n: int, \
    x_base: float) -> Contest:
    ct = Count(ballots, ncand, quota, seats)
    for _ in range(n):
        ct.step()
    return ct.contest(x_base)


def seeding(ct: Contest, k: float) -> Optional[dict]:
    """
        Tries each strong set S made of the j highest hopeful candidates
        at the base node, and returns the one with the largest weak set
        whose exit cost is at least k (fewest others on ties).
    """
    left = ct.seats_left
    if left <= 0:
        return None

    q = ct.quota
    order = sorted(ct.hopeful, key=lambda c: -ct.base[c])

    best: Optional[dict] = None
    for j in range(left, len(order)):
        S = set(order[:j])
        t = min(ct.base[s] for s in S)
        mpt, first = ct.ahead_of(S)

        rest = order[j:]
        # Weak means MPT(l) + k < t - k for k changed ballots.
        L = [c for c in rest if t - mpt[c] > 2*k]
        O = [c for c in rest if t - mpt[c] <= 2*k]
        if not L:
            continue

        weak_x = (t - max(mpt[l] for l in L))/2
        strong_q = min(q - first[s] for s in S)
        other_q = min((q - mpt[o] for o in O + L), default=INF)
        x = min(ct.x_base, weak_x, strong_q, other_q)
        cand = {"S": len(S), "L": len(L), "O": len(O), "X": x, \
            "strong": S, "weak": L, "other": O}
        if x < k:
            continue

        if best is None or (cand["L"], -cand["O"]) > (best["L"], -best["O"]):
            best = cand

    return best


def load(path: str):
    if path.endswith(".blt"):
        candidates, ballots, *_ = read_ballots_blt(path)
    elif path.endswith(".json"):
        candidates, ballots, *_ = read_ballots_json(path)
    else:
        candidates, ballots, *_ = read_ballots_txt(path)
    return candidates, ballots


def fmt(x: float) -> str:
    return "" if x == INF else f"{x:.0f}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-data", default="../stv-rla/data")
    parser.add_argument("-csv", default=None)
    parser.add_argument("-only", nargs="*", default=None)
    parser.add_argument("-fracs", nargs="*", type=float, \
        default=[1, 1/2, 1/4, 1/8, 1/16])
    parser.add_argument("-base", choices=["vs", "forced", "both"], \
        default="both")
    args = parser.parse_args()

    # P_seats/P_elims: seatings and eliminations before the base node.
    # XP: changes needed to avoid reaching it. covered: P_elims + L.
    header = "contest,C,seats,quota,UB,k,base,P_seats,P_elims,XP," \
        "VS_via_transfers,vs_order_gap,blocked_by,S,L,O,seeds,X,covered,secs"
    print(header, flush=True)
    out = open(args.csv, "w") if args.csv else None
    if out:
        print(header, file=out, flush=True)

    def emit(row: str) -> None:
        print(row, flush=True)
        if out:
            print(row, file=out, flush=True)

    def seed_cols(sd: Optional[dict], elims: int) -> str:
        if sd is None:
            return f",,,,,{elims}"
        return f"{sd['S']},{sd['L']},{sd['O']},{2**sd['O']}," \
            f"{sd['X']:.0f},{elims + sd['L']}"

    for path, seats, name, given_ub in INSTANCES:
        if args.only and not any(o in name for o in args.only):
            continue

        candidates, ballots = load(f"{args.data}/{path}")
        ncand = len(candidates)
        order_c: list[int] = []
        order_a: list[int] = []
        winners: list[int] = []
        quota, tallies, _ = simulate_stv(ballots, candidates, seats, \
            order_c, order_a, winners)

        ub = math.ceil(min(compute_weub(candidates, winners, order_c, \
            order_a, tallies), compute_simple_ub(candidates, quota, winners)))
        if given_ub is not None:
            ub = min(ub, given_ub)

        if args.base in ("forced", "both"):
            xp, acts = forced_profile(ballots, ncand, quota, seats, \
                order_c, order_a)

        lead = f"{name},{ncand},{seats},{quota},{ub}"
        for frac in args.fracs:
            k = max(1, math.ceil(ub*frac))

            if args.base in ("vs", "both"):
                t0 = time.time()
                ct, info = build_vs_contest(ballots, ncand, quota, seats, k)
                sd = None if info["blocked_by"] is not None \
                    else seeding(ct, k)
                blocked = "" if info["blocked_by"] is None \
                    else candidates[info["blocked_by"]].id
                emit(f"{lead},{k},vs,{info['vs']},0,{fmt(info['vs_gap'])}," \
                    f"{int(info['from_transfers'])}," \
                    f"{fmt(info['order_gap'])},{blocked}," \
                    f"{seed_cols(sd, 0)},{time.time() - t0:.0f}")

            if args.base in ("forced", "both"):
                t0 = time.time()
                best: Optional[tuple] = None
                for n in forced_bases(xp, acts, k):
                    ct = contest_after(ballots, ncand, quota, seats, n, xp[n])
                    sd = seeding(ct, k)
                    elims = acts[:n].count(0)
                    key = (elims + (sd["L"] if sd else 0), \
                        -(sd["O"] if sd else 0), n)
                    if best is None or key > best[0]:
                        best = (key, n, elims, sd)
                if best is None:
                    emit(f"{lead},{k},forced,,,,,,,{seed_cols(None, 0)}," \
                        f"{time.time() - t0:.0f}")
                else:
                    _, n, elims, sd = best
                    emit(f"{lead},{k},forced,{n - elims},{elims}," \
                        f"{fmt(xp[n])},,,,{seed_cols(sd, elims)}," \
                        f"{time.time() - t0:.0f}")

    if out:
        out.close()


if __name__ == "__main__":
    main()
