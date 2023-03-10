from pyscipopt import Model, SCIP_PARAMSETTING, SCIP_PARAMEMPHASIS

from utils import gen_equivalence_classes, reduce_ballots

import time

epsilon = 0.0001

def distribute_ballots_t(rstart, R, bw, cp_bw, wi, bvalue, caveats, ys, b, \
    lballot, LAST_ROUND, winners, tvalue, nqcr, qcr, tallies, rem, candpos, \
    order_q):
    """
        This function is used to build up a candidates tally at the start of 
        any given round. The 'tallies' structure maps candidate numbers and 
        rounds to an expression representing their tally at the start of that
        round. If the round is greater than 0, this expression will already
        contain a variable representing their tally at the start of the last
        round. This function is designed to be used recursively. 

        The function is called for a ballot 'b' that, at the start of round 
        'rstart' is sitting with the candidate 'bw'. That candidate is either
        elected or eliminated in round 'cp_bw'. The value of the ballot at 
        this point is expressed by the expression 'bvalue'. That expression may
        contain a transfer value variable multiplied by a number of qcr/nqcr
        variables that ensure that particular candidates did/did not have a 
        quota at the start of certain rounds. These qcr/nqcr variables will be
        contained in the structure 'caveats'. These 'caveats' are things that
        must hold for the ballot to have found its way to 'bw' by the start of
        round 'rstart'.

        For example,

            caveats = [(1, 0, 0), (2, 0, 1)]

        expresses two caveats, the first that candidate 1 must not have a quota
        at the start of round 0, and the second that candidate 2 must have a 
        quota at the start of round 0. These two caveats can be combined in the 
        expression nqcr[1,0] * qcr[2,0].

        A ballot type may arrive in a candidate c's tally in two different 
        rounds depending on who has a quota when. This means that the ys[]
        variable for that ballot will appear in two different expressions in
        tallies[c,].  However, these expressions will have binary variable
        multipliers that ensure that only one of the expressions will have a non
        zero value in any solution of our distance-to model. Similarly, a ballot
        type may arrive in different candidates' tallies in a round depending on
        who had a quota when. In this case, also, binary multipliers are used to
        ensure that it will only contribute to the tally of one candidate in any
        given round.

        This function assumes we have stepped through the ballot preferences and
        are currently at index 'wi', where as mentioned, the ballot is currently
        residing with candidate 'bw'. The function continues to step through
        the ballot preferences, and counting rounds, until it reaches a round
        where it should move to another candidate. The 'tallies' data structure
        will be updated accordingly. If we reach a point where the ballot may
        be transferred to a particular candidate (eg. depending on whether
        certain candidates have/don't have quotas at certain points), we 
        make a recursive call to this function to 'play out' this particular
        reality with the appropriate caveats added to 'caveats'.

        R          : Length of the current outcome prefix.

        LAST_ROUND : Even though the outcome prefix may be R in length, we may
                     only need to create constraints and variable up to an 
                     earlier round. For example, if we have a situation where 
                     all seats have been filled in the first few rounds, and
                     there are candidates left standing. Or, if the outcome
                     eliminates candidates until there are N candidates 
                     left with N seats left to be filled.

        lballot    : Number of preferences on the ballot type 'b'

        ys         : Variables for the number of ballots cast of each ballot 
                     type

        winners    : List of winners in the original outcome

        tvalue     : Variables for transfer values, indexed by round (this 
                     variable map will only contain rounds in which a 
                     candidate was elected).

        nqcr       : Binary variables, created only for candidates who are 
                     seated, such that nqcr[c,r] is 1 only if candidate c does 
                     not have a quota at the start of round r.

        qcr        : Binary variables, created only for candidates who are 
                     seated, such that qcr[c,r] is 1 only if candidate c has a 
                     quota at the start of round r.

        tallies    : tallies[c,r] returns an expression for the tally of 
                     candidate c at the start of round r.

        rem        : Candidates that are not in the order_c/order_a for the 
                     outcome being solved for (ie. they are not in the outcome 
                     prefix).

        candpos    : Map between candidate number and the position in the 
                     outcome prefix in which they are either seated or 
                     eliminated. If the candidate is in 'rem' they will have a 
                     position that is longer than the outcome prefix.

        order_q    : Map between candidates who are seated in the outcome 
                     prefix (in a position that requires them to have a quota 
                     i.e., they are not simply remaining at the end) and the 
                     range of rounds in which they could, based on the outcome 
                     prefix, have received their quota.
    """

    # Ballot is currently sitting with 'ballotwith' at the start of round
    # 'rstart'
    ballotwith = bw

    # To keep track of the last person the ballot was with (used to know
    # when we have changed 'ballotwith' over the course of the following loop)
    last_ballotwith = ballotwith

    # Position of candidate 'ballotwith' in the outcome prefix (note that for
    # candidates in 'rem', the ballots that sit with them will never leave
    # them for the purposes of this distance-to model). 
    cp_ballotwith = cp_bw

    # Value of ballots of this type, at this point.
    ballot_value = bvalue

    # Marker for where we are up to in stepping through the ballot preferences
    withindex = wi

    # Indicate that the ballot is with 'ballotwith' at the start of round
    # 'start' (note: we do not include ballots in tallies[c,r] that reached
    # candidate c in a round before r-1, these are already captured by the
    # presence of variable vcr[c,r-1] in the tallies[c,r] expression).
    tallies[ballotwith,rstart] += ballot_value*ys[b.num]
    
    for r in range(rstart, R):
        if ballotwith != None:
            # The ballot is still with candidate 'ballotwith' at the 
            # start of this round, but we need to decide if it should
            # move to another candidate in this round.
            if last_ballotwith != ballotwith:
                # Ballot moved to 'ballotwith' in round r-1. 
                tallies[ballotwith,r] += ballot_value*ys[b.num]
                last_ballotwith = ballotwith 

            if r == LAST_ROUND:
                break

            if cp_ballotwith == r and ballotwith in winners:
                # ballot will change in value for subsequent recipients
                # (depending on caveats).
                ballot_value = 1
                for cp, rq, val in caveats:
                    if val == 0:
                        ballot_value *= nqcr[cp,rq]
                    else:
                        ballot_value *= qcr[cp,rq]

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

                    if ballotwith in winners:
                        if ballotwith in order_q:
                            # Could the new candidate already have a quota?
                            # If so, they may be skipped.
                            qposses = order_q[ballotwith]

                            # Earliest round in which 'ballotwith' could
                            # have achieved their quota.
                            minqp = min(qposses)

                            # Latest roundin which 'ballotwith' could have
                            # achieved their quota.
                            maxqp = max(qposses)

                            if maxqp < r:
                                # we skip this candidate; they will already
                                # have a quota. 
                                withindex += 1
                                continue

                            if minqp < r:
                                # ballotwith could get it, but might not
                                # imagine it does get it, let's play out
                                # this reality with a recursive call.
                                nbv = ballot_value*nqcr[ballotwith,r]
                                distribute_ballots_t(r+1, R, ballotwith, \
                                    cp_ballotwith, withindex, nbv, \
                                    caveats[:] + [(ballotwith, r, 0)], ys, b, \
                                    lballot, LAST_ROUND, winners, tvalue, \
                                    nqcr, qcr, tallies, rem, candpos, order_q)

                                # Now we are assuming that 'ballotwith' has
                                # a quota at the start of round 'r', and the
                                # ballot type is skipping them. We adjust
                                # the ballot value with this caveat in place.
                                ballot_value *= qcr[ballotwith, r]
                                caveats.append((ballotwith, r, 1))
                                
                                # Move on to next possibility.
                                withindex += 1
                                continue

                        # otherwise, we will move to next break statement

                    # Ballot should sit with 'ballotwith' at the start
                    # of the next round.
                    break

                # We have reached the end of the ballot.
                if withindex == lballot:
                    ballotwith = None  



