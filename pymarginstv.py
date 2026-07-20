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

from __future__ import annotations

import argparse
import math
from time import perf_counter
import time

from utils import read_ballots_txt, read_ballots_json, \
    read_ballots_blt, simulate_stv, compute_weub, compute_simple_ub

from stvtree import treestv


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

    # Input: where to apply parallelism during the search (when -pc > 1).
    # 'nodes': expand up to -pc frontier nodes in parallel, with each
    # worker evaluating all children of its node ('nodes', the default);
    # 'children': expand one frontier node at a time and evaluate its
    # children in parallel across -pc workers.
    parser.add_argument('-para', choices=['nodes', 'children'], \
        default='nodes')

    # Input: max solve time (s) for algorithm 
    parser.add_argument('-limit', type=int, default=10000)

    # Input: whether to compute displacement lower bound 
    parser.add_argument('-dlb', action='store_true', default=False)

    # Input: whether to use enhanced pruning strategy
    parser.add_argument('-lse', action='store_true', default=False)

    # Input: whether to use new eqlb bounding mechanism
    parser.add_argument('-eqlb', action='store_true', default=False)

    # Input: whether to only use lower bounding heuristics during search
    parser.add_argument("-nominlps", action='store_true', default=False)
    
    parser.add_argument("-just_sim", action='store_true', default=False)

    parser.add_argument("-displayname", dest='displayname', default=None)

    parser.add_argument("-ub", type=int, default=None)

    # Input: whether to include quota achievement as part of the order
    # prefixes created and searched through by the margin computation method.
    parser.add_argument("-useqprefix", action='store_true', default=False)

    # Output: Log file 
    parser.add_argument('-log', dest='log', type=str)

    args = parser.parse_args()

    if args.displayname is None:
        args.displayname = args.data

    log = open(args.log, "w")

    # Read STV data file: check for given input data type
    if args.data.endswith(".blt"):
        candidates, ballots = read_ballots_blt(args.data)[:2]

    elif args.data.endswith(".json"):
        candidates, ballots = read_ballots_json(args.data)[:2]

    else:
        candidates, ballots = read_ballots_txt(args.data)[:2]

    # Simulated election outcome: order_c contains candidates in order
    # of when they are elected/eliminated; order_a contains a series of 1s/0s
    # where 1 represents an election/0 an elimination. 
    order_c: list[int] = []
    order_a: list[int] = []

    winners: list[int] = []

    # Simulate election, return quota, candidate tallies per round, and
    # the total valid ballots cast.
    quota, tallies, totvotes = simulate_stv(ballots, candidates, args.seats,\
        order_c, order_a, winners, log=log)

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

    print("WEUB {}, simple UB {}, external UB {}.".format(weub, simple_ub, args.ub if external_upper_bound else "absent"),file=log,flush=True)


    # Start branch and bound.
    tstart = time.time()
    lb, ub, nexps, nsolves, ignores, agg_prunes = treestv(ballots, candidates, \
        winners, order_c, order_a, upper_bound, args, quota, totvotes, log=log)
    tend = time.time()

    print("{}--{}, {}, {}, {}, {}".format(lb, ub, nexps, nsolves, ignores, \
        agg_prunes),file=log)

    t0_end = perf_counter()

    # datafile, candidates, seats, quota, init_ub, found_lb, found_ub, nodes_exp, minlps_solved, time(s)
    print(f"{args.displayname}, {len(candidates)}, {args.seats}, {quota}, {original_upper_bound}, {lb}, {ub}, {nexps}, {nsolves}, "
          f"{tend-tstart}, {t0_end-t0_start}, {args.lse}, {args.dlb}, {args.eqlb}, {external_upper_bound}")

    log.close()


