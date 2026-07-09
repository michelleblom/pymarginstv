import unittest
from stvtree import calc_tallies
from utils import Ballot

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

if __name__ == '__main__':
    unittest.main()