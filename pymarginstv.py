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
import math

from utils import read_ballots_stv, read_ballots_txt, read_ballots_json, \
    simulate_stv, compute_weub, compute_simple_ub, merge_outcome

from stvtree import treestv, compute_last_round, get_order_q

from stvdistance import stvdistance


if __name__ == "__main__":
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

    upper_bound = math.ceil(min(weub, simple_ub))

    print("WEUB {}, simple UB {}".format(weub, simple_ub),file=log,flush=True)

    # Start branch and bound.
    lb, ub, nexps, nsolves, ignores = treestv(ballots, candidates, winners, \
        order_c, order_a, upper_bound, args.seats, args, quota, totvotes, \
        agap=args.agap, tlimit=args.limit, log=log)

    print("{}--{}, {}, {}, {}".format(lb, ub, nexps, nsolves, ignores),file=log)

    # Baillieston
    #EVALUATED [6, 1, 9, 2, 7, 4, 0, 8, 3, 10, 5]/[1, 1, 0, 0, 0, 0, 0, 0, 1, 0, 1] LB 0 (D 0 EQ 0)
    #DISTANCE 0/0
    # EVALUATED [6, 1, 9, 2, 8, 10, 4]/[1, 1, 0, 0, 0, 0, 0] LB 0 (D 0 EQ 0)
    # DISTANCE 0/0 

    #node_order_c = [6, 1, 9, 2, 8, 10, 4]
    #node_order_a = [1, 1, 0, 0, 0, 0, 0] 
    #node_winners = [6,1]
    #rem = [0,3,5,7]

    #LAST_ROUND = compute_last_round(node_order_c,node_order_a, args.seats, 11)

    #order_q = get_order_q(node_order_c, node_order_a, LAST_ROUND, node_winners)
       
    #m_order_c,m_order_a,m_order_q,merge_map,supers,round_conv = \
    #        merge_outcome(node_order_c, node_order_a, order_q, rem)

    #print(m_order_c)
    #print(m_order_a)

    #LAST_ROUND = compute_last_round(m_order_c, m_order_a, args.seats,\
    #        len(m_order_c) + len(rem))
    
    #print(LAST_ROUND)    
    #_, dist, dist_ub=stvdistance(candidates, ballots, m_order_c, \
    #        m_order_a, rem, node_winners, m_order_q, merge_map, \
    #        supers, totvotes, args, quota, upper_bound, LAST_ROUND, \
    #        0, isleaf=True, log=None)

    #print(dist)
    #print(dist_ub)

    log.close()


