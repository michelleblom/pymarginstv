from __future__ import annotations

from pyscipopt import Model, Eventhdlr
from pyscipopt.scip import PY_SCIP_PARAMEMPHASIS, PY_SCIP_EVENTTYPE


from utils import Ballot, CandidateLike, gen_equivalence_classes, \
    reduce_ballots

import argparse
import math
import time

from typing import Any, Optional, Sequence

epsilon = 0.0001

#
# On this branch, we implement the US-style STV model.
#

def distribute_ballots_t(R: int, bw: int, cp_bw: int, wi: int, bvalue: Any,
    b: Ballot, lballot: int, LAST_ROUND: int, winners: set[int],
    tvalue: dict[int, Any], tallies: dict[tuple[int, int], Any],
    rem: list[int], candpos: dict[int, int],
    order_q: dict[int, int]) -> None:

    # Ballot is currently sitting with 'ballotwith' at the start of round 0.
    # Becomes None once the ballot is exhausted.
    ballotwith: Optional[int] = bw

    # To keep track of the last person the ballot was with (used to know
    # when we have changed 'ballotwith' over the course of the following loop)
    last_ballotwith = ballotwith

    # Position of candidate 'ballotwith' in the outcome prefix (note that for
    # candidates in 'rem', the ballots that sit with them will never leave
    # them for the purposes of this distance-to model). 
    cp_ballotwith = cp_bw

    # To represent total value of ballots of this type, at this point.
    ballot_value = bvalue

    # Marker for where we are up to in stepping through the ballot preferences
    withindex = wi

    # Indicate that the ballot is with 'ballotwith' at the start of round
    # 0 (note: we do not include ballots in tallies[c,r] that reached
    # candidate c in a round before r-1, these are already captured by the
    # presence of variable vcr[c,r-1] in the tallies[c,r] expression).
    tallies[bw,0] += ballot_value

    for r in range(R):
        if ballotwith is not None:
            # The ballot is still with candidate 'ballotwith' at the
            # start of this round, but we need to decide if it should
            # move to another candidate in this round.
            if last_ballotwith != ballotwith:
                # Ballot moved to 'ballotwith' in round r-1. 
                tallies[ballotwith,r] += ballot_value
                last_ballotwith = ballotwith 

            if r == LAST_ROUND:
                break

            if cp_ballotwith == r and ballotwith in winners:
                # ballot will change in value for subsequent recipients
                ballot_value *= tvalue[r]


            # Does the ballot type move to a new person during this round.
            # If 'ballotwith' is still standing at the end of the prefix,
            # they will have the ballot type in all rounds up to R.
            # Otherwise, if candidate 'ballotwith' has been either 
            # eliminated or elected in round 'r' or before, then the 
            # ballot type may move to a new candidate
            if (ballotwith not in rem) and cp_ballotwith <= r:
                withindex += 1
                while withindex < lballot:
                    # now, 'ballotwith' is a *possible* candidate to give 
                    # the ballot to, not a candidate who necessarily 'has' the
                    # ballot. 
                    ballotwith = b.prefs[withindex]
                    cp_ballotwith = candpos[ballotwith]

                    # If the new possibility for 'ballotwith' will have
                    # been elected/eliminated before the next round,
                    # then they will not have the ballot type at the
                    # start of the next round.
                    if cp_ballotwith <= r:
                        withindex += 1
                        continue

                    if ballotwith in winners and ballotwith in order_q:
                        # Does the new candidate already have a quota?
                        # If so, they are skipped.
                        if order_q[ballotwith] < r:
                            # we skip this candidate; they will already
                            # have a quota. 
                            withindex += 1
                            continue

                        # otherwise, we will move to next break statement

                    # Ballot should sit with 'ballotwith' at the start
                    # of the next round.
                    break

                # We have reached the end of the ballot.
                if withindex == lballot:
                    ballotwith = None  


class TerminateAtIntegerSolution(Eventhdlr):
    def __init__(self, model: Any) -> None:
        Eventhdlr.__init__(model)

    def eventinit(self) -> None:
        self.model.catchEvent(PY_SCIP_EVENTTYPE.BESTSOLFOUND, self)

    def eventexit(self) -> None:
        self.model.dropEvent(PY_SCIP_EVENTTYPE.BESTSOLFOUND, self)

    def eventexec(self, event: Any) -> None:
        primal_bound = self.model.getPrimalbound()
        dual_bound = self.model.getDualbound()
        if math.ceil(primal_bound) == math.ceil(dual_bound):
            # print(f"{primal_bound=}, {dual_bound=}. Optimal integer solution found. Terminating", flush=True)
            self.model.interruptSolve()


