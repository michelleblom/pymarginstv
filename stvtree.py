from __future__ import annotations

from stvdistance import stvdistance
from utils import Ballot, BallotMetadata, Candidate, CandidateLike, PrefSeq, \
    merge_outcome, get_order_q, pack_prefs

import argparse
import gc
import importlib
import math
import numpy as np
import os
import subprocess
import sys
import time

from array import array
from bisect import bisect_left, bisect_right, insort
from hashlib import blake2b
from multiprocessing import Pool
from struct import pack
# These aliases are evaluated at import time, unlike annotations (which
# 'from __future__ import annotations' defers), so they use the typing
# generics rather than the builtin ones for compatibility with Python
# versions before 3.9.
from typing import Any, Container, Dict, List, NamedTuple, Optional, \
    Sequence, Set, TextIO, Tuple

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
QRange = Tuple[int, int]

# Canonical outcome-prefix signature: a 16 byte digest, see
# outcome_signature().
Signature = bytes

class EqlbCtx(NamedTuple):
    N: int                       # number of candidates
    transfer: dict[int, tuple[float,float]]   # Transfer values of prefix winners
    elim_lb: float               # elim_lb accumulated over prefix rounds
    quota_lb: float              # quota_lb accumulated over prefix rounds
    no_quota_lb: float           # noquota_lb accumulated over prefix rounds
    nq_cons_added: list[int]     # For each prior round, the candidates for
                                 # whom no-quota constraints were added, as a
                                 # bitmask over candidate numbers (bit c set
                                 # means candidate c). One mask per round is a
                                 # few dozen bytes where a set of ~N candidate
                                 # numbers was several kilobytes, and every
                                 # node in the frontier carries one list of
                                 # them; masks are also immutable, so a child
                                 # inherits its parent's without copying.
    winners: set[int]

    # Absent (None) on a context held by a frontier node: all three are
    # functions of the node's outcome prefix, and restore_derived rebuilds
    # them when the node is expanded. Reading one without restoring it first
    # fails loudly rather than quietly behaving like an empty prefix.
    gone: Optional[list[int]]
    gone_set: Optional[set[int]]
    gone_pos: Optional[dict[int, int]]

    round: int                   # last round in which context was updated.

    # Sum of the shortfalls (quota minus upper tally, when positive) of the
    # winners seated by quota so far. Only accumulated under -sumq.
    deficit_sum: float = 0.0

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
    gone_pos: Optional[dict[int,int]]   # see EqlbCtx.gone_pos
    winners: set[int]

    above: Optional[np.ndarray]
    present: Optional[np.ndarray]
    curtally: Optional[np.ndarray]
    reassign: Optional[np.ndarray]

    start: int
    lowerbound: int


def as_disp_array(values: Any) -> np.ndarray:
    """
        Store a displacement summary as a float64 numpy array.

        These are by far the largest thing a TreeNode carries: 'above'
        and 'reassign' are N x N, and as a list of lists of Python floats
        an 82 candidate senate contest pays about 220 KB for each against
        about 54 KB for the array -- with N^2 separate float objects for
        the cyclic collector to walk and for every forked worker to copy.

        The build loops still fill Python lists, because scalar numpy
        item assignment is markedly slower than list indexing and those
        loops run over every ballot; only the finished summary is
        converted. Passing an array through is a no-op.
    """
    return np.asarray(values, dtype=np.float64)



# Result of evaluating a child node in eval_child(): (isleaf, order_c,
# order_a, order_q, lb, dlb, eqlb, dist, dist_ub, rem, winners, solved).
ChildResult = Tuple[bool, EqlbCtx, DispCache, List[int], \
    List[int], Dict[int, QRange], float, float, float, Optional[float], \
    Optional[float], List[int], Set[int], bool]


# Frontier node data shipped to expand_node(): (eqlbctx, order_c, order_a,
# order_q, rem, winners, dist).
FNodeData = Tuple[EqlbCtx, DispCache, List[int], List[int], \
    Dict[int, QRange], List[int], Set[int], float]


# Width of the outcome-prefix digest. Signatures are retained for every
# node the search has ever inserted, so their size, not their speed, is
# what matters. At 16 bytes the chance of any collision over a run of
# 10^8 nodes is around 10^-23; a collision would wrongly subsume one
# node under another.
SIG_DIGEST_SIZE = 16


def _canonical_outcome(order_c: list[int], order_a: list[int], \
    order_q: dict[int, QRange]) -> bytes:
    """
        Byte encoding of an outcome prefix that is equal for exactly the
        structurally equivalent prefixes described by outcome_signature.

        Eliminated blocks and quota rounds are sorted, so that sets
        compare equal regardless of order, and every variable-length run
        is length-prefixed, so that no two distinct prefixes can encode
        to the same bytes. Values are packed as fixed-width signed
        little-endian integers; order_q rounds may be -1.
    """
    out: list[bytes] = []
    block: list[int] = []

    def emit(values: list[int]) -> None:
        out.append(pack('<i', len(values)))
        if values:
            out.append(pack('<%di' % len(values), *values))

    for i in range(len(order_c)):
        if order_a[i] == 1:
            block.sort()
            emit(block)                     # eliminated since last seating
            emit([order_c[i]])              # the candidate seated here
            block = []
        else:
            block.append(order_c[i])

    block.sort()
    emit(block)                             # trailing eliminations

    quotas: list[int] = []
    for c in sorted(order_q):
        lo, hi = order_q[c]
        quotas += [c, lo, hi]
    emit(quotas)

    return b''.join(out)


def outcome_signature(order_c: list[int], order_a: list[int], \
    order_q: dict[int, QRange]) -> Signature:
    """
        Canonical, hashable form of an outcome prefix under the node
        'similarity' relation used for subsumption: two prefixes are
        structurally equivalent iff they have the same order_a, the same
        seated candidate at each seating position, equal *sets* of
        eliminated candidates between consecutive seatings, and the same
        quota-round range for each candidate achieving a quota.

        Returned as a digest rather than as the nested tuple/frozenset
        structure it summarises. Frontier.sig_dists keeps a signature for
        every node ever inserted, including expanded ones, so at senate
        prefix depths the structural form cost several KB per node and
        dominated memory over a long search; the digest is 49 bytes flat.
        blake2b is used rather than hash() because it does not vary with
        PYTHONHASHSEED and so stays stable across worker processes.
    """
    return blake2b(_canonical_outcome(order_c, order_a, order_q), \
        digest_size=SIG_DIGEST_SIZE).digest()


def pack_order_q(order_q: dict[int, QRange]) -> "array[int]":
    """
        Pack a node's quota rounds for storage on a TreeNode. A dict of
        n entries with tuple values costs several hundred bytes; this is
        64 + 6n. Insertion order is preserved so that the dict rebuilt by
        unpack_order_q iterates exactly as the original did, keeping log
        output and MINLP constraint order unchanged. Node equivalence
        does not depend on it either way: outcome_signature sorts
        independently.
    """
    flat: list[int] = []

    for c, (lo, hi) in order_q.items():
        flat += [c, lo, hi]

    return array('h', flat)


def unpack_order_q(packed: "array[int]") -> dict[int, QRange]:
    """
        Rebuild the quota-round dict from its packed form. Done once per
        node expansion, against a node that survived in the frontier.
    """
    return {packed[i]: (packed[i + 1], packed[i + 2]) \
        for i in range(0, len(packed), 3)}


def derive_rem(order_c: Sequence[int], candidates: Sequence[CandidateLike]) \
    -> list[int]:
    """
        Candidates still standing after an outcome prefix: everything not
        already placed in order_c, in candidate-list order.

        Derived rather than stored. It is a list of up to ncands entries
        on every node in a frontier that can reach hundreds of thousands
        of nodes, and it is needed only when a node is expanded.
    """
    placed = set(order_c)

    return [c.num for c in candidates if c.num not in placed]


