from stvdistance import stvdistance


class TreeNode:
    """
        Data structure for a node in our tree of alternate outcomes.

        order_c  : Outcome prefix (candidate seating/election order)

        order_a  : Outcome prefix (whether an elimination or election occurred).

        winners  : Original winners (identified by their number).

        distance : How many votes have to change (lower bound) to realise the
                   given outcome prefix.
        
    """
    def __init__(self, order_c, order_a, winners, rem, distance):
        self.order_c = order_c
        self.order_a = order_a
        self.rem = rem

        self.dist = distance
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

        summary += "with distance {}".format(self.dist)

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

    def insert(self, node):
        """
            Nodes are inserted into the frontier on the basis of their 
            distance value, smallest first.
        """
        for i in range(len(self.nodes)):
            if node.dist < self.nodes[i].dist:
                self.nodes.insert(i, node)
                return

        self.nodes.append(node)
        self.size += 1 

    def pop(self):
        """
            Return first node in frontier, remove it from frontier.
        """
        return self.nodes.pop(0) if self.nodes != [] else None

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
            if log != None:
                print("EVALUATING {}/{}".format(node_order_c, node_order_a),\
                    file=log)

            # Compute order_q map
            order_q = get_order_q(node_order_c, node_order_a, 0, node_winners)
            
            # Evaluate distance for our new tree node.
            _, dist = stvdistance(candidates, ballots, node_order_c, \
                node_order_a, rem, node_winners, order_q, merge_map, [],\
                tot_ballots, args, quota, running_ub, 0, log=log)

            if log != None:
                print("    DISTANCE {}".format(dist), file=log)

            if dist == None or dist >= running_ub:
                continue

            # Create and add node to our frontier.
            newn = TreeNode(node_order_c,node_order_a,node_winners,rem,dist)

            frontier.insert(newn)


    if log != None:
        print(frontier, file=log)

    converged = False

    while frontier.size > 0:
        running_lb = min([n.dist for n in frontier.nodes])

        if abs(running_ub - running_lb) <= agap:
            converged = True
            break

        # Expand node with smallest assigned distance (first in frontier)
        fnode = frontier.pop()

        if fnode == None:
            break

        if log != None:
            print("EXPANDING NODE {}".format(fnode), file=log)

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
                if seats_filled == seats:
                    node_order_c += rem
                    node_order_a += [0]*nrem
                    new_rem = []

                elif seats - seats_filled == nrem:
                    # Are we in a situation where the number of seats left
                    # equals the number of candidates in rem?
                    node_order_c += rem
                    node_winners.update(rem)
                    node_order_a += [1]*nrem
                    new_rem = []
                    seats_filled = seats

                if node_winners == winner_set:
                    # This represents the original outcome
                    continue


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

                _, dist = stvdistance(candidates, ballots, node_order_c, \
                    node_order_a, new_rem, node_winners, order_q,merge_map,[],\
                    tot_ballots, args, quota, running_ub, LAST_ROUND, log=log)

                if log != None:
                    print("    DISTANCE {}".format(dist), file=log)

                if dist == None or dist >= running_ub:
                    continue

                if seats_filled == seats:
                    running_ub = dist

                    if abs(running_ub - running_lb) <= agap:
                        converged = True
                        break

                    frontier.prune(running_ub, log=log)
                        
                else:
                    newn = TreeNode(node_order_c, node_order_a, \
                        node_winners, rem, dist)

                    frontier.insert(newn)


            if converged:
                break

        if converged:
            break

        if log != None:
            print(frontier, file=log)


    if converged:            
        if log != None:
            print("MARGIN COMPUTATION CONVERGED: {}--{}.".format(\
                running_lb, running_ub), file=log)
            

    return running_lb, running_ub

