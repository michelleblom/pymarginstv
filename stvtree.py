from __future__ import annotations

from stvdistance import stvdistance
from utils import Ballot, BallotMetadata, Candidate, CandidateLike, merge_outcome, get_order_q

import argparse
import cProfile
import importlib
import math
import multiprocessing
import numpy as np
import os
import time

from bisect import bisect_left, bisect_right, insort
from multiprocessing import Pool
from typing import Any, Container, NamedTuple, Optional, Sequence, TextIO

# Quota-in-prefix variant of the MINLP model, in which order_q records a
# single exact quota round per candidate. The hyphenated filename cannot be
# imported with a plain import statement.
stvdistance_qprefix = importlib.import_module('stvdistance-qprefix').stvdistance

epsilon = 0.9

# Range of rounds (earliest, latest) in which a seated candidate could first
# achieve a quota. The value convention depends on the search mode: with
# useqprefix, entries are exact (earliest == latest) and give the first round
# at whose start the candidate holds a quota (0 = on first preferences);
# otherwise entries follow get_order_q's convention, giving the round of
# transfers that could first produce the quota (-1 = on first preferences).
QRange = tuple[int, int]

# Canonical outcome-prefix signature: see outcome_signature().
Signature = tuple[tuple[Any, ...], frozenset[tuple[int, QRange]]]

class EqlbCtx(NamedTuple):
    N: int                       # number of candidates
    transfer: dict[int, tuple[float,float]]   # Transfer values of prefix winners
    elim_lb: float               # elim_lb accumulated over prefix rounds
    quota_lb: float              # quota_lb accumulated over prefix rounds
    no_quota_lb: float           # noquota_lb accumulated over prefix rounds
    nq_cons_added: list[set[int]] # For each prior round, candidates for whom 
                                  # no quota constraints were added
    winners: set[int]
    gone: list[int]
    gone_set: set[int]
    gone_pos: dict[int, int]

    round: int                   # last round in which context was updated.

class DispCache(NamedTuple):
    """
        Returns (val(b) = value ballot b carries once prefix has been applied):
        present[x]      = sum of val(b) over ballots on which x still stands
        above[x][y]     = sum of val(b) over ballots on which x and y both stand
                          and x is ranked above y
        curtally[x]     = sum of val(b) over ballots whose first still-standing
                          candidate is x
        reassign[g][x]  = sum of val(b) over ballots whose first still-standing
                          candidate is g and whose next still-standing is x
    """
    N: int
    new_winner: bool
    gone_pos: dict[int,int]
    winners: set[int]

    above: Optional[list[list[float]]]
    present: Optional[list[float]]
    curtally: Optional[list[float]]
    reassign: Optional[list[list[float]]]

    start: int
    lowerbound: int



# Result of evaluating a child node in eval_child(): (isleaf, order_c,
# order_a, order_q, lb, dlb, eqlb, dist, dist_ub, rem, winners, solved).
ChildResult = tuple[bool, EqlbCtx, DispCache, list[int], \
    list[int], dict[int, QRange], float, float, float, Optional[float], \
    Optional[float], list[int], set[int], bool]


# Frontier node data shipped to expand_node(): (eqlbctx, order_c, order_a,
# order_q, rem, winners, dist).
FNodeData = tuple[EqlbCtx, DispCache, list[int], list[int], dict[int, QRange], list[int], \
    set[int], float]


def outcome_signature(order_c: list[int], order_a: list[int], \
    order_q: dict[int, QRange]) -> Signature:
    """
        Canonical, hashable form of an outcome prefix under the node
        'similarity' relation used for subsumption: two prefixes are
        structurally equivalent iff they have the same order_a, the same
        seated candidate at each seating position, equal *sets* of
        eliminated candidates between consecutive seatings, and the same
        quota-round range for each candidate achieving a quota.
    """
    parts: list[Any] = []
    block: list[int] = []
    for i in range(len(order_c)):
        if order_a[i] == 1:
            parts.append((frozenset(block), order_c[i]))
            block = []
        else:
            block.append(order_c[i])
    parts.append(frozenset(block))

    return tuple(parts), frozenset(order_q.items())


class TreeNode:
    """
        Data structure for a node in our tree of alternate outcomes.

        order_c  : Outcome prefix (candidate seating/election order)

        order_a  : Outcome prefix (whether an elimination or election occurred).

        order_q  : For each candidate who receives a quota throughout the
                   prefix, the range (earliest, latest) of rounds in which
                   they could first achieve a quota (see QRange for the
                   per-mode value convention).

        winners  : Winners thus far in prefix

        distance : How many votes have to change (lower bound) to realise the
                   given outcome prefix.

        eqlbctx  : Saved elimination-quota lower bound computations for the parent
                   (or earlier ancestor) of this node.            

    """

    __slots__ = ('id', 'order_c', 'order_a', 'order_q', 'rem', \
        'dist', 'dist_ub', 'winners', 'eqlbctx', 'disp_cache', 'sig')

    id: Optional[int]
    order_c: list[int]
    order_a: list[int]
    order_q: dict[int, QRange]
    rem: list[int]
    dist: Optional[float]
    dist_ub: Optional[float]
    winners: set[int]
    eqlbctx: EqlbCtx
    disp_cache: DispCache
    sig: Signature

    def __init__(self, order_c: list[int], order_a: list[int], \
        order_q: dict[int, QRange], winners: set[int], rem: list[int], \
        eqlbctx: EqlbCtx, disp_cache: DispCache, \
        distance: Optional[float], dist_ub: Optional[float]) -> None:

        self.id = None

        self.order_c = order_c
        self.order_a = order_a
        self.order_q = order_q

        self.sig = outcome_signature(order_c, order_a, order_q)

        self.rem = rem

        self.dist = distance  # lower bound from MINLP solve
        self.dist_ub = dist_ub  # upper bound from MINLP solve
        self.winners = winners
        self.eqlbctx = eqlbctx
        self.disp_cache = disp_cache

    def __str__(self) -> str:
        """
            Return string representation of this tree node.
        """

        quotas: list[list[str]] = [[] for r in self.order_c]
        for c,(_,hi) in self.order_q.items():
            quotas[max(hi,0)].append(str(c))

        summary = ""

        for r in range(len(self.order_c)):
            action = "e" if self.order_a[r] == 0 else "s"
            if len(quotas[r]) > 0:
              qlist = " ( "
              for qc in quotas[r]:
                qlist += qc + " "
              qlist += ")"
              action += qlist
            summary += str(self.order_c[r]) + action + " "

        summary += "with distance {}/{}".format(self.dist, self.dist_ub)

        return summary


class Frontier:
    """
        Data structure containing the tree nodes that form the frontier
        (current leafs/unexpanded nodes) of the tree of alternate
        possibilities we are searching through.

        Subsumption ('similar node') checks are answered from sig_dists, a
        map from a node's canonical outcome signature to the sorted distance
        values of all structurally-equivalent nodes currently participating
        in the search (frontier + expanded, excluding pruned). This replaces
        retaining every expanded TreeNode object and linearly scanning them.
    """

    def __init__(self) -> None:
        # TreeNode objects, sorted by distance (ties FIFO)
        self.nodes: list[TreeNode] = []
        # parallel list of node distances, for bisection
        self.dists: list[float] = []
        self.size = 0

        # signature -> sorted list of distances
        self.sig_dists: dict[Signature, list[float]] = {}

        self.idcntr = 0

        self.ignore_cntr = 0
        self.agg_prune_cntr = 0

    def get_lower_bound(self) -> float:
        if self.size > 0:
            assert self.nodes[0].dist is not None
            return self.nodes[0].dist
        return np.inf

    def pop(self, number: int) -> list[TreeNode]:
        # Popped (expanded) nodes keep their entry in sig_dists so that
        # they continue to subsume structurally-equivalent nodes, but the
        # node objects themselves are released once expansion is done.
        popped = self.nodes[:number]
        del self.nodes[:number]
        del self.dists[:number]
        self.size = len(self.nodes)
        return popped

    def __str__(self) -> str:
        """
            Return string representation of the frontier.
        """
        summary = "--------------------------------------------------\n"
        summary += "FRONTIER ({} nodes)\n".format(self.size)

        if self.size > 10:
            for i in range(5):
                summary += str(self.nodes[i]) + '\n'

            summary += '...\n'

            for i in range(self.size - 5, self.size):
                summary += str(self.nodes[i]) + '\n'

        else:
            for node in self.nodes:
                summary += str(node) + '\n'

        summary += "--------------------------------------------------\n"
        return summary

    def _unregister(self, node: TreeNode) -> None:
        assert node.dist is not None
        dlist = self.sig_dists.get(node.sig)
        if dlist is not None:
            i = bisect_left(dlist, node.dist)
            if i < len(dlist) and dlist[i] == node.dist:
                del dlist[i]
            if not dlist:
                del self.sig_dists[node.sig]

    def prune(self, upperbound: float, log: Optional[TextIO] = None) -> None:
        """
            Remove all nodes from the frontier whose distance value is
            greater than or equal to 'upperbound'.
        """
        if self.size > 0:
            i = 0
            while i < self.size:
                d = self.nodes[i].dist
                assert d is not None
                if d >= upperbound:
                    break
                i += 1

            if i < self.size:
                for n in self.nodes[i:]:
                    if log != None and i > 0:
                        print("Pruning {}".format(str(n)), file=log)
                    self._unregister(n)

                del self.nodes[i:]
                del self.dists[i:]
                self.size = len(self.nodes)

    def insert(self, node: TreeNode, lse: bool = True, \
        log: Optional[TextIO] = None) -> Optional[int]:
        """
            Nodes are inserted into the frontier on the basis of their
            distance value, smallest first. A node is subsumed (not
            inserted) if a structurally-equivalent node exists whose
            distance already covers it.
        """
        assert node.dist is not None

        if self.size > 0:
            dlist = self.sig_dists.get(node.sig)
            if dlist:
                if lse:
                    # Subsumed by any equivalent node with distance no more
                    # than epsilon above ours; smallest distance suffices.
                    if node.dist >= dlist[0] - epsilon:
                        self.ignore_cntr += 1
                        return None
                else:
                    # Subsumed by any equivalent node within epsilon.
                    i = bisect_left(dlist, node.dist - epsilon)
                    if i < len(dlist) and dlist[i] <= node.dist + epsilon:
                        self.ignore_cntr += 1
                        return None

        node.id = self.idcntr
        self.idcntr += 1

        i = bisect_right(self.dists, node.dist)
        self.nodes.insert(i, node)
        self.dists.insert(i, node.dist)
        self.size += 1

        dlist = self.sig_dists.get(node.sig)
        if dlist is None:
            self.sig_dists[node.sig] = [node.dist]
        else:
            insort(dlist, node.dist)

        return i


