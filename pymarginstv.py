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

    quota, tallies, totvotes = simulate_stv(ballots, candidates, args.seats,\
        order_c, order_a, order_q, winners, log=log)


    weub = compute_weub(candidates, winners, order_c, order_a, tallies)
    simple_ub = compute_simple_ub(candidates, quota, winners)

    upper_bound = min(weub, simple_ub)

    print("WEUB {}, simple UB {}".format(weub, simple_ub), file=log)

    lb, ub = treestv(ballots, candidates, winners, order_c, order_a,\
        upper_bound, args.seats, args, quota, totvotes, log=log)

    log.close()
