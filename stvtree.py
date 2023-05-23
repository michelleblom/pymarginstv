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
    def __init__(self, pid, order_c, order_a, winners, rem, distance, dist_ub):
        self.id = None
        self.pid = pid

        self.order_c = order_c
        self.order_a = order_a
        self.rem = rem

        self.dist = distance # lower bound from MINLP solve
        self.dist_ub = dist_ub # upper bound from MINLP solve
        self.seats_filled = len(winners) # number of seats already filled.
        self.winners = winners

        self.children = [] # List of ids


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
        self.nodes = [] # list of ids
        self.size = 0

        self.expanded = [] # list of ids

        self.node_map = {} # map between node id and node object

        self.idcntr = 0

        self.ignore_cntr = 0

    def get_node(self, nid):
        if nid in self.node_map:
            return self.node_map[nid]
        return None

    def get_lower_bound(self):
        lb = np.inf
        for n in self.nodes:
            lb = min(lb, self.get_node(n).dist)

        return lb

    def pop(self, number):
        if self.size <= number:
            popped = self.nodes[:]
            self.expanded.extend(popped)
            self.nodes = []
            self.size = 0
            return [self.get_node(p) for p in popped]

        self.size -= number
        popped = self.nodes[:number]
        self.expanded.extend(popped)
        self.nodes = self.nodes[number:]
        return [self.get_node(p) for p in popped]
            
    

    def __str__(self):
        """
            Return string representation of the frontier.
        """
        summary = "--------------------------------------------------\n"
        summary += "FRONTIER ({} nodes)\n".format(self.size)

        if self.size > 10:
            for i in range(5):
                summary += str(self.get_node(self.nodes[i])) + '\n'

            summary += '...\n'

            for i in range(self.size-5,self.size):
                summary += str(self.get_node(self.nodes[i])) + '\n'

        else:
            for node in self.nodes:
                summary += str(self.get_node(node)) + '\n'

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
                if self.get_node(self.nodes[i]).dist >= upperbound:
                    break
                i += 1

            if i == 0:
                self.nodes.clear()
                self.size = 0

            elif i < self.size:
                if log != None:
                    for n in self.nodes[i:]:
                        print("Pruning {}".format(str(self.get_node(n))), \
                            file=log)

                self.nodes = self.nodes[:i]
                self.size = len(self.nodes)


    def similar_node(self, inode, node, lse=True):
        if inode.order_a != node.order_a:
            return False

        if lse:
            if (inode.dist < node.dist - epsilon):
                return False
        else:
            if abs(inode.dist - node.dist) > epsilon:
                return False

        elim_seq1 = set()
        elim_seq2 = set()

        for i in range(len(inode.order_c)):

            if inode.order_a[i] == 1:
                if inode.order_c[i] != node.order_c[i]:
                    return False

                if elim_seq1 != elim_seq2:
                    return False

                elim_seq1 = set()
                elim_seq2 = set()

            if inode.order_a[i] == 0:
                elim_seq1.add(inode.order_c[i])
                elim_seq2.add(node.order_c[i])

        if elim_seq1 == elim_seq2:
            self.ignore_cntr += 1
            return True

        return False


    def insert(self, node, lse=True,log=None):
        """
            Nodes are inserted into the frontier on the basis of their 
            distance value, smallest first.
        """
        if self.size > 0:
            for fnode in self.nodes:
                fnodeobj = self.get_node(fnode)
                if fnodeobj.dist > node.dist + epsilon:
                    break

                if self.similar_node(node, fnodeobj, lse=lse):
                    return None

            for fnode in self.expanded:
                fnodeobj = self.get_node(fnode)
                if self.similar_node(node, fnodeobj, lse=lse):
                    return None
        
        node.id = self.idcntr
        self.idcntr += 1

        self.node_map[node.id] = node

        for i in range(len(self.nodes)):
            if node.dist < self.get_node(self.nodes[i]).dist:
                self.nodes.insert(i, node.id)
                self.size += 1 
                return i
        
        self.nodes.append(node.id)
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
        pos = order_c.index(w) if w in order_c else LAST_ROUND
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


