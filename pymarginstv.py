#
#    Copyright (C) 2023  Michelle Blom
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

from utils import read_ballots_stv, read_ballots_txt, read_ballots_json, \
    simulate_stv, compute_weub, compute_simple_ub, merge_outcome

from stvtree import treestv


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    # Input: stv data file
    parser.add_argument('-d', dest='data')

    # Input: number of seats in election
    parser.add_argument('-s', dest='seats', type=int)

    # Input: acceptable gap to which to solve MINLPs
    parser.add_argument('-g', dest='gap', type=float, default=0.01)
    parser.add_argument('-agap', dest='agap', type=int, default=1)
    
    # Input: max solve time (s) for MINLPs 
    parser.add_argument('-t', dest='time', type=int, default=500)


    # Output: Log file 
    parser.add_argument('-log', dest='log', type=str)

    args = parser.parse_args()

    log = open(args.log, "w")

    # Read STV data file
    candidates, ballots, cid2num = None, None, None

    # Check for given input data type
    if args.data.endswith(".stv"):
        candidates, ballots, _, cid2num, _ = read_ballots_stv(args.data)

    elif args.data.endswith(".json"):
        candidates, ballots, _, cid2num, _ = read_ballots_json(args.data)

    else:
        candidates, ballots, _, cid2num, _ = read_ballots_txt(args.data)

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

    # Heuristics for computing initial upper bounds on the margin. 
    # WEUB stands for "winner elimination upper bound".
    weub = compute_weub(candidates, winners, order_c, order_a, tallies)
    simple_ub = compute_simple_ub(candidates, quota, winners)

    upper_bound = min(weub, simple_ub)

    print("WEUB {}, simple UB {}".format(weub, simple_ub), file=log)

    # Start branch and bound.
    lb, ub = treestv(ballots, candidates, winners, order_c, order_a,\
        upper_bound, args.seats, args, quota, totvotes, agap=args.agap,log=log)

    log.close()

# TODO: Debug test3.json with 3 seats, 1886 is definitely a manipulation 
# size that will change the result, see test4.json. BUT, infeasible according
# to stvdistance.
# Actual outcome: 0 1 2 3 4 5 8 7 6
# Actual outcome: 1 1 0 0 0 0 0 0 1
# Prefix 0/1 should give distance of 0.