def padding_start(order_a: Sequence[int], ncands: int) -> int:
    """
        First round of an outcome prefix that is padding. When a child fills
        the last seat, the candidates left are appended as eliminations, but
        the count ends once every seat is filled: those rounds never happen
        and must not add to any bound. Returns len(order_a) when there is no
        padding.
    """
    pxlen = len(order_a)
    if pxlen != ncands:
        return pxlen

    i = pxlen
    while i > 0 and order_a[i - 1] == 0:
        i -= 1
    return i


def derive_winners(order_c: Sequence[int], order_a: Sequence[int]) -> set[int]:
    """
        Candidates seated within an outcome prefix. Derived rather than
        stored, for the same reason as derive_rem.
    """
    return {c for i, c in enumerate(order_c) if order_a[i] == 1}


def restore_derived(eqlbctx: EqlbCtx, disp_cache: DispCache, \
    order_c: Sequence[int]) -> tuple[EqlbCtx, DispCache]:
    """
        Rebuild the context state that a TreeNode does not store, given the
        node's outcome prefix. Called once for a node about to be expanded,
        for all of its children to share.

        Each of the three is a function of the prefix alone. The walk in
        compute_elim_quota_lb_* appends each round's candidate to the incoming
        gone, so a context that has covered rounds 0..round-1 holds exactly
        order_c[:round], with gone_set and gone_pos the set and the
        position map over it. The displacement cache's gone_pos is the same
        map over the rounds its own walk has covered, order_c[:start].

        Storing them cost a list, a set and two dicts of up to ncands entries
        on every node in a frontier that reaches hundreds of thousands of
        nodes -- around 7 KB per node at senate prefix depths, several times
        what the rest of a node's context comes to. Rebuilding is O(depth),
        paid once per expanded node against once per stored node, which is the
        same trade derive_rem and derive_winners already make.
    """
    gone = list(order_c[:eqlbctx.round])

    eqlbctx = eqlbctx._replace(gone=gone, gone_set=set(gone), \
        gone_pos={c: i for i, c in enumerate(gone)})

    disp_cache = disp_cache._replace(gone_pos={c: i for i, c in \
        enumerate(order_c[:disp_cache.start])})

    return eqlbctx, disp_cache


class TreeNode:
    """
        Data structure for a node in our tree of alternate outcomes.

        order_c  : Outcome prefix (candidate seating/election order)

        order_a  : Outcome prefix (whether an elimination or election occurred).

        order_q  : For each candidate who receives a quota throughout the
                   prefix, the range (earliest, latest) of rounds in which
                   they could first achieve a quota (see QRange for the
                   per-mode value convention).

        distance : How many votes have to change (lower bound) to realise the
                   given outcome prefix.

        eqlbctx  : Saved elimination-quota lower bound computations for the parent
                   (or earlier ancestor) of this node.            

    """

    # A node's still-standing candidates and its set of seated candidates
    # are not stored: both are functions of order_c and order_a (see
    # derive_rem/derive_winners) and are needed only when the node is
    # expanded, whereas a frontier can hold hundreds of thousands of nodes
    # at once. For the same reason the three order structures are held
    # packed and rebuilt on access.
    __slots__ = ('id', '_order_c', '_order_a', '_order_q', \
        'dist', 'dist_ub', 'eqlbctx', 'disp_cache', 'sig')

    id: Optional[int]
    _order_c: PrefSeq
    _order_a: PrefSeq
    _order_q: "array[int]"
    dist: Optional[float]
    dist_ub: Optional[float]
    eqlbctx: EqlbCtx
    disp_cache: DispCache
    sig: Signature

    def __init__(self, order_c: list[int], order_a: list[int], \
        order_q: dict[int, QRange], \
        eqlbctx: EqlbCtx, disp_cache: DispCache, \
        distance: Optional[float], dist_ub: Optional[float]) -> None:

        self.id = None

        self.sig = outcome_signature(order_c, order_a, order_q)

        self._order_c = pack_prefs(order_c)
        self._order_a = pack_prefs(order_a)
        self._order_q = pack_order_q(order_q)

        self.dist = distance  # lower bound from MINLP solve
        self.dist_ub = dist_ub  # upper bound from MINLP solve

        # The prefix walks' own record of the prefix is not kept: see
        # restore_derived, which rebuilds it at expansion time.
        self.eqlbctx = eqlbctx._replace(gone=None, gone_set=None, \
            gone_pos=None)
        self.disp_cache = disp_cache._replace(gone_pos=None)

    @property
    def order_c(self) -> list[int]:
        """Outcome prefix, unpacked. Rebuilt on each access."""
        return list(self._order_c)

    @property
    def order_a(self) -> list[int]:
        """Seat/eliminate flags, unpacked. Rebuilt on each access."""
        return list(self._order_a)

    @property
    def order_q(self) -> dict[int, QRange]:
        """Quota rounds, unpacked. Rebuilt on each access."""
        return unpack_order_q(self._order_q)

    def __str__(self) -> str:
        """
            Return string representation of this tree node.
        """

        order_c = self._order_c
        order_a = self._order_a

        quotas: list[list[str]] = [[] for r in order_c]
        for c,(_,hi) in self.order_q.items():
            quotas[max(hi,0)].append(str(c))

        summary = ""

        for r in range(len(order_c)):
            action = "e" if order_a[r] == 0 else "s"
            if len(quotas[r]) > 0:
              qlist = " ( "
              for qc in quotas[r]:
                qlist += qc + " "
              qlist += ")"
              action += qlist
            summary += str(order_c[r]) + action + " "

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
    the round following prefix `gone`. This method only gives the correct tallies
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


def multi_elim_lb(gaps: list[float], deficit_sum: float) -> float:
    """
    Lower bound from eliminating e while it stands above several continuing
    candidates at once (-multielim).

    gaps holds L(e) - U(c) for each continuing candidate c. A changed ballot
    can lower e against every c at once but raise only one c, so it closes
    at most m + 1 units of the m largest positive gaps plus the quota
    shortfall deficit_sum. The bound is the best of (sum of the m largest
    positive gaps + deficit_sum) / (m + 1) over m >= 1.
    """
    best: float = 0
    total: float = 0
    m = 0
    for g in sorted((g for g in gaps if g > 0), reverse=True):
        m += 1
        total += g
        best = max(best, (total + deficit_sum)/(m + 1))
    return best


