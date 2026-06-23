"""Smoke tests for package structure."""
import unittest


class TestImports(unittest.TestCase):
    def test_bootstrap_and_modules(self):
        from hellcats.bootstrap import init
        init(pick_area=False)
        from hellcats.aircraft import F6F_Hellcat, F4U_Corsair, SBD_Dauntless, Boeing747_200
        from hellcats.missions import MISSIONS, MissionCoralSea, MissionMidwayCAP
        from hellcats.disasters import DISASTER_SCENARIOS
        self.assertEqual(len(MISSIONS), 10)
        self.assertEqual(len(DISASTER_SCENARIOS), 4)
        self.assertTrue(issubclass(SBD_Dauntless, F6F_Hellcat))
        self.assertIn(MissionCoralSea, MISSIONS)
        self.assertIn(MissionMidwayCAP, MISSIONS)


if __name__ == "__main__":
    unittest.main()