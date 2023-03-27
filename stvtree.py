from stvdistance import stvdistance
from utils import merge_outcome

import math
import numpy as np
import time

from multiprocessing import Pool

epsilon = 0.9

class TreeNode:
    """
        Data structure for a node in our tree of alternate outcomes.

        order_c  : Outcome prefix (candidate seating/election order)

        order_a  : Outcome prefix (whether an elimination or election occurred).

        winners  : Original winners (identified by their number).

        distance : How many votes have to change (lower bound) to realise the
                   given outcome prefix.
        
    """
    def __init__(self, order_c, order_a, winners, rem, distance, dist_ub):
        self.order_c = order_c
        self.order_a = order_a
        self.rem = rem

        self.dist = distance # lower bound from MINLP solve
        self.dist_ub = dist_ub # upper bound from MINLP solve
        self.seats_filled = len(winners) # number of seats already filled.
        self.winners = winners


    def __str__(self):
        """
            Return string representation of this tree node.
        """
        summary = ""

        for r in range(len(self.order_c)):
            action = "e" if self.order_a[r] == 0 else "s"
            summary += str(self.order_c[r]) + action + " "

        summary += "with distance {}/{}".format(self.dist, self.dist_ub)

        return summary


class Frontier:
    """
        Data structure containing the tree nodes that form the frontier
        (current leafs/unexpanded nodes) of the tree of alternate 
        possibilities we are searching through.
    """
    def __init__(self):
        self.nodes = []
        self.size = 0


    #def pop(self, index):
    #    if self.size == 0:
    #        return None

    #    self.size -= 1
    #    return self.nodes.pop(0)
    
    def pop(self, number):
        if self.size <= number:
            popped = self.nodes[:]
            self.nodes = []
            self.size = 0
            return popped

        self.size -= number
        popped = self.nodes[:number]
        self.nodes = self.nodes[number:]
        return popped
            
    

    def __str__(self):
        """
            Return string representation of the frontier.
        """
        summary = "--------------------------------------------------\n"
        summary += "FRONTIER ({} nodes)\n".format(self.size)

        if self.size > 10:
            for i in range(5):
                summary += str(self.nodes[i]) + '\n'

            summary += '...\n'

            for i in range(self.size-5,self.size):
                summary += str(self.nodes[i]) + '\n'

        else:
            for node in self.nodes:
                summary += str(node) + '\n'

        summary += "--------------------------------------------------\n"
        return summary

    def prune(self, upperbound, log=None):
        """
            Remove all nodes from the frontier whose distance value is
            greater than or equal to 'upperbound'.
        """
        if self.size > 0:
            i = 0
            while i < self.size:
                if self.nodes[i].dist >= upperbound:
                    break
                i += 1

            if i == 0:
                self.nodes.clear()
                self.size = 0

            elif i < self.size:
                if log != None:
                    for n in self.nodes[i:]:
                        print("Pruning {}".format(str(n)), file=log)

                self.nodes = self.nodes[:i]
                self.size = len(self.nodes)



    def similar_node(self, inode, node):
        if inode.order_a != node.order_a:
            return False

        if abs(inode.dist-node.dist) > epsilon:
            return False

        elim_seq1 = set()
        elim_seq2 = set()

        for i in range(len(inode.order_c)):

            if inode.order_a[i] == 1 and (inode.order_c[i]!=node.order_c[i]):
                return False

            if inode.order_a[i] == 1:
                if elim_seq1 != elim_seq2:
                    return False

                elim_seq1 = set()
                elim_seq2 = set()

            if inode.order_a[i] == 0:
                elim_seq1.add(inode.order_c[i])
                elim_seq2.add(node.order_c[i])

        return elim_seq1 == elim_seq2


    def insert(self, node, log=None):
        """
            Nodes are inserted into the frontier on the basis of their 
            distance value, smallest first.
        """
        for fnode in self.nodes:
            if self.similar_node(node, fnode):
                #print("Node {} similar to {}".format(node, fnode), file=log)
                return None

        for i in range(len(self.nodes)):
            if node.dist < self.nodes[i].dist:
                self.nodes.insert(i, node)
                self.size += 1 
                return i

        self.nodes.append(node)
        self.size += 1 
        return self.size-1