def compute_last_round(order_c: list[int], order_a: list[int], seats: int, \
    ncands: int) -> int:
    """
        Given an outcome prefix (order_c/order_a), determine what 
        round we should form constraints up to when solving the model
        that gives us the distance value for that prefix. For example, if
        the end of the prefix is going to be a bunch of candidates who 
        are seated because they are the last left standing -- we only need
        to ensure that they should be the last few left standing, not
        that any one of them has more votes than the other at that point.

        seats  :   Number of seats in the election.

        ncands :   Number of candidates in the election.
    """
    c_cntr = 0
    s_cntr = 0

    LAST_ROUND = 0
    loc = len(order_c)
    for r in range(loc):
        c_cntr += 1

        if order_a[r] == 1:
            s_cntr += 1

        if s_cntr == seats:
            break

        if ncands - c_cntr == seats - s_cntr:
            break

        LAST_ROUND += 1

    return min(loc - 1, LAST_ROUND)


def compute_round_tallies_q_prefix(ballots: list[Ballot], \
    gone: list[int], gone_set: set[int], transfer: Any, winners: set[int], \
    order_q: dict[int, QRange], gone_pos: dict[int, int], N: int) -> list[float]:
    """
    One ballot pass giving each still-standing candidate's tally at the start of
    the round following prefix `gone`. This method only give the correct tallies
    in the context where a candidate is to be eliminated this round (no ballots
    will skip any candidates, and we can safely give each ballot to its first
    ranked remaining candidate).
    """
    tallies: list[float] = [0.0] * N
    for b in ballots:
        first = -1
        for p in b.prefs:
            if p not in gone_set:
                first = p
                break
        if first == -1:  # ballot is exhausted
            continue
        ev_add, _ = calc_tallies_q_prefix(b, gone, transfer, winners, order_q, \
            gone_pos)
        tallies[first] += ev_add
    return tallies


def compute_elim_quota_lb_STV26_q_prefix(eqlbctx: EqlbCtx, cands: Sequence[CandidateLike], \
    ballots: list[Ballot], order_c: list[int], order_a: list[int], \
    quota: int, order_q: dict[int, QRange], elim_tallies: Optional[list[float]]) -> EqlbCtx:
    """
    This function calculates the lower bound on the number of votes that need to be changed
    to alter the outcome of an election prefix. It does this by considering the elimination and quota
    constraints of the election.

    Parameters:
    cands (list): A list of Candidate objects representing the candidates in the election.
    ballots (list): A list of Ballot objects representing the ballots cast in the election.
    order_c (list): A list representing the order in which candidates were eliminated or seated.
    order_a (list): A list of 0s and 1s indicating whether a candidate was eliminated (0) or 
                    seated (1) in each round.
    quota (int): The quota for the election, i.e., the minimum number of votes a candidate 
                 needs to win a seat.
    order_q (dict): A dictionary mapping winning candidates to the range (earliest, latest) of 
                    rounds in which they could first have a quota at the start of the round (degenerate 
                    in q-prefix mode).

    Returns:
    tuple: The lower bound on the number of votes that need to be changed to alter the outcome of 
           the election prefix, and a map from each seated winner to their transfer value.
    """

    elim_lb = eqlbctx.elim_lb
    quota_lb = eqlbctx.quota_lb
    no_quota_lb = eqlbctx.no_quota_lb
    nq_cons_added = [{*eqlbctx.nq_cons_added[i]} for i in range(eqlbctx.N)]
    transfer = {**eqlbctx.transfer}    
    gone = [*eqlbctx.gone]
    gone_set = {*eqlbctx.gone_set}
    gone_pos = {**eqlbctx.gone_pos}  
    winners = {*eqlbctx.winners}
    start = eqlbctx.round

    PXLEN = len(order_c)

    # Earliest round at which a candidate still standing at the end of the
    # prefix could hold a quota. Two constraints bound it.
    #
    # It cannot be at or before the prefix's last elimination: nobody may hold
    # a quota in a round where a candidate is eliminated.
    #
    # It cannot be earlier than the latest quota round in order_q. Seating
    # order follows the round in which a quota was achieved, ties broken by
    # tally, so a continuing candidate that had reached its quota before one of
    # the prefix's seated candidates would have been seated ahead of it. A tie
    # is consistent with not being seated, so the bound is not strict.
    #
    # A ballot that last moved before this round cannot have skipped a
    # continuing candidate, so it is certain who holds it. When the prefix ends
    # with an elimination -- a padded complete prefix included -- the first
    # constraint puts this past every reachable move_r (at most PXLEN - 2), so
    # no ballot is ever treated as uncertain.
    lastelim = PXLEN - 1
    while lastelim >= 0 and order_a[lastelim] == 1:
        lastelim -= 1

    # Note: qearliest is the earliest round in which a continuing candidate
    # (not seated in the prefix) can have a quota.
    qearliest = lastelim + 1
    if order_q:
        qearliest = max(qearliest, max(order_q[c][0] for c in order_q))

    # Check: did we just come out of a seating block and are now eliminating?
    # If so, check whether we need to compute some additional no-quota bounds.
    # Two shapes qualify: a run of two or more seatings followed by an
    # elimination (tail [1, 1, 0]), and a complete prefix whose tail is padded
    # with eliminations. Both leave the prefix ending in an elimination, so the
    # quota rounds in the block are no longer ambiguous. Note this is a test on
    # the shape of order_a, not on how many rounds this call is covering: start
    # is 0 whenever the context is not cached, which says nothing about the tail.
    lastseat = PXLEN - 1
    while lastseat >= 0 and order_a[lastseat] == 0:
        lastseat -= 1

    if 0 <= lastseat < PXLEN - 1 and (PXLEN == eqlbctx.N \
        or (lastseat >= 1 and order_a[lastseat - 1] == 1)):
        j = lastseat
        while j >= 0 and order_a[j] == 1:
            nqlb, nqs = backcompute_nq_bound(j, eqlbctx, cands, ballots, order_c, order_q, quota)
            no_quota_lb = max(no_quota_lb, nqlb)
            nq_cons_added[j].update(nqs)
            j -= 1

    for i in range(start, PXLEN):
        ce = order_c[i]

        if order_a[i] == 0:  # candidate eliminated
            if i == 0:
                tallies = [cand.fp_votes for cand in cands]
            elif i == start and elim_tallies != None:
                tallies = elim_tallies
            else:
                tallies = compute_round_tallies_q_prefix(ballots, gone, gone_set, \
                    transfer, winners, order_q, gone_pos, eqlbctx.N)

            # No one should have a quota
            no_quota_lb = max(0, tallies[ce] - quota)
            others = [c.num for c in cands if c.num not in gone_set and c.num != ce]
            for c in others:
                elim_lb = max(elim_lb, max(0, 0.5 * (tallies[ce] - tallies[c])))
                no_quota_lb = max(no_quota_lb, max(0, tallies[c] - quota))
                nq_cons_added[i].add(c)


        else:  # candidate seated
            # Can the ballot walk below be replaced by the round tallies
            # prec_et already computed once for this expansion? It can when
            # every candidate still standing that has a quota round recorded
            # reaches it no earlier than this round. move_r indexes into gone,
            # whose length is i, so move_r <= i - 1 < i, and then:
            #
            #   - the skip test never fires, so each ballot lands on its first
            #     preference still standing, exactly as the round tallies do;
            #   - qearliest is at least ce's quota round, so move_r < qearliest
            #     for every ballot and every one of them is certain, putting
            #     the same value into both tallies.
            #
            # So both tallies equal the round tallies elementwise and can alias
            # that array -- nothing below writes to them. The array is shared
            # with this node's sibling children, so it must stay read-only.
            reuse_elim_tallies = i > 0 and i == start and elim_tallies is not None \
                and ce in order_q and order_q[ce][0] == i \
                and all(order_q[c][0] >= i for c in order_q if c not in gone_set)

            if i == 0:
                min_tallies: list[float] = [cand.fp_votes for cand in cands]
                max_tallies = min_tallies
            elif reuse_elim_tallies:
                assert elim_tallies is not None
                min_tallies = elim_tallies
                max_tallies = elim_tallies
            else:
                min_tallies = [0.0] * eqlbctx.N
                max_tallies = [0.0] * eqlbctx.N

                for b in ballots:
                    sv_add = None
                    move_r = -1
                    for p in b.prefs:
                        if p in gone_set:
                            continue

                        if sv_add is None:
                            sv_add, move_r = calc_tallies_q_prefix(b, gone, \
                                transfer, winners, order_q, gone_pos)

                        if p in order_q and order_q[p][0] <= move_r:
                            continue # definitely skipped

                        # p is either in order_q with a quota round later than
                        # the ballot's last move, or outside it and unable to
                        # hold a quota yet: either way the ballot stays with p.
                        if p in order_q or move_r < qearliest:
                            min_tallies[p] += sv_add

                        # Otherwise p may or may not still hold the ballot, and
                        # we stop either way. Nothing later on this ballot can
                        # be consumed: every order_q member has a quota round at
                        # or before qearliest <= move_r, so all of them are
                        # skipped by the test above, and the max tallies of
                        # candidates outside order_q are never read. If those
                        # ever do get consumed, this exit has to go and the walk
                        # must continue, adding only to max_tallies, until the
                        # preferences run out.
                        max_tallies[p] += sv_add
                        break

            rem = [c.num for c in cands if c.num not in gone_set]
            for c in rem:
                if c in order_q and order_q[c][0] <= i:
                    quota_lb = max(quota_lb, quota - max_tallies[c])

            if ce in order_q:  # candidate got a quota, else seated by default (last round)
                winners.add(ce)

                # Min/max tally should be the same
                mint,maxt = min_tallies[ce],max_tallies[ce]
                assert(abs(maxt-mint)<= epsilon)
                cmax = maxt
                value = max(cmax, quota)  # restrict value to be at lest quota
                tv = (value - quota)/value
                transfer[ce] = (tv, tv)

                # cost to displace the candidate with largest tally that is also above quota only active if
                # no eliminations/seatings has happened
                displacement_cost: float = 0
                if not gone:  # no eliminations or seatings yet
                    fp_others_max = max([cands[c.num].fp_votes for c in cands \
                                         if c.num not in gone_set and c.num != ce])
                    # if someone has reached quota, we need to surpass their votes
                    displacement_cost = max(0, 0.5 * (fp_others_max - cmax))  

                quota_lb = max(quota_lb, quota - cmax, displacement_cost)

        gone.append(ce)
        gone_set.add(ce)
        gone_pos[ce] = i

    return EqlbCtx(eqlbctx.N, transfer, elim_lb, quota_lb, no_quota_lb, nq_cons_added, \
                   winners, gone, gone_set, gone_pos, PXLEN)




