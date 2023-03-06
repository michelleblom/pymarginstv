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

    # Reframe order_q so we have a range of rounds in which winners
    # could have achieved their quota
    R = len(order_c)

    r_order_q = {}
    for w in winners:
        if not (w in order_q):
            continue

        pos = order_c.index(w)
        
        minrq = pos-1
        maxrq = pos-1

        for r in range(pos-1, -1, -1):
            if order_a[r] == 1:
                minrq -= 1    
            else:
                break

        r_order_q[w] = (minrq, maxrq)
    
    print("order_c {}".format(order_c), file=log)
    print("order_a {}".format(order_a), file=log)
    print("r_order_q {}".format(r_order_q), file=log)

    m_order_c, m_order_a, m_order_q, merge_map, supers, _ = merge_outcome(\
        order_c, order_a, r_order_q)

    print("m_order_c {}".format(m_order_c), file=log)
    print("m_order_a {}".format(m_order_a), file=log)
    print("m_order_q {}".format(m_order_q), file=log)
    
    stvdistance(candidates, ballots, m_order_c, m_order_a, [], winners, \
        m_order_q, merge_map, supers, tot_ballots, args, quota, upper_bound, \
        log=log)

    log.close()