def stvdistance(candidates, ballots, order_c, order_a, rem, winners, order_q,\
    merge_map, supers, tot_ballots, args, quota, upperbound, LAST_ROUND, \
    log=None):
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

        rem          : List of candidates not present in order_c.

        winners      : Candidates who have been elected to a seat in order_c.

        order_q      : For those candidates who have been elected on a quota,
                       order_q[w] gives a tuple (l,u) where l is the earliest
                       round in which they could have achieved a quota (by
                       vote transfers in that round) and u is the latest.

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

        log          : Will either be None or an output stream to use when
                       printing out diagnostics.
    """

    R = len(order_c)

    cands = order_c + rem

    # Rework order_c/order_a on the basis of LAST_ROUND
    if LAST_ROUND < R-1:
        rem += order_c[LAST_ROUND+1:]
        order_c = order_c[:LAST_ROUND+1]
        order_a = order_a[:LAST_ROUND+1]

        R = LAST_ROUND + 1

    # Form equivalence classes over ballots. 
    classes, _, class_map = gen_equivalence_classes(order_c, rem)

    # Reduce ballots to equivalence classes
    reduce_ballots(len(candidates), order_c, rem, merge_map, ballots, \
        classes, class_map)

    model = Model("STVDISTANCE")
    model.setEmphasis(SCIP_PARAMEMPHASIS.OPTIMALITY)
    #model.hideOutput()
    model.setRealParam("limits/gap", args.gap)
    #model.setRealParam("limits/time", args.time)

    # VARIABLES
    # 'Signature' here refers to equivalence class rankings.
    #
    # ps: Number of ballots that are modified so that their new signature is s
    # ms: Number of ballots whose original signature is s, but are now changed
    #     to a different signature.
    # ys: Number of ballots of signature s in new profile.
    #
    # vcr: Tally of candidate c at the start of round r. 
    # qcr: Binary variable with value 1 if the tally of candidate c at the
    #      the start of round r and 0 otherwise.
    # nqcr: not qcr (useful in model building)

    ps = {}
    ms = {}
    ys = {}

    vcr = {}
    qcr = {}
    nqcr = {}

    # Integer number of ballots sitting in the tally pile of candidate 'c'
    # at the start of round 'r' (ie. number of pieces of paper).
    ncr = {}

    # Transfer value applied to ballots leaving an elected candidates 
    # tally in round 'r' (assuming a candidate was seated in 'r'). Note these 
    # variables will only be defined for rounds where a candidate was seated
    # in a round that is not equal to LAST_ROUND.
    tvalue = {}


    # mapping between candidate and their index in the order_c prefix, equal
    # to R+1 (where R is the length of the prefix) if they are still standing
    # at the end of the prefix.
    candpos = { c : 0 for c in cands }
    nonsupers = {c for c in cands if (not c in supers)}

    tallies = {}
    for c in cands:
        pos = R+1
        if c in order_c:
            pos = order_c.index(c)
        
        candpos[c] = pos

        for r in range(R):
            if pos < r: 
                break

            # Create variables for tallies of candidates at the start of
            # each round, and number of ballots in their tally pile.
            vcr[c,r] = model.addVar(vtype="C", lb=0, ub=tot_ballots, \
                name="vcr(%s,%s)"%(c,r))

            ncr[c,r] = model.addVar(vtype="I", lb=0, ub=tot_ballots, \
                name="ncr(%s,%s)"%(c,r))

            tallies[c,r] = 0

            if r > 0:
                tallies[c,r] += vcr[c,r-1]

            # For the winners that get a quota at some point, create
            # quota/not-quota binaries.
            if c in winners and c in order_c:
                qcr[c,r] = model.addVar(vtype="B", name="qcr(%s,%s)"%(c,r))
                nqcr[c,r] = model.addVar(vtype="B", name="nqcr(%s,%s)"%(c,r))

                model.addCons(nqcr[c,r] == 1 - qcr[c,r])
                model.addCons(vcr[c,r] >= quota*qcr[c,r])
                model.addCons(vcr[c,r] <= nqcr[c,r]*(quota-epsilon) + \
                    qcr[c,r] * tot_ballots)
        

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
            ce = order_c[r]
            if ce in nonsupers:
                for co in nonsupers:
                    if ce != co and candpos[co] > r:
                        model.addCons(vcr[ce,r] <= vcr[co,r])

        else:
            # The candidate that is elected on a quota will have a quota.
            if (ce,r) in qcr:
                model.chgVarLb(qcr[ce,r], 1)

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
            if r == 0 or order_a[r] == 0:
                for co in nonsupers:
                    if ce != co and candpos[co] > r:
                        model.addCons(vcr[ce,r] >= vcr[co,r])
    
            if r != LAST_ROUND:
                # define transfer value variable for candidate who has
                # just been seated.
                tvalue[r] = model.addVar(vtype="C",lb=0,ub=1.0,name="tv(%s)"%r)

                model.chgVarUb(nqcr[ce,r], 0)
                model.addCons((tvalue[r]-epsilon)*ncr[ce,r]<=(vcr[ce,r]-quota))
                model.addCons((tvalue[r]+epsilon)*ncr[ce,r]>=(vcr[ce,r]-quota))

    sum_ps = 0
    sum_ms = 0

    for b in classes:
        ps[b.num] = model.addVar(vtype="I", lb=0, ub=upperbound, \
            name="ps(%s)"%b.num)

        ms[b.num] = model.addVar(vtype="I", lb=0, ub=min(upperbound,b.votes),\
            name="ms(%s)"%b.num)

        ys[b.num] = model.addVar(vtype="C", lb=0, ub=tot_ballots, \
            name="ys(%s)"%b.num)

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

        # Caveats is a list of triples (candidate, round, value of qcr for
        # that candidate and that round). The e_pi_c_r map will define
        # what ballot classes will sit with a candidate, at the start of
        # a round, assuming that a set of qcr variables have certain values.
        # This set may be empty.
        caveats = []

        # Number of rankings on the ballot type.
        lballot = len(b.prefs)

        # Populate tallies[] expressions, defining who has this ballot
        # in different rounds.
        distribute_ballots_t(0, R, ballotwith, cp_ballotwith, withindex, 1, \
            [], ys, b, lballot, LAST_ROUND, winners, tvalue, nqcr, qcr, \
            tallies, rem, candpos, order_q)
    
    # Constraint enforces consistency  
    model.addCons(sum_ps == sum_ms)

    # Connect tally expressions to tally variables.
    for c in cands:
        pos = candpos[c]
        for r in range(min(LAST_ROUND+1, pos+1)):
            model.addCons(vcr[c,r] == tallies[c,r])  

    # Weird thing with quicksum introducing an offset for objective, so
    # am avoiding using it.
    model.setObjective(sum_ps, "minimize")

    #model.writeProblem()

    model.optimize()

    if model.getStatus() == "infeasible":
        return False, None

    else:
        # As we are usually going to stop solving when we get to an 
        # allowed gap, return lower bound on objective.
        return True, model.getDualbound()
