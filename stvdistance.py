from pyscipopt import Model, SCIP_PARAMSETTING, SCIP_PARAMEMPHASIS

from utils import gen_equivalence_classes, reduce_ballots

import time

epsilon = 0.0001

# NOTE: When test3 is merged, problem becomes infeasible. But when 
# unmerged, it is feasible.

def distribute_ballots_t(rstart, R, bw, cp_bw, wi, bvalue, caveats, ys, b, \
    lballot, LAST_ROUND, winners, tvalue, nqcr, qcr, tallies, rem, candpos, \
    order_q):

    ballotwith = bw
    last_ballotwith = ballotwith
    cp_ballotwith = cp_bw
    ballot_value = bvalue
    withindex = wi

    # The ballot is with candidate 'ballotwith' at the 
    # start of round 'rstart', but we need to decide if/when it should
    # move to another candidate. 
    tallies[ballotwith,rstart] += ballot_value*ys[b.num]
    
    for r in range(rstart, R):
        if ballotwith != None:
            # The ballot is still with candidate 'ballotwith' at the 
            # start of this round, but we need to decide if it should
            # move to another candidate in this round.
            if last_ballotwith != ballotwith: 
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
                                # imagine it does
                                nbv = ballot_value*nqcr[ballotwith,r]
                                distribute_ballots_t(r+1, R, ballotwith, \
                                    cp_ballotwith, withindex, nbv, \
                                    caveats[:] + [(ballotwith, r, 0)], ys, b, \
                                    lballot, LAST_ROUND, winners, tvalue, \
                                    nqcr, qcr, tallies, rem, candpos, order_q)

                                ballot_value *= qcr[ballotwith, r]
                                caveats.append((ballotwith, r, 1))
                                

                                withindex += 1
                                continue

                        # otherwise, we will move to next break statement

                    # Ballot should sit with 'ballotwith' at the start
                    # of the next round.
                    break

                if withindex == lballot:
                    ballotwith = None  

def stvdistance(candidates, ballots, order_c, order_a, rem, winners, order_q,\
    merge_map, supers, tot_ballots, args, quota, upperbound, log=None):

    # Assume no merged candidates for now.
    R = len(order_c)

    # Work out when we can stop caring about a candidate having a 
    # quota, and transfer values.
    cands = order_c + rem

    # Do we get to a round where everyone left standing is winning?
    c_cntr = 0
    s_cntr = 0
    num_cands = len(cands)

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

    tstart = time.perf_counter()

    # Form equivalence classes over ballots. 
    classes, _, class_map = gen_equivalence_classes(order_c, rem)

    tnow = time.perf_counter()
    print("Time spent generating equivalence classes: {}".format(tnow-tstart))

    tstart = tnow

    # Reduce ballots to equivalence classes
    reduce_ballots(len(candidates), order_c, rem, merge_map, ballots, \
        classes, class_map)

    tnow = time.perf_counter()
    print("Time spent generating reducing ballots to classes: {}".format(\
        tnow-tstart))

    if log != None:
        print("Number of equivalence classes: {}".format(len(classes)),\
            file=log)

        #for c in classes:
        #    print(c, file=log)

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

    # Transfer value applied to ballots leaving an elected candidates 
    # tally in round 'r' (assuming a candidate was seated in 'r'). Note
    # variables will only be defined for rounds where a candidate was seated.
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

            vcr[c,r] = model.addVar(vtype="C", lb=0, ub=tot_ballots, \
                name="vcr(%s,%s)"%(c,r))

            ncr[c,r] = model.addVar(vtype="I", lb=0, ub=tot_ballots, \
                name="ncr(%s,%s)"%(c,r))

            tallies[c,r] = 0

            if r > 0:
                tallies[c,r] += vcr[c,r-1]

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
        if order_a[r] == 0:
            for c in nonsupers:
                pos = candpos[c]

                if pos >= r: # If 'c' is still standing at the start of 'r'
                    model.addCons(vcr[c,r] <= quota - epsilon)

            ce = order_c[r]
            if ce in nonsupers:
                for co in nonsupers:
                    if ce != co and candpos[co] > r:
                        model.addCons(vcr[ce,r] <= vcr[co,r] - epsilon)

        else:
            cs = order_c[r]
            if (cs,r) in qcr:
                model.chgVarLb(qcr[cs,r], 1)
            
            if r != LAST_ROUND:
                w = order_c[r]
                tvalue[r] = model.addVar(vtype="C",lb=0,ub=1.0,name="tv(%s)"%r)

                model.chgVarUb(nqcr[w,r], 0)
                model.addCons((tvalue[r]-epsilon)*ncr[w,r] <= (vcr[w,r]-quota))
                model.addCons((tvalue[r]+epsilon)*ncr[w,r] >= (vcr[w,r]-quota))

    sum_ps = 0
    sum_ms = 0


    print("Working through classes")
    tstart = time.perf_counter()

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

        distribute_ballots_t(0, R, ballotwith, cp_ballotwith, withindex, 1, \
            [], ys, b, lballot, LAST_ROUND, winners, tvalue, nqcr, qcr, \
            tallies, rem, candpos, order_q)


      
    tnow = time.perf_counter()
    print("Finished working through classes, time {}".format(tnow-tstart))
 
    model.addCons(sum_ps == sum_ms)

    print("Move to defining candidate tallies each round")
    tstart = time.perf_counter()

    for c in cands:
        pos = candpos[c]
        for r in range(min(LAST_ROUND+1, pos+1)):
            model.addCons(vcr[c,r] == tallies[c,r])  

    print("Done {}s".format(time.perf_counter()-tstart))

    # Weird thing with quicksum introducing an offset for objective, so
    # am avoiding using it.
    model.setObjective(sum_ps, "minimize")

    #model.writeProblem()

    print("Optimizing")
    model.optimize()

    print("Done")

    if model.getStatus() == "infeasible":
        print("infeasible")

    else:
        print("Objective: {}".format(model.getObjVal()))
