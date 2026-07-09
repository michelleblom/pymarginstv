import copy
import unittest
from dataclasses import dataclass
from stvtree import calc_tallies, compute_elim_quota_lb_new
from utils import Ballot, Candidate

class TestCalcTallies(unittest.TestCase):
    epsilon = 0.000001

    def compareFloat(self, value, target):
        self.assertTrue(abs(value-target) <= TestCalcTallies.epsilon)

    """
    calc_tallies: This function calculates the contribution of ballot b to candidate c if that candidate is to 
    be seated or eliminated in the next round. 

    Parameters:
    b (Ballot): The ballot type for which the value bounds are being calculated.
    gone (list): A list of candidates that have been eliminated or seated.
    transfer (dict): A dictionary mapping candidates to their transfer values.
    winners (list): A list of candidates that have won, must be contained in gone
    order_q (dict): A dictionary mapping winning candidates to the first round in which they 
                    have a quota at the start of that round.

    Returns:
    tuple: A tuple containing the seating-based ballot value and elimination-based ballot value 

    """
    def testSanityCheck1(self):
        b = Ballot(0, 5, [5,3,0,2,1,4,6], 7)
        # Check ballot value at each point
        v, m = calc_tallies(b, [], {}, [5,3,1,4,6],  {5: 0, 3: 1, 1: 4, 4: 5, 6: 6})
        self.assertEqual(v, 5)
        self.assertEqual(m, -1)

    def testSinglePreferenceBallotSeated1(self):
        b = Ballot(0, 5, [5], 7)
        gone = []
        transfer = {}
        winners = [5,3,1,4,6]
        
        order_q = {5: 0, 3: 1, 1: 4, 4: 5, 6: 6}

        transfer[5] = 0.6
        gone.append(5)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 3)
        self.assertEqual(m, 0)

        transfer[3] = 0.3
        gone.append(3)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 3)
        self.assertEqual(m, 0)

        gone.append(0)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.assertEqual(v, 3)
        self.assertEqual(m, 0)

        gone.append(2)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 3)
        self.assertEqual(m, 0)

        transfer[1] = 0.12
        gone.append(1)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 3)
        self.assertEqual(m, 0)

        transfer[4] = 0.05
        gone.append(4)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 3)
        self.assertEqual(m, 0)

    def testSinglePreferenceBallotSeated2(self):
        b = Ballot(0, 5, [3], 7)
        gone = []
        transfer = {}
        winners = [5,3,1,4,6]
        
        order_q = {5: 0, 3: 1, 1: 4, 4: 5, 6: 6}

        transfer[5] = 0.6
        gone.append(5)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 5)
        self.assertEqual(m, -1)

        transfer[3] = 0.3
        gone.append(3)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 1.5)
        self.assertEqual(m, 1)

        gone.append(0)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 1.5)
        self.assertEqual(m, 1)

        gone.append(2)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 1.5)
        self.assertEqual(m, 1)

        transfer[1] = 0.12
        gone.append(1)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 1.5)
        self.assertEqual(m, 1)

        transfer[4] = 0.05
        gone.append(4)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 1.5)
        self.assertEqual(m, 1)   

    def testSinglePreferenceBallotEliminated1(self):
        b = Ballot(0, 5, [2], 7)
        gone = []
        transfer = {}
        winners = [5,3,1,4,6]
        
        order_q = {5: 0, 3: 1, 1: 4, 4: 5, 6: 6}

        transfer[5] = 0.6
        gone.append(5)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 5)
        self.assertEqual(m, -1)

        transfer[3] = 0.3
        gone.append(3)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 5)
        self.assertEqual(m, -1)

        gone.append(0)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 5)
        self.assertEqual(m, -1)

        gone.append(2)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 5)
        self.assertEqual(m, 3)

        transfer[1] = 0.12
        gone.append(1)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 5)
        self.assertEqual(m, 3)

        transfer[4] = 0.05
        gone.append(4)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 5)
        self.assertEqual(m, 3)  

    def testSinglePreferenceBallotEliminated2(self):
        b = Ballot(0, 5, [2], 7)
        gone = []
        transfer = {}
        winners = [3,1,4,6]
        
        order_q = {3: 1, 1: 4, 4: 5, 6: 6}

        gone.append(2)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 5)
        self.assertEqual(m, 0)

        transfer[3] = 0.3
        gone.append(3)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 5)
        self.assertEqual(m, 0)

    def testBallotPreferencesNotInGone(self):
        b = Ballot(0, 5, [2,7,5], 8)
        gone = []
        transfer = {}
        winners = [3,1,4]
        
        order_q = {3: 0, 1: 2, 4: 3}

        transfer[3] = 0.3
        gone.append(3)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 5)
        self.assertEqual(m, -1)

        gone.append(0)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 5)
        self.assertEqual(m, -1)

        transfer[1] = 0.12
        gone.append(1)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 5)
        self.assertEqual(m, -1)

        transfer[4] = 0.05
        gone.append(4)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 5)
        self.assertEqual(m, -1)

        gone.append(6)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 5)
        self.assertEqual(m, -1)


    def testNoskips1(self):
        b = Ballot(0, 1, [5,3,0,2,1,4,6], 7)
        gone = []
        transfer = {}
        winners = [5,3,1,4,6]
        
        order_q = {5: 0, 3: 1, 1: 4, 4: 5, 6: 6}

        # Check ballot value at each point
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.assertEqual(v, 1)
        self.assertEqual(m, -1)

        transfer[5] = 0.6
        gone.append(5)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 0.6)
        self.assertEqual(m, 0)

        transfer[3] = 0.3
        gone.append(3)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 0.18)
        self.assertEqual(m, 1)

        gone.append(0)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.assertEqual(v, 0.18)
        self.assertEqual(m, 2)

        gone.append(2)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 0.18)
        self.assertEqual(m, 3)

        transfer[1] = 0.12
        gone.append(1)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 0.0216)
        self.assertEqual(m, 4)

        transfer[4] = 0.05
        gone.append(4)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 0.00108)
        self.assertEqual(m, 5)

    def testNoskips2(self):
        b = Ballot(0, 1, [3,5,2,1], 7)
        gone = []
        transfer = {}
        winners = [5,3,1,4,6]
        
        order_q = {5: 0, 3: 1, 1: 4, 4: 5, 6: 6}

        # Check ballot value at each point
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.assertEqual(v, 1)
        self.assertEqual(m, -1)

        transfer[5] = 0.6
        gone.append(5)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.assertEqual(v, 1)
        self.assertEqual(m, -1)

        transfer[3] = 0.3
        gone.append(3)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 0.3)
        self.assertEqual(m, 1)

        gone.append(0)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.assertEqual(v, 0.3)
        self.assertEqual(m, 1)

        gone.append(2)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 0.3)
        self.assertEqual(m, 3)

        transfer[1] = 0.12
        gone.append(1)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 0.036)
        self.assertEqual(m, 4)

        transfer[4] = 0.05
        gone.append(4)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 0.036)
        self.assertEqual(m, 4)

    def testSkips1(self):
        b = Ballot(0, 1, [5,3,0,2,1,4,6], 7)
        gone = []
        transfer = {}
        winners = [5,3,1,4,6]
        
        order_q = {5: 0, 3: 0, 1: 4, 4: 5, 6: 6}

        # Check ballot value at each point
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.assertEqual(v, 1)
        self.assertEqual(m, -1)

        transfer[5] = 0.6
        gone.append(5)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 0.6)
        self.assertEqual(m, 0)

        transfer[3] = 0.3
        gone.append(3)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 0.6)
        self.assertEqual(m, 0)

        gone.append(0)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.assertEqual(v, 0.6)
        self.assertEqual(m, 2)

        gone.append(2)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 0.6)
        self.assertEqual(m, 3)

        transfer[1] = 0.12
        gone.append(1)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 0.072)
        self.assertEqual(m, 4)

        transfer[4] = 0.05
        gone.append(4)
        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 0.0036)
        self.assertEqual(m, 5)

    # ---- Elimination-only paths ----

    def testEliminationsOnly(self):
        # With no winners involved, the ballot value never changes; only the
        # round of the last move advances as the ballot walks down its prefs.
        b = Ballot(0, 1, [0,2,4], 7)

        v, m = calc_tallies(b, [0], {}, [], {})
        self.assertEqual(v, 1)
        self.assertEqual(m, 0)

        v, m = calc_tallies(b, [0,2], {}, [], {})
        self.assertEqual(v, 1)
        self.assertEqual(m, 1)

        v, m = calc_tallies(b, [0,2,4], {}, [], {})
        self.assertEqual(v, 1)
        self.assertEqual(m, 2)

        # Eliminations of candidates the ballot never reaches leave it untouched
        v, m = calc_tallies(b, [1,3], {}, [], {})
        self.assertEqual(v, 1)
        self.assertEqual(m, -1)

    def testSkipThroughEarlierElimination(self):
        # The ballot moves off 2 (eliminated in round 1) and skips over 0, which
        # was eliminated in round 0 before the ballot reached it. Skipping through
        # an already-eliminated candidate does not advance move_r.
        b = Ballot(0, 1, [2,0,1], 7)

        v, m = calc_tallies(b, [0,2], {}, [], {})
        self.assertEqual(v, 1)
        self.assertEqual(m, 1)

        # A later unrelated elimination still leaves move_r at 1
        v, m = calc_tallies(b, [0,2,3], {}, [], {})
        self.assertEqual(v, 1)
        self.assertEqual(m, 1)

    # ---- Transfer value ranges ----

    def testTransferZero(self):
        # A candidate seated exactly at quota has transfer 0: the ballot value
        # becomes 0 and stays 0 through later transfers.
        b = Ballot(0, 1, [5,3,1], 7)
        winners = [5,3]
        order_q = {5: 0, 3: 1}
        transfer = {5: 0}

        v, m = calc_tallies(b, [5], transfer, winners, order_q)
        self.assertEqual(v, 0)
        self.assertEqual(m, 0)

        transfer[3] = 0.5
        v, m = calc_tallies(b, [5,3], transfer, winners, order_q)
        self.assertEqual(v, 0)
        self.assertEqual(m, 1)

    def testTransferNearOne(self):
        b = Ballot(0, 250, [4,2], 7)
        v, m = calc_tallies(b, [4], {4: 0.999}, [4], {4: 0})
        self.compareFloat(v, 249.75)
        self.assertEqual(m, 0)

    # ---- Quota-skip branch ----

    def testQuotaSkipBoundary(self):
        # The skip applies iff order_q[bp] <= move_r. Same ballot and history,
        # order_q on either side of the boundary.
        b = Ballot(0, 1, [5,3,0], 7)
        winners = [5,3]
        transfer = {5: 0.6, 3: 0.5}
        gone = [5,3]

        # 3 first had a quota in round 1, but the ballot last moved in round 0:
        # no skip, value reduced
        v, m = calc_tallies(b, gone, transfer, winners, {5: 0, 3: 1})
        self.compareFloat(v, 0.3)
        self.assertEqual(m, 1)

        # 3 already had a quota in round 0, when the ballot moved: skip,
        # no reduction, move_r unchanged
        v, m = calc_tallies(b, gone, transfer, winners, {5: 0, 3: 0})
        self.compareFloat(v, 0.6)
        self.assertEqual(m, 0)


    def testConsecutiveQuotaSkips(self):
        # The ballot hops over two already-quota'd winners (3 and 4) with no
        # value loss, then transfers through 1 with reduction.
        b = Ballot(0, 1, [5,3,4,1], 7)
        winners = [5,3,4,1]
        order_q = {5: 0, 3: 0, 4: 0, 1: 3}
        transfer = {5: 0.6, 3: 0.9, 4: 0.9, 1: 0.5}

        v, m = calc_tallies(b, [5,3,4,1], transfer, winners, order_q)
        self.compareFloat(v, 0.3) # 0.6 * 0.5
        self.assertEqual(m, 3)

    def testNoQuotaSkipOnFirstPreference(self):
        # A first preference is never quota-skipped, even with a quota from
        # round 0: the ballot transfers through 3 with reduction.
        b = Ballot(0, 1, [3,1], 7)
        winners = [5,3]
        order_q = {5: 0, 3: 0}
        transfer = {5: 0.6, 3: 0.5}

        v, m = calc_tallies(b, [5,3], transfer, winners, order_q)
        self.compareFloat(v, 0.5)
        self.assertEqual(m, 1)

    # ---- Seated before reached ----

    def testSeatedBeforeReached(self):
        # Winner 0 is seated in round 0, before the ballot leaves its first
        # preference. When the ballot reaches 0 mid-prefs it is skipped with no
        # reduction (0's transfer must not apply) and no move_r update.
        b = Ballot(0, 1, [3,0,4], 7)
        winners = [0,4]
        order_q = {0: 0, 4: 2}
        transfer = {0: 0.5, 4: 0.5}

        v, m = calc_tallies(b, [0,3], transfer, winners, order_q)
        self.assertEqual(v, 1)
        self.assertEqual(m, 1)

        # Ballot then lands on 4 (quota from round 2 > move_r of 1, so no skip)
        v, m = calc_tallies(b, [0,3,4], transfer, winners, order_q)
        self.compareFloat(v, 0.5)
        self.assertEqual(m, 2)

    # ---- Termination / exhaustion ----

    def testBallotExhaustedBeforeGoneEnds(self):
        # Once every preference is consumed, later rounds cannot change the result
        b = Ballot(0, 1, [3,5], 7)
        winners = [5]
        order_q = {5: 1}
        transfer = {5: 0.5}

        v, m = calc_tallies(b, [3,5], transfer, winners, order_q)
        self.compareFloat(v, 0.5)
        self.assertEqual(m, 1)

        v, m = calc_tallies(b, [3,5,0,2], transfer, winners, order_q)
        self.compareFloat(v, 0.5)
        self.assertEqual(m, 1)

    def testBallotExhaustedByEliminations(self):
        # A ballot whose every preference is eliminated keeps its full value;
        # detecting exhaustion is the caller's concern
        b = Ballot(0, 1, [3,0], 7)
        v, m = calc_tallies(b, [3,0,2], {}, [], {})
        self.assertEqual(v, 1)
        self.assertEqual(m, 1)

    def testGoneExhaustedBeforeBallot(self):
        b = Ballot(0, 1, [0,1,2,3,4], 7)
        v, m = calc_tallies(b, [0], {}, [], {})
        self.assertEqual(v, 1)
        self.assertEqual(m, 0)

    # ---- Non-mutation ----

    def testInputsNotMutated(self):
        # A scenario exercising every branch (seating, elimination, quota-skip,
        # seated-before-reached) must leave all inputs untouched
        b = Ballot(0, 1, [5,0,3,1], 7)
        gone = [5,0,3,1]
        winners = [5,3,1]
        order_q = {5: 0, 3: 0, 1: 3}
        transfer = {5: 0.6, 3: 0.5, 1: 0.4}

        prefs_copy = copy.deepcopy(b.prefs)
        gone_copy = copy.deepcopy(gone)
        winners_copy = copy.deepcopy(winners)
        order_q_copy = copy.deepcopy(order_q)
        transfer_copy = copy.deepcopy(transfer)

        v, m = calc_tallies(b, gone, transfer, winners, order_q)
        self.compareFloat(v, 0.24)
        self.assertEqual(m, 3)

        self.assertEqual(b.prefs, prefs_copy)
        self.assertEqual(b.votes, 1)
        self.assertEqual(gone, gone_copy)
        self.assertEqual(winners, winners_copy)
        self.assertEqual(order_q, order_q_copy)
        self.assertEqual(transfer, transfer_copy)


