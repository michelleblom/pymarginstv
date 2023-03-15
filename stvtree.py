from stvdistance import stvdistance
import numpy as np

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


    def pop(self, index):
        """
            Return first node in frontier, remove it from frontier.
        """
        return self.nodes.pop(index) if self.nodes != [] else None

    def __str__(self):
        """
            Return string representation of the frontier.
        """
        summary = "--------------------------------------------------\n"
        summary += "FRONTIER\n"

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


    def similar(self, node1, node2):
        if abs(node1.dist - node2.dist) > epsilon:
            return False
        
        if abs(node1.dist_ub - node2.dist_ub) > epsilon:
            return False

        if node1.order_a != node2.order_a:
            return False

        elim_seq1 = set()
        elim_seq2 = set()

        for i in range(len(node1.order_c)):

            if node1.order_a[i] == 1 and (node1.order_c[i]!=node2.order_c[i]):
                return False

            if node1.order_a[i] == 1:
                if elim_seq1 != elim_seq2:
                    return False

                elim_seq1 = set()
                elim_seq2 = set()

            if node1.order_a[i] == 0:
                elim_seq1.add(node1.order_c[i])
                elim_seq2.add(node2.order_c[i])

        return elim_seq1 == elim_seq2


    def insert(self, node, log=None):
        """
            Nodes are inserted into the frontier on the basis of their 
            distance value, smallest first.
        """
        for fnode in self.nodes:
            if self.similar(node, fnode):
                if log != None:
                    print("Node similar to {}".format(fnode), file=log)
                return None

        for i in range(len(self.nodes)):
            if node.dist < self.nodes[i].dist:
                self.nodes.insert(i, node)
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


def compute_disp_lb(node_order_c, node_order_a, winner_set, ballots, rem):
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
        og_losers = []
        og_winners = []

        for c in rem:
            if c in winner_set:
                og_winners.append(c)
            else:
                og_losers.append(c)

    disp_lowerbound = 0
    if og_losers != []:
        lprefix = len(node_order_c)

        displacement_cost = np.inf
        # We look for the least cost way of giving an original loser the 
        # chance of having more votes than one of the original winners at
        # some point in the future. We do this by comparing the maximum
        # possible vote the loser could have, while the winner is still 
        # standing, against the minimum possible vote the winner could have.
        # For the latter, at present, we use their first preference vote. But,
        # we could factor in votes that must have passed to them from 
        # candidates processed in the outcome prefix.
        for ogl in og_losers:
            for ogw in og_winners:
                # What would be the least displacement cost to
                # displace ogw with ogl? What is the maximum vote
                # that ogl could have assuming ogw is still standing?
                mint_ogw = 0
                maxt_ogl = 0
                for b in ballots:
                    prefs = b.prefs[:]

                    # Remove candidates from prefs that have been eliminated
                    # in the outcome prefix.
                    for i in range(lprefix):
                        if node_order_a[i] == 0:
                            prefs.remove(node_order_c[i])

                    # Allocate votes of type b to ogw or ogl as appropriate
                    if prefs[0] == ogw:
                        mint_ogw += b.votes
                        continue
                           
                    pos_w = b.prefs.index(ogw) if ogw in b.prefs else -1
                    pos_l = b.prefs.index(ogl) if ogl in b.prefs else -1
                           
                    if pos_w != -1 and (pos_l == -1 or pos_w < pos_l):
                        maxt_ogl += b.votes

                # We must at least ensure that we can make maxt_ogl
                # greater or equal to mint_ogw 
                displacement_cost = min(displacement_cost, 0.5*max(0,\
                    mint_ogw - maxt_ogl))

        disp_lowerbound = displacement_cost

    return disp_lowerbound


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

    winner_set = set(winners)

    ncands = len(candidates)

    frontier = Frontier()

    running_ub = upperbound
    running_lb = 0

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
            
            disp_lowerbound = compute_disp_lb(node_order_c, node_order_a, \
                winner_set, ballots, rem)
            
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

    while frontier.size > 0:
        running_lb = min([n.dist for n in frontier.nodes])

        if log != None:
            print("Lower bound {}, upper bound {}".format(running_lb,\
                running_ub), file=log)

        if abs(running_ub - running_lb) <= agap:
            converged = True
            break

        # Expand node with smallest assigned distance (first in frontier)
        fnode = frontier.pop(0)

        if fnode == None:
            break

        running_lb, running_ub, converged, _ = expand_node(fnode, \
            frontier, ballots, candidates, winner_set, running_lb, running_ub, \
            seats, ncands, args, quota, tot_ballots, merge_map, \
            agap=agap, log=log)

        if converged:
            break


        if log != None and frontier.size > 0:
            print("Lower bound {}, upper bound {}".format(running_lb,\
                running_ub), file=log)
            print(frontier, file=log)

    if converged or frontier.size == 0:            
        if log != None:
            print("-------------------------------------------", file=log)
            print("MARGIN COMPUTATION CONVERGED: {}--{}.".format(\
                running_lb, running_ub), file=log)
            print("-------------------------------------------", file=log)
            

    return running_lb, running_ub