def backcompute_nq_bound(i : int, ctx : EqlbCtx, cands: Sequence[CandidateLike], ballots: list[Ballot],\
                         order_c : list[int], order_q: dict[int, QRange], quota : int):

    gone = order_c[:i+1]
    gone_set = set(gone)
    rem_qs = [c for c in order_q.keys() if c not in gone_set and order_q[c][0] > i  \
              and not(c in ctx.nq_cons_added[i])]

    no_quota_lb: float = 0
    nq_cons_added: set[int] = set()

    if rem_qs == []:
        return no_quota_lb, nq_cons_added

    tallies: list[float]
    if i == 0:
        tallies = [cand.fp_votes for cand in cands]
    else:
        tallies = [0.0] * ctx.N

        for b in ballots:
            sv_add = None
            move_r = -1
            for p in b.prefs:
                if p in gone_set:
                    continue

                if sv_add is None:
                    sv_add, move_r = calc_tallies_q_prefix(b, gone, \
                        ctx.transfer, ctx.winners, order_q, ctx.gone_pos)

                if p in order_q:
                    if order_q[p][0] > move_r:
                        tallies[p] += sv_add
                        break
                    else:
                        continue

                tallies[p] += sv_add
                break

    for c in rem_qs:
        no_quota_lb = max(no_quota_lb, tallies[c] - quota)
        nq_cons_added.add(c)

    return no_quota_lb, nq_cons_added



def calc_tallies_q_prefix(b: Ballot, gone: list[int], transfer: dict[int, tuple[float,float]], \
    winners: Container[int], order_q: dict[int, QRange], \
    gone_pos: Optional[dict[int, int]] = None) -> tuple[float, int]:
    """
    This function calculates the value of the given ballot after the candidates in gone
    have been seated/eliminated in the order specified.

    Parameters:
    b (Ballot): The ballot type for which the value bounds are being calculated.
    gone (list): A list of candidates that have been eliminated or seated.
    transfer (dict): A dictionary mapping candidates to their transfer values.
    winners (list/set): Candidates that have won, must be contained in gone
    order_q (dict): A dictionary mapping winning candidates to the range
                    (earliest, latest) of rounds in which they could first
                    have a quota at the start of the round.
    gone_pos (dict): Optional precomputed map from candidate to their index in
                     gone. Callers evaluating many ballots against the same
                     gone list should pass this to avoid rebuilding it.

    Returns:
    tuple: A tuple containing the ballot value, and the last round in which it moved to a new candidate.

    """
    b_value = b.votes  # contribution of ballot to next candidate

    if gone_pos is None:
        gone_pos = {c: i for i, c in enumerate(gone)}

    prefs = b.prefs
    nprefs = len(prefs)
    ngone = len(gone)

    bidx = 0
    eidx = 0
    move_r = -1 # last round in which ballot moved
    while bidx < nprefs and eidx < ngone:  # while ballot not fully transferred
        bp = prefs[bidx]

        # bp already processed (seated or eliminated) in a round the ballot
        # has moved past: skip to next preference.
        pos = gone_pos.get(bp, -1)
        if 0 <= pos < eidx:
            bidx += 1
            continue

        ep = gone[eidx]

        if ep not in winners:  # eliminated candidate
            if bp == ep: move_r = eidx
            eidx += 1
        elif bidx > 0 and bp in order_q and order_q[bp][0] <= move_r:
            # bp already had a quota when the ballot was finding a new home
            # bp skipped, no reduction in ballot value
            bidx += 1
        elif bp == ep:  # ballot is transferred through seating
            b_value *= transfer[bp][0]
            move_r = eidx
            eidx += 1
            bidx += 1
        else:  # ep is seated before reached by ballot
            eidx += 1

    return b_value, move_r


def compute_elim_quota_lb_STV26(eqlbctx: EqlbCtx, cands: Sequence[CandidateLike], \
    ballots: list[Ballot], order_c: list[int], order_a: list[int], \
    quota: int, order_q: dict[int, QRange]) \
    -> EqlbCtx:
    """
    This function calculates the lower bound on the number of votes that need to be changed
    to alter the outcome of an election prefix. It does this by considering the elimination and quota
    constraints of the election.

    Parameters:
    cands (list): A list of Candidate objects representing the candidates in the election.
    ballots (list): A list of Ballot objects representing the ballots cast in the election.
    order_c (list): A list representing the order in which candidates were eliminated or seated.
    order_a (list): A list of 0s and 1s indicating whether a candidate was eliminated (0) or seated 
                   (1) in each round.
    quota (int): The quota for the election, i.e., the minimum number of votes a candidate needs to win a seat.
    order_q (dict): A dictionary mapping winning candidates to the range of rounds in which they could 
                    first achieve a quota (only membership is used in this function).

    Returns:
    tuple: The lower bound on the number of votes that need to be changed to alter the outcome of the 
           election prefix, and a map from each seated winner to (lower, upper) bounds on their transfer value.
    """

    elim_lb = eqlbctx.elim_lb
    quota_lb = eqlbctx.quota_lb
    transfer = {**eqlbctx.transfer}    
    gone = [*eqlbctx.gone]
    gone_set = {*eqlbctx.gone_set}
    winners = {*eqlbctx.winners}
    start = eqlbctx.round

    PXLEN = len(order_c)
    for i in range(start, PXLEN):
        ce = order_c[i]

        if order_a[i] == 0:  # candidate eliminated
            # Compute min vote 'ce' could have at this point, needs to be
            # less than max vote of other (non-super) candidates at this point
            # max_ce = cands[ce].fp_votes
            min_ce = cands[ce].fp_votes

            # dict of remaining candidates (eliminated or seated after ce)
            if i == 0:
                max_others : dict[int,float] = {c.num: cands[c.num].fp_votes for c in cands if c.num != ce}
            else:
                max_others = {c.num: 0 for c in cands if c.num not in gone_set and c.num != ce}

                for b in ballots:
                    prefs = [p for p in b.prefs if p not in gone_set]

                    if not prefs:  # ballot is exhausted
                        continue

                    _, elb_add, ub_add = calc_tallies(b, gone, transfer, winners)

                    if prefs[0] != ce:  # transferred to other (including fp votes)
                        max_others[prefs[0]] += ub_add
                    elif b.prefs[0] != ce:  # transferred to ce (fp votes already allocated)
                        min_ce += elb_add

            for _, v in max_others.items():
                elim_lb = max(elim_lb, max(0, 0.5 * (min_ce - v)))

        else:  # candidate seated
            if ce in order_q:  # candidate got a quota, else seated by default (last round)
                if i == 0:
                    lb_value = cands[ce].fp_votes
                    ub_value = lb_value
                else:
                    lb_value = 0  # lb on value of ballots
                    ub_value = 0  # ub on value of ballots (quota <= lb_value <= ub_value <= len(ballots))
                    for b in ballots:
                        prefs = [p for p in b.prefs if p not in gone_set]

                        if prefs:  # ballot is not exhausted
                            slb_add, _, ub_add = calc_tallies(b, gone, transfer, winners)
                            if prefs[0] == ce:
                                lb_value += slb_add
                            if i >= 1 and order_a[i-1] == 1 and ce in prefs:  # ambiguous case: ballot could be in any pile
                                ub_value += ub_add
                            elif prefs[0] == ce:
                                ub_value += ub_add

                winners.add(ce)

                cmax = ub_value
                lb_value = max(lb_value, quota)  # restrict lb_value to be at lest quota
                ub_value = max(lb_value, ub_value)  # restrict ub_value to be at lest lb_value
                transfer[ce] = ((lb_value - quota)/lb_value, (ub_value - quota)/ub_value)

                # cost to displace the candidate with largest tally that is also above quota 0nly active if
                # no eliminations/seatings has happened
                displacement_cost: float = 0
                if not gone:  # no eliminations yet
                    fp_others_max = max([cands[c.num].fp_votes for c in cands \
                                         if c.num not in gone_set and c.num != ce])
                    # if someone has reached quota, we need to surpass their votes
                    displacement_cost = max(0, 0.5 * (fp_others_max - cmax))  

                quota_lb = max(quota_lb, quota - cmax, displacement_cost)

        gone.append(ce)
        gone_set.add(ce)

    return EqlbCtx(eqlbctx.N, transfer, elim_lb, quota_lb, 0, [], \
                   winners, gone, gone_set, {}, PXLEN)