@dataclass
class Election:
    candidates : list[Candidate]
    ballots : list[Ballot]
    order_c : list[int]
    order_a : list[int]
    quota : int
    order_q : dict[int,int]


class TestElimQuotaLBNew(unittest.TestCase):

    def createTestElectionPaperExample(self):
        candidates = []
        ballots = []

        # create candidates
        for i in range(5):
            c = Candidate(i, i);
            candidates.append(c)

        # create ballots
        b0 = Ballot(0, 250, [0], 5)
        ballots.append(b0)
        candidates[0].fp_votes += 250

        b1 = Ballot(1, 120, [1, 0, 2], 5)
        ballots.append(b1)
        candidates[1].fp_votes += 120

        b2 = Ballot(2, 400, [2,3], 5)
        ballots.append(b2)
        candidates[2].fp_votes += 400

        b3 = Ballot(3, 350, [4], 5)
        ballots.append(b3)
        candidates[4].fp_votes += 350

        b4 = Ballot(4, 110, [2,3,4], 5)
        ballots.append(b4)
        candidates[2].fp_votes += 110;

        order_c = [2,4,1,0,3]
        order_a = [1,1,0,1,0]
        quota = 308
        order_q = {2:0, 4:0, 0:3}

        return Election(candidates, ballots, order_c, order_a, quota, order_q)
    

    def test_PaperExample_ReportedOrder(self):
        e = self.createTestElectionPaperExample()

        lb, _ = compute_elim_quota_lb_new(e.candidates, e.ballots, e.order_c, e.order_a, e.quota, e.order_q)

        self.assertEqual(lb, 0)  

    def test_PaperExample_CF_Original1(self):
        e = self.createTestElectionPaperExample()

        lb, _ = compute_elim_quota_lb_new(e.candidates, e.ballots, [2,0], [1,0], e.quota, {2:0})

        self.assertEqual(lb, 65) 

    def test_PaperExample_CF_Original2(self):
        e = self.createTestElectionPaperExample()

        lb, _ = compute_elim_quota_lb_new(e.candidates, e.ballots, [2,1], [1,1], e.quota, {2:0, 1:1})

        self.assertEqual(lb, 188) 


    def test_PaperExample_CF_Original3(self):
        e = self.createTestElectionPaperExample()

        lb, _ = compute_elim_quota_lb_new(e.candidates, e.ballots, [2,3], [1,0], e.quota, {2:0})

        self.assertEqual(lb, 41)     

    def test_PaperExample_CF_Original4(self):
        e = self.createTestElectionPaperExample()

        lb, _ = compute_elim_quota_lb_new(e.candidates, e.ballots, [2,3], [1,1], e.quota, {2:0,3:1})

        self.assertEqual(lb, 106)   

    def test_PaperExample_CF_Original4(self):
        e = self.createTestElectionPaperExample()

        lb, _ = compute_elim_quota_lb_new(e.candidates, e.ballots, [2,4], [1,0], e.quota, {2:0})

        self.assertEqual(lb, 115)           

    def test_PaperExample_CF_Original5(self):
        e = self.createTestElectionPaperExample()

        lb, _ = compute_elim_quota_lb_new(e.candidates, e.ballots, [2,4], [1,1], e.quota, {2:0,4:1})

        self.assertEqual(lb, 0) 

    def test_PaperExample_CF_Original6(self):
        e = self.createTestElectionPaperExample()

        lb, _ = compute_elim_quota_lb_new(e.candidates, e.ballots, [2,4,0], [1,1,0], e.quota, {2:0,4:1})

        self.assertEqual(lb, 65)

    def test_PaperExample_CF_Original7(self):
        e = self.createTestElectionPaperExample()

        lb, _ = compute_elim_quota_lb_new(e.candidates, e.ballots, [2,4,1,0,3], [1,1,1,0,0], e.quota, {2:0,4:0,1:2})

        # This was one example where the result differed from what the original code gave (which was 
        # 84 votes). However, the correct answer is 188 votes.

        self.assertEqual(lb, 188)

    def test_PaperExample_CF_Original8(self):
        e = self.createTestElectionPaperExample()

        lb, _ = compute_elim_quota_lb_new(e.candidates, e.ballots, [2,4,3], [1,1,0], e.quota, {2:0,4:1})

        self.assertEqual(lb, 41)    

    def test_PaperExample_CF_Original9(self):
        e = self.createTestElectionPaperExample()

        lb, _ = compute_elim_quota_lb_new(e.candidates, e.ballots, [2,4,3,0,1], [1,1,1,0,0], e.quota, {2:0,4:1,3:2})

        self.assertEqual(lb, 106)  

    def test_PaperExample_CF_Original9(self):
        e = self.createTestElectionPaperExample()

        lb, _ = compute_elim_quota_lb_new(e.candidates, e.ballots, [2,4,1], [1,1,0], e.quota, {2:0,4:1})

        self.assertEqual(lb, 0)   

    def test_PaperExample_CF_Original10(self):
        e = self.createTestElectionPaperExample()

        lb, _ = compute_elim_quota_lb_new(e.candidates, e.ballots, [0], [0], e.quota, {})

        self.assertEqual(lb, 125)   

    def test_PaperExample_CF_Original11(self):
        e = self.createTestElectionPaperExample()

        lb, _ = compute_elim_quota_lb_new(e.candidates, e.ballots, [0], [1], e.quota, {0:0})

        self.assertEqual(lb, 130)                                        

    def test_PaperExample_CF_Original11(self):
        e = self.createTestElectionPaperExample()

        lb, _ = compute_elim_quota_lb_new(e.candidates, e.ballots, [1], [0], e.quota, {})

        self.assertEqual(lb, 60)   

    def test_PaperExample_CF_Original12(self):
        e = self.createTestElectionPaperExample()

        lb, _ = compute_elim_quota_lb_new(e.candidates, e.ballots, [1], [1], e.quota, {1:0})

        self.assertEqual(lb, 195)   

    def test_PaperExample_CF_Original13(self):
        e = self.createTestElectionPaperExample()

        lb, _ = compute_elim_quota_lb_new(e.candidates, e.ballots, [2], [0], e.quota, {})

        self.assertEqual(lb, 255)           

    def test_PaperExample_CF_Original14(self):
        e = self.createTestElectionPaperExample()

        lb, _ = compute_elim_quota_lb_new(e.candidates, e.ballots, [2], [1], e.quota, {2:0})

        self.assertEqual(lb, 0)  

    def test_PaperExample_CF_Original15(self):
        e = self.createTestElectionPaperExample()

        lb, _ = compute_elim_quota_lb_new(e.candidates, e.ballots, [3], [0], e.quota, {})

        self.assertEqual(lb, 0)          

    def test_PaperExample_CF_Original16(self):
        e = self.createTestElectionPaperExample()

        lb, _ = compute_elim_quota_lb_new(e.candidates, e.ballots, [3], [1], e.quota, {3:0})

        self.assertEqual(lb, 308)  

    def test_PaperExample_CF_Original17(self):
        e = self.createTestElectionPaperExample()

        lb, _ = compute_elim_quota_lb_new(e.candidates, e.ballots, [4], [0], e.quota, {})

        self.assertEqual(lb, 175)  

    def test_PaperExample_CF_Original18(self):
        e = self.createTestElectionPaperExample()

        lb, _ = compute_elim_quota_lb_new(e.candidates, e.ballots, [4], [1], e.quota, {4:0})

        self.assertEqual(lb, 80)  

    def test_PaperExample_QuotaVariation(self):
        e = self.createTestElectionPaperExample();

        # EVALUATED [2, 3]/[1, 1]/{2: 0, 3: 1} LB 106 (D 0 EQ 106)
        # EVALUATED [2, 3]/[1, 1]/{2: 0, 3: 0} LB 308 (D 0 EQ 308)

        lb, _ = compute_elim_quota_lb_new(e.candidates, e.ballots, [2,3], [1,1], e.quota, {2:0, 3:1})

        self.assertEqual(lb, 106)

        # The next lower bound is higher because in this case '3' does not get any transferred votes from
        # '2' and remains on 0 votes in the second round (meaning that they need to make up an entire quota)
        lb, _ = compute_elim_quota_lb_new(e.candidates, e.ballots, [2,3], [1,1], e.quota, {2:0, 3:0})

        self.assertEqual(lb, 308)

if __name__ == '__main__':
    unittest.main()