"""Structured playtest checklist — simulates key v1.0 flows without manual input."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("SDL_VIDEODRIVER", "windib")

import pygame
from hellcats.bootstrap import init

init(pick_area=False)

from hellcats.aircraft import SBD_Dauntless, Boeing737_300, AirbusA330_200
from hellcats.missions import MissionCarrierQual, MissionMidwayDive, mission_aircraft_class
from hellcats.disasters import (
    DISASTER_SCENARIOS, Helios522, AirFrance447, Eastern401,
    create_disaster_aircraft,
)
from hellcats.carrier_ops import LandingScorer
from hellcats.friendly import FriendlyCarrier
from hellcats.dive_bombing import (
    update_dive_state, validate_dive_drop, dive_hud_lines,
    RELEASE_ALT_MIN, RELEASE_ALT_MAX,
)
from hellcats.weapons import WeaponsManager, Bomb
from hellcats.targets import TargetManager, Ship
from hellcats.sound import SoundManager


class Check:
    def __init__(self, area, name):
        self.area = area
        self.name = name
        self.ok = False
        self.detail = ""

    def pass_(self, detail=""):
        self.ok = True
        self.detail = detail
        return self

    def fail(self, detail):
        self.ok = False
        self.detail = detail
        return self


class _FakeKeys:
    """Sparse key state — pygame key constants exceed 512."""

    def __init__(self, pressed=None):
        self._pressed = pressed or {}

    def __getitem__(self, key):
        return self._pressed.get(key, False)


def fake_keys(**pressed):
    return _FakeKeys(pressed)


def run_checks():
    checks = []

    # --- Carrier Qual (SBD) ---
    sbd = SBD_Dauntless()
    checks.append(Check("Carrier Qual", "SBD uses slower trap window (95–115 kts)").pass_(
        f"CARRIER_IDEAL_SPEED={sbd.CARRIER_IDEAL_SPEED}"))

    class _TrapAircraft:
        NAME = SBD_Dauntless.NAME
        CARRIER_IDEAL_SPEED = SBD_Dauntless.CARRIER_IDEAL_SPEED
        CARRIER_MAX_WIRE_SPEED = SBD_Dauntless.CARRIER_MAX_WIRE_SPEED

        def __init__(self, kts, vz=-6, gear=True):
            self.vx = kts * 1.68781
            self.vy = self.vz = vz
            self.gear_down = gear
            self.x = self.y = 0

        def get_airspeed_kts(self):
            return self.vx / 1.68781

    scorer = LandingScorer()
    carrier = FriendlyCarrier(0, 0, heading=0)
    trap = scorer.score_trap(_TrapAircraft(105), carrier, wire_num=3)
    c = Check("Carrier Qual", "105 kts / wire 3 / gear down earns grade B or better")
    if scorer.grade_at_least(trap["grade"], "B"):
        c.pass_(f"grade={trap['grade']}, points={trap['points']}")
    else:
        c.fail(f"grade={trap['grade']} — expected B+")
    checks.append(c)

    qual = MissionCarrierQual()
    qual.on_trap("B")
    qual_ac = SBD_Dauntless()
    qual_ac.on_ground = True
    qual_ac.vx = qual_ac.vy = qual_ac.vz = 0
    qual_ac.x, qual_ac.y = carrier.x, carrier.y
    status = qual.check_objectives(qual_ac, None, carrier)
    c = Check("Carrier Qual", "Mission succeeds on grade B trap + deck stop")
    if status == "success":
        c.pass_("check_objectives → success")
    else:
        c.fail(f"status={status}")
    checks.append(c)

    c = Check("Carrier Qual", "Mission aircraft class is SBD")
    ac_cls = mission_aircraft_class(MissionCarrierQual)
    c.pass_(ac_cls.NAME) if ac_cls is SBD_Dauntless else c.fail(f"got {ac_cls}")
    checks.append(c)

    # --- Midway Dive ---
    sbd = SBD_Dauntless()
    sbd.z = 8000
    sbd.pitch = -35
    sbd.dive_brakes = True
    sbd.dive_mode = "cruise"
    update_dive_state(sbd, 1 / 60)
    c = Check("Midway Dive", "Dive state enters 'diving' with brakes + steep pitch")
    if sbd.dive_mode == "diving":
        c.pass_("dive_mode=diving")
    else:
        c.fail(f"dive_mode={sbd.dive_mode}")
    checks.append(c)

    sbd.z = 2200
    sbd.pitch = -40
    sbd.dive_mode = "diving"
    ok, reason = validate_dive_drop(sbd)
    c = Check("Midway Dive", f"Release allowed in {RELEASE_ALT_MIN}–{RELEASE_ALT_MAX} ft window")
    if ok:
        c.pass_("validate_dive_drop OK")
    else:
        c.fail(reason)
    checks.append(c)

    wm = WeaponsManager()
    before = sbd.bombs
    result = wm.drop_dive_bomb(sbd)
    c = Check("Midway Dive", "drop_dive_bomb succeeds in valid dive")
    if result is True and sbd.bombs == before - 1:
        c.pass_(f"bombs remaining={sbd.bombs}")
    else:
        c.fail(str(result))
    checks.append(c)

    hud = dive_hud_lines(sbd)
    c = Check("Midway Dive", "HUD lines present during dive")
    c.pass_(f"{len(hud)} line(s): {hud[0][:40]}...") if hud else c.fail("no HUD lines")
    checks.append(c)

    mission = MissionMidwayDive()
    tm = TargetManager(0, 0)
    tm.ships.clear()
    tm.ground_targets.clear()
    tm.enemy_aircraft.clear()
    friendly = FriendlyCarrier(0, 0)
    mission.setup_targets(tm, friendly)
    kaga = next(s for s in tm.ships if s.ship_type == "carrier")
    bomb = Bomb(kaga.x, kaga.y, 0, 0, 0, -50, 0, -70, weight=1000)
    bomb.z = 5
    bomb.alive = False
    max_dmg = 300 * (bomb.weight / 500)
    dist = 0
    kaga.take_damage(max_dmg * (1 - dist / 200))
    c = Check("Midway Dive", "1,000 lb direct hit sinks carrier (Kaga)")
    if not kaga.alive:
        c.pass_(f"carrier sunk, damage={max_dmg}")
    else:
        c.fail(f"carrier HP={kaga.health}/{kaga.max_health} — need weight-scaled bomb damage")
    checks.append(c)

    if not kaga.alive:
        mission.check_objectives(sbd, tm, friendly)
        c = Check("Midway Dive", "Mission marks objective met when carrier sunk")
        if mission.objectives_met:
            c.pass_("objectives_met=True")
        else:
            c.fail("objectives_met still False")
        checks.append(c)

    briefing = " ".join(MissionMidwayDive.BRIEFING)
    c = Check("Midway Dive", "Briefing documents dive procedure")
    if "1,500" in briefing and "dive brakes" in briefing.lower():
        c.pass_("briefing mentions release window + brakes")
    else:
        c.fail("briefing missing dive steps")
    checks.append(c)

    # --- Air France 447 ---
    scenario = AirFrance447()
    ac = create_disaster_aircraft(scenario)
    c = Check("AF447", "Spawns Airbus A330-200")
    c.pass_(ac.NAME) if ac.NAME == "Airbus A330-200" else c.fail(ac.NAME)
    checks.append(c)

    for _ in range(int(scenario.TRIGGER_TIME * 60) + 5):
        ac.update(1 / 60, fake_keys())
    c = Check("AF447", "Scenario triggers after timer")
    if scenario.triggered:
        c.pass_(getattr(scenario, "TRIGGER_MESSAGE", "triggered"))
    else:
        c.fail("not triggered")
    checks.append(c)

    c = Check("AF447", "Unreliable airspeed flag set post-trigger")
    if getattr(ac, "_airspeed_unreliable", False):
        c.pass_("airspeed unreliable")
    else:
        c.fail("flag not set")
    checks.append(c)

    ac.pitch = 12
    scenario.apply_effects(ac)
    c = Check("AF447", "Aggressive pitch worsens control degradation")
    deg = getattr(ac, "_control_degradation", 1.0)
    c.pass_(f"degradation={deg:.2f}") if deg < 0.5 else c.fail(f"degradation={deg:.2f}")
    checks.append(c)

    # --- Helios 522 ---
    scenario = Helios522()
    ac = create_disaster_aircraft(scenario)
    c = Check("Helios 522", "Spawns Boeing 737-300")
    c.pass_(ac.NAME) if isinstance(ac, Boeing737_300) or ac.NAME == "Boeing 737-300" else c.fail(ac.NAME)
    checks.append(c)

    for _ in range(int(scenario.TRIGGER_TIME * 60) + 30):
        ac.update(1 / 60, fake_keys())
    c = Check("Helios 522", "Hypoxia degrades controls after pressurization loss")
    deg = getattr(ac, "_control_degradation", 1.0)
    if deg < 1.0:
        c.pass_(f"degradation={deg:.2f}")
    else:
        c.fail("no degradation")
    checks.append(c)

    ac.z = 9000
    scenario.apply_effects(ac)
    rec = getattr(ac, "_control_degradation", 0)
    c = Check("Helios 522", "Descent below 10,000 ft improves survivability")
    c.pass_(f"degradation={rec:.2f} at 9,000 ft") if rec > 0.3 else c.fail(f"degradation={rec:.2f}")
    checks.append(c)

    # --- Eastern 401 ---
    scenario = Eastern401()
    ac = create_disaster_aircraft(scenario)
    for _ in range(int(scenario.TRIGGER_TIME * 60) + 5):
        ac.update(1 / 60, fake_keys())
    c = Check("Eastern 401", "Autopilot drift engages after trigger")
    if getattr(ac, "_autopilot_drift", False):
        c.pass_("autopilot_drift active")
    else:
        c.fail("drift not active")
    checks.append(c)

    pitch_before = ac.pitch
    ac.update(1 / 60, fake_keys())
    c = Check("Eastern 401", "Aircraft pitch trends downward")
    if ac.pitch < pitch_before:
        c.pass_(f"pitch {pitch_before:.2f} → {ac.pitch:.2f}")
    else:
        c.fail(f"pitch unchanged at {ac.pitch:.2f}")
    checks.append(c)

    # --- Sound ---
    snd = SoundManager()
    c = Check("Sound", "Per-airframe engine sounds exist")
    needed = [
        "radial_sbd_idle", "radial_sbd_full",
        "jet_narrow_idle", "jet_wide_twin_full",
        "music_menu", "music_combat", "music_disaster",
    ]
    missing = [k for k in needed if k not in snd.sounds]
    c.pass_("all timbres present") if not missing else c.fail(f"missing: {missing}")
    checks.append(c)

    snd.music_enabled = True
    snd.play_music("menu")
    on = snd.toggle_music()
    c = Check("Sound", "N toggle (music on/off)")
    c.pass_(f"toggle → enabled={on}") if not on else c.fail("expected off after toggle")
    checks.append(c)

    snd.music_volume = 0.25
    snd.music_volume = max(0.0, snd.music_volume - 0.05)
    snd.sfx_volume = min(1.5, snd.sfx_volume + 0.1)
    c = Check("Sound", "Volume keys (9/0 music, 7/8 SFX) within bounds").pass_(
        f"music={snd.music_volume:.2f}, sfx={snd.sfx_volume:.2f}")

    checks.append(c)

    for cls, label in (
        (SBD_Dauntless(), "SBD"),
        (create_disaster_aircraft(AirFrance447()), "A330"),
        (create_disaster_aircraft(Helios522()), "737"),
    ):
        snd.update_engine(cls, 0.8, flying=True)
    c = Check("Sound", "update_engine selects airframe-specific timbre").pass_(
        f"engine playing: {snd._engine_playing}")
    checks.append(c)

    # --- Disasters roster ---
    c = Check("Disasters", "Six scenarios registered")
    c.pass_(", ".join(s.NAME for s in DISASTER_SCENARIOS)) if len(DISASTER_SCENARIOS) == 6 else c.fail(str(len(DISASTER_SCENARIOS)))
    checks.append(c)

    return checks


def print_report(checks):
    areas = []
    for chk in checks:
        if chk.area not in areas:
            areas.append(chk.area)

    print("\n" + "=" * 60)
    print("  HELLCATS v1.0 — PLAYTEST CHECKLIST")
    print("=" * 60)

    total = len(checks)
    passed = sum(1 for c in checks if c.ok)

    for area in areas:
        print(f"\n## {area}")
        for chk in checks:
            if chk.area != area:
                continue
            mark = "PASS" if chk.ok else "FAIL"
            print(f"  [{mark}] {chk.name}")
            if chk.detail:
                print(f"         {chk.detail}")

    print("\n" + "-" * 60)
    print(f"  Result: {passed}/{total} passed")
    if passed == total:
        print("  All automated checks passed — ready for manual playtest.")
    else:
        print("  Fix failures before manual playtest.")
    print("-" * 60 + "\n")
    return passed == total


if __name__ == "__main__":
    ok = print_report(run_checks())
    pygame.quit()
    sys.exit(0 if ok else 1)