def calc_tallies(b: Ballot, gone: list[int], \
    transfer: dict[int, tuple[float, float]], winners: Container[int]) \
    -> tuple[float, float, float]:
    """
    This function calculates the lower and upper bounds on the value of a ballot after transfers.

    Parameters:
    b (Ballot): The ballot type for which the value bounds are being calculated.
    gone (list): A list of candidates that have been eliminated or seated.
    transfer (dict): A dictionary mapping candidates to their transfer values.
    winners (list): A list of candidates that have won, must be contained in gone

    Returns:
    tuple: A tuple containing the seating-based lower bound, elimination-based lower bound, and 
            upper bound on the value of the ballot after transfers.
    """
    b_value_slb = b.votes  # seating lower bound
    b_value_elb = b.votes  # elimination lower bound
    b_value_ub = b.votes  # upper bound
    final_block = []
    for ep in reversed(gone):
        if ep in winners:
            final_block.append(ep)
        else:
            break

    eliminated = set()
    seated = set()
    bidx = 0
    eidx = 0
    seat_block = False
    while bidx < len(b.prefs) and eidx < len(gone):  # while ballot not fully transferred
        bp = b.prefs[bidx]
        ep = gone[eidx]
        if ep not in winners:  # eliminated candidate
            eliminated.add(ep)
            eidx += 1
        elif bp in eliminated:  # full transfer: candidate eliminated
            seat_block = False  # (potential) previous seating block exited
            bidx += 1
        elif bp == ep:  # ballot is transferred through seating
            b_value_elb *= transfer[bp][0]  # lb: transfer through every cand in seating block
            if bp in final_block:
                b_value_slb *= 0  # lb: cand in question is skipped if we're trying to seat them
            else:
                b_value_slb *= transfer[bp][0]
            if not seat_block:  # not in a block
                b_value_ub *= transfer[bp][1]  # ub: transfer via first only, skips rest of seating block
            seat_block = True  # we have entered a block (possibly size one)
            eidx += 1
            bidx += 1
        elif bp in seated:  # skipping: bp already seated
            bidx += 1
        else:  # ep is seated before reached by ballot
            seated.add(ep)
            eidx += 1

    return b_value_slb, b_value_elb, b_value_ub


def compute_elim_quota_lb_BST19(eqlbctx : EqlbCtx, cands: Sequence[CandidateLike], \
    ballots: list[Ballot], order_c: list[int], order_a: list[int], \
    quota: int, order_q: dict[int, QRange]) -> EqlbCtx:

    elim_lb = eqlbctx.elim_lb
    quota_lb = eqlbctx.quota_lb   
    gone = [*eqlbctx.gone]
    gone_set = {*eqlbctx.gone_set}
    winners = {*eqlbctx.winners}
    start = eqlbctx.round

    PXLEN = len(order_c)
    for i in range(start, PXLEN):
        ce = order_c[i]

        if order_a[i] == 0:
            # Compute min vote 'ce' could have at this point, needs to be
            # less than max vote of other (non super) candidates at this point
            min_ce = cands[ce].fp_votes

            if i == 0:
                max_others : dict[int,float] = {c.num: cands[c.num].fp_votes for c in cands if c.num != ce}
            else:
                max_others = {c.num: 0 for c in cands if c.num not in gone_set and c.num != ce}

                for b in ballots:
                    prefs = []
                    through_winner = False
                    for p in b.prefs:
                        if not p in gone:
                            prefs.append(p)

                        if p in winners:
                            through_winner = True

                    if prefs == []:
                        continue

                    if prefs[0] != ce:
                        max_others[prefs[0]] += b.votes


                    elif b.prefs[0] != ce and not through_winner:
                        # We are giving 'ce' extra votes if all the candidates
                        # ranked higher than 'ce' have already been eliminated
                        # according to the given outcome.
                        min_ce += b.votes

            for c, v in max_others.items():
                elim_lb = max(elim_lb, max(0, 0.5 * (min_ce - v)))

        else:
            winners.add(ce)

            if ce in order_q:
                cmax: float
                if i == 0:
                    cmax = cands[ce].fp_votes
                else:
                    cmax = 0.0
                    for b in ballots:
                        prefs = []
                        for p in b.prefs:
                            if not p in gone:
                                prefs.append(p)

                        if prefs != [] and prefs[0] == ce:
                            cmax += b.votes

                quota_lb = max(quota_lb, quota - cmax)

        gone.append(ce)
        gone_set.add(ce)

    return EqlbCtx(eqlbctx.N, {}, elim_lb, quota_lb, 0, [], \
                   winners, gone, gone_set, {}, PXLEN)




def build_disp_cache_initial_q_prefix(N: int, candidates: Sequence[CandidateLike], \
    ballot_metadata : BallotMetadata) -> DispCache:
    return DispCache(N, False, {}, set(), ballot_metadata.above, \
                    ballot_metadata.mentions, [c.fp_votes for c in candidates], \
                    ballot_metadata.reassign, 0, 0)

def update_disp_cache_q_prefix(disp_cache: DispCache, ballots: list[Ballot], node_order_c: list[int], \
    node_order_q: dict[int, QRange], rem: list[int], transfer: dict[int, tuple[float,float]]) -> DispCache:

    if disp_cache.reassign == None:
        N = disp_cache.N
        min_r : list[float] =  [0]*N
        reassign  = [[0.0] * N for _ in range(N)]
        present = [0.0] * N
        above = [[0.0] * N for _ in range(N)]

        rem_set = set(rem)
        for b in ballots:
            pres = [p for p in b.prefs if p in rem_set]
            if not pres:
                continue
            c = pres[0]
            # This block changed in this quota-specific version of margin-stv
            value, move_r = calc_tallies_q_prefix(b, node_order_c, transfer, disp_cache.winners, \
                node_order_q, disp_cache.gone_pos)

            if c in node_order_q:
                if node_order_q[c][0] > move_r:
                    min_r[c] += value
            else:
                min_r[c] += value
                if len(pres) > 1:
                    reassign[c][pres[1]] += value

            for i, x in enumerate(pres):
                present[x] += value
                row = above[x]
                for y in pres[i + 1:]:
                    row[y] += value  

        # _replace returns a new tuple -- it does not mutate in place, so the
        # result has to be kept and returned.
        disp_cache = disp_cache._replace(curtally=min_r, present=present, \
                                        above=above, reassign=reassign)

    return disp_cache

