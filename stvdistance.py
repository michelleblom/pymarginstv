from pyscipopt import Model, SCIP_PARAMSETTING, SCIP_PARAMEMPHASIS

from utils import gen_equivalence_classes, reduce_ballots

epsilon = 0.0001


# order_q[w] returns a list of rounds in which it is possible that candidate
# w achieved a quota.
def stvdistance(candidates, ballots, order_c, order_a, rem, winners, order_q,\
    merge_map, tot_ballots, args, quota, upperbound, log=None):

    # Assume no merged candidates for now.
    R = len(order_c)

    # Work out when we can stop caring about a candidate having a 
    # quota, and transfer values.

    # Do we get to a round where everyone left standing is winning?
    c_cntr = 0
    s_cntr = 0
    num_cands = len(candidates)

    LAST_ROUND = 0
    for r in range(R):
        c_cntr += 1
        
        if order_a[r] == 1:
            s_cntr += 1 

        if s_cntr == args.seats:
            break

        if num_cands - c_cntr == args.seats - s_cntr:
            break 

        LAST_ROUND += 1  

    # Rework order_c/order_a
    if LAST_ROUND < R-1:
        rem += order_c[LAST_ROUND+1:]
        order_c = order_c[:LAST_ROUND+1]
        order_a = order_a[:LAST_ROUND+1]

        R = LAST_ROUND + 1

    if log != None:
        print("Last round for model: {}".format(LAST_ROUND), file=log)

    # Form equivalence classes over ballots. 
    classes, _, class_map = gen_equivalence_classes(order_c, rem)

    # Reduce ballots to equivalence classes
    reduce_ballots(len(candidates), order_c, rem, merge_map, ballots, \
        classes, class_map)

    if log != None:
        print("Number of equivalence classes: {}".format(len(classes)),\
            file=log)

        for c in classes:
            print(c, file=log)

    model = Model("STVDISTANCE")
    #model.setRealParam("limits/gap", args.g)
    #model.setRealParam("limits/time", args.time)

    cands = order_c + rem

    # VARIABLES
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
    # at the start of round 'r'.
    ncr = {}

    # Need to pre-compute a structure indicating what ballot classes sit
    # with specific candidates at the start of each round of activity.
    # Indexed by candidate number and then round. As some ballots classes
    # could sit with different candidates in a particular round (due to the
    # fact that we don't know apriori the round in which a winner will have
    # achieved their quota--and ballots skip over candidates who already
    # have a quota). Mostly we will know when a winner got a quota, it's
    # only when there is an order with a sequence of seatings in a row
    # that there can be some uncertainty. For a candidate 'c' and round 'r',
    # this map will give a list of (ballot class, caveats) where caveats
    # is a list of triples (candidate, round, value of qcr for
    # that candidate and that round). The e_pi_c_r map will define
    # what ballot classes will sit with a candidate, at the start of
    # a round, assuming that a set of qcr variables have certain values.
    # This set may be empty.
    e_pi_c_r = {}

    # Data structure identifying the rounds in which each ballot class is
    # involved in a surplus transfer. Key: ballot class id, Value is a list
    # of rounds.
    e_pi_st = {}

    # Transfer value applied to ballots leaving an elected candidates 
    # tally in round 'r' (assuming a candidate was seated in 'r'). Note
    # variables will only be defined for rounds where a candidate was seated.
    tvalue = {}


    # mapping between candidate and their index in the order_c prefix, equal
    # to R+1 (where R is the length of the prefix) if they are still standing
    # at the end of the prefix.
    candpos = { c : 0 for c in cands }

    for c in cands:
        pos = R+1
        if c in order_c:
            pos = order_c.index(c)
        
        candpos[c] = pos

        for r in range(R):
            if pos < r: 
                break

            vcr[c,r] = model.addVar(vtype="C", lb=0, ub=tot_ballots, \
                name="vcr(%s,%s)"%(c,r))

            ncr[c,r] = model.addVar(vtype="I", lb=0, ub=tot_ballots, \
                name="ncr(%s,%s)"%(c,r))

            qcr[c,r] = model.addVar(vtype="B", name="qcr(%s,%s)"%(c,r))
            nqcr[c,r] = model.addVar(vtype="B", name="nqcr(%s,%s)"%(c,r))

            model.addCons(nqcr[c,r] == 1 - qcr[c,r])

            # Constraints relating to binary quota indicator qcr, which
            # is set to 1 if the candidate c has a quota by the start of 
            # round r. 
            if r > 0:
                model.addCons(qcr[c,r-1] <= qcr[c,r])
            
            model.addCons(vcr[c,r] >= quota*qcr[c,r])

            model.addCons(vcr[c,r] <= nqcr[c,r]*(quota-epsilon) + \
                qcr[c,r] * tot_ballots)

            # Initialise map indicating what ballot class types may
            # sit with this candidate at the start of this round.
            e_pi_c_r[c,r] = []
        
      
    sum_ps = 0
    sum_ms = 0

    print("Working through classes")

    for b in classes:
        ps[b.num] = model.addVar(vtype="I", lb=0, ub=upperbound, \
            name="ps(%s)"%b.num)

        ms[b.num] = model.addVar(vtype="I", lb=0, ub=min(upperbound,b.votes),\
            name="ms(%s)"%b.num)

        ys[b.num] = model.addVar(vtype="C", lb=b.votes, ub=tot_ballots, \
            name="ys(%s)"%b.num)

        sum_ps += ps[b.num]
        sum_ms += ms[b.num]

        model.addCons(ys[b.num] == b.votes + ps[b.num] - ms[b.num])

        # Initialise entry for ballot class in the map to store rounds in
        # which the ballot type is involved in a surplus transfer.
        e_pi_st[b.num] = []

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

        for r in range(R):
            if ballotwith != None:
                # The ballot is still with candidate 'ballotwith' at the 
                # start of this round, but we need to decide if it should
                # move to another candidate in this round.
                e_pi_c_r[ballotwith,r].append((b.num, caveats[:]))

                if r == LAST_ROUND:
                    break

                # Does the ballot type move to a new person during this round.
                # If 'ballotwith' is still standing at the end of the prefix,
                # they will have the ballot type in all rounds up to R.
                # Otherwise, if candidate 'ballotwith' has been either 
                # eliminated or elected in round 'r' or before, then the 
                # ballot type may move to a new candidate
                if (ballotwith not in rem) and cp_ballotwith <= r:
                    withindex += 1
                    while withindex < lballot:
                        ballotwith = b.prefs[withindex]
                        cp_ballotwith = candpos[ballotwith]

                        # If the new candidate for 'ballotwith' will have
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
                                minqp = min(qposses)
                                maxqp = max(qposses)

                                if maxqp < r:
                                    # we skip this candidate
                                    withindex += 1
                                    continue

                                if minqp < r:
                                    # ballotwith could get it, but might not
                                    e_pi_c_r[ballotwith,r+1].append((b.num, \
                                        caveats[:] + [(ballotwith,r,0)]))

                                    caveats.append((ballotwith, r, 1))

                                    withindex += 1
                                    continue

                            # otherwise, we will move to next break statement

                        # Ballot should sit with 'ballotwith' at the start
                        # of the next round.
                        break

                    if withindex == lballot:
                        ballotwith = None   
       
    print(e_pi_c_r, file=log)
    print("Finished working through classes")
 
    model.addCons(sum_ps == sum_ms)

    for r in range(LAST_ROUND+1):
        if order_a[r] == 0:
            for c in cands:
                pos = candpos[c]

                if pos >= r: # If 'c' is still standing at the start of 'r'
                    model.addCons(vcr[c,r] <= quota - epsilon)
                    model.chgVarUb(qcr[c,r], 0)
                    model.chgVarUb(nqcr[c,r], 1)

            # Assume no "merged" candidates for now.
            ce = order_c[r]
            for co in cands:
                if ce != co and candpos[co] > r:
                    model.addCons(vcr[ce,r] <= vcr[co,r] - epsilon)
        else:
            model.chgVarLb(qcr[order_c[r],r], 1)
            
            if r != LAST_ROUND:
                tvalue[r] = model.addVar(vtype="C",lb=0,ub=1.0,name="tv(%s)"%r)

    print("Transfer value constraints; working out what ballots involved in tf")

    # Add constraints on the tallies of candidate that are elected during
    # the prefix, ensuring that they have a quota's worth of votes at the
    # right times.
    for w in winners:
        # In what round where they seated?
        pos = candpos[w]

        if pos >= LAST_ROUND:
            continue

        # All ballot types that sit with 'w' at the start of round 'pos'
        # will be involved in a surplus transfer. Technically, some ballots
        # will exhaust, we will deal with that later.
        for b,caveats in e_pi_c_r[w,pos]:
            e_pi_st[b].insert(0,(pos,caveats))

        # Constrain transfer value 
        model.addCons((tvalue[pos]-epsilon)*ncr[w,pos] <= (vcr[w,pos]-quota))
        model.addCons((tvalue[pos]+epsilon)*ncr[w,pos] >= (vcr[w,pos]-quota))

    print("Move to defining candidate tallies each round")

    for c in cands:
        pos = candpos[c]
        for r in range(min(LAST_ROUND+1, pos+1)):
            # what ballots could be in c's tally at the start of r?
            possballots = e_pi_c_r[c,r]

            tally = 0

            for bnum, caveats in possballots:
                # Has this ballot gone through a surplus transfer: there is 
                # a possibility that the last transfer is one of a number of
                # options.
                contrib = 0
                contrib_set = False

                transfers = e_pi_st[bnum]
                for tround, tcaveats in transfers:
                    if tround >= r:
                        continue

                    if tcaveats == []:
                        if not contrib_set:
                            contrib = tvalue[tround]*ys[bnum]
                            contrib_set = True
                        break

                    multiplier = 1
                    for cp, rq, val in tcaveats:
                        if val == 0:
                            multiplier *= nqcr[cp,rq]
                        else:
                            multiplier *= qcr[cp,rq]

                    contrib += ys[bnum]*multiplier*tvalue[tround]
                    contrib_set = True

                if not contrib_set:
                    contrib = ys[bnum]
                

                multiplier = 1                    
                for cc, cr, qv in caveats:
                    if qv == 1:
                        multiplier *= qcr[cc,cr]
                    else:
                        multiplier *= nqcr[cc,cr]
                        
                tally += contrib * multiplier

            model.addCons(vcr[c,r] == tally)            

    print("done")

    # Weird thing with quicksum introducing an offset for objective, so
    # am avoiding using it.
    model.setObjective(sum_ps, "minimize")

    model.writeProblem()

    print("Optimizing")
    model.optimize()

    print("Done")

    if model.getStatus() == "infeasible":
        print("infeasible")

    else:
        print("Objective: {}".format(model.getObjVal()))
