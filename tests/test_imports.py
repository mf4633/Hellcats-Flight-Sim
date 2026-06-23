"""Smoke tests for package structure."""
import unittest


class TestImports(unittest.TestCase):
    def test_bootstrap_and_modules(self):
        from hellcats.bootstrap import init
        init(pick_area=False)
        from hellcats.aircraft import F6F_Hellcat, F4U_Corsair, SBD_Dauntless, Boeing747_200
        from hellcats.missions import (
            MISSIONS, MissionCoralSea, MissionMidwayCAP,
            MissionMidwayDive, MissionCarrierQual,
        )
        from hellcats.disasters import DISASTER_SCENARIOS
        from hellcats.carrier_ops import LandingScorer
        from hellcats.sound import SoundManager
        self.assertEqual(len(MISSIONS), 12)
        self.assertEqual(len(DISASTER_SCENARIOS), 4)
        self.assertTrue(issubclass(SBD_Dauntless, F6F_Hellcat))
        self.assertIn(MissionCoralSea, MISSIONS)
        self.assertIn(MissionMidwayCAP, MISSIONS)
        self.assertIn(MissionMidwayDive, MISSIONS)
        self.assertIn(MissionCarrierQual, MISSIONS)
        self.assertEqual(SBD_Dauntless.CARRIER_IDEAL_SPEED, (95, 115))
        mgr = SoundManager()
        self.assertIn('music_menu', mgr.sounds)
        self.assertTrue(LandingScorer().grade_at_least('A', 'B'))


if __name__ == "__main__":
    unittest.main()