def compute_disp_lb_STV26_q_prefix(disp_cache: DispCache, ballot_metadata : BallotMetadata,\
    ballots: list[Ballot], node_order_c: list[int], node_order_a: list[int], \
    node_order_q: dict[int, QRange], winner_set: set[int], rem: list[int], \
    quota: int, seats: int, transfer: dict[int, tuple[float,float]]) -> DispCache:
    """
        Consider a prefix where it is clear that at least one original loser
        still standing has to displace one of the original winners still
        standing (e.g., our prefix contains just eliminations or only original
        winners getting seated). In this case, we need to ensure that at least
        one of the original losers will not be eliminated before one of the
        original winners. We can put a lower bound on the number of vote
        changes required to ensure this by taking the difference between
        the maximum tallies of the remaining original losers and the minimum
        tallies of the remaining original winners. We then take the minimum of
        these vote changes as a lower bound.


        node_order_c : Outcome prefix, list of candidates in the order that
                       they are either elected or eliminated.

        node_order_a : Outcome prefix, list of 0s/1s for each round of the
                       prefix indicating whether a candidate was eliminated
                       in that round (0) or elected (1).

        winner_set   : Set of original winners of the election.

        ballots      : List of Ballot data structures representing ballot
                       types cast in the election and how many instances of
                       that type are present (reported).

        rem          : List of candidates not present in node_order_c.

    """

    # Determine if we need an original loser to get seated sometime
    # in the future (past the current outcome prefix)
    # new_winner is monotone down the tree -- once the prefix has changed who
    # won, every extension of it has too -- so once set it is carried in the
    # cache and the prefix is not rescanned.
    new_winner : bool = disp_cache.new_winner

    norder : int = len(node_order_c)
    if not new_winner:
        for i in range(disp_cache.start, norder):
            if node_order_a[i] == 1:
                if node_order_c[i] not in winner_set:
                    new_winner = True
                    break
            elif node_order_c[i] in winner_set:
                new_winner = True
                break

    # The displacement argument only applies while the prefix still leaves the
    # original outcome intact. Persist the flag so descendants short circuit
    # here without rescanning. Note we deliberately do not advance start: it is
    # paired with gone_pos, which this path does not extend.
    if new_winner:
        return disp_cache._replace(new_winner=True, lowerbound=0)

    # Compile set of original losers, and winners, that remain standing after
    # the outcome prefix node_order_c/node_order_a.
    og_losers: list[int] = []
    og_winners: list[int] = []
    for c in rem:
        if c in winner_set:
            og_winners.append(c)
        else:
            og_losers.append(c)

    sleft = seats - sum(node_order_a)
    nleft = len(rem)

    if sleft == nleft or og_losers == [] or og_winners == []:
        return disp_cache._replace(lowerbound=0)

    winners = {c for i, c in enumerate(node_order_c) if node_order_a[i] == 1}

    rem_set = set(rem)
    gone_pos = {**disp_cache.gone_pos}
    for i in range(disp_cache.start, norder):
        gone_pos[node_order_c[i]] = i

    ncand = disp_cache.N
    og_winners_set = set(og_winners)

    ca = node_order_a[-1]
    if ca == 0 and disp_cache.curtally and disp_cache.reassign and disp_cache.present and disp_cache.above:
        ce = node_order_c[-1]
        min_r = [disp_cache.curtally[c] + disp_cache.reassign[ce][c] for c in range(disp_cache.N)]
        reassign = None
        present = disp_cache.present
        above = disp_cache.above

    else:
        min_r : list[float] =  [0]*ncand 
        reassign  = [[0.0] * ncand for _ in range(ncand)]
        present = [0.0] * ncand
        above = [[0.0] * ncand for _ in range(ncand)]

        for b in ballots:
            pres = [p for p in b.prefs if p in rem_set]
            if not pres:
                continue
            c = pres[0]
            # This block changed in this quota-specific version of margin-stv
            value, move_r = calc_tallies_q_prefix(b, node_order_c, transfer, winners, \
                node_order_q, gone_pos)

            if c in node_order_q:
                if node_order_q[c][0] > move_r:
                    min_r[c] += value
            else:
                min_r[c] += value
                if len(pres) > 1:
                    reassign[c][pres[1]] += value

            for i, x in enumerate(pres):
                present[x] += value
                row = above[x]
                for y in pres[i + 1:]:
                    row[y] += value        

    # calculate how much it costs to seat ogl
    lowerbound: float = np.inf
    for ogl in og_losers:
        displacement_cost: float = np.inf
        left_at_end_costs: list[float] = []

        max_ogl: float = present[ogl]

        for r in rem:
            if r == ogl:
                continue

            max_l_r = max_ogl - above[r][ogl]  # value on ballots where ogl outlasts r
            dp = max(0.0, 0.5 * (min_r[r] - max_l_r))
            left_at_end_costs.append(dp)
            if r in og_winners_set:
                displacement_cost = min(displacement_cost, dp)

        quota_cost = max(0, quota - max_ogl)
        left_at_end_costs.sort()

        # ogl needs to outlast nleft - sleft candidates
        left_at_end_cost = max(left_at_end_costs[:nleft - sleft])

        lowerbound = min(lowerbound, max(displacement_cost, min(quota_cost,left_at_end_cost)))

    # minus small amount before ceil to avoid situation where noise has 
    # given us a lowerbound with a very tiny fractional component and we 
    # round up to nearest integer. 
    lowerbound = math.ceil(lowerbound - 1e-4)
    return DispCache(ncand, new_winner, gone_pos, winners, above, present, min_r, reassign, norder, lowerbound)


def compute_disp_lb_STV26(disp_cache: DispCache, candidates: Sequence[CandidateLike], \
    ballots: list[Ballot], node_order_c: list[int], node_order_a: list[int], \
    winner_set: set[int], rem: list[int], quota: int, seats: int, \
    transfer: dict[int, tuple[float, float]]) -> DispCache:
    """
        Consider a prefix where it is clear that at least one original loser
        still standing has to displace one of the original winners still
        standing (e.g., our prefix contains just eliminations or only original
        winners getting seated). In this case, we need to ensure that at least
        one of the original losers will not be eliminated before one of the
        original winners. We can put a lower bound on the number of vote
        changes required to ensure this by taking the difference between
        the maximum tallies of the remaining original losers and the minimum
        tallies of the remaining original winners. We then take the minimum of
        these vote changes as a lower bound.


        node_order_c : Outcome prefix, list of candidates in the order that
                       they are either elected or eliminated.

        node_order_a : Outcome prefix, list of 0s/1s for each round of the
                       prefix indicating whether a candidate was eliminated
                       in that round (0) or elected (1).

        winner_set   : Set of original winners of the election.

        ballots      : List of Ballot data structures representing ballot
                       types cast in the election and how many instances of
                       that type are present (reported).

        rem          : List of candidates not present in node_order_c.

        quota        : Quota for the election.

        seats        : Number of seats in the election.

        transfer     : Map from each seated winner to (lower, upper) bounds
                       on their transfer value.

        globalub     : Running upper bound on the margin (currently unused).

    """
    # Determine if we need an original loser to get seated sometime
    # in the future (past the current outcome prefix)
    new_winner = False
    for i in range(len(node_order_c)):
        if node_order_a[i] == 1:
            if node_order_c[i] not in winner_set:
                new_winner = True
                break
        elif node_order_c[i] in winner_set:
            new_winner = True
            break

    # The displacement argument only applies while the prefix still leaves the
    # original outcome intact. Persist the flag so descendants short circuit
    # here without rescanning. Note we deliberately do not advance start: it is
    # paired with gone_pos, which this path does not extend.
    if new_winner:
        return disp_cache._replace(new_winner=True, lowerbound=0)    

    # Compile set of original losers, and winners, that remain standing after
    # the outcome prefix node_order_c/node_order_a. The sets will remain
    # empty if we have already changed who won the election in the outcome
    # prefix.
    og_losers = []
    og_winners = []
    if not new_winner:
        for c in rem:
            if c in winner_set:
                og_winners.append(c)
            else:
                og_losers.append(c)

    sleft = seats - sum(node_order_a)
    nleft = len(rem)

    if sleft == nleft or og_losers == [] or og_winners == []:
        return disp_cache._replace(lowerbound=0)

    winners = {c for i, c in enumerate(node_order_c) if node_order_a[i] == 1}

    min_r : dict[int,float] = {c.num: 0 for c in candidates if c.num in rem}
    filtered_ballots = []
    for b in ballots:
        prefs = [p for p in b.prefs if p in rem]
        if not prefs:
            continue
        _, elb, ub = calc_tallies(b, node_order_c, transfer, winners)
        filtered_ballots.append((b.ranks, elb, ub))
        min_r[prefs[0]] += elb


    ncand = len(candidates)

    # calculate how much it costs to seat ogl
    lowerbound = np.inf
    for ogl in og_losers:
        displacement_cost = np.inf
        left_at_end_costs = []

        max_l = [0.0]*ncand

        max_ogl = 0.0
        for ranks, elb, ub in filtered_ballots:
            posl = ranks[ogl]
            if posl != -1:
                max_ogl += ub

            # calculate how much it costs to displace r with ogl
            for r in rem:
                if r == ogl:
                    continue
                
                posw = ranks[r]
                if posl != -1 and (posw == -1 or posl < posw):  # ogl ranked above ogw
                      max_l[r] += ub

        
        for r in rem:
            if r == ogl:
                continue;

            dp = max(0.0, 0.5 * (min_r[r] - max_l[r]))
            left_at_end_costs.append(dp)
            if r in og_winners:
                displacement_cost = min(displacement_cost, dp)

        quota_cost = max(0, quota - max_ogl)
        left_at_end_costs.sort()

        # ogl needs to outlast nleft - sleft candidates
        left_at_end_cost = max(left_at_end_costs[:nleft - sleft])

        lowerbound = min(lowerbound, max(displacement_cost, min(quota_cost,left_at_end_cost)))

    # Snap away floating-point noise before rounding up (see the q-prefix
    # variant): a bound that is mathematically an integer can land just above
    # it and spuriously inflate this lower bound past its true value.
    return disp_cache._replace(lowerbound=math.ceil(lowerbound - 1e-6))