def compute_elim_quota_lb_STV26_q_prefix(eqlbctx: EqlbCtx, cands: Sequence[CandidateLike], \
    ballots: list[Ballot], order_c: list[int], order_a: list[int], \
    quota: int, order_q: dict[int, QRange], elim_tallies: Optional[list[float]], \
    transfers_only: bool = False, sumq: bool = False, \
    multielim: bool = False) -> EqlbCtx:
    """
    With transfers_only set, walk the prefix purely to maintain transfer values
    (and gone/gone_set/gone_pos/winners), accumulating none of the bounds. The
    displacement bound and prec_et both consume transfer values but neither
    computes them, so they need this when the elimination/quota bound itself is
    switched off and compute_elim_quota_lb_BST19 -- which does not track
    transfers -- supplies the bound instead.

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
    deficit_sum = eqlbctx.deficit_sum
    no_quota_lb = eqlbctx.no_quota_lb
    nq_cons_added = list(eqlbctx.nq_cons_added)
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
    # with an elimination -- a padded complete prefix included, where no one
    # left unseated can hold a quota as there are never more quotas than
    # seats -- the first constraint puts this past every reachable move_r (at
    # most PXLEN - 2), so no ballot is ever treated as uncertain.
    lastelim = PXLEN - 1
    while lastelim >= 0 and order_a[lastelim] == 1:
        lastelim -= 1

    # Note: qearliest is the earliest round in which a continuing candidate
    # (not seated in the prefix) can have a quota.
    qearliest = lastelim + 1
    if order_q:
        qearliest = max(qearliest, max(order_q[c][0] for c in order_q))

    padfrom = padding_start(order_a, eqlbctx.N)

    for i in range(start, PXLEN):
        ce = order_c[i]

        if order_a[i] == 0:  # candidate eliminated
            # An elimination round sets no transfer value, so it has nothing to
            # contribute when only those are wanted. Padded rounds add nothing.
            if transfers_only or i >= padfrom:
                gone.append(ce)
                gone_set.add(ce)
                gone_pos[ce] = i
                continue

            if i == 0:
                tallies = [cand.fp_votes for cand in cands]
            elif i == start and elim_tallies != None:
                tallies = elim_tallies
            else:
                tallies = compute_round_tallies_q_prefix(ballots, gone, gone_set, \
                    transfer, winners, order_q, gone_pos, eqlbctx.N)

            # No one should have a quota. Accumulate, as elim_lb and quota_lb
            # do: each round's no-quota cost is independently a valid lower
            # bound, so the largest across the prefix is the one to keep.
            no_quota_lb = max(no_quota_lb, max(0, tallies[ce] - quota))
            others = [c.num for c in cands if c.num not in gone_set and c.num != ce]
            nqmask = nq_cons_added[i]
            for c in others:
                elim_lb = max(elim_lb, max(0, 0.5 * (tallies[ce] - tallies[c])))
                no_quota_lb = max(no_quota_lb, max(0, tallies[c] - quota))
                nqmask |= 1 << c
            nq_cons_added[i] = nqmask

            if multielim:
                elim_lb = max(elim_lb, multi_elim_lb([tallies[ce] - tallies[c] \
                    for c in others], deficit_sum))


        else:  # candidate seated
            # Note: the only tallies we care about in this else branch are
            # the maximum tally of the candidate seated in this round, and 
            # the maximum tallies of any continuing candidate that is 
            # recorded to have a quota at the start of this round.
             
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

            # Only max_tallies feeds the bounds. min_tallies exists purely to
            # cross-check that ce's two tallies agree, which they must: the
            # ballot walk credits both together for any candidate in order_q,
            # and ce always is. That check has caught a real error before -- it
            # is what flagged the certainty threshold being set below qearliest
            # -- so it is kept, but gated on __debug__ so both it and the work
            # feeding it vanish under python -O.
            if i == 0:
                max_tallies = [cand.fp_votes for cand in cands]
                if __debug__:
                    min_tallies: list[float] = max_tallies
            elif reuse_elim_tallies:
                assert elim_tallies is not None
                max_tallies = elim_tallies
                if __debug__:
                    min_tallies = elim_tallies
            else:
                max_tallies = [0.0] * eqlbctx.N
                if __debug__:
                    min_tallies = [0.0] * eqlbctx.N

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
                        if __debug__:
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

            if not transfers_only:
                rem = [c.num for c in cands if c.num not in gone_set]
                shortfall: float = 0
                for c in rem:
                    if c in order_q and order_q[c][0] <= i:
                        quota_lb = max(quota_lb, quota - max_tallies[c])
                        shortfall += max(0, quota - max_tallies[c])

                # -sumq: votes changed to lift a short candidate to the quota
                # are used up there, so shortfalls of different candidates add.
                if sumq:
                    quota_lb = max(quota_lb, deficit_sum + shortfall)

            if ce in order_q:  # candidate got a quota, else seated by default (last round)
                winners.add(ce)

                # Min/max tally should be the same -- see above.
                if __debug__:
                    assert abs(max_tallies[ce] - min_tallies[ce]) <= epsilon

                cmax = max_tallies[ce]
                value = max(cmax, quota)  # restrict value to be at lest quota
                tv = (value - quota)/value
                transfer[ce] = (tv, tv)

                if sumq and not transfers_only:
                    deficit_sum += max(0, quota - cmax)

                if not transfers_only:
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

    # Did we come out of a seating block into eliminations? If so, work back
    # over the block computing additional no-quota bounds. Two shapes qualify:
    # a run of two or more seatings followed by an elimination (tail [1, 1, 0]
    # -- and equally [1, 1, 0, 0, ...]), and a complete prefix whose tail is
    # padded with eliminations. Both leave the prefix ending in an elimination,
    # so the quota rounds in the block are no longer ambiguous. This is a test
    # on the shape of order_a, not on how many rounds this call covered: start
    # is 0 whenever the context is not cached, which says nothing about the tail.
    #
    # This runs after the round loop, not before it. backcompute_nq_bound reads
    # transfer, winners and gone_pos to value ballots at round j, and only the
    # completed walk has those for every round of the prefix. Run beforehand it
    # was handed the incoming context, which covers rounds below eqlbctx.round
    # only -- empty in the uncached path, and short by the newly seated round
    # for a padded leaf. Seated candidates then looked eliminated and carried no
    # surplus reduction, inflating the round tallies and so the bound, which is
    # the unsound direction for a lower bound.
    lastseat = PXLEN - 1
    while lastseat >= 0 and order_a[lastseat] == 0:
        lastseat -= 1

    if not transfers_only and 0 <= lastseat < PXLEN - 1 and (PXLEN == eqlbctx.N \
        or (lastseat >= 1 and order_a[lastseat - 1] == 1)):
        # Context reflecting the whole prefix this call has now walked.
        walked = eqlbctx._replace(transfer=transfer, winners=winners, \
            gone=gone, gone_set=gone_set, gone_pos=gone_pos, \
            nq_cons_added=nq_cons_added, round=PXLEN)

        j = lastseat
        while j >= 0 and order_a[j] == 1:
            nqlb, nqs = backcompute_nq_bound(j, walked, cands, ballots, order_c, order_q, quota)
            no_quota_lb = max(no_quota_lb, nqlb)
            nq_cons_added[j] |= nqs
            j -= 1

    return EqlbCtx(eqlbctx.N, transfer, elim_lb, quota_lb, no_quota_lb, nq_cons_added, \
                   winners, gone, gone_set, gone_pos, PXLEN, deficit_sum)




def backcompute_nq_bound(i : int, ctx : EqlbCtx, cands: Sequence[CandidateLike], ballots: list[Ballot],\
                         order_c : list[int], order_q: dict[int, QRange], quota : int):

    # The no-quota constraint being checked here is the one that holds *at*
    # round i: a continuing candidate whose quota round is later than i must
    # not already hold a quota when order_c[i] is seated. So the tallies below
    # have to be the round i state, which is the one reached after the rounds
    # before i -- order_c[:i] -- have been processed. Slicing to i+1 instead
    # values the ballots at the start of round i+1, and then a candidate whose
    # quota round is exactly i+1 gets charged for a quota it is entitled to
    # hold, inflating a lower bound (the unsound direction). The i == 0 branch
    # below, which uses first preferences, is the same convention, as is the
    # round loop in compute_elim_quota_lb_STV26_q_prefix.
    #
    # order_c[i] itself never needs excluding by gone_set: a candidate seated
    # at round i has a quota round at or before i, so the filter below drops it.
    gone = order_c[:i]
    gone_set = set(gone)
    already = ctx.nq_cons_added[i]
    rem_qs = [c for c in order_q.keys() if c not in gone_set and order_q[c][0] > i  \
              and not((already >> c) & 1)]

    no_quota_lb: float = 0
    nq_cons_added: int = 0

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
        nq_cons_added |= 1 << c

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


class RoundTallies(NamedTuple):
    """
        Per-candidate summaries of the ballots at the start of one round of an
        outcome prefix, computed once for the node being expanded and read by
        all of its children.

        Without exact quota rounds a ballot does not have a single value but a
        range, and the elimination-quota bound reads three different points of
        that range, so the sums are kept apart:

        ub_first[x]   : upper-bound value of the ballots whose first still
                        standing candidate is x
        ub_present[x] : upper-bound value of every ballot on which x still
                        stands. This is what x's tally could be when the round
                        before was a seating, where it is not settled which
                        pile a ballot sits in
        elb_gain[x]   : elimination-bound value of the ballots that have
                        reached x from an earlier preference -- whose first
                        still standing candidate is x, but whose first
                        preference was not
        slb_first[x]  : seating lower-bound value of the ballots whose first
                        still standing candidate is x
    """
    ub_first: list[float]
    ub_present: list[float]
    elb_gain: list[float]
    slb_first: list[float]


def compute_round_tallies(ballots: list[Ballot], gone: list[int], \
    gone_set: set[int], transfer: dict[int, tuple[float, float]], \
    winners: set[int], N: int) -> RoundTallies:
    """
        One pass over the ballots giving, for every candidate at once,
        everything the elimination-quota bound needs to know about the round
        that follows the prefix `gone`.

        This is the counterpart of compute_round_tallies_q_prefix, and it
        covers more of the work than that one does. calc_tallies never consults
        order_q, so a ballot's value here depends only on gone, transfer and
        winners, all three fixed by the prefix of the node being expanded.
        Every child of that node therefore sees exactly the same ballot values,
        whether the child eliminates a candidate or seats one, and this single
        pass serves all of them. The quota-prefix variant has to work out
        whether a child's quota rounds allow its tallies to be reused
        (reuse_elim_tallies); there is no analogue of that test here.

        final_block, which decides the seating lower bound inside calc_tallies,
        is read off the trailing seatings of `gone`, so it too is the same for
        every child.
    """
    ub_first = [0.0] * N
    ub_present = [0.0] * N
    elb_gain = [0.0] * N
    slb_first = [0.0] * N

    for b in ballots:
        prefs = [p for p in b.prefs if p not in gone_set]

        if not prefs:  # ballot is exhausted
            continue

        slb_add, elb_add, ub_add = calc_tallies(b, gone, transfer, winners)

        first = prefs[0]
        ub_first[first] += ub_add
        slb_first[first] += slb_add

        # The bound credits a candidate being eliminated only with the ballots
        # that reached them from an earlier preference; their first preferences
        # are already counted in fp_votes.
        if b.prefs[0] != first:
            elb_gain[first] += elb_add

        for p in prefs:
            ub_present[p] += ub_add

    return RoundTallies(ub_first, ub_present, elb_gain, slb_first)


def compute_elim_quota_lb_STV26(eqlbctx: EqlbCtx, cands: Sequence[CandidateLike], \
    ballots: list[Ballot], order_c: list[int], order_a: list[int], \
    quota: int, order_q: dict[int, QRange], \
    precomputed: Optional[RoundTallies] = None, \
    transfers_only: bool = False, sumq: bool = False, \
    multielim: bool = False) -> EqlbCtx:
    """
    With transfers_only set, walk the prefix purely to maintain transfer values,
    accumulating none of the bounds. See the quota-prefix variant for why.

    precomputed holds the round tallies that generate_children computed once for
    the node being expanded (-prec_et). They describe the round at the start of
    the walk, so they apply when i == eqlbctx.round, and every child of the node
    can use them: see compute_round_tallies. Round 0 has its own first
    preference shortcut and needs none of this, which is why they are only worth
    computing alongside -eqlbc, the setting under which the walk starts
    somewhere past round 0.

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
    deficit_sum = eqlbctx.deficit_sum
    transfer = {**eqlbctx.transfer}    
    gone = [*eqlbctx.gone]
    gone_set = {*eqlbctx.gone_set}
    winners = {*eqlbctx.winners}
    start = eqlbctx.round

    PXLEN = len(order_c)
    padfrom = padding_start(order_a, eqlbctx.N)
    for i in range(start, PXLEN):
        ce = order_c[i]

        if order_a[i] == 0:  # candidate eliminated
            # An elimination round sets no transfer value. Padded rounds add
            # nothing.
            if transfers_only or i >= padfrom:
                gone.append(ce)
                gone_set.add(ce)
                continue

            # Compute min vote 'ce' could have at this point, needs to be
            # less than max vote of other (non-super) candidates at this point
            # max_ce = cands[ce].fp_votes
            min_ce = cands[ce].fp_votes

            # dict of remaining candidates (eliminated or seated after ce)
            if i == 0:
                max_others : dict[int,float] = {c.num: cands[c.num].fp_votes for c in cands if c.num != ce}
            elif i == start and precomputed is not None:
                # Both quantities the branch below walks the ballots for are
                # per-candidate sums the shared pass has already taken: what
                # each other candidate holds, and what has reached ce from an
                # earlier preference.
                ub_first = precomputed.ub_first
                max_others = {c.num: ub_first[c.num] for c in cands \
                    if c.num not in gone_set and c.num != ce}
                min_ce += precomputed.elb_gain[ce]
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

            if multielim:
                elim_lb = max(elim_lb, multi_elim_lb([min_ce - v \
                    for v in max_others.values()], deficit_sum))

        else:  # candidate seated
            if ce in order_q:  # candidate got a quota, else seated by default (last round)
                if i == 0:
                    lb_value = cands[ce].fp_votes
                    ub_value = lb_value
                elif i == start and precomputed is not None:
                    lb_value = precomputed.slb_first[ce]
                    # Whether the round before this one was a seating is a
                    # property of the prefix the children share, so this picks
                    # the same sum for every one of them. After a seating it is
                    # not settled which pile a ballot sits in, and ce's tally
                    # could be as high as the value on every ballot that still
                    # ranks them; otherwise it is the ballots that sit with ce.
                    if order_a[i-1] == 1:
                        ub_value = precomputed.ub_present[ce]
                    else:
                        ub_value = precomputed.ub_first[ce]
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

                if not transfers_only:
                    # cost to displace the candidate with largest tally that is also above quota 0nly active if
                    # no eliminations/seatings has happened
                    displacement_cost: float = 0
                    if not gone:  # no eliminations yet
                        fp_others_max = max([cands[c.num].fp_votes for c in cands \
                                             if c.num not in gone_set and c.num != ce])
                        # if someone has reached quota, we need to surpass their votes
                        displacement_cost = max(0, 0.5 * (fp_others_max - cmax))  

                    quota_lb = max(quota_lb, quota - cmax, displacement_cost)

                # -sumq: shortfalls of winners seated by quota add up.
                if sumq and not transfers_only:
                    deficit_sum += max(0, quota - cmax)
                    quota_lb = max(quota_lb, deficit_sum)

        gone.append(ce)
        gone_set.add(ce)

    return EqlbCtx(eqlbctx.N, transfer, elim_lb, quota_lb, 0, \
                   [0] * eqlbctx.N, winners, gone, gone_set, \
                   {c: i for i, c in enumerate(gone)}, PXLEN, deficit_sum)


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


