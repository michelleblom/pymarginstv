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

        for r in len(self.order_c):
            action = "e" if self.order_a[r] == 0 else "s"
            summary += str(r) + action + " "

        summary += "with distance {}".format(self.dist)

        return summary


class Frontier:
    def __init__(self):
        self.nodes = []
        self.size = 0

    def insert(node):
        for i in range(len(self.nodes)):
            if node.dist < self.nodes[i].dist:
                self.nodes.insert(i, node)
                return

        self.nodes.append(node)
        self.size += 1 

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

        


def treestv(ballots, candidates, winners, order_c, order_a, upperbound, \
    seats, agap=1, log=None):

    frontier = Frontier()

    running_ub = upperbound
    running_lb = 0

    logf = open(log, 'w') if log != None else None

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
            dist = stvdistance(candidates, ballots, node_order_c, \
                node_order_a, rem, node_winners, log=logf)

            if dist >= running_ub:
                continue

            newn = TreeNode(node_order_c,node_order_a,node_winners,rem,dist)

            frontier.insert(newn)

    if logf != None:
        print(frontier, file=logf)

    converged = False

    while frontier.size() > 0:
        running_lb = min([n.dist for n in frontier.nodes])

        if abs(running_ub - running_lb) <= agap:
            converged = True
            break

        # Expand node with smallest assigned distance (first in frontier)
        fnode = frontier.pop(0)

        if logf != None:
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

                dist = stvdistance(candidates, ballots, node_order_c, \
                    node_order_a, rem, node_winners, log=logf)

                if dist >= running_ub:
                    continue

                # Have we filled all seats?
                seats_filled = sum(node_order_a)

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

        if logf != None:
            print(frontier, file=logf)


    if converged:            
        if logf != None:
            print("MARGIN COMPUTATION CONVERGED: {}--{}.".format(\
                running_lb, running_ub), file=logf)
            

    return running_lb, running_ub