def treestv(ballots: list[Ballot], ballot_metadata : BallotMetadata, candidates: list[Candidate], \
            winners: list[int], order_c: list[int], order_a: list[int], \
            upperbound: float, args: argparse.Namespace, \
            quota: int, tot_ballots: float, log: Optional[TextIO] = None) \
            -> tuple[float, float, int, int, int, int]:
    """
        Main function for performing the branch-and-bound algorithm that
        searches for the least number of vote changes required to elect
        a different set of winners than those in 'winners'.

        candidates   : List of Candidate data structures, ordered by 
                       candidate 'number' (note, 'number' is an index, not
                       their numeric id).

        ballots      : List of Ballot data structures representing ballot 
                       types cast in the election and how many instances of
                       that type are present (reported).

        winners      : List of candidates (by their number) that won in 
                       the reported outcome. 

        order_c      : Reported outcome (order in which candidates were
                       elected/eliminated).

        order_a      : List of 0s/1s indicating whether the candidate
                       'processed' in each round was elected-1/eliminated-0.

        upperbound   : Computed upper bound on the margin of victory.

        args         : Command line arguments (args.agap gives the gap
                       between the running lower and upper bounds on the
                       margin at which we terminate the branch-and-bound
                       algorithm; args.limit gives the max solve time).

        quota        : Quota for the election

        tot_ballots  : Total number of ballots cast in the election.

        log          : Will either be None or an output stream to use when
                       printing out diagnostics.
    """

    tstart = time.time()

    agap = args.agap
    tlimit = args.limit

    winner_set = set(winners)
    ncands = len(candidates)

    frontier = Frontier()

    running_ub = upperbound
    running_lb: float = 0

    nexps = 0
    nsolves = 0

    # Lightweight candidate records for child evaluation: that code only
    # reads .num and .fp_votes, so we avoid shipping the ballot/simulation
    # bookkeeping stored on Candidate objects to every worker process.
    lite_cands = [CandLite(c.num, c.fp_votes) for c in candidates]

    # Election invariants used by eval_child/eval_child_initial/expand_node.
    # These are sent to each worker process once (via the pool initializer)
    # rather than being pickled into every task.
    initargs = (ballots, ballot_metadata, lite_cands, winner_set, ncands, args, quota, \
        tot_ballots, list(order_c), list(order_a))

    # Set up the evaluation context in this process too, for args.pc == 1.
    _init_worker(*initargs)

    pool = None
    if args.pc > 1:
        # One pool for the whole search (previously a fresh pool was spawned
        # for every expansion). Workers are recycled periodically to bound
        # any memory retained by the MINLP solver across solves.
        pool = Pool(processes=args.pc, initializer=_init_worker, \
            initargs=initargs, maxtasksperchild=50)

    try:
        children: list[tuple[list[int], list[int], dict[int, QRange], \
            set[int], list[int], float]] = []

        # Initialise frontier. For each candidate, they can either be elected
        # to a seat or eliminated. Assumption: election involves at least 2
        # seats, so our initial set of nodes will not include any leaves.
        for cand in candidates:
            node_order_c = [cand.num]

            rem = [c.num for c in candidates if c.num != cand.num]

            for o in range(2):
                node_order_a = [o]
                node_winners = set([cand.num]) if o == 1 else set()

                node_order_q: dict[int, QRange] = {}
                if o == 1:
                    if args.useqprefix:
                        # Quota-in-prefix convention: quota held at the
                        # start of round 0 (on first preferences). The
                        # MINLP in stvdistance-qprefix.py encodes a first
                        # preference quota as round 0, not -1.
                        node_order_q = { cand.num : (0, 0) }
                    else:
                        # get_order_q convention: -1 marks a quota achieved
                        # on first preferences.
                        node_order_q = { cand.num : (-1, -1) }

                children.append((node_order_c, node_order_a, node_order_q, \
                                 node_winners, rem, running_ub))

        if pool is not None:
            result = pool.starmap(eval_child_initial, children)
        else:
            result = [eval_child_initial(*c) for c in children]

        for lb, dlb, eqlb, node, solved in result:
            if solved:
                nsolves += 1

            if log != None:
                print("EVALUATING {}/{} LB {} (D {} EQ {})".format( \
                    node.order_c, node.order_a, lb, dlb, eqlb),  file=log, flush=True)

                if lb < running_ub:
                    if node.dist is None:
                        print("    DISTANCE None/Infeasible", file=log, flush=True)
                    elif node.dist == -1:
                        print("    No solution found by timeout", file=log,  flush=True)
                        print("    Margin computation terminated", file=log,  flush=True)
                    else:
                        assert node.dist_ub is not None
                        print("    DISTANCE {:.2f}/{:.2f}".format(node.dist,  node.dist_ub), file=log, flush=True)

            if node.dist == -1:
                return running_lb, running_ub, nexps, nsolves,  frontier.ignore_cntr, frontier.agg_prune_cntr

            # skip infeasible nodes
            if node.dist is None or node.dist >= running_ub:
                continue
            else:
                if log != None:
                    print("        Added to frontier", file=log, flush=True)

            if frontier.size > 0:
                running_lb = frontier.get_lower_bound()
            else:
                running_lb = node.dist

            frontier.insert(node, lse=args.lse, log=log)

        if log != None:
            print("Lower bound {}, upper bound {}".format(running_lb, running_ub), file=log, flush=True)

            print(frontier, file=log, flush=True)

        converged = False

        tnow = time.time()
        if log != None:
            print("Time elapsed {}s".format(tnow - tstart), file=log, flush=True)

        if tlimit != None and tnow - tstart > tlimit:
            print("Time start {}, now {}, difference {}".format(tstart, tnow, tnow  - tstart), file=log, flush=True)
            return running_lb, running_ub, nexps, nsolves, frontier.ignore_cntr, frontier.agg_prune_cntr

        if frontier.size == 0:  # search space exhausted
            running_lb = running_ub  # running_ub must be a true lower bound
            if log is not None:
                print("Search space exhausted", file=log, flush=True)

        while frontier.size > 0:
            running_lb = frontier.get_lower_bound()

            if log != None:
                print("Lower bound {}, upper bound {}".format(running_lb, running_ub), file=log, flush=True)

            if abs(running_ub - running_lb) <= agap:
                converged = True
                break

            # Expand node with smallest assigned distance (first in frontier)
            fnodes = frontier.pop(args.pc)
            nexps += 1

            toexpand: list[tuple[FNodeData, float]] = []

            # expand nodes until frontier is empty or we have converged
            for fn in fnodes:
                if log != None:
                    print("EXPANDING NODE {}".format(fn), file=log, flush=True)

                assert(fn.dist is not None)
                toexpand.append(((fn.eqlbctx, fn.disp_cache, fn.order_c, fn.order_a, fn.order_q, \
                    fn.rem, fn.winners, fn.dist), running_ub))

            if pool is not None and getattr(args, "evalpara", False):
                # Child-granularity parallelism: generate every popped node's
                # children (with their shared amortisation) here, then evaluate
                # all children across the pool. Mirrors the initial frontier.
                all_specs = [c for t in toexpand for c in generate_children(*t)]
                flat = pool.starmap(eval_child, all_specs)
                expanded = [flat]
            elif pool is not None:
                # Node-granularity parallelism: each worker expands one node
                # (generating and evaluating its children).
                expanded = pool.starmap(expand_node, toexpand)
            else:
                expanded = [expand_node(*t) for t in toexpand]

            for child_results in expanded:
                for isleaf, eqlbctx, disp_cache, node_order_c, node_order_a, node_order_q, lb, dlb, eqlb, dist, \
                        dist_ub, new_rem, node_winners, solved in child_results:

                    if solved:
                        nsolves += 1

                    if log != None:
                        print("EVALUATED {}/{}/{} LB {} (D {} EQ {})".format( \
                            node_order_c, node_order_a, node_order_q, lb, dlb, eqlb), \
                            file=log, flush=True)

                        if dist == None:
                            print("    DISTANCE None/Infeasible", file=log, \
                                  flush=True)
                        else:
                            print("    DISTANCE {}/{}, MINLP used: {}".format(dist, dist_ub, solved), \
                                  file=log, flush=True)

                    # skip infeasible nodes
                    if dist is None or dist >= running_ub:
                        if log != None:
                            print("        PRUNED!", file=log, flush=True)
                        continue

                    if isleaf:
                        # fully evaluated leaf nodes
                        if log != None:
                            print("        LEAF", file=log, flush=True)

                        if log != None and dist < running_ub:
                            print("Reducing upper bound from {} to {}".format(running_ub, dist), \
                                  file=log, flush=True)

                        running_ub = min(running_ub, dist)  # update running_ub if possible

                        if abs(running_ub - running_lb) <= agap:
                            converged = True
                            break

                        frontier.prune(running_ub, log=log)
                    else:
                        newn = TreeNode(node_order_c, node_order_a, node_order_q, \
                                        node_winners, new_rem, eqlbctx, disp_cache, dist, dist_ub)

                        idx = frontier.insert(newn, lse=args.lse, log=log)

                        if log is not None and idx is None:
                            print("        SUBSUMED", file=log, flush=True)
                if converged:
                    break

            # Per-round bookkeeping. This has to run once the whole batch of
            # popped nodes has been processed, not after each parent: every
            # node in the batch is removed from the frontier up front, so
            # mid-batch the frontier is missing the subtrees of the parents
            # not yet handled. Testing it for emptiness there abandons their
            # already-computed children, and reading a lower bound off it
            # there can be too high.
            # Skip when already converged: that path breaks out before
            # frontier.prune, so the frontier can still hold nodes at or above
            # running_ub and reading a bound off it would invert lb/ub.
            if not converged and frontier.size > 0:
                # check if running_lb can be increased
                old_lb = running_lb
                running_lb = max(running_lb, frontier.get_lower_bound())

                if old_lb < running_lb and log is not None:
                    print(f"Increasing lower bound from {old_lb} to {running_lb}", file=log, flush=True)

                if abs(running_ub - running_lb) <= agap:
                    converged = True
                    break

            if frontier.size == 0:  # search space exhausted
                running_lb = running_ub  # running_ub must be a true lower bound
                if log is not None:
                    print("Search space exhausted", file=log, flush=True)

            if converged:
                break

            tnow = time.time()
            if log != None and frontier.size > 0:
                print("Lower bound {}, upper bound {}".format(running_lb, \
                    running_ub), file=log, flush=True)
                print(frontier, file=log, flush=True)
                print("Time elapsed {}s".format(tnow - tstart), file=log, flush=True)

            if tlimit != None and tnow - tstart > tlimit:
                return running_lb, running_ub, nexps, nsolves, frontier.ignore_cntr,\
                    frontier.agg_prune_cntr

    finally:
        if pool is not None:
            pool.terminate()
            pool.join()

    if converged or frontier.size == 0:
        if log != None:
            print("-------------------------------------------", file=log, \
                  flush=True)
            print("MARGIN LB: {}--{}, {} nodes expanded, {} solves.".format( \
                running_lb, running_ub, nexps, nsolves), file=log, flush=True)
            print("-------------------------------------------", file=log, \
                  flush=True)

    if log != None:
        print("Time to finish: {}s".format(time.time() - tstart), file=log)

    return running_lb, running_ub, nexps, nsolves, frontier.ignore_cntr,\
        frontier.agg_prune_cntr

