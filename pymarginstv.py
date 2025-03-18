#
#    Copyright (C) 2025  Michelle Blom, Alexander Ek
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

import os
import sys
import argparse
import math
from time import perf_counter
import time

from utils import read_ballots_stv, read_ballots_txt, read_ballots_json, \
    read_ballots_blt, simulate_stv, compute_weub, compute_simple_ub, \
    merge_outcome

from stvtree import treestv, compute_last_round, get_order_q, eval_child

from stvdistance import stvdistance


if __name__ == "__main__":
    t0_start = perf_counter()
    parser = argparse.ArgumentParser()

    # Input: stv data file
    parser.add_argument('-d', dest='data')

    # Input: number of seats in election
    parser.add_argument('-s', dest='seats', type=int)

    # Input: acceptable gap to which to solve MINLPs
    parser.add_argument('-g', dest='gap', type=float, default=0.01)

    # Input: acceptable difference between running lower and upper bounds
    # on "margin lower bound", will trigger termination of algorithm.
    parser.add_argument('-agap', dest='agap', type=int, default=1)
   
    # Input: whether to merge eliminated candidates or not
    parser.add_argument('-m', action='store_true', default=False)
 
    # Input: max solve time (s) for MINLPs for non-leaf nodes
    parser.add_argument('-t', dest='time', type=int, default=100)
    
    # Input: max solve time (s) for MINLPs for leaf nodes
    parser.add_argument('-thard', dest='thard', type=int, default=150)
    
    # Input: Number of children to evaluate in parallel, default 1
    parser.add_argument('-pc', type=int, default=1)

    # Input: max solve time (s) for algorithm 
    parser.add_argument('-limit', type=int, default=10000)

    # Input: whether to compute displacement lower bound 
    parser.add_argument('-dlb', action='store_true', default=False)

    # Input: whether to use enhanced pruning strategy
    parser.add_argument('-lse', action='store_true', default=False)

    # Input: whether to use initial candidate manipulations 
    parser.add_argument('-icm', action='store_true', default=False)

    # Input: whether to use new eqlb bounding mechanism
    parser.add_argument('-eqlb', action='store_true', default=False)

    # Input: whether to only use lower bounding heuristics during search
    parser.add_argument("-nominlps", action='store_true', default=False)
    
    parser.add_argument("-just_sim", action='store_true', default=False)

    parser.add_argument("-displayname", dest='displayname', default=None)

    parser.add_argument("-ub", type=int, default=None)

    # Output: Log file 
    parser.add_argument('-log', dest='log', type=str)

    args = parser.parse_args()

    if args.displayname is None:
        args.displayname = args.data

    log = open(args.log, "w")

    # Read STV data file
    candidates, ballots, cid2num = None, None, None

    # Check for given input data type
    if args.data.endswith(".stv"):
        candidates, ballots, _, cid2num, nballots = read_ballots_stv(args.data)

    elif args.data.endswith(".blt"):
        candidates, ballots, _, cid2num, nballots, _ = read_ballots_blt(args.data)

    elif args.data.endswith(".json"):
        candidates, ballots, _, cid2num, nballots = read_ballots_json(args.data)

    else:
        candidates, ballots, _, cid2num, nballots = read_ballots_txt(args.data)

    # Simulated election outcome: order_c contains candidates in order
    # of when they are elected/eliminated; order_a contains a series of 1s/0s
    # where 1 represents an election/0 an elimination. 
    order_c = [] 
    order_a = []

    # Map between candidates who win on a quota, and the range of rounds
    # in which they could have achieved their quota (with a -1 representing
    # a candidate who may have had a quota on first preferences. For example,
    # order_q[w] = (-1,0) says that w could have had their quota on first
    # preferences or they could have achieved it through the vote transfers
    # in round 0.
    order_q = {}
    winners = []

    # Simulate election, return quota, candidate tallies per round, and
    # the total valid ballots cast.
    quota, tallies, totvotes = simulate_stv(ballots, candidates, args.seats,\
        order_c, order_a, order_q, winners, log=log)

    if args.just_sim:
        if log != None:
            print("{}".format(candidates[order_c[0]].id), end='', file=log)

            for i in range(1, len(candidates)):
                print(",{}".format(candidates[order_c[i]].id), end='',file=log)

            print("", file=log)

            print("{}".format(order_a[0]), end='', file=log)
            for i in range(1, len(candidates)):
                print(",{}".format(order_a[i]), end='', file=log)

        exit(0)

    # Heuristics for computing initial upper bounds on the margin.
    # WEUB stands for "winner elimination upper bound".
    weub = compute_weub(candidates, winners, order_c, order_a, tallies)
    simple_ub = compute_simple_ub(candidates, quota, winners)

    upper_bound = math.ceil(min(weub, simple_ub))
    external_upper_bound = False
    if args.ub is not None:
        external_upper_bound = True
        upper_bound = math.ceil(min(upper_bound, args.ub))
    original_upper_bound = upper_bound

    print("WEUB {}, simple UB {}".format(weub, simple_ub),file=log,flush=True)

    if args.icm:
        # THIS PART IS A BIT BUGGY

        #  Try to reduce upper bound on lower bound by evaluating some
        # complete alternate outcomes that we think will require the least
        # amount of manipulation.
        ncand = len(candidates)

        # Who is the last winner? Last eliminated
        le = None
        le_idx = None
        lw = None
        lw_idx = None

        filled = 0
        for r in range(len(order_a)):
            if filled == args.seats:
                break
            if order_a[r] == 1:
                lw = order_c[r]
                lw_idx = r
                filled += 1
            else:
                le = order_c[r]
                le_idx = r

        # Swap position of last winner and last eliminated candidate before
        # them
        cand_manip_c = order_c[:]
        cand_manip_c[le_idx] = lw
        cand_manip_c[lw_idx] = le

        new_winners = set(winners)
        new_winners.remove(lw)
        new_winners.add(le)
        rem = []

        if log:
            print("Testing candidate {}/{}".format(cand_manip_c,order_a),\
                file=log)

        _, _, _, _, _, _, dist, dist_ub, _, _, _ = eval_child(0, cand_manip_c,\
            order_a, args, ncand, new_winners, winners, candidates, ballots, \
            totvotes, rem, quota, upper_bound, order_c, order_a, True)

        if log:
            print("Candidate upper bound {}".format(dist_ub), file=log)

        if dist_ub != None and dist_ub < upper_bound:
            upper_bound = dist_ub
            print("Reducing upper bound to {}".format(dist_ub), file=log)

        if lw_idx < ncand-1:
            # There are candidates still standing after last winner is
            # seated.
            for i in range(lw_idx+1, ncand):
                # Swap position of lw and candidate at pos 'i'

                cand_manip_c = order_c[:]
                cand_manip_c[lw_idx] = order_c[i]
                cand_manip_c[i] = lw

                new_winners = set(winners)
                new_winners.remove(lw)
                new_winners.add(order_c[i])
                rem = []
                if log:
                    print("Testing candidate {}/{}".format(cand_manip_c, \
                        order_a), file=log)

                _, _, _, _, _, _, dist, dist_ub, _, _, _ = eval_child(0, \
                    cand_manip_c, order_a, args, ncand, new_winners, winners, \
                    candidates, ballots, totvotes, rem, quota, upper_bound, \
                    order_c, order_a, True)

                if log:
                    print("Candidate upper bound {}".format(dist_ub), file=log)

                if dist_ub != None and dist_ub < upper_bound:
                    upper_bound = dist_ub
                    print("Reducing upper bound to {}".format(dist_ub),file=log)

    # Start branch and bound.
    tstart = time.time()
    lb, ub, nexps, nsolves, ignores = treestv(ballots, candidates, winners, \
        order_c, order_a, upper_bound, args.seats, args, quota, totvotes, \
        agap=args.agap, tlimit=args.limit, log=log)
    tend = time.time()

    print("{}--{}, {}, {}, {}".format(lb, ub, nexps, nsolves, ignores),file=log)
    # print("{},{}--{}, {}, {}, {}, MARGIN LB, {}, ORIGINAL UB, {}".format(args.data, lb, ub, \
    #     nexps, nsolves, ignores, lb, original_upper_bound))

    t0_end = perf_counter()

    # datafile, candidates, seats, quota, init_ub, found_lb, found_ub, nodes_exp, minlps_solved, time(s)
    print(f"{args.displayname}, {len(candidates)}, {args.seats}, {quota}, {original_upper_bound}, {lb}, {ub}, {nexps}, {nsolves}, "
          f"{tend-tstart}, {t0_end-t0_start}, {args.lse}, {args.dlb}, {args.eqlb}, {external_upper_bound}")

    #winner_set = {0, 1, 5, 4}
    #node_winners = [0, 1, 3, 5]
    #node_order_c = [0, 1, 2, 3, 4, 5]
    #node_order_a = [1, 1, 0, 1, 0, 1]

    #_, _, _, _, _, _, dist, dist_ub, _, _, _ = eval_child(0, node_order_c, \
    #    node_order_a, args, len(candidates), node_winners, winner_set, \
    #    candidates, ballots, totvotes, [], quota, 100000000, [0, 1, 5, 2, 3, 4],\
    #    [1, 1, 1, 0, 0, 1], True)

    log.close()