def compute_elim_quota_lb(cands, ballots, order_c, order_a, quota, order_q):
    gone = []
    elim_lb = 0
    quota_lb = 0

    winners = []
    
    for i in range(len(order_c)):
        ce = order_c[i]

        if order_a[i] == 0:
            # Compute min vote 'ce' could have at this point, needs to be 
            # less than max vote of other (non super) candidates at this point
            min_ce = cands[ce].fp_votes

            max_others = {c.num : 0 for c in cands if not c.num in gone \
                and c.num != ce}

            for b in ballots:
                prefs = []
                through_winner = False
                for p in b.prefs:
                    if not p in gone:
                        prefs.append(p)

                    if p in winners:
                        through_winner = True

                if prefs == []:
                    continue

                if prefs[0] != ce:
                    max_others[prefs[0]] += b.votes
            
    
                elif b.prefs[0] != ce and not through_winner:
                    # We are giving 'ce' extra votes if all the candidates
                    # ranked higher than 'ce' have already been eliminated
                    # according to the given outcome. 
                    min_ce += b.votes                    

            for c,v in max_others.items():
                elim_lb = max(elim_lb, max(0, 0.5 * (min_ce - v)))
        
        else:
            winners.append(ce)

            if ce in order_q:
                cmax = 0
                for b in ballots:
                    prefs = []
                    for p in b.prefs:
                        if not p in gone:
                            prefs.append(p)

                    if prefs != [] and prefs[0] == ce:
                        cmax += b.votes

                quota_lb = max(quota_lb, quota-cmax)

        gone.append(ce) 

    return math.ceil(max(elim_lb, quota_lb))         
         
                   
def filterballot(b, order_c, order_a):
    prefs = []
    winners = []

    for p in b.prefs:
        idx = order_c.index(p) if p in order_c else -1

        if idx == -1:
            prefs.append(p)
        elif order_a[idx] == 1:
            winners.append(p)

    return prefs, winners


def nowinner(prefs, w, winners):
    for p in prefs:
        if p == w:
            return True

        if p in winners:
            return False
    

def compute_disp_lb(candidates, ballots, node_order_c, node_order_a, \
    winner_set, rem, quota, seats):
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
        prefs, winners = filterballot(b, node_order_c, node_order_a)
        if prefs != []:
            filtered_ballots.append((prefs, b.prefs, b.votes, winners))

    sleft = seats - sum(node_order_a)
    nleft = len(rem)

    lowerbound = 0
    if og_losers != [] and og_winners != []:
        lprefix = len(node_order_c)
        lowerbound = np.inf
        
        for ogl in og_losers:
            displacement_cost = np.inf
            left_at_end_costs = []

            for ogw in og_winners:
                max_l = 0
                min_w = 0

                for prefs,oprefs,votes,winners in filtered_ballots:
                    if oprefs[0] == ogw:
                        min_w += votes
                        continue

                    if prefs[0] == ogw:
                        if winners == []:
                            min_w += votes
                        continue

                    posl = prefs.index(ogl) if ogl in prefs else -1
                    posw = prefs.index(ogw) if ogw in prefs else -1

                    if posl != -1 and (posw == -1 or posl < posw):
                        max_l += votes

                dp = max(0, 0.5*(min_w - max_l))
                left_at_end_costs.append(dp)
                displacement_cost = min(displacement_cost, dp)

            for r in rem:
                if r == ogl or r in og_winners:
                    continue
    
                max_l = 0
                min_r = 0

                for prefs,_,votes,winners in filtered_ballots:
                    if prefs[0] == r:
                        if winners == []:
                            min_r += votes
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

            lowerbound = min(lowerbound, max(displacement_cost, min(\
                quota_cost, left_at_end_cost)))
            
    return math.ceil(lowerbound)





