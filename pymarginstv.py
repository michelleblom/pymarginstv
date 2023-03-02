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
    simulate_stv, compute_weub, compute_simple_ub

#from stvtree import treestv

from stvdistance import stvdistance

if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    # Input: stv data file
    parser.add_argument('-d', dest='data')
    parser.add_argument('-s', dest='seats', type=int)

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

    order_c = []
    order_a = []
    order_q = {}
    winners = []

    quota, tallies = simulate_stv(ballots, candidates, args.seats, \
        order_c, order_a, order_q, winners, log=log)



    weub = compute_weub(candidates, winners, order_c, order_a, tallies)
    simple_ub = compute_simple_ub(candidates, quota, winners)

    upper_bound = min(weub, simple_ub)

    #lb, ub = treestv(ballots, candidates, winners, order_c, order_a,\
    #    upper_bound, args.seats, log=log

    print("WEUB {}, simple UB {}".format(weub, simple_ub), file=log)

    # Testing stvdistance
    tot_ballots = sum([b.votes for b in ballots])

    # Assuming no merging
    merge_map = { c.num : c.num for c in candidates } 

    # Reframe order_q so we have a range of rounds in which winners
    # could have achieved their quota
    R = len(order_c)

    r_order_q = {}
    for w in winners:
        if not (w in order_q):
            continue

        rq = order_q[w]
        pos = order_c.index(w)
        
        minrq = rq
        maxrq = rq

        for r in range(minrq, 0, -1):
            if order_a[r] == 1:
                minrq -= 1    

        for r in range(maxrq, pos, 1):
            if order_a[r] == 1:
                maxrq += 1

        r_order_q[w] = (minrq, maxrq)

    print("r_order_q {}".format(r_order_q), file=log)

    # cut order_c and order_a off when the final winner gets their seat,
    # put all remaining candidates in 'rem'
    n_order_c = []
    n_order_a = []

    filled = 0
    rem = []
    for r in range(len(order_c)):
        if filled == args.seats:
            rem.append(order_c[r])
            continue

        n_order_c.append(order_c[r])
        if order_a[r] == 1:
            n_order_a.append(1)
            filled += 1
        else:
            n_order_a.append(0)

    print("order_c {}".format(n_order_c), file=log)
    print("order_a {}".format(n_order_a), file=log)
    print("order_q {}".format(r_order_q), file=log)

    stvdistance(candidates, ballots, n_order_c, n_order_a, rem, winners, \
        r_order_q, merge_map, tot_ballots, args, quota, upper_bound, log=log)

    log.close()