def _needs_transfers(args: argparse.Namespace) -> bool:
    """Does anything in this configuration consume transfer values?

    The displacement bound reads them via calc_tallies, and prec_et's round
    tallies do too, in both prefix variants. Neither computes them: they come
    from the elimination/quota bound as a side effect. So when that bound is
    switched off and BST19 stands in for it, the prefix still has to be walked
    for transfers alone.
    """
    return bool(args.dlb or args.dlbc or args.prec_et)


# TODO: Determine if non-q-prefix variant EQLB can made use of any precomputed tallies.
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
    padfrom = padding_start(order_a, eqlbctx.N)
    for i in range(start, PXLEN):
        ce = order_c[i]

        # Padded rounds add nothing.
        if i >= padfrom:
            gone.append(ce)
            gone_set.add(ce)
            continue

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

            for _, v in max_others.items():
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

    # No transfer values: this bound never needs them. Callers that do need them
    # (the displacement bound, prec_et) obtain them from a transfers_only walk.
    # nq_cons_added and gone_pos are still shaped correctly so the context is
    # structurally valid wherever it is passed on.
    return EqlbCtx(eqlbctx.N, {}, elim_lb, quota_lb, 0, \
                   [0] * eqlbctx.N, winners, gone, gone_set, \
                   {c: i for i, c in enumerate(gone)}, PXLEN)