def expand_node(fnode, frontier, ballots, candidates, winner_set, lb, ub,\
    seats, ncands, args, quota, tot_ballots, merge_map, agap=1, log=None):

    converged = False
    running_lb = lb
    running_ub = ub

    if log != None:
        print("EXPANDING NODE {}".format(fnode), file=log)

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
            if seats_filled == seats:
                node_order_c += rem
                node_order_a += [0]*nrem
                new_rem = []
                isleaf = True

            elif seats - seats_filled == nrem:
                # Are we in a situation where the number of seats left
                # equals the number of candidates in rem?
                node_order_c += rem
                node_winners.update(rem)
                node_order_a += [1]*nrem
                new_rem = []
                seats_filled = seats
                isleaf = True

            if node_winners == winner_set:
                # This represents the original outcome
                continue

            disp_lowerbound = compute_disp_lb(node_order_c, node_order_a, \
                winner_set, ballots, new_rem)

            disp_lowerbound = max(disp_lowerbound, fnode.dist)

            # Work out the round at which we can stop forming constraints,
            # compute bounds on when candidate could achieve their quotas,
            # solve the distance-to model.
            LAST_ROUND = compute_last_round(node_order_c,node_order_a,\
                seats, ncands)

            order_q = get_order_q(node_order_c, node_order_a, \
                LAST_ROUND, node_winners)
        
            if log != None:
                print("EVALUATING {}/{}".format(node_order_c, \
                    node_order_a), file=log)
                print("Displacement LB {}".format(disp_lowerbound), file=log)

            _, dist, dist_ub=stvdistance(candidates,ballots,node_order_c, \
                node_order_a, new_rem, node_winners, order_q, merge_map,[],\
                tot_ballots, args, quota, running_ub, LAST_ROUND, \
                disp_lowerbound, isleaf=isleaf, log=log)

            if log != None:
                if dist == None:
                    print("    DISTANCE None/Infeasible", file=log)
                elif dist == -1:
                    print("    No solution found by timeout", file=log)
                    print("    Margin computation terminated", file=log)
                else:
                    print("    DISTANCE {}/{}".format(dist, dist_ub),\
                        file=log)
            
            if dist == -1:
                break

            if dist == None or dist >= running_ub:
                continue

            if frontier.size > 0:
                running_lb = min(dist, min([n.dist for n in frontier.nodes]))
            else:
                running_lb = dist

            if seats_filled == seats:
                if log != None and dist_ub < running_ub:
                    print("Reducing upper bound to {}".format(dist_ub), \
                        file=log)

                running_ub = min(running_ub, dist_ub)

                if abs(running_ub - running_lb) <= agap:
                    converged = True
                    break

                frontier.prune(running_ub, log=log)

            else:
                newn = TreeNode(node_order_c, node_order_a, \
                    node_winners, rem, dist, dist_ub)

                index = frontier.insert(newn, log=log)

                if index != None:
                    children.append((index, dist))

    return running_lb, running_ub, converged, children