class TerminateOnPruningBound(Eventhdlr):
    """
    Interrupt the solve as soon as the dual bound alone decides the tree
    node's fate. The caller prunes an outcome prefix whenever
    ceil(dual bound) reaches the running upper bound, so once the bound gets
    there the (often expensive) remainder of the infeasibility or optimality
    proof adds nothing.
    """
    def __init__(self, model: Any, upperbound: float) -> None:
        Eventhdlr.__init__(model)
        self.upperbound = upperbound
        self.ncalls = 0

    def eventinit(self) -> None:
        self.model.catchEvent(PY_SCIP_EVENTTYPE.NODESOLVED, self)

    def eventexit(self) -> None:
        self.model.dropEvent(PY_SCIP_EVENTTYPE.NODESOLVED, self)

    def eventexec(self, event: Any) -> None:
        # The global bound moves slowly; checking every 64th node keeps the
        # Python callback overhead negligible on large trees.
        self.ncalls += 1
        if self.ncalls & 63:
            return
        if math.ceil(self.model.getDualbound()) >= self.upperbound:
            self.model.interruptSolve()


def stvdistance(candidates: Sequence[CandidateLike], ballots: list[Ballot],
    order_c: list[int], order_a: list[int], rem_cands: list[int],
    winners: set[int], order_q: dict[int, int], merge_map: dict[int, int],
    supers: list[int], tot_ballots: float, args: argparse.Namespace,
    quota: int, upperbound: float, LAST_ROUND: int, lowerbound: float,
    isleaf: bool = False) -> tuple[bool, Optional[int], Optional[int]]:
    """
        Compute the number of ballots we would have to alter in order to 
        achieve the outcome prefix stated in order_c and order_a. 

        order_c   : List of candidate numbers in order of their elimination/
                    election in the outcome prefix. This list may not 
                    include all candidates in the election.

        order_a   : List of 0s/1s representing whether a candidate is 
                    eliminated or elected in that round of the outcome prefix

        For example, order_c = [1,4,2,3] and order_a = [1,0,0,1] indicates
        that candidate 1 is elected in the first round, candidate 4 and 2 are
        eliminated in the next two rounds, and candidate 3 is elected in the
        fourth round.

        Other inputs:

        candidates   : List of Candidate data structures, ordered by 
                       candidate 'number' (note, 'number' is an index, not
                       their numeric id).

        ballots      : List of Ballot data structures representing ballot 
                       types cast in the election and how many instances of
                       that type are present (reported).

        rem_cands    : List of candidates not present in order_c.

        winners      : Candidates who have been elected to a seat in order_c.

        order_q      : For those candidates who have been elected on a quota,
                       order_q[w] returns the first round where they have a 
                       quota at the start of the round. 

        merge_map    : It may be that we have apriori merged some candidates
                       into a super candidate. In this case, merge_map will
                       map original candidate numbers to their new number
                       in the merged outcome. The list order_c will contain
                       the merged candidates, but the provided ballots'
                       preferences will be in terms of the original candidate
                       numbers.

        supers       : List of candidate numbers that represent 'merged'
                       candidates. We need this information as we cannot
                       form certain constraints involving the merged 
                       candidates (eg. that they have less votes than
                       everyone else when they are eliminated).

        tot_ballots  : Total number of ballots cast in the election.

        args         : Command line arguments.

        quota        : Quota of the election.

        upperbound   : Upper bound on the number of vote changes we want to
                       consider when trying to achieve the given outcome
                       prefix.

        LAST_ROUND   : Do not form constraints relating to rounds that
                       occur after LAST_ROUND in order_c.

        lowerbound   : Max of displacement/quota lower bound. This represents 
                       a lower bound on the number of votes we have to change
                       for one of the original losers that is still 
                       standing after the outcome prefix to displace one
                       of the original winners that is still standing. It
                       represents a lower bound on the vote change required
                       for an original loser to, at some point, have the
                       chance of having more votes than an original winner.
                       Quota lower bound represents minimum manipulation
                       required to give a candidate who needs a quota in
                       a certain round, a quota.

        isleaf       : Flag indicating whether the outcome prefix actually
                       represents a complete outcome. 
  
    """

    t_start = time.perf_counter()

    R = len(order_c)

    cands = order_c + rem_cands
    N = len(candidates)

    # Rework order_c/order_a on the basis of LAST_ROUND
    rem = rem_cands
    if LAST_ROUND < R-1:
        rem = rem_cands + order_c[LAST_ROUND+1:]
        order_c = order_c[:LAST_ROUND+1]
        order_a = order_a[:LAST_ROUND+1]

        R = LAST_ROUND + 1

    last_seating_block_start = N
    if order_a[-1] == 1:
        for i in range(len(order_c)-1, -1, -1):
            if order_a[i] == 1:
                last_seating_block_start = i
            else:
                break


    # Form equivalence classes over ballots. 
    classes, _, class_map = gen_equivalence_classes(order_c, rem, N)

    # Reduce ballots to equivalence classes
    reduce_ballots(len(candidates), order_c, rem, merge_map, ballots, \
        classes, class_map)

    #for c in classes:
    #    print(c, file=log)

    model = Model("STVDISTANCE")
    model.setEmphasis(PY_SCIP_PARAMEMPHASIS.OPTIMALITY)
    model.hideOutput()
    model.setParam("separating/closecuts/separelint", False)
    model.setParam("benders/default/cutstrengthenintpoint", 'i')

    # Keep handles: includeEventhdlr sets handler.model, so each handler
    # forms a reference cycle with the model that has to be broken by hand
    # once solving is done (see the finally block).
    hdlrs = [TerminateAtIntegerSolution(model),
             TerminateOnPruningBound(model, upperbound)]

    model.includeEventhdlr(hdlrs[0],
        "terminate_at_integer_solution",
        "Event handler that terminates solving when ceil(primal) == ceil(dual)")

    model.includeEventhdlr(hdlrs[1],
        "terminate_on_pruning_bound",
        "Event handler that terminates solving when ceil(dual) reaches the "
        "caller's pruning threshold")

    if isleaf:
        model.setRealParam("limits/time", args.thard)
        model.setRealParam("limits/gap", 0.0)  # no gap limit for leaf nodes
    else:
        model.setRealParam("limits/time", args.time)
        model.setRealParam("limits/gap", args.gap)

    # if printmore:
    #     print(args.gap)
    #     print(f"PRINTING MORE INFORMATION. {isleaf=}", flush=True)
    #     model.setParam("display/verblevel", 5)
    # else:
    #     model.hideOutput()

    # VARIABLES
    # 'Signature' here refers to equivalence class rankings.
    #
    # ps: Number of ballots that are modified so that their new signature is s
    # ms: Number of ballots whose original signature is s, but are now changed
    #     to a different signature.
    # ys: Number of ballots of signature s in new profile.
    #
    # vcr: Tally of candidate c at the start of round r.

    ps: dict[int, Any] = {}
    ms: dict[int, Any] = {}
    ys: dict[int, Any] = {}

    vcr: dict[tuple[int, int], Any] = {}

    # Transfer value applied to ballots leaving an elected candidates 
    # tally in round 'r' (assuming a candidate was seated in 'r'). Note these 
    # variables will only be defined for rounds where a candidate was seated
    # in a round that is not equal to LAST_ROUND.
    tvalue: dict[int, Any] = {}


    # mapping between candidate and their index in the order_c prefix, equal
    # to R+1 (where R is the length of the prefix) if they are still standing
    # at the end of the prefix.
    candpos: dict[int, int] = {}
    nonsupers = {c for c in cands if (not c in supers)}

    # Valid, order-independent tally bounds to tighten the nonconvex relaxation:
    #  - reachable[c]: a candidate can only ever hold ballots that rank them, so
    #    their tally in any round is <= (reported votes on ballots ranking c) +
    #    the <= upperbound ballots we may add.
    #  - fp_by_num[c]: reported first preferences. Round 0 tallies equal first
    #    preferences in *every* elimination order, so vcr[c,0] is within
    #    +/- upperbound of fp[c] (only round 0 is order-independent this way).
    fp_by_num = {cd.num: cd.fp_votes for cd in candidates}
    reachable = [0.0] * N
    for cl in classes:
        for p in set(cl.prefs):
            if p < N:
                reachable[p] += cl.votes

    tallies: dict[tuple[int, int], Any] = {}
    for c in cands:
        pos = R+1
        if c in order_c:
            pos = order_c.index(c)
        
        candpos[c] = pos

        for r in range(R):
            if pos < r: 
                break

            # Create variables for tallies of candidates at the start of
            # each round, with tightened (but valid) bounds.
            if r == 0 and c in nonsupers:
                vlb = max(0.0, fp_by_num[c] - upperbound)
                vub = min(tot_ballots, fp_by_num[c] + upperbound)
            else:
                vlb = 0.0
                vub = min(tot_ballots, reachable[c] + upperbound)
            vcr[c,r] = model.addVar(vtype="C", lb=vlb, ub=vub, \
                name="vcr(%s,%s)"%(c,r))

            tallies[c,r] = 0

            if r > 0:
                tallies[c,r] += vcr[c,r-1]
        

    for r in range(LAST_ROUND+1):
        # Note: candidates in 'nonsupers' are the ones that have not
        # been marged into a 'super candidate'
        ce = order_c[r]
        if order_a[r] == 0:
            # No non-merged candidate can have a quota when a candidate 
            # is eliminated. 
            for c in nonsupers:
                pos = candpos[c]

                if pos >= r: # If 'c' is still standing at the start of 'r'
                    model.addCons(vcr[c,r] <= quota - epsilon)

            # The eliminated candidate (assuming they are not a merged
            # candidate) must be the one with the smallest tally.
            if ce in nonsupers:
                for co in nonsupers:
                    if ce != co and candpos[co] > r:
                        model.addCons(vcr[ce,r] <= vcr[co,r])

        else:
            # Make sure all candidates who have achieved a quota by the 
            # start of this round do have at least a quota's worth of votes.
            # [Only add constraint for candidates that got their quota as 
            # a result of the last rounds distribution/or the round is 0 and 
            # they have a quota on first preferences. 
            for co in nonsupers:
                if co in order_q:
                    rq = order_q[co]

                    if rq == r:
                        model.addCons(vcr[co,r] >= quota)

                    elif r < last_seating_block_start and rq > r:
                        model.addCons(vcr[co,r] <= quota-epsilon)
                elif r < last_seating_block_start and candpos[co] > r:
                    model.addCons(vcr[co,r] <= quota-epsilon)

                

            # Note that it is not necessarily true that the candidate, of
            # those with a quota, that has the highest tally is the one that
            # is seated first. A candidate that achieved a quota earlier than
            # than another, will be seated first. For candidates that acheived
            # a quota at the same time, they will be seated in order of 
            # their surplus size (largest first). 
            # 
            # I don't think we need to add constraints that ensure that the 
            # order seatings within a block of seatings in general, however
            # we should ensure that the first seated candidate after either
            # an elimination, or at the start of the prefix, is the one with
            # the highest tally at that point. 
            if r == 0 or order_a[r-1] == 0:
                for co in nonsupers:
                    if ce != co and candpos[co] > r:
                        model.addCons(vcr[ce,r] >= vcr[co,r])
    
            if r != LAST_ROUND:
                # define transfer value variable for candidate who has
                # just been seated.
                tvalue[r] = model.addVar(vtype="C",lb=0,ub=1.0,name="tv(%s)"%r)

                model.addCons((tvalue[r]-epsilon)*vcr[ce,r]<=(vcr[ce,r]-quota))
                model.addCons((tvalue[r]+epsilon)*vcr[ce,r]>=(vcr[ce,r]-quota))

    sum_ps: Any = 0
    sum_ms: Any = 0

    for b in classes:
        ps[b.num] = model.addVar(vtype="C", lb=0, ub=upperbound, \
            name="ps(%s)"%b.num)

        ms[b.num] = model.addVar(vtype="C", lb=0, ub=min(upperbound,b.votes),\
            name="ms(%s)"%b.num)

        ys[b.num] = model.addVar(vtype="C", lb=0, \
            ub=min(tot_ballots, b.votes + upperbound), name="ys(%s)"%b.num)

        sum_ps += ps[b.num]
        sum_ms += ms[b.num]

        model.addCons(ys[b.num] == b.votes + ps[b.num] - ms[b.num])

        # Running indicator of who this ballot type is sitting with
        ballotwith = b.prefs[0] 

        # Index of candidate 'ballotwith' in the ballot preference ranking 
        withindex = 0

        # Position of the candidate who currently owns the ballot type in
        # the prefix order (could be R+1 if they are still standing)
        cp_ballotwith = candpos[ballotwith] 

        # Number of rankings on the ballot type.
        lballot = len(b.prefs)

        # Populate tallies[] expressions, defining who has this ballot
        # in different rounds.
        distribute_ballots_t(R, ballotwith, cp_ballotwith, withindex,
            ys[b.num], b, lballot, LAST_ROUND, winners, tvalue,
            tallies, rem, candpos, order_q)
  
    # Constraint enforces consistency  
    model.addCons(sum_ps == sum_ms)

    # Connect tally expressions to tally variables. 
    for c in cands:
        pos = candpos[c]

        for r in range(min(LAST_ROUND+1, pos+1)):
            model.addCons(vcr[c,r] == tallies[c,r])  
               
    # The manipulation budget enters as an objective cutoff rather than a
    # linear constraint: SCIP then terminates as soon as the global dual
    # bound reaches the cutoff (instead of refuting every open node's LP to
    # certify infeasibility), and the cutoff participates in reduced-cost
    # fixing and cutoff propagation at every node. Status is "infeasible"
    # when no manipulation cheaper than the bound exists -- solutions of cost
    # exactly `upperbound` are excluded, which is sound for the search: an
    # equal-cost outcome never improves the running upper bound, and the
    # initial upper bound (WEUB) is attainable by construction.
    model.setObjlimit(float(upperbound))
    model.addCons(sum_ps >= lowerbound)

    #model.includeEventhdlr(TimerHndlr(args.time), "TimelimitReached", \
    #    "Timelimit reached")

    # Weird thing with quicksum introducing an offset for objective, so
    # am avoiding using it.
    model.setObjective(sum_ps, "minimize")
    #model.writeProblem()

    model.optimize()

    try:
        status = model.getStatus()

        dual = max(0, int(math.ceil(model.getDualbound())))

        # With an objective limit, SCIP reports the limit itself as the
        # primal bound (and keeps rejected heuristic solutions in its store),
        # so a genuine solution exists only when the primal bound is strictly
        # below the cutoff.
        primal_raw = model.getPrimalbound()
        if primal_raw < upperbound - 1e-9:
            primal = max(0, int(math.ceil(primal_raw)))
        else:
            primal = int(model.infinity())  # no usable solution found

        # Sidecar per-solve log: one line per MINLP invocation, appended by
        # whichever worker ran it, for profiling where solver time goes.
        # Columns: status, scip_time, wall_time (incl. model build), nnodes,
        # dual, primal, upperbound, lowerbound, isleaf, prefix_len,
        # order_c, order_a.
        #if getattr(args, "log", None):
        #    try:
        #        with open(args.log + ".solves.csv", "a") as sf:
        #            print(f"{status},{model.getSolvingTime():.2f},"
        #                  f"{time.perf_counter() - t_start:.2f},"
        #                  f"{model.getNNodes()},{dual},{primal},"
        #                  f"{upperbound},{lowerbound},{int(isleaf)},"
        #                  f"{len(order_c)},"
        #                   f"{'|'.join(map(str, order_c))},"
        #                  f"{'|'.join(map(str, order_a))}", file=sf)
        #    except OSError:
        #        pass

        if status in ("infeasible", "inforunbd"):
            return False, None, None

        # As we are usually going to stop solving when we get to an
        # allowed gap, return lower bound on objective.
        return True, dual, primal
    finally:
        # Release SCIP's memory for this problem immediately. Each event
        # handler holds a back-reference to the model, so the pair is a
        # reference cycle that plain refcounting cannot reclaim; dropping
        # that edge lets the model (and its SCIP environment) be freed as
        # soon as the last name goes away. This used to be handled with a
        # gc.collect() per solve, which cost roughly as much as building the
        # model because a full collection has to walk every ballot on the
        # heap.
        model.freeProb()
        for h in hdlrs:
            h.model = None
        hdlrs.clear()
        del model
