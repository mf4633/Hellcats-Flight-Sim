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
        from hellcats.disasters import DISASTER_SCENARIOS, Helios522
        from hellcats.carrier_ops import LandingScorer
        from hellcats.sound import SoundManager
        self.assertEqual(len(MISSIONS), 12)
        from hellcats.disasters import create_disaster_aircraft, AirFrance447, Eastern401
        from hellcats.dive_bombing import validate_dive_drop
        self.assertEqual(len(DISASTER_SCENARIOS), 6)
        self.assertIn(AirFrance447, DISASTER_SCENARIOS)
        self.assertIn(Eastern401, DISASTER_SCENARIOS)
        sbd = SBD_Dauntless()
        sbd.dive_mode = 'cruise'
        ok, _ = validate_dive_drop(sbd)
        self.assertFalse(ok)
        ac = create_disaster_aircraft(Helios522())
        self.assertEqual(ac.NAME, "Boeing 737-300")
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