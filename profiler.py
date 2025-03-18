from cProfile import Profile
from pstats import SortKey, Stats
from run_experiments import *

with Profile() as profile:
    run_audit()
    (
        Stats(profile)
        .strip_dirs()
        .sort_stats(SortKey.CALLS)
        .print_stats()
    )


def compute_disp_lb_new(candidates, ballots, node_order_c, node_order_a, winner_set, rem, quota, seats, transfer):
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
    new_winner = False
    for i in range(len(node_order_c)):
        if node_order_a[i] == 1:
            w = node_order_c[i]
            if not (w in winner_set):
                new_winner = True
                break

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

    filtered_ballots = []
    for b in ballots:
        prefs, winners = filterballot(b, node_order_c, node_order_a)
        if prefs != []:
            filtered_ballots.append((prefs, b.prefs, b.votes, winners))

    sleft = seats - sum(node_order_a)
    nleft = len(rem)

    if sleft == nleft:
        return 0

    lowerbound = 0
    if og_losers != [] and og_winners != []:
        lprefix = len(node_order_c)
        lowerbound = np.inf

        # calculate how much it costs to seat ogl
        for ogl in og_losers:
            displacement_cost = np.inf
            left_at_end_costs = []

            # calculate how much it costs to displace ogw with ogl
            for r in rem:
                if r == ogl:
                    continue
                max_l = 0
                min_w = 0

                for b in ballots:
                    prefs = []  # ballot preferences after eliminating prefix
                    transfer_path = []
                    transferring = True
                    for p in b.prefs:
                        if p in rem:  # p still in the race, ballot not exhausted
                            prefs.append(p)
                            transferring = False
                        if transferring:
                            if p in winner_set:
                                transfer_path.append(p)
                            else:
                                transfer_path.append(None)

                    if not prefs:  # ballot is exhausted
                        continue
                    elif prefs[0] == r:  # transferred to ogw
                        lb_add1, _, _ = calc_tallies(b, node_order_a, node_order_c, transfer, transfer_path,
                                                         seated=False)
                        lb_add2, _, _ = calc_tallies(b, node_order_a, node_order_c, transfer, transfer_path,
                                                         seated=True)
                        min_w += min(lb_add1, lb_add2)
                    else:
                        posl = prefs.index(ogl) if ogl in prefs else -1
                        posw = prefs.index(r) if r in prefs else -1
                        if posl != -1 and (posw == -1 or posl < posw):  # ogl ranked above ogw
                            _, ub_add1, _ = calc_tallies(b, node_order_a, node_order_c, transfer, transfer_path, seated=False)
                            _, ub_add2, _ = calc_tallies(b, node_order_a, node_order_c, transfer, transfer_path, seated=True)
                            max_l += max(ub_add1, ub_add2)

                dp = max(0.0, 0.5 * (min_w - max_l))
                left_at_end_costs.append(dp)
                if r in og_winners:
                    displacement_cost = min(displacement_cost, dp)

            max_l = 0
            for prefs, _, votes, _ in filtered_ballots:
                if ogl in prefs:
                    max_l += votes

            quota_cost = max(0, max_l - quota)
            left_at_end_costs.sort()

            # ogl needs to outlast nleft - sleft candidates
            # print(f"left_at_end_costs={left_at_end_costs}, nleft={nleft}, sleft={sleft}, rem={rem}, og_losers={og_losers}, og_winner={og_winners}", flush=True)
            left_at_end_cost = max(left_at_end_costs[:nleft - sleft])

            lowerbound = min(lowerbound, max(displacement_cost, min(quota_cost, left_at_end_cost)))

    return math.ceil(lowerbound)