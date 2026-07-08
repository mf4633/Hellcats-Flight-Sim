"""Bomb blast-damage tests.

A fast-falling bomb used to step past the narrow `0 < z <= 10` impact window in
a single physics frame, so `weapons_mgr.update` reaped it before `check_hits`
ran and the target took no damage. Blast now keys on a detonation flag set at
surface impact, applied exactly once.
"""
import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from hellcats.bootstrap import init  # noqa: E402

init(pick_area=False)

from hellcats.weapons import WeaponsManager, Bomb  # noqa: E402
from hellcats.targets import TargetManager, Ship  # noqa: E402


def _run(vz, z0, weight=1000, frames=400):
    """Drop a bomb dead-centered on a carrier and run the real per-frame order."""
    tm = TargetManager(0, 0)
    tm.ships.clear()
    tm.ground_targets.clear()
    tm.enemy_aircraft.clear()
    ship = Ship(0, 0, "carrier")
    tm.ships.append(ship)
    hp0 = ship.health

    wm = WeaponsManager()
    wm.bombs.append(Bomb(0, 0, z0, 0, 0, vz, 0, -90, weight=weight))

    damage_frames = 0
    for _ in range(frames):
        wm.update(1 / 60)          # matches game.py: weapons update (+reap)...
        before = ship.health
        tm.check_hits(wm)          # ...then target hit-checks
        if ship.health < before:
            damage_frames += 1
    return hp0 - ship.health, damage_frames, len(wm.bombs)


class TestBombBlast(unittest.TestCase):
    def test_fast_bomb_still_damages_ship(self):
        # ~15 ft/frame — skips the old (0, 10] window entirely.
        damage, frames, left = _run(vz=-900, z0=12.0)
        self.assertGreater(damage, 0, "fast-falling bomb dealt no damage")
        self.assertEqual(frames, 1, "blast must apply exactly once")
        self.assertEqual(left, 0, "bomb should be reaped after detonation")

    def test_very_fast_bomb_still_damages_ship(self):
        damage, frames, left = _run(vz=-1800, z0=40.0)
        self.assertGreater(damage, 0)
        self.assertEqual(frames, 1)

    def test_slow_bomb_unchanged(self):
        damage, frames, _ = _run(vz=-120, z0=12.0)
        self.assertGreater(damage, 0)
        self.assertEqual(frames, 1)

    def test_dropped_from_altitude(self):
        # Realistic level/dive drop that free-falls to the surface.
        damage, frames, left = _run(vz=-400, z0=2000.0)
        self.assertGreater(damage, 0)
        self.assertEqual(frames, 1)
        self.assertEqual(left, 0)

    def test_miss_deals_no_damage(self):
        # Bomb far from the ship (outside blast radius) never damages it.
        tm = TargetManager(0, 0)
        tm.ships.clear()
        tm.ground_targets.clear()
        tm.enemy_aircraft.clear()
        ship = Ship(0, 0, "carrier")
        tm.ships.append(ship)
        hp0 = ship.health
        wm = WeaponsManager()
        wm.bombs.append(Bomb(5000, 5000, 12.0, 0, 0, -900, 0, -90, weight=1000))
        for _ in range(60):
            wm.update(1 / 60)
            tm.check_hits(wm)
        self.assertEqual(ship.health, hp0)


if __name__ == "__main__":
    unittest.main()