def treestv(ballots, candidates, winners, order_c, order_a, upperbound, \
    seats,  args, quota, tot_ballots, agap=1, tlimit=None, log=None):
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

    merge_map = {c.num : c.num for c in candidates}  

    nexps = 0
    nsolves = 0

    children = []

    # Initialise frontier. For each candidate, they can either be elected
    # to a seat or eliminated. Assumption: election involves at least 2
    # seats, so our initial set of nodes will not include any leaves.
    for cand in candidates:
        node_order_c  = [cand.num]
        rem = [c.num for c in candidates if c.num != cand.num]

        for o in range(2):
            node_order_a = [o]
            node_winners = set([cand.num]) if o == 1 else []

            children.append((node_order_c, node_order_a, node_winners, \
                winner_set, candidates, ballots, rem, quota, args, merge_map,\
                tot_ballots, running_ub, order_c, order_a))

    with Pool(processes=args.pc) as pool:
        result = pool.starmap(eval_child_initial, children)

        for lb, dlb, eqlb, node, solved in result:
            if solved:
                nsolves += 1

            if log != None:
                print("EVALUATING {}/{} LB {} (D {} EQ {})".format(\
                    node.order_c, node.order_a, lb, dlb, eqlb), \
                    file=log, flush=True)
                if dlb != 0:
                    print("D is non-zero.", file=log, flush=True)
                           
                if lb < running_ub:                    
                    if node.dist == None:
                        print("    DISTANCE None/Infeasible", file=log, \
                            flush=True)
                    elif node.dist == -1:
                        print("    No solution found by timeout", file=log,\
                            flush=True)
                        print("    Margin computation terminated", file=log, \
                            flush=True)
                    else:
                        print("    DISTANCE {:.2f}/{:.2f}".format(node.dist, \
                            node.dist_ub), file=log, flush=True)

            if node.dist == -1:
                return running_lb, running_ub, nexps, nsolves, \
                    frontier.ignore_cntr

            if node.dist == None or node.dist >= running_ub:
                continue
            
            if frontier.size > 0:
                running_lb = min(node.dist, min([frontier.get_node(n).dist \
                    for n in frontier.nodes]))
            else:
                running_lb = node.dist

            frontier.insert(node, lse=args.lse, log=log)

    if log != None:
        print("Lower bound {}, upper bound {}".format(running_lb,\
            running_ub), file=log, flush=True)

        print(frontier, file=log, flush=True)


    converged = False

    tnow = time.time()
    if  log != None:
        print("Time elapsed {}s".format(tnow-tstart), file=log, flush=True)
    
    if tlimit != None and tnow-tstart > tlimit:
        return running_lb, running_ub

    while frontier.size > 0:
        running_lb = frontier.get_lower_bound()

        if log != None:
            print("Lower bound {}, upper bound {}".format(running_lb,\
                running_ub), file=log, flush=True)

        if abs(running_ub - running_lb) <= agap:
            converged = True
            break

        # Expand node with smallest assigned distance (first in frontier)
        fnodes = frontier.pop(1)
        nexps += 1

        if fnodes == []:
            break
               
        arg_list = []
        min_lb = running_ub
        for fn in fnodes:
            if log != None:
                print("EXPANDING NODE {}".format(fn), file=log, flush=True)

            _, children = expand_node(fn, ballots, candidates, winner_set, \
                running_ub, ncands, args, quota, tot_ballots, merge_map, \
                order_c, order_a)

            for isleaf, node_order_c, node_order_a, lb, dlb, eqlb, dist, \
                dist_ub, new_rem, node_winners, solved in children:

                if solved:
                    nsolves += 1

                if log != None:
                    print("EVALUATED {}/{} LB {} (D {} EQ {})".format(\
                        node_order_c, node_order_a, lb, dlb, eqlb), \
                        file=log, flush=True)
                    if dlb != 0:
                        print("D is non-zero.", file=log, flush=True)

                    
                    if dist == None:
                        print("    DISTANCE None/Infeasible", file=log, \
                            flush=True)
                    else:
                        print("    DISTANCE {}/{}".format(dist, dist_ub), \
                            file=log, flush=True)
                
                if dist == None or dist >= running_ub:
                    continue

                if frontier.size > 0:
                    running_lb=min(dist, frontier.get_lower_bound())
                else:
                    running_lb=min(dist, running_ub)

                if isleaf:
                    min_lb = min(min_lb, lb)

                    if log != None and dist_ub < running_ub:
                        print("Reducing upper bound to {}".format(dist_ub),\
                            file=log, flush=True)

                    running_ub = min(running_ub, dist_ub)

                    if abs(running_ub - running_lb) <= agap:
                        converged = True
                        break

                    frontier.prune(running_ub, log=log)
                else:
                    newn = TreeNode(fn.id, node_order_c, node_order_a, \
                        node_winners, new_rem, dist, dist_ub)

                    idx = frontier.insert(newn, lse=args.lse, log=log)

                    if idx != None:
                        fn.children.append(newn.id)
                    
                    min_lb = min(min_lb, newn.dist)
                        

            if converged:
                break

            elif frontier.size == 0:
                running_lb = max(running_lb, min_lb)


            #if args.ap:
                # Update distances for expanded node (and ancestors) based on 
                # evaluations of expanded nodes children
            #    frontier.back_propagate(fn.id)
 
        if converged:
            break


        tnow = time.time()
        if log != None and frontier.size > 0:
            print("Lower bound {}, upper bound {}".format(running_lb,\
                running_ub), file=log, flush=True)
            print(frontier, file=log, flush=True)
            print("Time elapsed {}s".format(tnow-tstart), file=log, \
                flush=True)

        if tlimit != None and tnow-tstart > tlimit:
            return running_lb, running_ub, nexps, nsolves, frontier.ignore_cntr


    if converged or frontier.size == 0:            
        if log != None:
            print("-------------------------------------------", file=log, \
                flush=True)
            print("MARGIN LB: {}--{}, {} nodes expanded, {} solves.".format(\
                running_lb, running_ub, nexps, nsolves), file=log, flush=True)
            print("-------------------------------------------", file=log, \
                flush=True)

    if log != None:
        print("Time to finish: {}s".format(time.time()-tstart), file=log)
            
    return running_lb, running_ub, nexps, nsolves, frontier.ignore_cntr

           
