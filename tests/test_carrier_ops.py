"""Tests for carrier landing scorer."""
import unittest
from hellcats.carrier_ops import LandingScorer, GRADE_POINTS
from hellcats.friendly import FriendlyCarrier


class _FakeAircraft:
    NAME = "Test Aircraft"
    CARRIER_IDEAL_SPEED = (100, 120)
    CARRIER_MAX_WIRE_SPEED = 140

    def __init__(self, kts=110, vz=-8, gear=True):
        self.vx, self.vy, self.vz = kts * 1.68781, 0, vz
        self.gear_down = gear
        self.x, self.y = 0, 0

    def get_airspeed_kts(self):
        return (self.vx ** 2 + self.vy ** 2) ** 0.5 / 1.68781


class TestLandingScorer(unittest.TestCase):
    def test_perfect_trap(self):
        scorer = LandingScorer()
        carrier = FriendlyCarrier(0, 0, heading=0)
        ac = _FakeAircraft(kts=110, vz=-5)
        result = scorer.score_trap(ac, carrier, wire_num=3)
        self.assertIn(result['grade'], ('S', 'A', 'B'))
        self.assertGreater(result['points'], 0)

    def test_bolter_fails(self):
        scorer = LandingScorer()
        carrier = FriendlyCarrier(0, 0, heading=0)
        result = scorer.score_trap(_FakeAircraft(), carrier, 0, bolter=True)
        self.assertEqual(result['grade'], 'F')
        self.assertEqual(result['points'], 0)

    def test_grade_ordering(self):
        scorer = LandingScorer()
        self.assertTrue(scorer.grade_at_least('A', 'B'))
        self.assertTrue(scorer.grade_at_least('S', 'B'))
        self.assertFalse(scorer.grade_at_least('C', 'B'))


if __name__ == "__main__":
    unittest.main()