# Lightweight stand-in for Candidate in worker processes: the child
# evaluation code only reads these two fields.
class CandLite(NamedTuple):
    num: int
    fp_votes: float

# Per-process evaluation context (election invariants), set once per worker
# by the pool initializer -- and in the main process for args.pc == 1 --
# instead of pickling these into every task.
Ctx = tuple[list[Ballot], BallotMetadata, Sequence[CandLite], set[int], \
    int, argparse.Namespace, int, float, list[int], list[int]]

_CTX: Optional[Ctx] = None


# Worker-local profiler state: (profiler, output path, [last dump time]).
_PROF: Optional[tuple[cProfile.Profile, str, list[float]]] = None


def _start_worker_profile() -> None:
    """Profile this pool worker, dumping stats periodically at task boundaries.

    Opt-in via MSTV_PROFILE=<output dir>. Only pool workers are profiled:
    _init_worker also runs in the parent (for pc == 1), and enabling a
    profiler there before Pool() forks would leave every child with an
    inherited, never-disabled profiler.

    The search ends with pool.terminate(), so workers are SIGTERMed and never
    unwind cleanly -- neither atexit nor a SIGTERM handler reliably produces a
    complete dump. Instead each worker rewrites its own profile every
    _PROF_INTERVAL seconds, so whatever is on disk when it is killed is a
    valid profile of everything up to the last task boundary.
    """
    global _PROF

    outdir = os.environ.get("MSTV_PROFILE")
    if not outdir:
        return
    if multiprocessing.current_process().name == "MainProcess":
        return

    os.makedirs(outdir, exist_ok=True)

    # Workers are recycled (maxtasksperchild), so a pid can recur; pick a
    # free name once and keep rewriting it.
    base = os.path.join(outdir, "worker_{}".format(os.getpid()))
    path, n = base + ".prof", 0
    while os.path.exists(path):
        n += 1
        path = "{}_{}.prof".format(base, n)

    pr = cProfile.Profile()
    _PROF = (pr, path, [time.time()])
    pr.enable()


_PROF_INTERVAL = 20.0


def _profile_tick() -> None:
    """Flush this worker's profile if the dump interval has elapsed."""
    if _PROF is None:
        return
    pr, path, last = _PROF
    now = time.time()
    if now - last[0] < _PROF_INTERVAL:
        return
    last[0] = now
    pr.disable()
    try:
        # Write via a temp file so a kill mid-dump cannot leave a truncated
        # profile in place of the previous good one.
        tmp = path + ".tmp"
        pr.dump_stats(tmp)
        os.replace(tmp, path)
    finally:
        pr.enable()


def _init_worker(ballots: list[Ballot], ballot_metadata: BallotMetadata, \
                 candidates: Sequence[CandLite], \
                 winner_set: set[int], ncands: int, \
                 args: argparse.Namespace, quota: int, tot_ballots: float, \
                 full_order_c: list[int], full_order_a: list[int]) -> None:
    global _CTX
    _CTX = (ballots, ballot_metadata, candidates, winner_set, ncands, args, quota, \
        tot_ballots, full_order_c, full_order_a)
    _start_worker_profile()


def collapse_order_q(order_q: dict[int, QRange]) -> dict[int, int]:
    """
        Collapse quota-round ranges to the single exact round expected by
        the quota-in-prefix MINLP model; when args.useqprefix is set the
        ranges must be degenerate (earliest == latest).
    """
    return {c: rng[1] for c, rng in order_q.items()}


def solve_stvdistance(candidates: Sequence[CandidateLike], \
    ballots: list[Ballot], order_c: list[int], order_a: list[int], \
    rem: list[int], winners: set[int], order_q: dict[int, QRange], \
    merge_map: dict[int, int], supers: list[int], tot_ballots: float, \
    args: argparse.Namespace, quota: int, upperbound: float, \
    last_round: int, lowerbound: float, isleaf: bool = False) \
    -> tuple[bool, Optional[int], Optional[int]]:
    """
        Solve the distance MINLP for an outcome prefix using the model
        variant selected by args.useqprefix: the quota-in-prefix model
        (stvdistance-qprefix.py) records a single exact quota round per
        candidate, the default model works with quota-round ranges.
    """
    if args.useqprefix:
        return stvdistance_qprefix(candidates, ballots, order_c, order_a, \
            rem, winners, collapse_order_q(order_q), merge_map, supers, \
            tot_ballots, args, quota, upperbound, last_round, lowerbound, \
            isleaf)

    return stvdistance(candidates, ballots, order_c, order_a, rem, \
        winners, order_q, merge_map, supers, tot_ballots, args, quota, \
        upperbound, last_round, lowerbound, isleaf)


def eval_child_initial(node_order_c: list[int], node_order_a: list[int], \
                       node_order_q: dict[int, QRange], node_winners: set[int], \
                       rem: list[int], running_ub: float) \
                       -> tuple[float, float, float, TreeNode, bool]:
    assert _CTX is not None
    ballots, ballot_metadata, candidates, winner_set, ncands, args, quota, tot_ballots, \
        full_order_c, full_order_a = _CTX

    # Is this a prefix of the original outcome?
    l = len(node_order_c)
    orig_prefix = node_order_c[:l] == full_order_c[:l] and node_order_a[:l] == full_order_a[:l]

    transfer = None
    _eqlbctx = EqlbCtx(ncands, {}, 0, 0, 0, [set()]*ncands, set(), [], set(), {}, 0)
    if args.eqlb or args.eqlbc:
        if args.useqprefix:
            _eqlbctx = compute_elim_quota_lb_STV26_q_prefix(_eqlbctx, candidates, \
                ballots, node_order_c, node_order_a, quota, node_order_q, None)
        else:
            _eqlbctx  = compute_elim_quota_lb_STV26(_eqlbctx, candidates, ballots, \
                node_order_c, node_order_a, quota, node_order_q)
    else:
        _eqlbctx = compute_elim_quota_lb_BST19(_eqlbctx, candidates, ballots, node_order_c, \
                                     node_order_a, quota, node_order_q)
    eqlb = max(0, math.ceil(max(_eqlbctx.elim_lb, _eqlbctx.quota_lb, _eqlbctx.no_quota_lb)))
    transfer = _eqlbctx.transfer

    if orig_prefix:
        eqlb = 0

    _disp_cache = DispCache(ncands, False, {}, set(), ballot_metadata.above, \
                    ballot_metadata.mentions, [c.fp_votes for c in candidates], \
                    ballot_metadata.reassign, 0, 0)
    if eqlb >= running_ub:
        return eqlb, 0, eqlb, TreeNode(node_order_c, node_order_a, node_order_q, \
            node_winners, rem, _eqlbctx, _disp_cache, eqlb, eqlb), False

    if (args.dlb or args.dlbc) and transfer is not None:
        if args.useqprefix:
            _disp_cache = compute_disp_lb_STV26_q_prefix(_disp_cache, ballot_metadata,  \
                ballots, node_order_c, node_order_a, node_order_q, \
                winner_set, rem, quota, args.seats, transfer)
        else:
            _disp_cache = compute_disp_lb_STV26(_disp_cache, candidates, ballots, \
                node_order_c, node_order_a, winner_set, rem, quota, args.seats, transfer)
        disp_lowerbound = _disp_cache.lowerbound   
    else:
        disp_lowerbound = 0

    lb = max(disp_lowerbound, eqlb)

    # Initial-frontier nodes are internal -- they are always inserted into the
    # frontier, never leaf-handled, and they are solved as non-leaves -- so
    # like every other internal node they are only solved under -allminlps.
    # This is eval_child's skipsolve with isleaf fixed to False.
    skipsolve: bool = args.nominlps or not args.allminlps

    if lb >= running_ub or skipsolve:
        return lb, disp_lowerbound, eqlb, TreeNode(node_order_c, node_order_a, node_order_q, \
            node_winners, rem, _eqlbctx, _disp_cache, lb, lb), False

    merge_map = {c.num: c.num for c in candidates}

    # Evaluate distance for our new tree node.
    _, dist, dist_ub = solve_stvdistance(candidates, ballots, node_order_c, \
                                   node_order_a, rem, node_winners, node_order_q, merge_map, [], \
                                   tot_ballots, args, quota, running_ub, 0, lb)

    return lb, disp_lowerbound, eqlb, TreeNode(node_order_c, \
          node_order_a, node_order_q, node_winners, rem, _eqlbctx, _disp_cache, dist, dist_ub), True


