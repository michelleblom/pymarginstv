from stvdistance import stvdistance
from utils import merge_outcome, find_item_index_next

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

        order_q  : The exact round in which candidates who receive a quota throughout
                   the prefix have a quota at the start of the round.

        winners  : Original winners (identified by their number).

        distance : How many votes have to change (lower bound) to realise the
                   given outcome prefix.
        
    """

    def __init__(self, pid, order_c, order_a, order_q, winners, rem, distance,\
        dist_ub, order_c_index):

        self.id = None
        self.pid = pid

        self.order_c = order_c
        self.order_a = order_a
        self.tuple_order_a = tuple(order_a)
        self.order_c_index = order_c_index
        self.order_q = order_q

        self.quotas = [[] for r in self.order_c]
        for c,r in order_q.items():
          self.quotas[r].append(c)

        self.rem = rem

        self.dist = distance  # lower bound from MINLP solve
        self.dist_ub = dist_ub  # upper bound from MINLP solve
        self.seats_filled = len(winners)  # number of seats already filled.
        self.winners = winners

        self.children = []  # List of ids

    def __str__(self):
        """
            Return string representation of this tree node.
        """
        summary = ""

        for r in range(len(self.order_c)):
            action = "e" if self.order_a[r] == 0 else "s"
            if len(self.quotas[r]) > 0:
              qlist = " ( "
              for c in self.quotas[r]:
                qlist += str(c) + " "
              qlist += ")"
              action += qlist
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
        self.nodes = []  # list of ids
        self.size = 0

        self.expanded = []  # list of ids

        self.node_map = {}  # map between node id and node object

        self.idcntr = 0

        self.ignore_cntr = 0
        self.agg_prune_cntr = 0

    def get_node(self, nid):
        if nid in self.node_map:
            return self.node_map[nid]
        return None

    def get_lower_bound(self):
        lb = np.inf
        if self.size > 0:
            return self.get_node(self.nodes[0]).dist
        else:
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

            for i in range(self.size - 5, self.size):
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


    def prune_descendants(self, node):
        if node.children == []:
            # If this node is on the frontier, prune and add to expanded
            idx = find_item_index_next(self.nodes, node.id)

            if idx >= 0:
                self.nodes.pop(idx)
                self.expanded.append(node.id)
                self.agg_prune_cntr += 1
                self.size -= 1
        else:
            for did in node.children:
                self.prune_descendants(self.node_map[did])

    def similar_seq(self, inode, node):
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
            return True

        return False

    def similar_node(self, inode, node, lse=True, agv=True):
        if inode.order_a != node.order_a:
            return False

        # For now, say that two notes are NOT similar if quotas are
        # not received in the same rounds
        for r in range(len(inode.order_c)):
          if set(inode.quotas[r]) != set(node.quotas[r]):
            return False
          
        if agv:
            sim_seq = self.similar_seq(inode, node)

            if not sim_seq:
                return False

            if lse:
                if inode.dist < node.dist - epsilon:
                    # Aggressively prune node/descendants of node
                    # that are on the frontier. 
                    self.prune_descendants(node)
                    return False
                
            else:
                if abs(inode.dist - node.dist) > epsilon:
                    # Aggressively prune node/descendants of node
                    # that are on the frontier. 
                    self.prune_descendants(node)
                    return False

            self.ignore_cntr += 1
            return True

        else:
            if lse:
                if (inode.dist < node.dist - epsilon):
                    return False
            else:
                if abs(inode.dist - node.dist) > epsilon:
                    return False

            sim_seq = self.similar_seq(inode, node)

            if sim_seq:
                self.ignore_cntr += 1
                return True

        return False

    def insert(self, node, lse=True, agv=True, log=None):
        """
            Nodes are inserted into the frontier on the basis of their 
            distance value, smallest first. Unless the node is tracking
            the reported outcome--then it is added to the front of the frontier
        """
        if self.size > 0:
            for fnode in self.nodes:
                fnodeobj = self.get_node(fnode)
                if (not agv) and fnodeobj.dist > node.dist + epsilon:
                    break

                if self.similar_node(node, fnodeobj, lse=lse, agv=agv):
                    return None

            for fnode in self.expanded:
                fnodeobj = self.get_node(fnode)
                if self.similar_node(node, fnodeobj, lse=lse, agv=agv):
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
        return self.size - 1


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

    return min(loc - 1, LAST_ROUND)


def compute_elim_quota_lb_new(cands, ballots, order_c, order_a, quota, order_q):
    """
    This function calculates the lower bound on the number of votes that need to be changed
    to alter the outcome of an election prefix. It does this by considering the elimination and quota
    constraints of the election.

    Parameters:
    cands (list): A list of Candidate objects representing the candidates in the election.
    ballots (list): A list of Ballot objects representing the ballots cast in the election.
    order_c (list): A list representing the order in which candidates were eliminated or seated.
    order_a (list): A list of 0s and 1s indicating whether a candidate was eliminated (0) or seated (1) in each round.
    quota (int): The quota for the election, i.e., the minimum number of votes a candidate needs to win a seat.
    order_q (dict): A dictionary mapping winning candidates to the first round in which they have a quota at the start of that round.

    Returns:
    int: The lower bound on the number of votes that need to be changed to alter the outcome of the election prefix.
    """
    gone = []
    gone_set = set()

    elim_lb = 0
    quota_lb = 0
    no_quota_lb = 0

    winners = []
    transfer = dict()

    last_seating_block = set()
    if order_a[-1] == 1:
        for i in range(len(order_c), -1):
            if order_a[i] == 1:
                last_seating_block.append(order_c[i])
            else:
                break
    
    for i in range(len(order_c)):
        ce = order_c[i]

        if order_a[i] == 0:  # candidate eliminated
            tallies = [0 for cand in cands]

            # Compute min vote 'ce' could have at this point, needs to be
            # less than max vote of other (non-super) candidates at this point
            #min_ce = cands[ce].fp_votes

            # dict of remaining candidates (eliminated or seated after ce)
            #others = {c.num: 0 for c in cands if c.num not in gone_set and c.num != ce}

            for b in ballots:
                prefs = [p for p in b.prefs if p not in gone_set]

                if not prefs:  # ballot is exhausted
                    continue

                ev_add, _ = calc_tallies(b, gone, transfer, winners, order_q)

                if prefs[0] != ce:  # transferred to other (including fp votes)
                   # others[prefs[0]] += ev_add
                   tallies[prefs[0]] += ev_add
                else:
                   tallies[ce] += ev_add
                   #b.prefs[0] != ce:  # transferred to ce (fp votes already allocated)
                   # min_ce += ev_add

            # No one should have a quota
            no_quota_lb = max(0, tallies[ce] - quota)
            others = [c.num for c in cands if c.num not in gone_set and c.num != ce]
            for c in others:
                elim_lb = max(elim_lb, max(0, 0.5 * (tallies[ce] - tallies[c])))
                no_quota_lb = max(no_quota_lb, max(0, tallies[c] - quota))


        else:  # candidate seated
            min_tallies = [0 for _ in cands]
            max_tallies = [0 for _ in cands]

            for b in ballots:
                prefs = [p for p in b.prefs if p not in gone_set]

                if prefs:
                    sv_add, move_r = calc_tallies(b, gone, transfer, winners, order_q)
                    move_through_lsb = False
                    for p in prefs:
                        if p in order_q:
                            if order_q[p] > move_r:
                                min_tallies[p] += sv_add
                                max_tallies[p] += sv_add
                                break
                            else:
                                continue
                            
                        if p in last_seating_block:
                            max_tallies[p] += sv_add
                            move_through_lsb = True
                            continue

                        if not move_through_lsb:
                            min_tallies[p] += sv_add
                        
                        max_tallies[p] += sv_add
                        break

            rem = [c.num for c in cands if c.num not in gone_set]
            for c in rem:
                if c in order_q and order_q[c] <= i:
                    quota_lb = max(quota_lb, quota - max_tallies[c])
                elif c not in last_seating_block:
                    no_quota_lb = max(no_quota_lb, min_tallies[c] - quota);
                        
            if ce in order_q:  # candidate got a quota, else seated by default (last round)
                #value = 0  # value of ballots
                #for b in ballots:
                #    prefs = [p for p in b.prefs if p not in gone_set]

                #    if prefs and prefs[0] == ce:  # ballot is not exhausted
                #        sv_add, move_r = calc_tallies(b, gone, transfer, winners, order_q)
                #        if order_q[ce] > move_r:
                #            value += sv_add

                winners.append(ce)

                # Min/max tally should be the same
                mint,maxt = min_tallies[ce],max_tallies[ce]
                assert(abs(maxt-mint)<= epsilon)
                cmax = maxt
                value = max(cmax, quota)  # restrict value to be at lest quota
                transfer[ce] = (value - quota)/value

                # cost to displace the candidate with largest tally that is also above quota only active if
                # no eliminations/seatings has happened
                displacement_cost = 0
                if not gone:  # no eliminations or seatings yet
                    fp_others_max = max([cands[c.num].fp_votes for c in cands if c.num not in gone_set and c.num != ce])
                    displacement_cost = max(0, 0.5 * (fp_others_max - cmax))  # if someone has reached quota, we need to surpass their votes

                quota_lb = max(quota_lb, quota - cmax, displacement_cost)

        gone.append(ce)
        gone_set.add(ce)

    lb = math.ceil(max(elim_lb, quota_lb, no_quota_lb))
    return max(0, lb), transfer


def calc_tallies(b, gone, transfer, winners, order_q):
    """
    This function calculates the value of the given ballot after the candidates in gone
    have been seated/eliminated in the order specified.

    Parameters:
    b (Ballot): The ballot type for which the value bounds are being calculated.
    gone (list): A list of candidates that have been eliminated or seated.
    transfer (dict): A dictionary mapping candidates to their transfer values.
    winners (list): A list of candidates that have won, must be contained in gone
    order_q (dict): A dictionary mapping winning candidates to the first round in which they 
                    have a quota at the start of that round.

    Returns:
    tuple: A tuple containing the ballot value, and the last round in which it moved to a new candidate. 

    """
    b_value = b.votes  # contribution of ballot to next candidate

    eliminated = {}
    seated = set()
    bidx = 0
    eidx = 0
    move_r = -1 # last round in which ballot moved
    while bidx < len(b.prefs) and eidx < len(gone):  # while ballot not fully transferred
        bp = b.prefs[bidx]
        ep = gone[eidx]
    
        if bp in seated:  # skipping: bp already seated
            bidx += 1
        elif bp in eliminated:  # full transfer: candidate eliminated
            bidx += 1
        elif ep not in winners:  # eliminated candidate
            eliminated[ep] = eidx
            if bp == ep: move_r = eidx
            eidx += 1
        elif bidx > 0 and bp in order_q and order_q[bp] <= move_r:
            # bp already had a quota when the ballot was finding a new home
            # bp skipped, no reduction in ballot value
            bidx += 1
        elif bp == ep:  # ballot is transferred through seating
            b_value *= transfer[bp]  
            move_r = eidx
            eidx += 1
            bidx += 1
        else:  # ep is seated before reached by ballot
            seated.add(ep)
            eidx += 1
        
    return b_value, move_r 


def compute_elim_quota_lb_old(cands, ballots, order_c, order_a, quota, order_q):
    gone = []
    gone_set = set()
    elim_lb = 0
    quota_lb = 0

    winners = []

    for i in range(len(order_c)):
        ce = order_c[i]

        if order_a[i] == 0:
            # Compute min vote 'ce' could have at this point, needs to be
            # less than max vote of other (non super) candidates at this point
            min_ce = cands[ce].fp_votes

            max_others = {c.num: 0 for c in cands if not c.num in gone_set \
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

            for c, v in max_others.items():
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

                quota_lb = max(quota_lb, quota - cmax)

        gone.append(ce)
        gone_set.add(ce)

    return math.ceil(max(elim_lb, quota_lb))


def filterballot(b, order_c, order_a, order_c_index):
    prefs = []
    winners = []

    for p in b.prefs:
        idx = order_c_index[p] #order_c.index(p) if p in order_c else -1

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


def compute_disp_lb_new(candidates, ballots, node_order_c, node_order_a, \
    node_order_q, winner_set, rem, quota, seats, transfer, globalub):
    """
        Consider a prefix where it is clear that at least one original loser
        still standing has to displace one of the original winners still
        standing (e.g., our prefix contains just eliminations or only original
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
    # in the future (past the current outcome prefix)
    new_winner = False
    for i in range(len(node_order_c)):
        if node_order_a[i] == 1:
            if node_order_c[i] not in winner_set:
                new_winner = True
                break
        elif node_order_c[i] in winner_set:
            new_winner = True
            break

    # Compile set of original losers, and winners, that remain standing after
    # the outcome prefix node_order_c/node_order_a. The sets will remain
    # empty if we have already changed who won the election in the outcome
    # prefix.
    og_losers = []
    og_winners = []
    if not new_winner:
        for c in rem:
            if c in winner_set:
                og_winners.append(c)
            else:
                og_losers.append(c)

    sleft = seats - sum(node_order_a)
    nleft = len(rem)

    if sleft == nleft or og_losers == [] or og_winners == []:
        return 0

    winners = {c for i, c in enumerate(node_order_c) if node_order_a[i] == 1}

    min_r = {c.num: 0 for c in candidates if c.num in rem}
    filtered_ballots = []
    for b in ballots:
        prefs = [p for p in b.prefs if p in rem]
        if not prefs:
            continue
        # Lines 631--638 changed in this quota-specific version of margin-stv
        value,move_r = calc_tallies(b, node_order_c, transfer, winners, node_order_q)
        filtered_ballots.append((b.ranks, value, move_r))
        c = prefs[0]
        if c in node_order_q:
            if node_order_q[c] > move_r:
                min_r[prefs[0]] += value
        else:
            min_r[prefs[0]] += value


    ncand = len(candidates)

    # calculate how much it costs to seat ogl
    lowerbound = np.inf
    for ogl in og_losers:
        displacement_cost = np.inf
        left_at_end_costs = []

        max_l = [0]*ncand

        max_ogl = 0
        for ranks, value, _ in filtered_ballots:
            posl = ranks[ogl]
            if posl != -1:
                max_ogl += value

            # calculate how much it costs to displace r with ogl
            for r in rem:
                if r == ogl:
                    continue
                
                posw = ranks[r]
                if posl != -1 and (posw == -1 or posl < posw):  # ogl ranked above ogw
                      max_l[r] += value

        
        for r in rem:
            if r == ogl:
                continue;

            dp = max(0.0, 0.5 * (min_r[r] - max_l[r]))
            left_at_end_costs.append(dp)
            if r in og_winners:
                displacement_cost = min(displacement_cost, dp)

        quota_cost = max(0, quota - max_ogl)
        left_at_end_costs.sort()

        # ogl needs to outlast nleft - sleft candidates
        left_at_end_cost = max(left_at_end_costs[:nleft - sleft])

        lowerbound = min(lowerbound, max(displacement_cost, min(quota_cost,left_at_end_cost)))

    return math.ceil(lowerbound)


def compute_disp_lb_old(candidates, ballots, node_order_c, node_order_a, \
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
    # in the future (past the current outcome prefix)
    new_winner = False
    ncand = len(candidates)

    order_c_index = {i : -1 for i in range(ncand)}

    for i in range(len(node_order_c)):
        order_c_index[node_order_c[i]] = i
        if node_order_a[i] == 1:
            if node_order_c[i] not in winner_set:
                new_winner = True
                break
        elif node_order_c[i] in winner_set:
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
        prefs, winners = filterballot(b, node_order_c, node_order_a, order_c_index)
        if prefs != []:
            filtered_ballots.append((prefs, b.prefs, b.ranks, b.votes, winners))

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

                for prefs, oprefs, ranks, votes, winners in filtered_ballots:
                    if oprefs[0] == ogw:
                        min_w += votes
                        continue

                    if prefs[0] == ogw:
                        if winners == []:
                            min_w += votes
                        continue

                    posl = ranks[ogl]
                    posw = ranks[ogw]

                    if posl != -1 and (posw == -1 or posl < posw):
                        max_l += votes

                dp = max(0, 0.5 * (min_w - max_l))
                left_at_end_costs.append(dp)
                displacement_cost = min(displacement_cost, dp)

            for r in rem:
                if r == ogl or r in og_winners:
                    continue

                max_l = 0
                min_r = 0

                for prefs, _, ranks, votes, winners in filtered_ballots:
                    if prefs[0] == r:
                        if winners == []:
                            min_r += votes
                        continue

                    posl = ranks[ogl]
                    posr = ranks[r]

                    if posl != -1 and (posr == -1 or posl < posr):
                        max_l += votes

                left_at_end_costs.append(max(0, 0.5 * (min_r - max_l)))

            max_l = 0
            for prefs, _, votes, _ in filtered_ballots:
                if ogl in prefs:
                    max_l += votes

            quota_cost = max(0, max_l - quota)
            left_at_end_costs.sort()

            # ogl needs to outlast nleft - sleft candidates 
            left_at_end_cost = max(left_at_end_costs[:nleft - sleft])

            lowerbound = min(lowerbound, max(displacement_cost, min( \
                quota_cost, left_at_end_cost)))

    return math.ceil(lowerbound)


def treestv(ballots, candidates, winners, order_c, order_a, order_q, upperbound, \
            seats, args, quota, tot_ballots, agap=1, tlimit=None, log=None):
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

        order_q      : A dictionary mapping winning candidates to the first round 
                       in which they have a quota at the start of that round.

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

    merge_map = {c.num: c.num for c in candidates}

    nexps = 0
    nsolves = 0

    children = []

    ncand = len(candidates)

    # Initialise frontier. For each candidate, they can either be elected
    # to a seat or eliminated. Assumption: election involves at least 2
    # seats, so our initial set of nodes will not include any leaves.
    for cand in candidates:
        node_order_c = [cand.num]
        order_c_index = {i : -1 for i in range(ncand)}
        order_c_index[cand.num] = 0

        rem = [c.num for c in candidates if c.num != cand.num]

        for o in range(2):
            node_order_a = [o]
            node_winners = set([cand.num]) if o == 1 else []
            node_order_q = { cand.num : 0 } if o == 1 else {}

            children.append((node_order_c, order_c_index, node_order_a, node_order_q, node_winners, \
                             winner_set, candidates, ballots, rem, quota, args, merge_map, \
                             tot_ballots, running_ub, order_c, order_a))

    result = []
    if args.pc > 1:
        with Pool(processes=args.pc) as pool:
            result = pool.starmap(eval_child_initial, children)
    else:
        for c in children:
            result.append(eval_child_initial(*c))

    for lb, dlb, eqlb, node, solved in result:

        if solved:
            nsolves += 1

        if log != None:
            print("EVALUATING {}/{} LB {} (D {} EQ {})".format( \
                node.order_c, node.order_a, lb, dlb, eqlb),  file=log, flush=True)

            if lb < running_ub:
                if node.dist == None:
                    print("    DISTANCE None/Infeasible", file=log, flush=True)
                elif node.dist == -1:
                    print("    No solution found by timeout", file=log,  flush=True)
                    print("    Margin computation terminated", file=log,  flush=True)
                else:
                    print("    DISTANCE {:.2f}/{:.2f}".format(node.dist,  node.dist_ub), file=log, flush=True)

        if node.dist == -1:
            return running_lb, running_ub, nexps, nsolves,  frontier.ignore_cntr, frontier.agg_prune_cntr

        # skip infeasible nodes
        if node.dist is None or node.dist >= running_ub:
            continue
        else:
            if log != None:
                print("        Added to frontier", file=log, flush=True)

        if frontier.size > 0:
            running_lb = frontier.get_lower_bound() 
        else:
            running_lb = node.dist

        frontier.insert(node, lse=args.lse, agv=args.agv, log=log)

    if log != None:
        print("Lower bound {}, upper bound {}".format(running_lb, running_ub), file=log, flush=True)

        print(frontier, file=log, flush=True)

    converged = False

    tnow = time.time()
    if log != None:
        print("Time elapsed {}s".format(tnow - tstart), file=log, flush=True)

    if tlimit != None and tnow - tstart > tlimit:
        print("Time start {}, now {}, difference {}".format(tstart, tnow, tnow  - tstart), file=log, flush=True)
        return running_lb, running_ub, nexps, nsolves, frontier.ignore_cntr, frontier.agg_prune_cntr

    if frontier.size == 0:  # search space exhausted
        running_lb = running_ub  # running_ub must be a true lower bound
        if log is not None:
            print("Search space exhausted", file=log, flush=True)

    while frontier.size > 0:
        running_lb = frontier.get_lower_bound()

        if log != None:
            print("Lower bound {}, upper bound {}".format(running_lb, running_ub), file=log, flush=True)

        if abs(running_ub - running_lb) <= agap:
            converged = True
            break

        # Expand node with smallest assigned distance (first in frontier)
        fnodes = frontier.pop(args.pc)
        nexps += 1

        if fnodes == []:
            break

        toexpand = []

        # expand nodes until frontier is empty or we have converged
        for fn in fnodes:
            if log != None:
                print("EXPANDING NODE {}".format(fn), file=log, flush=True)

            toexpand.append((fn, ballots, candidates, winner_set, \
                running_ub, ncands, args, quota, tot_ballots, merge_map, \
                order_c, order_a))


        result = None
        with Pool(processes=args.pc) as pool:
            result = pool.starmap(expand_node, toexpand)

        for _, children in result:

            for isleaf, node_order_c, order_c_index, node_order_a, node_order_q, lb, dlb, eqlb, dist, \
                    dist_ub, new_rem, node_winners, solved in children:

                if solved:
                    nsolves += 1

                if log != None:
                    print("EVALUATED {}/{}/{} LB {} (D {} EQ {})".format( \
                        node_order_c, node_order_a, node_order_q, lb, dlb, eqlb), \
                        file=log, flush=True)

                    if dist == None:
                        print("    DISTANCE None/Infeasible", file=log, \
                              flush=True)
                    else:
                        print("    DISTANCE {}/{}, MINLP used: {}".format(dist, dist_ub, solved), \
                              file=log, flush=True)

                # skip infeasible nodes
                if dist is None or dist >= running_ub:
                    if log != None:
                        print("        PRUNED!", file=log, flush=True)
                    continue

                if isleaf:
                    # fully evaluated leaf nodes
                    if log != None:
                        print("        LEAF", file=log, flush=True)

                    if log != None and dist < running_ub:
                        print("Reducing upper bound from {} to {}".format(running_ub, dist), \
                              file=log, flush=True)

                    running_ub = min(running_ub, dist)  # update running_ub if possible

                    if abs(running_ub - running_lb) <= agap:
                        converged = True
                        break

                    frontier.prune(running_ub, log=log)
                else:
                    newn = TreeNode(fn.id, node_order_c, node_order_a, node_order_q, \
                                    node_winners, new_rem, dist, dist_ub, order_c_index)

                    idx = frontier.insert(newn, lse=args.lse, agv=args.agv, log=log)

                    if log is not None and idx is None:
                        print("        SUBSUMED", file=log, flush=True)

                    if idx is not None:
                        fn.children.append(newn.id)
            if converged:
                break

            # check if running_lb can be increased
            old_lb = running_lb
            if frontier.size == 0:  # search space exhausted
                break  # no need to continue search
            else:
                running_lb = max(running_lb, frontier.get_lower_bound())

            if old_lb < running_lb and log is not None:
                print(f"Increasing lower bound from {old_lb} to {running_lb}", file=log, flush=True)

            if abs(running_ub - running_lb) <= agap:
                converged = True
                break

        if frontier.size == 0:  # search space exhausted
            running_lb = running_ub  # running_ub must be a true lower bound
            if log is not None:
                print("Search space exhausted", file=log, flush=True)

        if converged:
            break

        tnow = time.time()
        if log != None and frontier.size > 0:
            print("Lower bound {}, upper bound {}".format(running_lb, \
                                                          running_ub), file=log, flush=True)
            print(frontier, file=log, flush=True)
            print("Time elapsed {}s".format(tnow - tstart), file=log, \
                  flush=True)

        if tlimit != None and tnow - tstart > tlimit:
            return running_lb, running_ub, nexps, nsolves, frontier.ignore_cntr,\
                frontier.agg_prune_cntr

    if converged or frontier.size == 0:
        if log != None:
            print("-------------------------------------------", file=log, \
                  flush=True)
            print("MARGIN LB: {}--{}, {} nodes expanded, {} solves.".format( \
                running_lb, running_ub, nexps, nsolves), file=log, flush=True)
            print("-------------------------------------------", file=log, \
                  flush=True)

    if log != None:
        print("Time to finish: {}s".format(time.time() - tstart), file=log)

    return running_lb, running_ub, nexps, nsolves, frontier.ignore_cntr,\
        frontier.agg_prune_cntr


def eval_child_initial(node_order_c, order_c_index, node_order_a, node_order_q, node_winners, winner_set, \
                       candidates, ballots, rem, quota, args, merge_map, tot_ballots, running_ub, \
                       full_order_c, full_order_a, log=None):
    # Is this a prefix of the original outcome?
    l = len(node_order_c)
    orig_prefix = node_order_c[:l] == full_order_c[:l] and node_order_a[:l] == full_order_a[:l]


    transfer = None
    if args.eqlb:
        eqlb, transfer = compute_elim_quota_lb_new(candidates, ballots, node_order_c, \
                                     node_order_a, quota, node_order_q)
    else:
        eqlb = compute_elim_quota_lb_old(candidates, ballots, node_order_c, \
                                     node_order_a, quota, node_order_q)

    if orig_prefix:
        eqlb = 0

    if args.dlb and transfer is not None:
        disp_lowerbound = compute_disp_lb_new(candidates, ballots, node_order_c, node_order_a, node_order_q, winner_set, rem, quota,
                                              args.seats, transfer, running_ub)
    else:
        disp_lowerbound = 0

    lb = max(disp_lowerbound, eqlb)

    if lb >= running_ub:
        return lb, disp_lowerbound, eqlb, TreeNode(-1, node_order_c, \
           node_order_a, node_order_q, node_winners, rem, lb, lb, order_c_index), False

    # Evaluate distance for our new tree node.
    _, dist, dist_ub = stvdistance(candidates, ballots, node_order_c, \
                                   node_order_a, rem, node_winners, node_order_q, merge_map, [], \
                                   tot_ballots, args, quota, running_ub, 0, lb)

    return lb, disp_lowerbound, eqlb, TreeNode(-1, node_order_c, \
          node_order_a, node_order_q, node_winners, rem, dist, dist_ub, order_c_index), True


def eval_child(parent_dist, node_order_c, order_c_index, node_order_a, node_order_q, args, ncands, \
               node_winners, winner_set, candidates, ballots, tot_ballots, rem, \
               quota, running_ub, full_order_c, full_order_a, isleaf, log=None):

    # Work out the round at which we can stop forming constraints,
    # compute bounds on when candidate could achieve their quotas,
    # solve the distance-to model.
    LAST_ROUND = compute_last_round(node_order_c, node_order_a, args.seats, ncands)

    transfer = None
    if args.eqlb:
        eqlb, transfer = compute_elim_quota_lb_new(candidates, ballots, node_order_c, \
                                     node_order_a, quota, node_order_q)
    else:
        eqlb = compute_elim_quota_lb_old(candidates, ballots, node_order_c, \
                                     node_order_a, quota, node_order_q)

    if args.dlb and transfer:
        disp_lowerbound = compute_disp_lb_new(candidates, ballots, node_order_c, node_order_a, node_order_q, winner_set, rem, quota,
                                              args.seats, transfer, running_ub)
    else:
        disp_lowerbound = 0

    lowerbound = max(eqlb, max(disp_lowerbound, parent_dist))

    dist, dist_ub = None, None

    if lowerbound >= running_ub:  # or (not isleaf and sum(node_order_a) == 0):
        return (isleaf, node_order_c, order_c_index, node_order_a, node_order_q, lowerbound, \
                disp_lowerbound, eqlb, lowerbound, lowerbound, rem, \
                node_winners, False)

    if args.nominlps:
        return (isleaf, node_order_c, order_c_index, node_order_a, node_order_q, lowerbound, \
                disp_lowerbound, eqlb, lowerbound, lowerbound, rem, \
                node_winners, False)

    if args.m:
        m_order_c, m_order_a, m_order_q, merge_map, supers, round_conv = \
            merge_outcome(node_order_c, node_order_a, node_order_q, rem)

        LAST_ROUND = compute_last_round(m_order_c, m_order_a, args.seats, \
                                        len(m_order_c) + len(rem))

        _, dist, dist_ub = stvdistance(candidates, ballots, m_order_c, \
                                       m_order_a, rem, node_winners, m_order_q, merge_map, \
                                       supers, tot_ballots, args, quota, running_ub, LAST_ROUND, \
                                       lowerbound, isleaf)

    else:
        merge_map = {c.num: c.num for c in candidates}
        # merge_map = dict()
        _, dist, dist_ub = stvdistance(candidates, ballots, node_order_c, \
                                       node_order_a, rem, node_winners, node_order_q, merge_map, \
                                       [], tot_ballots, args, quota, running_ub, LAST_ROUND, \
                                       lowerbound, isleaf)

    return isleaf, node_order_c, order_c_index, node_order_a, node_order_q, \
        lowerbound, disp_lowerbound, eqlb, dist, dist_ub, rem, node_winners, True


def expand_node(fnode, ballots, candidates, winner_set, running_ub, ncands, \
                args, quota, tot_ballots, merge_map, full_order_c, full_order_a,\
                log=None):
    children = []

    reported = None

    # Add a candidate to the end of the outcome prefix represented
    # by the selected node. That candidate can either be seated or 
    # eliminated.
    newindx = len(fnode.order_c)

    for r in fnode.rem:
        # Candidate can either be elected or eliminated.
        for o in range(2):
            node_order_c = fnode.order_c + [r]
            order_c_index = fnode.order_c_index
            order_c_index[r] = newindx

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

            if seats_filled > args.seats:
                continue  # invalid outcome (too many seats filled)
            elif seats_filled == args.seats:
                node_order_c += rem
                node_order_a += [0] * nrem
                new_rem = []
                isleaf = True

                for i in range(newindx, len(node_order_c)):
                    order_c_index[node_order_c[i]] = i

            elif args.seats - seats_filled == nrem:
                # Are we in a situation where the number of seats left
                # equals the number of candidates in rem?
                if winner_set - node_winners == set(rem):
                    continue

                isleaf = True

            if node_winners == winner_set:
                # This represents the original outcome
                continue


            if o == 0:
                children.append((fnode.dist, node_order_c, order_c_index, node_order_a, fnode.order_q, args, \
                             ncands, node_winners, winner_set, candidates, ballots, \
                             tot_ballots, new_rem, quota, running_ub, full_order_c, \
                             full_order_a, isleaf, False))
            else:
                  for i in range(len(node_order_a)-1, -1, -1):
                      if node_order_a[i] == 1:
                          node_order_q = {**fnode.order_q, r : i}
                          children.append((fnode.dist, node_order_c, order_c_index, node_order_a, node_order_q, args, \
                             ncands, node_winners, winner_set, candidates, ballots, \
                             tot_ballots, new_rem, quota, running_ub, full_order_c, \
                             full_order_a, isleaf, False))
                      else:
                          break

    result = []

    for c in children:
        result.append(eval_child(*c))

    return fnode, result