def eval_child_initial(node_order_c, node_order_a, node_winners, winner_set, \
    candidates, ballots, rem, quota, args, merge_map, tot_ballots, running_ub,\
    full_order_c, full_order_a):

    # Prefix of original outcome should get 0 evaluation
    l = len(node_order_c)
    if node_order_c[:l] == full_order_c[:l] and node_order_a[:l] == \
        full_order_a[:l]:
        return 0, 0, 0, TreeNode(-1, node_order_c, node_order_a, node_winners,\
            rem, 0, 0), False

    # Compute order_q map
    order_q = get_order_q(node_order_c, node_order_a, 0, node_winners)
            
    disp_lowerbound = compute_disp_lb(candidates, ballots, \
        node_order_c, node_order_a, winner_set, rem, quota, args.seats) if \
        args.dlb else 0
                  
    eqlb = compute_elim_quota_lb(candidates, ballots, node_order_c, \
        node_order_a, quota, order_q)

    lb = max(disp_lowerbound, eqlb)
        
    if lb >= running_ub:
        return lb, disp_lowerbound, eqlb, TreeNode(-1, node_order_c,\
            node_order_a, node_winners, rem, lb, lb), False
                         
    # Evaluate distance for our new tree node.
    _, dist, dist_ub = stvdistance(candidates, ballots, node_order_c, \
        node_order_a, rem, node_winners, order_q, merge_map, [],\
        tot_ballots, args, quota, running_ub, 0, lb, log=None)

    return lb, disp_lowerbound, eqlb, TreeNode(-1, node_order_c, \
        node_order_a, node_winners, rem, dist, dist_ub), True     