def eval_child(parent_dist: float, eqlbctx: EqlbCtx, disp_cache: DispCache, node_order_c: list[int], \
               node_order_a: list[int], node_order_q: dict[int, QRange], \
               node_winners: set[int], rem: list[int], isleaf: bool, \
               running_ub: float, precomputed_elim_tallies: Optional[list[float]] = None) -> ChildResult:
    assert _CTX is not None
    ballots, ballot_metadata, candidates, winner_set, ncands, args, quota, tot_ballots, \
        _, _ = _CTX

    transfer  = None
    _eqlbctx  = None
    _disp_cache = None

    if not args.eqlbc:
        eqlbctx = EqlbCtx(ncands, {}, 0, 0, 0, [set()]*ncands, set(), [], set(), {}, 0)

    if not args.dlbc:
        disp_cache = DispCache(ncands, False, {}, set(), None, None, None, None, 0, 0)

    if args.eqlb or args.eqlbc:
        if args.useqprefix:
            _eqlbctx = compute_elim_quota_lb_STV26_q_prefix(eqlbctx, candidates, \
                ballots, node_order_c, node_order_a, quota, node_order_q, precomputed_elim_tallies)
        else:
            _eqlbctx = compute_elim_quota_lb_STV26(eqlbctx, candidates, ballots, \
                node_order_c, node_order_a, quota, node_order_q)
    else:
        _eqlbctx  = compute_elim_quota_lb_BST19(eqlbctx, candidates, ballots, node_order_c, \
                node_order_a, quota, node_order_q)
        
    eqlb = max(0, math.ceil(max(_eqlbctx.elim_lb, _eqlbctx.quota_lb, _eqlbctx.no_quota_lb)))
    transfer = _eqlbctx.transfer

    if eqlb >= running_ub:
        disp_cache = DispCache(ncands, False, {}, set(), None, None, None, None, 0, 0)
        return (isleaf, _eqlbctx, disp_cache, node_order_c, node_order_a, node_order_q, eqlb, \
                0, eqlb, eqlb, eqlb, rem, node_winners, False)
    
    # An empty transfer is legitimate -- no prefix winner has a transfer value
    # yet -- so test for None, not truthiness, matching eval_child_initial.
    if (args.dlb or args.dlbc) and transfer is not None:
        # Note, if we don't compute eqlb prior transfer will not be up to date.
        if args.useqprefix:
            _disp_cache = compute_disp_lb_STV26_q_prefix(disp_cache, ballot_metadata, \
                ballots, node_order_c, node_order_a, node_order_q, \
                winner_set, rem, quota, args.seats, transfer)
        else:
            _disp_cache = compute_disp_lb_STV26(disp_cache, candidates, ballots, \
                node_order_c, node_order_a, winner_set, rem, quota, \
                args.seats, transfer)
        disp_lowerbound = _disp_cache.lowerbound   
    else:
        _disp_cache = disp_cache
        disp_lowerbound = 0

    lowerbound = max(eqlb, max(disp_lowerbound, parent_dist))

    # Solve a leaf always, an internal node only under -allminlps, and nothing
    # under -nominlps.
    skipsolve: bool = args.nominlps or not (args.allminlps or isleaf)

    if lowerbound >= running_ub or skipsolve:
        return (isleaf, _eqlbctx, _disp_cache, node_order_c, node_order_a, node_order_q, lowerbound, \
                disp_lowerbound, eqlb, lowerbound, lowerbound, rem, node_winners, False)

    # Work out the round at which we can stop forming constraints, and
    # solve the distance-to model.
    if args.m:
        m_order_c, m_order_a, m_order_q, merge_map, supers = \
            merge_outcome(node_order_c, node_order_a, node_order_q, rem)

        LAST_ROUND = compute_last_round(m_order_c, m_order_a, args.seats, \
                                        len(m_order_c) + len(rem))

        _, dist, dist_ub = solve_stvdistance(candidates, ballots, m_order_c, \
                                       m_order_a, rem, node_winners, m_order_q, merge_map, \
                                       supers, tot_ballots, args, quota, running_ub, LAST_ROUND, \
                                       lowerbound, isleaf)

    else:
        LAST_ROUND = compute_last_round(node_order_c, node_order_a, \
                                        args.seats, ncands)

        merge_map = {c.num: c.num for c in candidates}
        _, dist, dist_ub = solve_stvdistance(candidates, ballots, node_order_c, \
                                       node_order_a, rem, node_winners, node_order_q, merge_map, \
                                       [], tot_ballots, args, quota, running_ub, LAST_ROUND, \
                                       lowerbound, isleaf)

    return isleaf, _eqlbctx, _disp_cache, node_order_c, node_order_a, node_order_q, \
        lowerbound, disp_lowerbound, eqlb, dist, dist_ub, rem, node_winners, True


def generate_children(fnode_data: FNodeData, running_ub: float) -> list:
    """
    Build the list of eval_child argument tuples for one frontier node,
    including the per-expansion amortisation (build_disp_cache / round tallies).
    Does NOT evaluate the children -- see expand_node (node-granularity
    parallelism) and the --evalpara path in treestv (child-granularity).
    """
    assert _CTX is not None
    ballots, _, candidates, winner_set, ncands, args, _, _, _, _ = _CTX

    eqlbctx, disp_cache, forder_c, forder_a, forder_q, frem, fwinners, fdist = fnode_data

    children: list[tuple[float, EqlbCtx, DispCache, list[int], list[int], \
        dict[int, QRange], set[int], list[int], bool, float, Optional[list[float]]]] = []

    elim_tallies = None
    if args.useqprefix:
        if args.dlbc:
            # Recompute reassign, above, present
            disp_cache = update_disp_cache_q_prefix(disp_cache, ballots, forder_c, \
                forder_q, frem, eqlbctx.transfer) # Need to fix for case where we don't have eqlb on

        if args.prec_et:
            elim_tallies = compute_round_tallies_q_prefix(ballots, \
                eqlbctx.gone, eqlbctx.gone_set, eqlbctx.transfer, \
                eqlbctx.winners, forder_q, eqlbctx.gone_pos, ncands)
   
                
    # Add a candidate to the end of the outcome prefix represented
    # by the selected node. That candidate can either be seated or
    # eliminated.
    for r in frem:
        # Candidate can either be elected or eliminated.
        for o in range(2):
            node_order_c = forder_c + [r]

            rem = [c.num for c in candidates if not c.num in node_order_c]

            node_winners = set(fwinners)
            if o == 1:
                node_winners.add(r)

            if node_winners == winner_set:
                # This represents the original outcome
                continue

            node_order_a = forder_a + [o]

            # Have we filled all seats?
            seats_filled = sum(node_order_a)

            new_rem = rem
            nrem = len(rem)
            isleaf = False

            if seats_filled > args.seats:
                continue  # invalid outcome (too many seats filled)
            elif seats_filled == args.seats:
                node_order_c += rem
                node_order_a += [0] * nrem
                new_rem = []
                isleaf = True

            elif args.seats - seats_filled == nrem:
                # Are we in a situation where the number of seats left
                # equals the number of candidates in rem?
                if winner_set - node_winners == set(rem):
                    continue

                isleaf = True

            if o == 0:
                children.append((fdist, eqlbctx, disp_cache, node_order_c, node_order_a, \
                    forder_q, node_winners, new_rem, isleaf, running_ub, elim_tallies))
            else:
                if args.useqprefix:
                    # Quota-round variants for r: any round in the run of
                    # consecutive seatings ending at r's own round. Scan
                    # from r's round (index len(forder_a)), not from the
                    # end of node_order_a: when this child fills the last
                    # seat, node_order_a has just been padded with the
                    # remaining eliminations, and scanning from the padded
                    # end would break immediately and generate no child at
                    # all, silently dropping every leaf outcome that ends
                    # with a seating.
                    LENF = len(forder_a)
                    minqr = LENF
                    if forder_a[-1] == 1:
                        minqr = forder_q[forder_c[-1]][0]

                    for i in range(LENF, minqr-1, -1):
                        node_order_q = {**forder_q, r : (i, i)}
                        children.append((fdist, eqlbctx, disp_cache, node_order_c, node_order_a, \
                            node_order_q, node_winners, new_rem, isleaf, running_ub, elim_tallies))
                else:
                    LAST_ROUND = compute_last_round(node_order_c, \
                        node_order_a, args.seats, ncands)
                    order_c_index = {c: idx for idx, c in enumerate(node_order_c)}
                    node_order_q = get_order_q(node_order_a, LAST_ROUND, \
                        node_winners, order_c_index)
                    children.append((fdist, eqlbctx, disp_cache, node_order_c, node_order_a, \
                        node_order_q, node_winners, new_rem, isleaf, running_ub, elim_tallies))

    return children


def expand_node(fnode_data: FNodeData, running_ub: float) -> list[ChildResult]:
    """Node-granularity expansion: generate this node's children and evaluate
    them (serially within this call). Used when parallelism is over nodes."""
    results = [eval_child(*c) for c in generate_children(fnode_data, running_ub)]
    _profile_tick()
    return results
