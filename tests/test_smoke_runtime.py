"""Functional smoke tests for previously-crashing runtime paths.

Each of these paths referenced a name that was dropped during the package
split (`random` in combat rendering, `math` in night searchlights/flares,
the `hotp_*` AI helpers in wingman logic, `SAVE_FILE` in campaign save/load,
`Campaign`/`HUD_RED` in the campaign screen). The unit tests never ran the
game loop, so the crashes stayed latent. These drive the real objects and
functions so a regression surfaces immediately.
"""
import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402
from hellcats.bootstrap import init  # noqa: E402

init(pick_area=False)

from hellcats.aircraft import F6F_Hellcat, SBD_Dauntless  # noqa: E402
from hellcats.targets import EnemyAircraft, GroundTarget  # noqa: E402
from hellcats.friendly import FriendlyAircraft, FriendlyCarrier  # noqa: E402
from hellcats.time_of_day import TimeOfDay  # noqa: E402
from hellcats.radio import RadioChatter  # noqa: E402
from hellcats.missions import Campaign, draw_campaign_status  # noqa: E402
from hellcats.disasters import AirFrance447, create_disaster_aircraft  # noqa: E402
from hellcats.dossier import PilotDossier  # noqa: E402
from hellcats.bootstrap import satellite_map  # noqa: E402
from hellcats.render_game import (  # noqa: E402
    draw_enemy_aircraft_3d, draw_wingmen_3d,
    draw_aircraft_symbol, draw_chase_view,
)


class TestRuntimeSmoke(unittest.TestCase):
    def setUp(self):
        self.surface = pygame.Surface((1280, 900))
        self.player = F6F_Hellcat()
        self.player.x, self.player.y, self.player.z = 0.0, 0.0, 5000.0
        self.player.heading = 0.0

    def test_render_smoking_enemy_uses_random(self):
        """draw_enemy_aircraft_3d smoke trail references random.randint."""
        enemy = EnemyAircraft(0.0, 9000.0, 5000.0, variant="fighter")
        enemy.smoke_trail = True
        enemy.alive = True
        # Should draw without NameError on `random`.
        draw_enemy_aircraft_3d(self.surface, enemy, self.player, 640, 450)

    def test_wingman_ai_update_uses_hotp_helpers(self):
        """FriendlyAircraft AI steering references hotp_delta_smooth/aero_lookup."""
        wingman = FriendlyAircraft(self.player, offset_side=1)
        enemy = EnemyAircraft(500.0, 4000.0, 5000.0, variant="fighter")
        for _ in range(30):
            wingman.update(1 / 60, self.player, [enemy])
        draw_wingmen_3d(self.surface, [wingman], self.player)

    def test_enemy_ai_update_fighter(self):
        enemy = EnemyAircraft(200.0, 3000.0, 5200.0, variant="fighter")
        carrier = FriendlyCarrier(0, -5000, heading=0)
        for _ in range(30):
            enemy.update(1 / 60, self.player, carrier)

    def test_enemy_ai_update_bomber(self):
        """The G4M Betty (bomber variant) AI references _half_toward_zero."""
        bomber = EnemyAircraft(500.0, 3000.0, 5000.0, variant="bomber")
        carrier = FriendlyCarrier(0, -5000, heading=0)
        for _ in range(60):
            bomber.update(1 / 60, self.player, carrier)

    def test_aircraft_symbol_non_boeing(self):
        """draw_aircraft_symbol / draw_chase_view formerly hit isinstance(None).

        Every non-Boeing airframe (Hellcat, Corsair, SBD) crashed with
        TypeError because `DisasterAircraft` resolved to None inside the
        isinstance tuple. Exercise both a fighter and a dive bomber.
        """
        for ac in (self.player, SBD_Dauntless()):
            draw_aircraft_symbol(self.surface, ac)
            draw_chase_view(self.surface, ac, satellite_map, 0.0)

    def test_aircraft_symbol_airliner(self):
        """The airliner rendering path still resolves after the isinstance fix."""
        disaster_ac = create_disaster_aircraft(AirFrance447())
        draw_aircraft_symbol(self.surface, disaster_ac)
        draw_chase_view(self.surface, disaster_ac, satellite_map, 0.0)

    def test_night_searchlights_and_flares_use_math(self):
        """draw_searchlights / draw_flares reference math.sqrt/radians/cos/sin."""
        tod = TimeOfDay(TimeOfDay.NIGHT)
        low = F6F_Hellcat()
        low.x, low.y, low.z, low.heading = 0.0, 0.0, 800.0, 0.0
        aa = GroundTarget(0.0, 6000.0, "aa_gun")
        aa.alive = True
        tod.draw_searchlights(self.surface, [aa], low)
        tod.drop_flare(0.0, 4000.0, 1000.0)
        tod.update(1 / 60)
        tod.draw_flares(self.surface, low)

    def test_radio_update_uses_math(self):
        radio = RadioChatter()
        carrier = FriendlyCarrier(0, -5000, heading=0)
        radio.check_context(self.player, None, carrier, [], None)
        radio.update(1 / 60)

    def test_campaign_save_load_uses_save_file(self):
        campaign = Campaign()
        campaign.start()
        campaign.save_aircraft_state(self.player)
        campaign.save()
        reloaded = Campaign()
        reloaded.load()  # touches SAVE_FILE on read path

    def test_campaign_status_screen(self):
        """draw_campaign_status references Campaign.MISSION_ORDER and HUD_RED."""
        campaign = Campaign()
        campaign.start()
        draw_campaign_status(self.surface, campaign, PilotDossier())

    def test_eastern401_descent_is_gentle(self):
        """Eastern 401 should slowly descend, not spiral into an accelerating dive."""
        from hellcats.disasters import Eastern401, create_disaster_aircraft

        class _NoKeys:
            def __getitem__(self, k):
                return False

        scenario = Eastern401()
        ac = create_disaster_aircraft(scenario)
        for _ in range(int(scenario.TRIGGER_TIME * 60) + 5):
            ac.update(1 / 60, _NoKeys())
        worst_fpm = 0.0
        for _ in range(int(10 * 60)):  # 10 s of drift
            ac.update(1 / 60, _NoKeys())
            worst_fpm = min(worst_fpm, ac.vz * 60)
        self.assertTrue(ac._autopilot_drift)
        self.assertLess(ac.vz, 0, "should be descending")
        # Bounded sink rate — the old bug accelerated past -7000 fpm in seconds.
        self.assertGreater(worst_fpm, -1200, f"descent too steep: {worst_fpm:.0f} fpm")

    def test_af447_airspeed_offset_bounded(self):
        """AF447 unreliable-airspeed offset drifts within bounds, not per-frame noise."""
        from hellcats.disasters import AirFrance447, create_disaster_aircraft

        class _NoKeys:
            def __getitem__(self, k):
                return False

        scenario = AirFrance447()
        ac = create_disaster_aircraft(scenario)
        for _ in range(int(scenario.TRIGGER_TIME * 60) + 5):
            ac.update(1 / 60, _NoKeys())
        prev = getattr(ac, "_display_airspeed_offset", 0.0)
        max_step = 0.0
        for _ in range(300):
            scenario.apply_effects(ac)
            cur = ac._display_airspeed_offset
            self.assertGreaterEqual(cur, -60.0)
            self.assertLessEqual(cur, 40.0)
            max_step = max(max_step, abs(cur - prev))
            prev = cur
        # Smooth drift: each step is small, not a full-range resample.
        self.assertLessEqual(max_step, 8.0, f"offset jumped {max_step:.1f} in one frame")


if __name__ == "__main__":
    unittest.main()