def compute_last_round(order_c, order_a, seats, ncands):
    """
        Given an outcome prefix (order_c/order_a), determine what 
        round we should form constraints up to when solving the model
        that gives us the distance value for that prefix. For example, if
        the end of the prefix is going to be a bunch of candidates who 
        are seated because they are the last left standing -- we only need
        to ensure that they should be the last few left standing, not
        that any one of them has more votes than the other at that point.

        seats  :   Number of seats in the election.

        ncands :   Number of candidates in the election.
    """
    c_cntr = 0
    s_cntr = 0

    LAST_ROUND = 0
    loc = len(order_c)
    for r in range(loc):
        c_cntr += 1
        
        if order_a[r] == 1:
            s_cntr += 1 

        if s_cntr == seats:
            break

        if ncands - c_cntr == seats - s_cntr:
            break 

        LAST_ROUND += 1  

    return min(loc-1, LAST_ROUND)

       
def get_order_q(order_c, order_a, LAST_ROUND, winners):
    """
        Determine the earliest and latest time that winners could have
        achieved a quota, given that we have determined we only care
        about winners that have been seated at or before LAST_ROUND.
    """
    order_q = {}
    for w in winners:
        pos = order_c.index(w)
        if pos > LAST_ROUND:
            continue
        
        minrq = pos-1
        maxrq = pos-1

        for r in range(pos-1, -1, -1):
            if order_a[r] == 1:
                minrq -= 1    
            else:
                break

        order_q[w] = (minrq, maxrq) 

    return order_q


def compute_quota_lb(candidates, ballots, node_order_c, node_order_a, \
    order_q, quota):

    gone = []
    quota_lb = 0
    for i in range(len(node_order_c)):
        c = node_order_c[i]

        if node_order_a[i] == 1 and c in order_q:
            # What is maximum vote for 'c' in round i?

            cmax = 0
            for b in ballots:
                prefs = []
                for p in b.prefs:
                    if not p in gone:
                        prefs.append(p)

                if prefs != [] and prefs[0] == c:
                    cmax += b.votes

            quota_lb = max(quota_lb, quota-cmax)
               
        gone.append(c) 

    return quota_lb
                            
def filterballot(b, order_c, order_a):
    prefs = []

    last_winner, widx = None, None
        
    for p in b.prefs:
        idx = order_c.index(p) if p in order_c else -1

        if idx == -1:
            prefs.append(p)
        else:
            if order_a[idx] == 1 and (widx == None or idx < widx):
                last_winner = p
                widx = idx

    return prefs, last_winner


def nowinner(prefs, w, winners):
    for p in prefs:
        if p == w:
            return True

        if p in winners:
            return False
    