def eval_child(parent_dist, node_order_c, node_order_a, args, ncands, \
    node_winners, winner_set, candidates, ballots, tot_ballots, rem, \
    quota, running_ub, full_order_c, full_order_a, isleaf):

    # Prefix of original outcome should get 0 evaluation
    l = len(node_order_c)
    if node_order_c[:l] == full_order_c[:l] and node_order_a[:l] == \
        full_order_a[:l]:
        return False, node_order_c, node_order_a, 0, 0, 0, 0, 0, rem, \
            node_winners, False


    # Work out the round at which we can stop forming constraints,
    # compute bounds on when candidate could achieve their quotas,
    # solve the distance-to model.
    LAST_ROUND = compute_last_round(node_order_c,node_order_a,args.seats,ncands)

    order_q = get_order_q(node_order_c, node_order_a, LAST_ROUND, node_winners)

    disp_lowerbound = compute_disp_lb(candidates, ballots, \
        node_order_c, node_order_a, winner_set, rem, quota, args.seats) if \
        args.dlb and (not isleaf) else 0

    eqlb = compute_elim_quota_lb(candidates, ballots, node_order_c, \
        node_order_a, quota, order_q)

    lowerbound = max(eqlb, max(disp_lowerbound, parent_dist))
    
    dist, dist_ub = None, None

    if lowerbound >= running_ub: # or (not isleaf and sum(node_order_a) == 0):
        return (isleaf, node_order_c, node_order_a, lowerbound, \
            disp_lowerbound, eqlb, lowerbound, lowerbound, rem, \
            node_winners, False)
   
    if args.nominlps:
        return isleaf, node_order_c, node_order_a, lowerbound, \
            disp_lowerbound, eqlb, lowerbound, lowerbound, rem, \
            node_winners, True

 
    if args.m:
        m_order_c,m_order_a,m_order_q,merge_map,supers,round_conv = \
            merge_outcome(node_order_c, node_order_a, order_q, rem)

        LAST_ROUND = compute_last_round(m_order_c, m_order_a, args.seats,\
            len(m_order_c) + len(rem))
        
        _, dist, dist_ub=stvdistance(candidates, ballots, m_order_c, \
            m_order_a, rem, node_winners, m_order_q, merge_map, \
            supers, tot_ballots, args, quota, running_ub, LAST_ROUND, \
            lowerbound, isleaf=isleaf, log=None)

    else:
        _, dist, dist_ub=stvdistance(candidates,ballots,node_order_c, \
            node_order_a, rem, node_winners, order_q, merge_map, \
            [], tot_ballots, args, quota, running_ub, LAST_ROUND, \
            lowerbound, isleaf=isleaf, log=None)

    return isleaf, node_order_c, node_order_a, lowerbound, disp_lowerbound, \
        eqlb, dist, dist_ub, rem, node_winners, True



def expand_node(fnode, ballots, candidates, winner_set, running_ub, ncands,\
    args, quota, tot_ballots, merge_map, full_order_c, full_order_a):

    children = []

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
                if winner_set - node_winners == set(rem):
                    continue
                isleaf = True

            if node_winners == winner_set:
                # This represents the original outcome
                continue

            children.append((fnode.dist, node_order_c, node_order_a, args, \
                ncands, node_winners, winner_set, candidates, ballots, \
                tot_ballots, new_rem, quota, running_ub, full_order_c, \
                full_order_a, isleaf))

    result = []
    with Pool(processes=args.pc) as pool:
        result = pool.starmap(eval_child, children)

    return fnode, result

 
