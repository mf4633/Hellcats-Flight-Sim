#!/usr/bin/env python3
"""
Quick smoke-test for Hellcats Flight Simulator
"""

import sys

try:
    print("Testing Hellcats Flight Simulator...")

    # Test aircraft module
    from aircraft import Vector3, BaseAircraft, PlayerAircraft, EnemyAircraft, AircraftType, AIBehavior

    v = Vector3(1, 2, 3)
    assert abs(v.magnitude() - 3.7416573) < 0.001
    print(f"[OK] Vector3 created and magnitude correct: {v}")

    v2 = Vector3(4, 5, 6)
    v3 = v + v2
    assert v3.x == 5 and v3.y == 7 and v3.z == 9
    print("[OK] Vector3 arithmetic works")

    player = PlayerAircraft(Vector3(0, 2000, 0))
    assert player.is_player is True
    assert player.type == AircraftType.F6F_HELLCAT
    assert player.health == 100.0
    print(f"[OK] PlayerAircraft created: {player.position}")

    enemy = EnemyAircraft(AircraftType.A6M_ZERO, Vector3(1000, 2000, 1000))
    assert enemy.is_player is False
    assert enemy.type == AircraftType.A6M_ZERO
    print(f"[OK] EnemyAircraft created: {enemy.position}")

    # Test damage does NOT compound
    original_max = enemy._base_max_speed
    enemy.take_damage(40)  # health -> 60 (below 70 threshold)
    speed_after_first = enemy.max_speed
    enemy.take_damage(5)   # health -> 55
    speed_after_second = enemy.max_speed
    assert enemy.max_speed == enemy._base_max_speed * (0.7 + (55 / 70) * 0.3)
    # Verify it's calculated from base, not compounded
    assert enemy._base_max_speed == original_max
    print("[OK] Damage degradation uses base values (no compounding)")

    # Test game module
    from game import EnhancedHellcatsSimulator, Mission, Projectile, GameState, ViewMode

    print("[OK] Game module imported")

    # Test mission creation (should produce fresh instances)
    import pygame
    pygame.init()
    sim = EnhancedHellcatsSimulator()

    m1 = sim._create_mission("guadalcanal")
    assert m1 is not None
    assert len(m1.enemy_aircraft) == 4
    print(f"[OK] Guadalcanal mission created with {len(m1.enemy_aircraft)} enemies")

    m2 = sim._create_mission("guadalcanal")
    assert m2 is not m1  # Fresh instance
    assert m2.enemy_aircraft[0] is not m1.enemy_aircraft[0]  # Fresh enemies
    print("[OK] Mission factory creates fresh instances (restart bug fixed)")

    m3 = sim._create_mission("carrier_strike")
    assert m3 is not None
    print(f"[OK] Carrier Strike mission created with {len(m3.enemy_aircraft)} enemies")

    m4 = sim._create_mission("kamikaze")
    assert m4 is not None
    print(f"[OK] Kamikaze mission created with {len(m4.enemy_aircraft)} enemies")

    pygame.quit()

    print("")
    print("=" * 50)
    print("All tests passed!")
    print("Run 'python game.py' or 'python main.py' to start.")
    print("=" * 50)

except Exception as e:
    print(f"[ERROR] {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