def build_disp_cache_initial_q_prefix(N: int, candidates: Sequence[CandidateLike], \
    ballot_metadata : BallotMetadata) -> DispCache:
    return DispCache(N, False, {}, set(), \
                    as_disp_array(ballot_metadata.above), \
                    as_disp_array(ballot_metadata.mentions), \
                    as_disp_array([c.fp_votes for c in candidates]), \
                    as_disp_array(ballot_metadata.reassign), 0, 0)

def update_disp_cache_q_prefix(disp_cache: DispCache, ballots: list[Ballot], node_order_c: list[int], \
    node_order_q: dict[int, QRange], rem: list[int], transfer: dict[int, tuple[float,float]]) -> DispCache:

    # Once the prefix has changed who won, the displacement argument no longer
    # applies and compute_disp_lb_STV26_q_prefix returns before reading any of
    # these summaries -- for this node and for every node below it, new_winner
    # being monotone down the tree. Rebuilding them here would be a pass over
    # the ballots per expansion whose result no child looks at (and, since this
    # path does not extend gone_pos, would not even describe this prefix).
    if disp_cache.new_winner:
        return disp_cache

    # reassign[g][x] is the transfer table: the total ballot value sitting on ballots whose first 
    # still-standing candidate is g and whose next still-standing candidate is x. In other words, 
    # if g were the next one eliminated, reassign[g][x] is how much of g's pile would land on x.
    # It exists purely to make the displacement bound incremental. 
    if disp_cache.reassign is None:
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
        disp_cache = disp_cache._replace(curtally=as_disp_array(min_r), \
                                        present=as_disp_array(present), \
                                        above=as_disp_array(above), \
                                        reassign=as_disp_array(reassign))

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
    #
    # The four ballot summaries are dropped rather than carried on: neither this
    # node nor any node below it reads them again (new_winner is monotone down
    # the tree), and every node the search has reached this way sits in the
    # frontier holding two N x N arrays -- around 180 KB per node at senate
    # scale, which is what exhausted memory on the larger contests.
    if new_winner:
        return disp_cache._replace(new_winner=True, lowerbound=0, \
            above=None, present=None, curtally=None, reassign=None)

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

    # As on the new_winner exit, the summaries are not carried on. sleft ==
    # nleft makes this node a leaf, which is never expanded; the other two
    # shapes are as monotone as new_winner is (an original loser cannot
    # reappear among the standing candidates, and eliminating or seating an
    # original winner sets new_winner in the child), so no descendant reads
    # them either.
    if sleft == nleft or og_losers == [] or og_winners == []:
        return disp_cache._replace(lowerbound=0, above=None, present=None, \
            curtally=None, reassign=None)

    winners = {c for i, c in enumerate(node_order_c) if node_order_a[i] == 1}

    rem_set = set(rem)
    gone_pos = {**disp_cache.gone_pos}
    for i in range(disp_cache.start, norder):
        gone_pos[node_order_c[i]] = i

    ncand = disp_cache.N
    og_winners_set = set(og_winners)

    ca = node_order_a[-1]
    # 'is not None' rather than a truth test: these are numpy arrays, whose
    # truth value is ambiguous and raises.
    if ca == 0 and disp_cache.curtally is not None \
        and disp_cache.reassign is not None \
        and disp_cache.present is not None and disp_cache.above is not None:
        ce = node_order_c[-1]
        min_r = disp_cache.curtally + disp_cache.reassign[ce]
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

    # A reassign of None says this node took the incremental path, and then the
    # other three summaries are not stored either. update_disp_cache_q_prefix
    # rebuilds all four from the ballots at this prefix before the node is
    # expanded -- that is what a reassign of None asks it to do -- so the copy
    # kept here would only ever be overwritten. And it is a copy, not a shared
    # reference: child results come back from the worker processes pickled, so
    # each child on this path held its own N x N above (about 90 KB per node at
    # senate scale) for as long as it sat in the frontier.
    #
    # A complete set is kept. Those nodes are the ones whose children read the
    # summaries incrementally, and update_disp_cache_q_prefix returns them
    # untouched, so dropping them would buy memory at the price of a ballot
    # pass per expansion. They are also confined to the part of the tree where
    # the prefix still leaves the original outcome intact: past that the bound
    # short circuits and the exit above drops the summaries anyway.
    if reassign is None:
        return DispCache(ncand, new_winner, gone_pos, winners, None, None, \
            None, None, norder, lowerbound)

    return DispCache(ncand, new_winner, gone_pos, winners, \
        as_disp_array(above), as_disp_array(present), as_disp_array(min_r), \
        as_disp_array(reassign), norder, lowerbound)


