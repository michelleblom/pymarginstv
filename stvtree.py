from stvdistance import stvdistance


class TreeNode:
    def __init__(self, order_c, order_a, winners, rem, distance):
        self.order_c = order_c
        self.order_a = order_a
        self.rem = rem

        self.dist = distance
        self.seats_filled = len(winners)
        self.winners = winners


    def __str__(self):
        summary = ""

        for r in range(len(self.order_c)):
            action = "e" if self.order_a[r] == 0 else "s"
            summary += str(self.order_c[r]) + action + " "

        summary += "with distance {}".format(self.dist)

        return summary


class Frontier:
    def __init__(self):
        self.nodes = []
        self.size = 0

    def insert(self, node):
        for i in range(len(self.nodes)):
            if node.dist < self.nodes[i].dist:
                self.nodes.insert(i, node)
                return

        self.nodes.append(node)
        self.size += 1 

    def pop(self):
        return self.nodes.pop(0) if self.nodes != [] else None

    def __str__(self):
        summary = "--------------------------------------------------\n"
        summary += "FRONTIER\n"

        for node in self.nodes:
            summary += str(node) + '\n'

        summary += "--------------------------------------------------\n"
        return summary

    def prune(self, upperbound):
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
                self.nodes = self.nodes[:i]
                self.size = len(self.nodes)


def compute_last_round(order_c, order_a, seats, ncands):
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
            
            _, dist = stvdistance(candidates, ballots, node_order_c, \
                node_order_a, rem, node_winners, order_q, merge_map, [],\
                tot_ballots, args, quota, running_ub, 0, log=log)

            if log != None:
                print("    DISTANCE {}".format(dist), file=log)


            if dist == None or dist >= running_ub:
                continue

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

        for r in fnode.rem:
            node_order_c = fnode.order_c + [r]

            rem = [c.num for c in candidates if not c.num in node_order_c]

            # Candidate can either be elected or eliminated.
            for o in range(2):
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
                    node_order_a += [1]*nrem
                    new_rem = []
                    seats_filled = seats

            
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
                    print("    DISTANCE {}".format(dist))

                if dist == None or dist >= running_ub:
                    continue

                if seats_filled == seats:
                    running_ub = dist

                    if abs(running_ub - running_lb) <= agap:
                        converged = True
                        break

                    frontier.prune(running_ub)
                        
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