def compute_disp_lb(candidates, ballots, node_order_c, node_order_a, \
    winner_set, rem, quota, seats, ag_matrix):
    """
        Consider a prefix where it is clear that at least one original loser 
        still standing has to displace one of the original winners still 
        standing (eg. our prefix contains just eliminations or only original 
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
    # in the future (past the current outcome prefix
    new_winner = False
    curr_winners = []
    for i in range(len(node_order_c)):
        if node_order_a[i] == 1:
            w = node_order_c[i]
            curr_winners.append(w)
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
        og_losers = []
        og_winners = []

        for c in rem:
            if c in winner_set:
                og_winners.append(c)
            else:
                og_losers.append(c)

    filtered_ballots = []
    for b in ballots:
        prefs,last_winner = filterballot(b, node_order_c, node_order_a)
        if prefs != []:
            filtered_ballots.append((prefs, b.prefs, b.votes, last_winner))

    sleft = seats - sum(node_order_a)
    nleft = len(rem)

    lowerbound = 0
    if og_losers != [] and og_winners != []:
        lprefix = len(node_order_c)

        lowerbound = np.inf
        
        # Can we establish a transfer value lower bound for each candidate 
        # seated in node_order_c, based on the original election profile?
        tvalues = {}
        for i in range(lprefix):
            if node_order_a[i] == 1:
                ci = node_order_c[i]
                prefix = node_order_c[:i]
                
                if prefix == []:
                    candi = candidates[ci]
                    tvalues[ci] = max(0, (candi.fp_votes - quota)/\
                        candi.fp_votes) if candi.fp_votes > 0 else 0

                    continue

                min_ci = 0
                papers_ci = 0
                for b in ballots:
                    if b.prefs[0] == ci:
                        min_ci += b.votes
                        papers_ci += b.votes
                        continue

                    prefs,lwinner = filterballot(b, prefix, node_order_a)
                    if prefs == []:
                        continue

                    if prefs[0] == ci:
                        papers_ci += b.votes

                        # Would 'ci' get these votes at full value?
                        if lwinner == None:
                            min_ci += b.votes

                tvalues[ci] = max(0, (min_ci - quota)/papers_ci) if \
                    papers_ci > 0 else 0

        for ogl in og_losers:
            ogl_lowerbound = 0
            displacement_cost = np.inf
            left_at_end_costs = []

            for ogw in og_winners:
                max_l = 0
                min_w = 0

                for prefs,oprefs,votes,lwinner in filtered_ballots:
                    if oprefs[0] == ogw:
                        min_w += votes
                        continue

                    if node_order_a[-1] == -1 and prefs[0] == ogw:
                        if lwinner == None:
                            min_w += votes
                        else:
                            min_w += votes*tvalues[lwinner]
                        continue

                    posl = prefs.index(ogl) if ogl in prefs else -1
                    posw = prefs.index(ogw) if ogw in prefs else -1

                    if posl != -1 and (posw == -1 or posl < posw):
                        max_l += votes

                dp = max(0, 0.5*(min_w - max_l))
                displacement_cost = min(displacement_cost, dp)
                left_at_end_costs.append(dp)

            for r in rem:
                if r == ogl or r in og_winners:
                    continue
    
                max_l = 0
                min_r = 0

                for prefs,_,votes,lwinner in filtered_ballots:
                    if prefs[0] == r:
                        if lwinner == None:
                            min_r += votes
                        else:
                            min_r += votes*tvalues[lwinner]
                        continue

                    posl = prefs.index(ogl) if ogl in prefs else -1
                    posr = prefs.index(r) if r in prefs else -1

                    if posl != -1 and (posr == -1 or posl < posr):
                        max_l += votes

                left_at_end_costs.append(max(0, 0.5*(min_r-max_l)))
               
            max_l = 0
            for prefs,_,votes,_ in filtered_ballots:
                if ogl in prefs:
                    max_l += votes

            quota_cost = max(0, max_l - quota)

            left_at_end_costs.sort()

            # ogl needs to outlast nleft - sleft candidates 
            left_at_end_cost = max(left_at_end_costs[:nleft-sleft])

            ogl_lowerbound = max(displacement_cost, min(quota_cost, \
                left_at_end_cost))
            
            lowerbound = min(lowerbound, ogl_lowerbound)
            
    return lowerbound





def treestv(ballots, candidates, winners, order_c, order_a, upperbound, \
    seats,  args, quota, tot_ballots, agap=1, log=None):
    """
        Main function for performing the branch-and-bound algorithm that
        searches for the least number of vote changes required to elect
        a different set of winners than those in 'winners'.

        candidates   : List of Candidate data structures, ordered by 
                       candidate 'number' (note, 'number' is an index, not
                       their numeric id).

        ballots      : List of Ballot data structures representing ballot 
                       types cast in the election and how many instances of
                       that type are present (reported).

        winners      : List of candidates (by their number) that won in 
                       the reported outcome. 

        order_c      : Reported outcome (order in which candidates were
                       elected/eliminated).

        order_a      : List of 0s/1s indicating whether the candidate 
                       'processed' in each round was elected-1/eliminated-0.

        upperbound   : Computed upper bound on the margin of victory.

        seats        : Number of seats up for election.

        args         : Command line arguments

        quota        : Quota for the election

        tot_ballots  : Total number of ballots cast in the election.

        agap         : We terminate the branch-and-bound algorithm once 
                       a running lower bound on the margin is within 1
                       votes of the running upper bound.

        log          : Will either be None or an output stream to use when
                       printing out diagnostics.
    """

    tstart = time.time()

    winner_set = set(winners)
    ncands = len(candidates)

    frontier = Frontier()

    running_ub = upperbound
    running_lb = 0

    # Compute AG relationships
    ag_matrix = {}

    for i in range(ncands):
        ci = candidates[i]
        ci_min = ci.fp_votes

        ci_max = 0
        for j in range(i+1, ncands):
            cj = candidates[j]
            cj_min = cj.fp_votes

            cj_max = 0

            for b in ballots:
                ci_pos = b.prefs.index(ci.num) if ci.num in b.prefs else -1
                cj_pos = b.prefs.index(cj.num) if cj.num in b.prefs else -1

                if ci_pos != -1 and (cj_pos == -1 or cj_pos > ci_pos):
                    ci_max += b.votes

                if cj_pos != -1 and (ci_pos == -1 or ci_pos > cj_pos):
                    cj_max += b.votes

            if ci_min > cj_max:
                ag_matrix[ci.num,cj.num] = math.ceil((ci_min-cj_max)/2)

            elif cj_min > ci_max:
                ag_matrix[cj.num,ci.num] = math.ceil((cj_min-ci_max)/2)
               
    print(upperbound, file=log)
    print(ag_matrix, file=log)

            
    merge_map = {c.num : c.num for c in candidates}  

    # Initialise frontier. For each candidate, they can either be elected
    # to a seat or eliminated. Assumption: election involves at least 2
    # seats, so our initial set of nodes will not include any leaves.
    for cand in candidates:
        node_order_c  = [cand.num]
        rem = [c.num for c in candidates if c.num != cand.num]

        for o in range(2):
            node_order_a = [o]
            node_winners = set([cand.num]) if o == 1 else []

            # Compute least number of votes that would need to change to
            # realise an outcome starting with node_order_c,node_order_a.

            # Compute order_q map
            order_q = get_order_q(node_order_c, node_order_a, 0, node_winners)
            
            disp_lowerbound = compute_disp_lb(candidates, ballots, \
                node_order_c, node_order_a, winner_set,  rem, quota, seats, \
                ag_matrix)
            
            if log != None:
                print("EVALUATING {}/{}".format(node_order_c, node_order_a),\
                    file=log)
                print("Displacement LB {}".format(disp_lowerbound), file=log)
                                               
            # Evaluate distance for our new tree node.
            _, dist, dist_ub = stvdistance(candidates, ballots, node_order_c, \
                node_order_a, rem, node_winners, order_q, merge_map, [],\
                tot_ballots, args, quota, running_ub, 0, disp_lowerbound, \
                log=log)

            if log != None:
                if dist == None:
                    print("    DISTANCE None/Infeasible", file=log)
                elif dist == -1:
                    print("    No solution found by timeout", file=log)
                    print("    Margin computation terminated", file=log)
                else:
                    print("    DISTANCE {:.2f}/{:.2f}".format(dist, dist_ub),\
                        file=log)

            if dist == -1:
                return running_lb, running_ub

            if dist == None or dist >= running_ub:
                continue
            
            if frontier.size > 0:
                running_lb = min(dist, min([n.dist for n in frontier.nodes]))
            else:
                running_lb = dist

            # Create and add node to our frontier.
            newn = TreeNode(node_order_c, node_order_a, node_winners, rem,\
                dist, dist_ub)

            frontier.insert(newn, log=log)


    if log != None:
        print("Lower bound {}, upper bound {}".format(running_lb,\
            running_ub), file=log)
        print(frontier, file=log)

    converged = False

    tnow = time.time()
    if  log != None:
        print("Time elapsed {}s".format(tnow-tstart), file=log)
    

    while frontier.size > 0:
        running_lb = min([n.dist for n in frontier.nodes])

        if log != None:
            print("Lower bound {}, upper bound {}".format(running_lb,\
                running_ub), file=log)

        if abs(running_ub - running_lb) <= agap:
            converged = True
            break

        # Expand node with smallest assigned distance (first in frontier)
        fnodes = frontier.pop(args.p)

        if fnodes == []:
            break
               

        arg_list = []
        for fn in fnodes:
            if args.p == 1 and log != None:
                print("EXPANDING NODE {}".format(fn), file=log)
            arg_list.append((fn, ballots, candidates, winner_set, running_ub,\
                ncands, args, quota, tot_ballots, merge_map, ag_matrix))

        result = []
        with Pool() as pool:
            result = pool.starmap(expand_node, arg_list)


        for fnode, children in result:
            for isleaf, node_order_c, node_order_a, disp_lb, dist, \
                dist_ub, new_rem, node_winners in children:

                if args.p == 1 and log != None:
                    print("EVALUATED {}/{}".format(node_order_c, \
                        node_order_a),file=log)
                    print("Displacement/Quota LB {}".format(disp_lb), \
                        file=log)
                    
                    if dist == None:
                        print("    DISTANCE None/Infeasible", file=log)
                    else:
                        print("    DISTANCE {}/{}".format(dist, dist_ub), \
                            file=log)
                
                if dist == None or dist >= running_ub:
                    continue

                if frontier.size > 0:
                    running_lb=min(dist,min([n.dist for n in frontier.nodes]))
                else:
                    running_lb=min(dist, running_ub)

                if isleaf:
                    if log != None and dist_ub < running_ub:
                        print("Reducing upper bound to {}".format(dist_ub),\
                            file=log)

                    running_ub = min(running_ub, dist_ub)

                    if abs(running_ub - running_lb) <= agap:
                        converged = True
                        break

                    frontier.prune(running_ub, log=log)
                else:
                    newn = TreeNode(node_order_c, node_order_a, node_winners,\
                        new_rem, dist, dist_ub)

                    frontier.insert(newn, log=log)
                    
            if converged:
                break

        if converged:
            break
                    
        if log != None and frontier.size > 0:
            print("Lower bound {}, upper bound {}".format(running_lb,\
                running_ub), file=log)
            print(frontier, file=log)
            tnow = time.time()
            print("Time elapsed {}s".format(tnow-tstart), file=log)

    if converged or frontier.size == 0:            
        if log != None:
            print("-------------------------------------------", file=log)
            print("MARGIN COMPUTATION CONVERGED: {}--{}.".format(\
                running_lb, running_ub), file=log)
            print("-------------------------------------------", file=log)
            
    return running_lb, running_ub

               

def expand_node(fnode, ballots, candidates, winner_set, ub, ncands,\
    args, quota, tot_ballots, merge_map, ag_matrix):

    result = []

    # Add a candidate to the end of the outcome prefix represented
    # by the selected node. That candidate can either be seated or 
    # eliminated.
    for r in fnode.rem:
        # Candidate can either be elected or eliminated.
        for o in range(2):
            node_order_c = fnode.order_c + [r]
            rem = [c.num for c in candidates if not c.num in node_order_c]

            node_winners = set(fnode.winners)
            if o == 1:
                node_winners.add(r)

            if node_winners == winner_set:
                # This represents the original outcome
                continue

            node_order_a = fnode.order_a + [o]

            # Have we filled all seats?
            seats_filled = sum(node_order_a)

            new_rem = rem
            nrem = len(rem)
            isleaf = False
            if seats_filled == args.seats:
                node_order_c += rem
                node_order_a += [0]*nrem
                new_rem = []
                isleaf = True

            elif args.seats - seats_filled == nrem:
                # Are we in a situation where the number of seats left
                # equals the number of candidates in rem?
                node_order_c += rem
                node_winners.update(rem)
                node_order_a += [1]*nrem
                new_rem = []
                seats_filled = args.seats
                isleaf = True

            if node_winners == winner_set:
                # This represents the original outcome
                continue

            
            # Work out the round at which we can stop forming constraints,
            # compute bounds on when candidate could achieve their quotas,
            # solve the distance-to model.
            LAST_ROUND = compute_last_round(node_order_c, node_order_a, \
                args.seats, ncands)

            order_q = get_order_q(node_order_c, node_order_a, LAST_ROUND, \
                node_winners)

            disp_lowerbound = compute_disp_lb(candidates, ballots, \
                node_order_c, node_order_a, winner_set,  new_rem, quota, \
                args.seats, ag_matrix)

            quota_lb = compute_quota_lb(candidates, ballots, node_order_c, \
                node_order_a, order_q, quota)

            # Don't want to use anything that might have been effected
            # by order in which eliminated candidates were placed in outcome.
            lowerbound = max(quota_lb, max(disp_lowerbound, fnode.dist))

            if lowerbound >= ub:
                result.append((isleaf, node_order_c, node_order_a, ub, ub, \
                    ub, new_rem, node_winners))
                continue


            dist, dist_ub = None, None

            isleaf = True if new_rem == [] else False

            if args.m:
                m_order_c,m_order_a,m_order_q,merge_map,supers,round_conv = \
                    merge_outcome(node_order_c, node_order_a, order_q, new_rem)

                LAST_ROUND = round_conv[LAST_ROUND]
        
                _, dist, dist_ub=stvdistance(candidates,ballots,m_order_c, \
                    m_order_a, new_rem, node_winners, order_q, merge_map, \
                    supers, tot_ballots, args, quota, ub, LAST_ROUND, \
                    lowerbound, isleaf=isleaf, log=None)

            else:
                _, dist, dist_ub=stvdistance(candidates,ballots,node_order_c, \
                    node_order_a, new_rem, node_winners, order_q, merge_map, \
                    [], tot_ballots, args, quota, ub, LAST_ROUND, \
                    lowerbound, isleaf=isleaf, log=None)

            result.append((isleaf,node_order_c,node_order_a,lowerbound,\
                dist, dist_ub, new_rem, node_winners))

    return fnode, result