def build_disp_arrays(ballots: list[Ballot], node_order_c: list[int], \
    rem: list[int], winners: set[int], transfer: dict[int, tuple[float, float]], \
    N: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
        One pass over the ballots giving the four summaries the displacement
        bound works from, evaluated at the outcome prefix node_order_c. This
        is the non-quota-prefix counterpart of the pass inside
        update_disp_cache_q_prefix.

        With val(b) written for the value ballot b carries once the prefix has
        been applied, and "standing" meaning not present in the prefix:

          curtally[x]    = sum of val(b) over ballots whose first standing
                           candidate is x -- a lower bound on x's tally
          present[x]     = sum of val(b) over ballots that rank x
          above[x][y]    = sum of val(b) over ballots ranking both x and y,
                           with x above y
          reassign[x][y] = sum of val(b) over ballots whose first standing
                           candidate is x and whose next standing candidate is
                           y: how much of x's pile would land on y were x the
                           next candidate eliminated

        Without exact quota rounds a ballot does not have a single value but a
        range, and the two ends serve different purposes here. curtally and
        reassign feed a lower bound on a tally and so take the elimination
        bound elb; present and above feed upper bounds and take ub.
    """
    curtally: list[float] = [0.0] * N
    present: list[float] = [0.0] * N
    above: list[list[float]] = [[0.0] * N for _ in range(N)]
    reassign: list[list[float]] = [[0.0] * N for _ in range(N)]

    rem_set = set(rem)
    for b in ballots:
        pres = [p for p in b.prefs if p in rem_set]
        if not pres:
            continue

        _, elb, ub = calc_tallies(b, node_order_c, transfer, winners)

        c = pres[0]
        curtally[c] += elb
        if len(pres) > 1:
            reassign[c][pres[1]] += elb

        for i, x in enumerate(pres):
            present[x] += ub
            row = above[x]
            for y in pres[i + 1:]:
                row[y] += ub

    return as_disp_array(curtally), as_disp_array(present), \
        as_disp_array(above), as_disp_array(reassign)


def update_disp_cache(disp_cache: DispCache, ballots: list[Ballot], \
    node_order_c: list[int], node_order_a: list[int], rem: list[int], \
    transfer: dict[int, tuple[float, float]]) -> DispCache:
    """
        Non-quota-prefix counterpart of update_disp_cache_q_prefix. Rebuild
        the displacement bound's ballot summaries at the prefix held by the
        node about to be expanded, so that all of its children share the one
        pass over the ballots rather than each paying for its own.

        A reassign of None is how compute_disp_lb_STV26 records that it took
        the incremental path: it can carry curtally, present and above forward
        over an elimination but not the transfer table, so that has to be
        rebuilt before the next expansion. When reassign is present the cache
        is already complete and this does nothing.

        A new_winner cache is skipped for the same reason as in the
        quota-prefix variant: the bound short circuits on it, so nothing below
        reads the summaries.
    """
    if disp_cache.new_winner:
        return disp_cache

    if disp_cache.reassign is not None:
        return disp_cache

    # The set of prefix winners is compiled the same way compute_disp_lb_STV26
    # compiles it, so that the ballot values cached here are the ones the bound
    # would have computed for itself.
    winners = {c for i, c in enumerate(node_order_c) if node_order_a[i] == 1}

    curtally, present, above, reassign = build_disp_arrays(ballots, \
        node_order_c, rem, winners, transfer, disp_cache.N)

    # _replace returns a new tuple -- it does not mutate in place.
    return disp_cache._replace(curtally=curtally, present=present, \
        above=above, reassign=reassign)


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
    # in the future (past the current outcome prefix). new_winner is monotone
    # down the tree -- once the prefix has changed who won, every extension of
    # it has too -- so once set it is carried in the cache and the rounds
    # already scanned are not scanned again. Without -dlbc the cache handed in
    # is blank (new_winner False, start 0) and this is the full scan it always
    # was.
    new_winner: bool = disp_cache.new_winner
    norder: int = len(node_order_c)
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
    # here without rescanning. Note we deliberately do not advance start: this
    # path leaves the cached arrays describing an earlier prefix.
    if new_winner:
        return disp_cache._replace(new_winner=True, lowerbound=0, \
            above=None, present=None, curtally=None, reassign=None)

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

    # See the quota-prefix variant: no descendant reads the summaries past
    # any of these exits, so they are dropped rather than carried on.
    if sleft == nleft or og_losers == [] or og_winners == []:
        return disp_cache._replace(lowerbound=0, above=None, present=None, \
            curtally=None, reassign=None)

    winners = {c for i, c in enumerate(node_order_c) if node_order_a[i] == 1}

    ncand = len(candidates)
    og_winners_set = set(og_winners)

    # The bound reads four summaries of the ballots, evaluated at this prefix
    # (see build_disp_arrays for what each holds). Everything it needs about an
    # original loser ogl follows from present and above without touching the
    # ballots again:
    #
    #   max_ogl  = present[ogl]                  (every ballot that could reach ogl)
    #   max_l[r] = present[ogl] - above[r][ogl]  (of those, the ones on which ogl
    #                                             outlasts r: r is either absent
    #                                             or ranked below ogl)
    #
    # When this prefix extends the cached one by a single elimination, all four
    # summaries can be carried forward instead of recomputed. Appending an
    # eliminated candidate ce to the prefix leaves every ballot's value alone:
    # calc_tallies gains one loop iteration that only records ce as eliminated,
    # and the sole quantity that changes is the seating lower bound b_value_slb,
    # via final_block, which this bound never reads. So:
    #
    #   - present and above are unchanged. Their entries are indexed by pairs of
    #     standing candidates, and dropping ce from the standing set does not
    #     alter whether any other pair stands, nor the value on the ballot. The
    #     entries for ce itself are simply never read again.
    #   - the ballots that sat with ce move to their next standing candidate,
    #     which is exactly what reassign[ce] records, so
    #     min_r = curtally + reassign[ce].
    #
    # This holds without knowing the round in which each prefix winner reached
    # a quota, so it carries over from the quota-prefix variant unchanged. What
    # cannot be carried forward is reassign itself: a ballot's *next* standing
    # candidate after ce is gone is not recoverable from the old table. Leaving
    # it as None tells update_disp_cache to rebuild all four, once, before this
    # node's children are evaluated.
    #
    # Reaching here means the prefix is the cached one plus exactly one round.
    # The other shapes -- a leaf padded out with the remaining eliminations, and
    # a node whose remaining seats equal its remaining candidates -- have rem
    # empty or sleft == nleft and returned above, and leaves are never expanded.
    cached_curtally = disp_cache.curtally
    cached_reassign = disp_cache.reassign
    cached_present = disp_cache.present
    cached_above = disp_cache.above

    reassign: Optional[np.ndarray]
    if node_order_a[-1] == 0 and cached_curtally is not None \
        and cached_reassign is not None and cached_present is not None \
        and cached_above is not None:
        ce = node_order_c[-1]
        min_r = cached_curtally + cached_reassign[ce]
        reassign = None
        present = cached_present
        above = cached_above
    else:
        min_r, present, above, reassign = build_disp_arrays(ballots, \
            node_order_c, rem, winners, transfer, ncand)

    # calculate how much it costs to seat ogl
    lowerbound = np.inf
    for ogl in og_losers:
        displacement_cost = np.inf
        left_at_end_costs = []

        max_ogl = present[ogl]

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

    # Snap away floating-point noise before rounding up (see the q-prefix
    # variant): a bound that is mathematically an integer can land just above
    # it and spuriously inflate this lower bound past its true value.
    lowerbound = math.ceil(lowerbound - 1e-4)

    # gone_pos is carried through untouched: the quota-prefix variant needs it
    # to value ballots, this one does not -- calc_tallies takes no such
    # argument. start is therefore paired only with the new_winner scan here,
    # and is advanced to cover the rounds just scanned.
    #
    # See the quota-prefix variant: on the incremental path (reassign None)
    # none of the four summaries are stored, because update_disp_cache rebuilds
    # all four before this node is expanded and each child would otherwise hold
    # its own unpickled copy of an N x N above. A complete set is kept, for the
    # children that read it incrementally.
    if reassign is None:
        return DispCache(ncand, new_winner, disp_cache.gone_pos, winners, \
            None, None, None, None, norder, lowerbound)

    return DispCache(ncand, new_winner, disp_cache.gone_pos, winners, \
        as_disp_array(above), as_disp_array(present), as_disp_array(min_r), \
        as_disp_array(reassign), norder, lowerbound)


# Fraction of currently-available memory the worker pool is allowed to
# commit to. The remainder is headroom for the frontier, which grows for
# as long as the search runs.
WORKER_MEMORY_BUDGET = 0.75


def _available_memory_bytes() -> Optional[int]:
    """
        Memory the OS can still hand out, or None if it cannot be
        determined on this platform.
    """
    try:
        with open('/proc/meminfo') as meminfo:      # Linux
            for line in meminfo:
                if line.startswith('MemAvailable:'):
                    return int(line.split()[1]) * 1024
    except (OSError, IndexError, ValueError):
        pass

    try:
        return os.sysconf('SC_AVPHYS_PAGES') * os.sysconf('SC_PAGE_SIZE')
    except (AttributeError, OSError, ValueError):
        pass

    # macOS has no SC_AVPHYS_PAGES; vm_stat reports the page classes that
    # can be handed out without swapping.
    try:
        out = subprocess.check_output(['vm_stat'], stderr=subprocess.DEVNULL)
        pagesize = os.sysconf('SC_PAGE_SIZE')
        free = 0
        wanted = ('Pages free:', 'Pages inactive:', 'Pages speculative:', \
            'Pages purgeable:')
        for line in out.decode().splitlines():
            if line.startswith(wanted):
                free += int(line.rsplit(':', 1)[1].strip().rstrip('.'))
        if free:
            return free * pagesize
    except (AttributeError, OSError, ValueError, \
        subprocess.SubprocessError):
        pass

    return None


def _process_rss_bytes() -> Optional[int]:
    """
        Resident set size of this process, or None if it cannot be
        determined on this platform.
    """
    try:
        with open('/proc/self/statm') as statm:      # Linux
            return int(statm.read().split()[1]) * os.sysconf('SC_PAGE_SIZE')
    except (OSError, IndexError, ValueError):
        pass

    try:
        out = subprocess.check_output(['ps', '-o', 'rss=', '-p', \
            str(os.getpid())], stderr=subprocess.DEVNULL)
        return int(out.strip()) * 1024
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def cap_worker_count(requested: int, log: Optional[TextIO] = None) -> int:
    """
        Reduce the requested worker count to one this machine can hold.

        Every worker reads every ballot on every task, and CPython writes
        to an object's header when it merely reads it, so a forked worker
        stops sharing the parent's ballot pages almost immediately: each
        one ends up resident for roughly what the parent is holding now.
        Requesting -pc workers therefore asks for about -pc times the
        current footprint, which is how a long run reaches the OOM killer
        on a machine that comfortably fits a single process.

        Returns 'requested' unchanged when the platform will not report
        memory, so this can only ever lower the worker count, never raise
        it. -nopccap skips the check entirely.
    """
    if requested <= 1:
        return requested

    rss = _process_rss_bytes()
    avail = _available_memory_bytes()

    if not rss or not avail:
        return requested

    allowed = max(1, int((WORKER_MEMORY_BUDGET * avail) // rss))

    if allowed >= requested:
        return requested

    msg = ("WARNING: reducing -pc from {} to {}: this process holds "
           "{:.1f} GB and only {:.1f} GB is available, so {} workers "
           "would likely exhaust memory. Pass -nopccap to override.").format(
               requested, allowed, rss / 1e9, avail / 1e9, requested)

    print(msg, file=sys.stderr, flush=True)

    if log is not None:
        print(msg, file=log, flush=True)

    return allowed


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

    # Cap the worker count at what this machine's free memory can hold.
    # Done before initargs is built so that args.pc -- which also decides
    # how many frontier nodes are popped per expansion, and which is
    # shipped to the workers -- stays consistent with the pool size.
    if args.pc > 1 and not getattr(args, 'nopccap', False):
        args.pc = cap_worker_count(args.pc, log)

    # Election invariants used by eval_child/eval_child_initial/expand_node.
    # These are sent to each worker process once (via the pool initializer)
    # rather than being pickled into every task.
    initargs = (ballots, ballot_metadata, lite_cands, winner_set, ncands, args, quota, \
        tot_ballots, list(order_c), list(order_a))

    # Set up the evaluation context in this process too, for args.pc == 1.
    _init_worker(*initargs)

    pool = None
    if args.pc > 1:
        # maxtasksperchild=50 tells each worker process to exit and be replaced by a 
        # fresh one after it has completed 50 tasks.
        # By default a multiprocessing.Pool worker lives for the whole life of the pool, 
        # so anything it accumulates in memory — caches, leaked allocations, memory the 
        # C-level MINLP solver holds onto after a solve — stays there until the pool is 
        # closed. Recycling every 50 tasks bounds that: the child dies, its address space 
        # is released back to the OS, and a new child is forked/spawned and re-run 
        # through _init_worker(*initargs).
        
        # One pool for the whole search (previously a fresh pool was spawned
        # for every expansion). Workers are recycled periodically to bound
        # any memory retained by the MINLP solver across solves.
        pool = Pool(processes=args.pc, initializer=_init_worker, \
            initargs=initargs, maxtasksperchild=50) 

    try:
        # Each element in this list will contain: order_c, order_a, order_q,
        # winners so far, and continuining candidate list for the cihld node, 
        # and current running_ub.
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
                # Rebuilt here rather than carried on the node: see
                # TreeNode. One O(ncands) pass per expanded node, against
                # a per-node cost every frontier node would pay.
                fn_order_c = fn.order_c
                fn_order_a = fn.order_a

                toexpand.append(((fn.eqlbctx, fn.disp_cache, fn_order_c, \
                    fn_order_a, fn.order_q, \
                    derive_rem(fn_order_c, candidates), \
                    derive_winners(fn_order_c, fn_order_a), fn.dist), \
                    running_ub))

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
                # Result format: boolean indicating whether the child is a complete outcome; context cache for 
                # computation of the EQLB; context cache for computation of the DLB; order_c, order_a, and order_q
                # for the node; overall heuristic LB assigned to child along with DLB and EQLB; MINLP distance computed
                # for the node alongside upper bound (they will differ if the MINLP did not get to solve to optimality),
                # note when MINLP not solved, the dist will be the heuristic LB; new set of continuing candidates; winners 
                # so far in the child; a boolean indicating whether the MINLP was solved for the child.  
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
                        # Context caches are stored with each node so they can be used by its children
                        newn = TreeNode(node_order_c, node_order_a, node_order_q, \
                                        eqlbctx, disp_cache, dist, dist_ub)

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
                # return current LB, UB on the LB, number of expansions, number of 
                # MINLP solves, number of nodes we could ignore via subsumption rules,
                # and number of pruned nodes (as their LB was >= running UB on margin LB). 
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
Ctx = Tuple[List[Ballot], BallotMetadata, Sequence[CandLite], Set[int], \
    int, argparse.Namespace, int, float, List[int], List[int]]

_CTX: Optional[Ctx] = None

# This is here to intialise some context that doesn't change over the course
# of the algorithm, but that all workers who are expanding nodes will use.
# This allows the workers to have access to this information without having 
# to repeatedly pass it to them via pickling.
def _init_worker(ballots: list[Ballot], ballot_metadata: BallotMetadata, \
                 candidates: Sequence[CandLite], \
                 winner_set: set[int], ncands: int, \
                 args: argparse.Namespace, quota: int, tot_ballots: float, \
                 full_order_c: list[int], full_order_a: list[int]) -> None:
    global _CTX
    _CTX = (ballots, ballot_metadata, candidates, winner_set, ncands, args, quota, \
        tot_ballots, full_order_c, full_order_a)

    # Everything reachable now -- the ballots above all else -- lives for
    # the whole search and can never become garbage. Move it into the
    # permanent generation so the cyclic collector stops walking it.
    #
    # This matters most in a forked worker, where it runs immediately
    # after the fork. A collection there would write a GC header word to
    # every inherited object, which copy-on-write turns into a private
    # copy of the parent's heap in each of the -pc workers. Freezing
    # keeps the pages the worker does not otherwise write genuinely
    # shared. In the main process it just saves collection time.
    gc.freeze()


# Rather than use two different types for order_q depending on whether we 
# are using the q_prefix variant or not, just use the same type. For the 
# q_prefix variant, the two values in the QRange will be the same.
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


# We have two separate "evaluation" functions for nodes depending on whether they
# are the "initial" nodes we are adding to the frontier at the start of the 
# algorithm or whether they are children that have been generated through expansion.
def eval_child_initial(node_order_c: list[int], node_order_a: list[int], \
                       node_order_q: dict[int, QRange], node_winners: set[int], \
                       rem: list[int], running_ub: float) \
                       -> tuple[float, float, float, TreeNode, bool]:
    # Get the context that was initialised through init_worker. Note that full_order_c
    # and full_order_a represents the reported complete outcome.
    assert _CTX is not None
    ballots, ballot_metadata, candidates, winner_set, ncands, args, quota, tot_ballots, \
        full_order_c, full_order_a = _CTX

    # Is this a prefix of the original outcome?
    l = len(node_order_c)
    orig_prefix = node_order_c[:l] == full_order_c[:l] and node_order_a[:l] == full_order_a[:l]

    transfer = None
    _eqlbctx = EqlbCtx(ncands, {}, 0, 0, 0, [0] * ncands, set(), [], set(), {}, 0)
    if args.eqlb or args.eqlbc:
        if args.useqprefix:
            _eqlbctx = compute_elim_quota_lb_STV26_q_prefix(_eqlbctx, candidates, \
                ballots, node_order_c, node_order_a, quota, node_order_q, None, \
                sumq=args.sumq, multielim=args.multielim)
        else:
            _eqlbctx  = compute_elim_quota_lb_STV26(_eqlbctx, candidates, ballots, \
                node_order_c, node_order_a, quota, node_order_q, sumq=args.sumq, \
                multielim=args.multielim)
    else:
        _base = _eqlbctx
        _eqlbctx = compute_elim_quota_lb_BST19(_base, candidates, ballots, node_order_c, \
                                     node_order_a, quota, node_order_q)

        # This segment of code is here because if we are using only dlb(c) and not eqlb(c),
        # then we can't make use of the transfer value data structure that gets populated 
        # when computing the EQLB. Instead, we have to compute it so that subsequent calls
        # to the DLB computation will have the transfer values of prior seated candidates.
        if _needs_transfers(args):
            if args.useqprefix:
                _tctx = compute_elim_quota_lb_STV26_q_prefix(_base, candidates, ballots, \
                    node_order_c, node_order_a, quota, node_order_q, None, \
                    transfers_only=True)
            else:
                _tctx = compute_elim_quota_lb_STV26(_base, candidates, ballots, \
                    node_order_c, node_order_a, quota, node_order_q, \
                    transfers_only=True)
            _eqlbctx = _eqlbctx._replace(transfer=_tctx.transfer, \
                gone_pos=_tctx.gone_pos)

    eqlb = max(0, math.ceil(max(_eqlbctx.elim_lb, _eqlbctx.quota_lb, _eqlbctx.no_quota_lb)))
    transfer = _eqlbctx.transfer

    if orig_prefix:
        eqlb = 0

    _disp_cache = DispCache(ncands, False, {}, set(), ballot_metadata.above, \
                    ballot_metadata.mentions, [c.fp_votes for c in candidates], \
                    ballot_metadata.reassign, 0, 0)

    # Short circuit if we have already established that the LB for the node is 
    # going to be equal to or greater than our running UB on the margin LB. 
    if eqlb >= running_ub:
        return eqlb, 0, eqlb, TreeNode(node_order_c, node_order_a, node_order_q, \
            _eqlbctx, _disp_cache, eqlb, eqlb), False

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
            _eqlbctx, _disp_cache, lb, lb), False

    # Note: MINLP is only tractable to solve when sequences of eliminated candidates, minus
    # the last eliminated candidate in the sequence, are merged into a "super candidate". 
    merge_map = {c.num: c.num for c in candidates}

    # Evaluate distance for our new tree node.
    _, dist, dist_ub = solve_stvdistance(candidates, ballots, node_order_c, \
                                   node_order_a, rem, node_winners, node_order_q, merge_map, [], \
                                   tot_ballots, args, quota, running_ub, 0, lb)

    return lb, disp_lowerbound, eqlb, TreeNode(node_order_c, \
          node_order_a, node_order_q, _eqlbctx, _disp_cache, dist, dist_ub), True

# Only called to evaluate children that have been generated as a result of an expansion.
def eval_child(parent_dist: float, eqlbctx: EqlbCtx, disp_cache: DispCache, node_order_c: list[int], \
               node_order_a: list[int], node_order_q: dict[int, QRange], \
               node_winners: set[int], rem: list[int], isleaf: bool, \
               running_ub: float, precomputed_elim_tallies: Optional[Any] = None) -> ChildResult:
    # precomputed_elim_tallies is whatever generate_children computed once for
    # this node under -prec_et, and the two prefix variants carry different
    # payloads: a single list of round tallies for the quota-in-prefix bound, a
    # RoundTallies of four sums for the other. Only one variant is ever active,
    # and each narrows the value in its own signature.
    assert _CTX is not None
    ballots, ballot_metadata, candidates, winner_set, ncands, args, quota, tot_ballots, \
        _, _ = _CTX

    transfer  = None
    _eqlbctx  = None
    _disp_cache = None

    # If we are not utilising context caching, pass in "blank" contexts to our LB computation functions.
    if not args.eqlbc:
        eqlbctx = EqlbCtx(ncands, {}, 0, 0, 0, [0] * ncands, set(), [], set(), {}, 0)

    if not args.dlbc:
        disp_cache = DispCache(ncands, False, {}, set(), None, None, None, None, 0, 0)

    if args.eqlb or args.eqlbc:
        if args.useqprefix:
            _eqlbctx = compute_elim_quota_lb_STV26_q_prefix(eqlbctx, candidates, \
                ballots, node_order_c, node_order_a, quota, node_order_q, precomputed_elim_tallies, \
                sumq=args.sumq, multielim=args.multielim)
        else:
            _eqlbctx = compute_elim_quota_lb_STV26(eqlbctx, candidates, ballots, \
                node_order_c, node_order_a, quota, node_order_q, \
                precomputed_elim_tallies, sumq=args.sumq, multielim=args.multielim)
    else:
        _eqlbctx  = compute_elim_quota_lb_BST19(eqlbctx, candidates, ballots, node_order_c, \
                node_order_a, quota, node_order_q)

        # See description for this code segment in eval_child_initial.
        if _needs_transfers(args):
            if args.useqprefix:
                _tctx = compute_elim_quota_lb_STV26_q_prefix(eqlbctx, candidates, \
                    ballots, node_order_c, node_order_a, quota, node_order_q, \
                    precomputed_elim_tallies, transfers_only=True)
            else:
                _tctx = compute_elim_quota_lb_STV26(eqlbctx, candidates, ballots, \
                    node_order_c, node_order_a, quota, node_order_q, \
                    precomputed_elim_tallies, transfers_only=True)
            _eqlbctx = _eqlbctx._replace(transfer=_tctx.transfer, \
                gone_pos=_tctx.gone_pos)

    eqlb = max(0, math.ceil(max(_eqlbctx.elim_lb, _eqlbctx.quota_lb, _eqlbctx.no_quota_lb)))
    transfer = _eqlbctx.transfer

    if eqlb >= running_ub:
        disp_cache = DispCache(ncands, False, {}, set(), None, None, None, None, 0, 0)
        return (isleaf, _eqlbctx, disp_cache, node_order_c, node_order_a, node_order_q, eqlb, \
                0, eqlb, eqlb, eqlb, rem, node_winners, False)
    
    # An empty transfer is legitimate if no prefix winner has a transfer value yet
    if (args.dlb or args.dlbc) and transfer is not None:
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

    # Put back what TreeNode did not store, before anything reads it: the
    # children resume both walks from this context.
    eqlbctx, disp_cache = restore_derived(eqlbctx, disp_cache, forder_c)

    children: list[tuple[float, EqlbCtx, DispCache, list[int], list[int], \
        dict[int, QRange], set[int], list[int], bool, float, Optional[Any]]] = []

    # Work done once here, for all of this node's children to share. The round
    # tallies are only read at round eqlbctx.round, and without -eqlbc
    # eval_child hands the bound a blank context, so its walk starts at round 0
    # -- which has its own first preference shortcut and reads nothing. Pairing
    # the test with args.eqlbc keeps that from being a ballot pass whose result
    # no child looks at.
    elim_tallies = None
    if args.useqprefix:
        if args.dlbc:
            # Recompute reassign, above, present
            disp_cache = update_disp_cache_q_prefix(disp_cache, ballots, forder_c, \
                forder_q, frem, eqlbctx.transfer) 

        if args.prec_et and args.eqlbc:
            elim_tallies = compute_round_tallies_q_prefix(ballots, \
                eqlbctx.gone, eqlbctx.gone_set, eqlbctx.transfer, \
                eqlbctx.winners, forder_q, eqlbctx.gone_pos, ncands)

    else:
        if args.dlbc:
            # Same amortisation for the variant that does not pin quota rounds:
            # rebuild the displacement bound's ballot summaries at this node
            # once, for all of its children to share, rather than once per
            # child.
            disp_cache = update_disp_cache(disp_cache, ballots, forder_c, forder_a, \
                frem, eqlbctx.transfer)

        if args.prec_et and args.eqlbc:
            # One pass covering every child, the ones that seat a candidate
            # included: see compute_round_tallies. The winners set and transfer
            # values are taken from the same context eval_child will resume the
            # walk from, so the ballot values here are the ones the bound would
            # have computed for itself.
            elim_tallies = compute_round_tallies(ballots, eqlbctx.gone, \
                eqlbctx.gone_set, eqlbctx.transfer, eqlbctx.winners, ncands)
   
                
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

                    # Here, we are creating a child for each round in which
                    # r could have first had their quota at the start of the
                    # round.
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
    return [eval_child(*c) for c in generate_children(fnode_data, running_ub)]
