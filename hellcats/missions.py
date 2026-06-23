"""Combat missions and campaign mode."""
import math
from hellcats.weather import Weather
from hellcats.time_of_day import TimeOfDay
from hellcats.targets import EnemyAircraft, Ship, GroundTarget
from hellcats.friendly import FriendlyBomber
from hellcats.hotp import hotp_rng
from hellcats.carrier_ops import LandingScorer
from hellcats.aircraft import F6F_Hellcat, SBD_Dauntless
from hellcats.bootstrap import (
    PHYSICS_DT, WIDTH, HEIGHT, HUD_GREEN, HUD_AMBER, HUD_RED, WHITE,
    font_title, font_large, font_med, font_small,
)
import pygame

# ============== MISSION SYSTEM ==============
class Mission:
    """Base class for combat missions"""
    NAME = "Unknown"
    BRIEFING = []
    OBJECTIVE = "Complete the mission"
    ORIGIN = "carrier"  # "carrier" or "airfield"
    START_ALT = 5000
    START_SPEED = 250
    START_HEADING = 0
    DIFFICULTY = 1  # 1-5 stars
    WEATHER = Weather.CLEAR
    TIME_OF_DAY = TimeOfDay.DAY
    CARRIER_TAKEOFF = False  # True = start on deck

    def __init__(self):
        self.status = "active"  # active, success, failed
        self.time = 0
        self.kills = {'aircraft': 0, 'ship': 0, 'ground': 0}
        self.objectives_met = False
        self.returned_to_base = False

    def setup_targets(self, target_mgr, carrier):
        """Override to customize targets for this mission"""

    def check_objectives(self, aircraft, target_mgr, carrier):
        """Override to check mission-specific objectives. Returns status string."""
        return "active"

    def get_score(self):
        return (self.kills['aircraft'] * 500 +
                self.kills['ship'] * 1000 +
                self.kills['ground'] * 100)


class MissionFlightSchool(Mission):
    NAME = "Flight School"
    DIFFICULTY = 1
    OBJECTIVE = "Practice flight skills. Land back on the carrier."
    BRIEFING = [
        "FLIGHT SCHOOL",
        "",
        "Welcome to fighter training, Ensign.",
        "Practice flying the F6F Hellcat.",
        "Get comfortable with takeoff, flight, and landing.",
        "",
        "Objective: Land back on the friendly carrier.",
        "The carrier is marked green on your radar (TAB to cycle range).",
        "",
        "Controls: W/S pitch, A/D roll, SHIFT/CTRL throttle",
        "F: flaps, G: gear, SPACE: fire weapons",
    ]
    START_ALT = 3000
    START_SPEED = 200

    def setup_targets(self, target_mgr, carrier):
        target_mgr.ships.clear()
        target_mgr.ground_targets.clear()
        target_mgr.enemy_aircraft.clear()

    def check_objectives(self, aircraft, target_mgr, carrier):
        if aircraft.on_ground and carrier.check_on_deck(aircraft.x, aircraft.y):
            v = math.sqrt(aircraft.vx**2 + aircraft.vy**2)
            if v < 15:
                self.returned_to_base = True
                return "success"
        return "active"


class MissionBombBase(Mission):
    NAME = "Bomb Base"
    DIFFICULTY = 2
    OBJECTIVE = "Bomb the enemy runway. Return to carrier."
    BRIEFING = [
        "BOMB BASE",
        "",
        "Intelligence reports an enemy airfield at bearing 045,",
        "approximately 4 miles from the carrier.",
        "",
        "Your mission: destroy the enemy runway and any",
        "ground installations. Watch for AA defenses.",
        "",
        "After completing the strike, return to the carrier",
        "for a safe landing.",
        "",
        "Loadout: 6x .50 cal, 6x HVAR rockets, 1x 500lb bomb",
    ]
    START_ALT = 5000
    START_SPEED = 250
    START_HEADING = 45

    def setup_targets(self, target_mgr, carrier):
        target_mgr.ships.clear()
        target_mgr.enemy_aircraft.clear()
        target_mgr.ground_targets.clear()
        # Enemy airfield
        base_x, base_y = 20000, 20000
        target_mgr.ground_targets.append(GroundTarget(base_x, base_y, 'hangar'))
        target_mgr.ground_targets.append(GroundTarget(base_x - 400, base_y, 'aa_gun'))
        target_mgr.ground_targets.append(GroundTarget(base_x + 400, base_y, 'aa_gun'))
        target_mgr.ground_targets.append(GroundTarget(base_x, base_y - 300, 'fuel_tank'))
        target_mgr.ground_targets.append(GroundTarget(base_x, base_y + 300, 'fuel_tank'))
        # A few patrol fighters
        target_mgr.enemy_aircraft.append(EnemyAircraft(base_x + 5000, base_y, 6000, heading=180))
        target_mgr.enemy_aircraft.append(EnemyAircraft(base_x - 3000, base_y + 5000, 5000, heading=270))

    def check_objectives(self, aircraft, target_mgr, carrier):
        # Check if hangar destroyed
        hangars_alive = sum(1 for t in target_mgr.ground_targets
                           if t.ground_type == 'hangar' and t.alive)
        if hangars_alive == 0:
            self.objectives_met = True

        if self.objectives_met and aircraft.on_ground and carrier.check_on_deck(aircraft.x, aircraft.y):
            v = math.sqrt(aircraft.vx**2 + aircraft.vy**2)
            if v < 15:
                self.returned_to_base = True
                return "success"

        return "active"


class MissionScramble(Mission):
    NAME = "Scramble"
    DIFFICULTY = 3
    OBJECTIVE = "Intercept incoming enemy bomber and escorts. Defend the carrier."
    BRIEFING = [
        "SCRAMBLE!",
        "",
        "Radar has detected incoming bogeys heading for the fleet!",
        "One enemy bomber with fighter escort, bearing 000,",
        "closing fast at 15,000 feet.",
        "",
        "You must intercept and destroy the bomber before it",
        "reaches the carrier. Destroy escorts if possible.",
        "",
        "Time is critical - you have less than 3 minutes!",
    ]
    START_ALT = 8000
    START_SPEED = 300
    START_HEADING = 0

    def setup_targets(self, target_mgr, carrier):
        target_mgr.ships.clear()
        target_mgr.ground_targets.clear()
        target_mgr.enemy_aircraft.clear()
        # Incoming bomber group from north
        bomber = EnemyAircraft(0, 60000, 12000, heading=180, variant='bomber')
        bomber.patrol_center_x = carrier.x  # Bomber flies toward carrier
        bomber.patrol_center_y = carrier.y
        target_mgr.enemy_aircraft.append(bomber)
        # Escorts
        target_mgr.enemy_aircraft.append(EnemyAircraft(2000, 62000, 11000, heading=180))
        target_mgr.enemy_aircraft.append(EnemyAircraft(-2000, 62000, 11000, heading=180))
        target_mgr.enemy_aircraft.append(EnemyAircraft(0, 64000, 13000, heading=180))

    def check_objectives(self, aircraft, target_mgr, carrier):
        # Check if bomber destroyed
        bomber_alive = any(e.alive and e.name == "G4M Betty" for e in target_mgr.enemy_aircraft)
        if not bomber_alive:
            self.objectives_met = True
            return "success"
        # Fail if bomber gets close to carrier
        for enemy in target_mgr.enemy_aircraft:
            if enemy.alive and enemy.name == "G4M Betty":
                dist = math.sqrt((enemy.x - carrier.x)**2 + (enemy.y - carrier.y)**2)
                if dist < 3000:
                    return "failed"
        return "active"


class MissionDivineWind(Mission):
    NAME = "Divine Wind"
    DIFFICULTY = 4
    OBJECTIVE = "Defend the carrier from 10 kamikaze fighters."
    BRIEFING = [
        "DIVINE WIND",
        "",
        "Spotters report two groups of five enemy suicide",
        "fighters approaching from the north.",
        "",
        "You are the only fighter in position to intercept.",
        "The carrier must not be hit.",
        "",
        "There are 10 enemy planes vs. you alone.",
        "Good luck!",
    ]
    START_ALT = 10000
    START_SPEED = 300
    START_HEADING = 0

    def setup_targets(self, target_mgr, carrier):
        target_mgr.ships.clear()
        target_mgr.ground_targets.clear()
        target_mgr.enemy_aircraft.clear()
        # Two waves of 5 kamikazes
        for i in range(5):
            x_off = (i - 2) * 1500
            target_mgr.enemy_aircraft.append(
                EnemyAircraft(x_off, 50000, 8000 + i * 500, heading=180))
        for i in range(5):
            x_off = (i - 2) * 1500
            target_mgr.enemy_aircraft.append(
                EnemyAircraft(x_off + 500, 70000, 9000 + i * 500, heading=180))

    def check_objectives(self, aircraft, target_mgr, carrier):
        enemies_alive = sum(1 for e in target_mgr.enemy_aircraft if e.alive)
        if enemies_alive == 0:
            self.objectives_met = True
            return "success"
        # Fail if any kamikaze gets within 500 ft of carrier
        for enemy in target_mgr.enemy_aircraft:
            if enemy.alive:
                dist = math.sqrt((enemy.x - carrier.x)**2 + (enemy.y - carrier.y)**2)
                if dist < 500:
                    return "failed"
        return "active"


class MissionFlatTop(Mission):
    NAME = "Flat Top"
    DIFFICULTY = 5
    OBJECTIVE = "Find and sink the enemy carrier."
    BRIEFING = [
        "FLAT TOP",
        "",
        "An enemy carrier has been spotted approximately",
        "8 miles northeast of your position.",
        "",
        "It is escorted by destroyers and has fighters",
        "on combat air patrol.",
        "",
        "Sink the carrier using bombs and rockets.",
        "Watch for heavy AA fire from the escort ships.",
        "Return to base when mission is complete.",
    ]
    START_ALT = 8000
    START_SPEED = 280
    START_HEADING = 45

    def setup_targets(self, target_mgr, carrier):
        target_mgr.ships.clear()
        target_mgr.ground_targets.clear()
        target_mgr.enemy_aircraft.clear()
        # Enemy fleet 8 nm northeast
        fleet_x, fleet_y = 40000, 40000
        target_mgr.ships.append(Ship(fleet_x, fleet_y, 'carrier', heading=225))
        target_mgr.ships.append(Ship(fleet_x - 2000, fleet_y - 3000, 'destroyer', heading=225))
        target_mgr.ships.append(Ship(fleet_x + 2000, fleet_y - 2000, 'destroyer', heading=225))
        # CAP fighters
        target_mgr.enemy_aircraft.append(EnemyAircraft(fleet_x + 3000, fleet_y, 10000, heading=0))
        target_mgr.enemy_aircraft.append(EnemyAircraft(fleet_x - 3000, fleet_y + 3000, 9000, heading=90))
        target_mgr.enemy_aircraft.append(EnemyAircraft(fleet_x, fleet_y - 5000, 8000, heading=180))

    def check_objectives(self, aircraft, target_mgr, carrier):
        carrier_alive = any(s.alive and s.ship_type == 'carrier' for s in target_mgr.ships)
        if not carrier_alive:
            self.objectives_met = True

        if self.objectives_met and aircraft.on_ground and carrier.check_on_deck(aircraft.x, aircraft.y):
            v = math.sqrt(aircraft.vx**2 + aircraft.vy**2)
            if v < 15:
                self.returned_to_base = True
                return "success"

        return "active"


class MissionBomberEscort(Mission):
    NAME = "Bomber Escort"
    DIFFICULTY = 4
    OBJECTIVE = "Escort B-17 formation to target. Protect them from interceptors."
    BRIEFING = [
        "BOMBER ESCORT",
        "",
        "Three B-17 Flying Fortresses are inbound to bomb an",
        "enemy supply depot 6 miles northeast of the carrier.",
        "",
        "Enemy fighters will attempt to intercept the formation.",
        "You must protect the bombers until they reach the target.",
        "",
        "At least ONE bomber must survive to drop its payload.",
        "Stay close to the formation — the Zeros will come fast.",
        "",
        "Loadout: 6x .50 cal, 6x HVAR rockets",
    ]
    START_ALT = 12000
    START_SPEED = 200
    START_HEADING = 45

    def __init__(self):
        super().__init__()
        self.bombers = []
        self.wave_timer = 0
        self.waves_spawned = 0
        self.max_waves = 3

    def setup_targets(self, target_mgr, carrier):
        target_mgr.ships.clear()
        target_mgr.ground_targets.clear()
        target_mgr.enemy_aircraft.clear()

        # Target is 6 nm northeast
        tgt_x, tgt_y = 30000, 30000

        # Ground target (supply depot)
        target_mgr.ground_targets.append(GroundTarget(tgt_x, tgt_y, 'hangar'))
        target_mgr.ground_targets.append(GroundTarget(tgt_x - 300, tgt_y, 'fuel_tank'))
        target_mgr.ground_targets.append(GroundTarget(tgt_x + 300, tgt_y, 'fuel_tank'))
        target_mgr.ground_targets.append(GroundTarget(tgt_x, tgt_y + 400, 'aa_gun'))

        # Spawn 3 B-17 bombers in formation, heading toward target
        bomber_start_x, bomber_start_y = 5000, 5000
        for i in range(3):
            b = FriendlyBomber(bomber_start_x + (i-1)*400, bomber_start_y - i*500,
                               12000, 45, tgt_x, tgt_y, offset_idx=i)
            self.bombers.append(b)

        # First wave of interceptors from the target direction
        target_mgr.enemy_aircraft.append(EnemyAircraft(20000, 20000, 13000, heading=225))
        target_mgr.enemy_aircraft.append(EnemyAircraft(22000, 18000, 12000, heading=225))
        self.waves_spawned = 1

    def check_objectives(self, aircraft, target_mgr, carrier):
        self.time += PHYSICS_DT

        # Update bombers
        for b in self.bombers:
            b.update(PHYSICS_DT)

        # Enemy fighters target bombers (redirect AI toward closest bomber)
        for enemy in target_mgr.enemy_aircraft:
            if enemy.alive and enemy.ai_state in ('patrol', 'intercept'):
                closest_bomber = None
                closest_dist = 999999
                for b in self.bombers:
                    if b.alive:
                        d = math.sqrt((b.x-enemy.x)**2 + (b.y-enemy.y)**2)
                        if d < closest_dist:
                            closest_dist = d
                            closest_bomber = b
                if closest_bomber and closest_dist < 30000:
                    enemy.last_known_player_x = closest_bomber.x
                    enemy.last_known_player_y = closest_bomber.y
                    enemy.last_known_player_z = closest_bomber.z

        # Enemy fire at bombers
        for enemy in target_mgr.enemy_aircraft:
            if not enemy.alive or not enemy.firing:
                continue
            for b in self.bombers:
                if not b.alive:
                    continue
                dist = math.sqrt((b.x-enemy.x)**2 + (b.y-enemy.y)**2 + (b.z-enemy.z)**2)
                if dist < enemy.GUN_MAX_RANGE:
                    hit_chance = 0.12 * PHYSICS_DT * (1000 / max(dist, 200))
                    if hotp_rng.fraction() < hit_chance:
                        b.take_damage(12)

        # Spawn new interceptor waves
        self.wave_timer += PHYSICS_DT
        if self.waves_spawned < self.max_waves and self.wave_timer > 20 * self.waves_spawned:
            # Spawn from different directions
            angles = [180, 315, 90]
            a = angles[self.waves_spawned % len(angles)]
            rad = math.radians(a)
            # Spawn near the bomber formation
            avg_bx = sum(b.x for b in self.bombers if b.alive) / max(1, sum(1 for b in self.bombers if b.alive))
            avg_by = sum(b.y for b in self.bombers if b.alive) / max(1, sum(1 for b in self.bombers if b.alive))
            for i in range(2 + self.waves_spawned):
                sx = avg_bx + math.sin(rad) * 15000 + (i-1) * 1500
                sy = avg_by + math.cos(rad) * 15000
                target_mgr.enemy_aircraft.append(
                    EnemyAircraft(sx, sy, 11000 + i*1000, heading=(a+180)%360))
            self.waves_spawned += 1

        # Check success: at least one bomber dropped its payload
        bombers_dropped = sum(1 for b in self.bombers if b.bombs_dropped)
        if bombers_dropped > 0:
            self.objectives_met = True
            return "success"

        # Check failure: all bombers destroyed
        bombers_alive = sum(1 for b in self.bombers if b.alive)
        if bombers_alive == 0:
            return "failed"

        return "active"


class MissionTorpedoRun(Mission):
    NAME = "Torpedo Run"
    DIFFICULTY = 4
    OBJECTIVE = "Torpedo the enemy transport convoy. Sink at least 2 ships."
    BRIEFING = [
        "TORPEDO RUN",
        "",
        "A Japanese supply convoy has been spotted 5 miles",
        "east of the fleet. Three transport ships escorted",
        "by two destroyers.",
        "",
        "You are armed with a Mk 13 aerial torpedo.",
        "Drop constraints: below 300 ft, under 150 kts.",
        "Make your run low and fast — the destroyers have AA.",
        "",
        "Sink at least 2 transports, then return to carrier.",
        "",
        "Loadout: 6x .50 cal, 1x Mk 13 torpedo",
        "Press 4 to select torpedo, SPACE to drop.",
    ]
    START_ALT = 3000
    START_SPEED = 200
    START_HEADING = 90
    CARRIER_TAKEOFF = True

    def __init__(self):
        super().__init__()
        self.ships_sunk = 0

    def setup_targets(self, target_mgr, carrier):
        target_mgr.ships.clear()
        target_mgr.ground_targets.clear()
        target_mgr.enemy_aircraft.clear()
        # Convoy 5 nm east — 3 transports in column, 2 destroyer escorts
        convoy_x, convoy_y = 30000, 0
        for i in range(3):
            target_mgr.ships.append(Ship(convoy_x, convoy_y + i * 2000, 'transport', heading=0))
        target_mgr.ships.append(Ship(convoy_x - 2000, convoy_y + 1000, 'destroyer', heading=0))
        target_mgr.ships.append(Ship(convoy_x + 2000, convoy_y + 3000, 'destroyer', heading=0))
        # Light air cover
        target_mgr.enemy_aircraft.append(EnemyAircraft(convoy_x + 5000, convoy_y, 8000, heading=270))

    def check_objectives(self, aircraft, target_mgr, carrier):
        # Count sunk transports
        transports_sunk = sum(1 for s in target_mgr.ships
                              if s.ship_type == 'transport' and not s.alive)
        self.ships_sunk = transports_sunk
        if transports_sunk >= 2:
            self.objectives_met = True

        if self.objectives_met and aircraft.on_ground and carrier.check_on_deck(aircraft.x, aircraft.y):
            v = math.sqrt(aircraft.vx**2 + aircraft.vy**2)
            if v < 15:
                self.returned_to_base = True
                return "success"

        return "active"

    def get_score(self):
        return (self.kills['aircraft'] * 500 +
                self.ships_sunk * 1500 +
                self.kills['ground'] * 100)


class MissionNightStrike(Mission):
    NAME = "Night Strike"
    DIFFICULTY = 5
    OBJECTIVE = "Night attack on enemy harbor. Destroy fuel depot."
    BRIEFING = [
        "NIGHT STRIKE",
        "",
        "Under cover of darkness, strike an enemy fuel depot",
        "on the coast, 6 miles northeast.",
        "",
        "AA searchlights will sweep for you. Stay low to avoid",
        "detection. Destroy the fuel tanks and return.",
        "",
        "Visibility is limited — use your instruments.",
        "Flares (press L) can illuminate the target area.",
        "",
        "Loadout: 6x .50 cal, 6x HVAR rockets, 1x 500lb bomb",
    ]
    START_ALT = 4000
    START_SPEED = 220
    START_HEADING = 45
    TIME_OF_DAY = TimeOfDay.NIGHT
    WEATHER = Weather.OVERCAST

    def setup_targets(self, target_mgr, carrier):
        target_mgr.ships.clear()
        target_mgr.ground_targets.clear()
        target_mgr.enemy_aircraft.clear()
        # Fuel depot 6 nm northeast
        depot_x, depot_y = 30000, 30000
        target_mgr.ground_targets.append(GroundTarget(depot_x, depot_y, 'fuel_tank'))
        target_mgr.ground_targets.append(GroundTarget(depot_x + 300, depot_y - 200, 'fuel_tank'))
        target_mgr.ground_targets.append(GroundTarget(depot_x - 300, depot_y + 200, 'fuel_tank'))
        target_mgr.ground_targets.append(GroundTarget(depot_x + 500, depot_y, 'hangar'))
        # AA positions with searchlights
        target_mgr.ground_targets.append(GroundTarget(depot_x - 600, depot_y - 400, 'aa_gun'))
        target_mgr.ground_targets.append(GroundTarget(depot_x + 600, depot_y + 400, 'aa_gun'))
        target_mgr.ground_targets.append(GroundTarget(depot_x, depot_y - 800, 'aa_gun'))
        # Night fighter patrol
        target_mgr.enemy_aircraft.append(EnemyAircraft(depot_x - 5000, depot_y, 6000, heading=90))

    def check_objectives(self, aircraft, target_mgr, carrier):
        fuel_alive = sum(1 for t in target_mgr.ground_targets
                         if t.ground_type == 'fuel_tank' and t.alive)
        if fuel_alive == 0:
            self.objectives_met = True

        if self.objectives_met and aircraft.on_ground and carrier.check_on_deck(aircraft.x, aircraft.y):
            v = math.sqrt(aircraft.vx**2 + aircraft.vy**2)
            if v < 15:
                self.returned_to_base = True
                return "success"

        return "active"


class MissionCoralSea(Mission):
    NAME = "Coral Sea"
    DIFFICULTY = 4
    OBJECTIVE = "Defend the task force. Stop the Japanese strike package."
    BRIEFING = [
        "CORAL SEA",
        "",
        "May 8, 1942 — the first carrier battle in history.",
        "Radar reports a Japanese strike inbound: bombers with",
        "Zero escorts, bearing 320, 12,000 feet.",
        "",
        "Protect the fleet. Shoot down the strike before it",
        "reaches the carrier group.",
        "",
        "Loadout: 6x .50 cal, 6x HVAR rockets",
    ]
    START_ALT = 10000
    START_SPEED = 280
    START_HEADING = 320
    CARRIER_TAKEOFF = True

    def setup_targets(self, target_mgr, carrier):
        target_mgr.ships.clear()
        target_mgr.ground_targets.clear()
        target_mgr.enemy_aircraft.clear()
        strike_x, strike_y = 0, 55000
        bomber = EnemyAircraft(strike_x, strike_y, 11000, heading=140, variant='bomber')
        bomber.patrol_center_x = carrier.x
        bomber.patrol_center_y = carrier.y
        target_mgr.enemy_aircraft.append(bomber)
        target_mgr.enemy_aircraft.append(EnemyAircraft(strike_x + 1800, strike_y + 2000, 12000, heading=140))
        target_mgr.enemy_aircraft.append(EnemyAircraft(strike_x - 1800, strike_y + 2000, 12000, heading=140))
        target_mgr.enemy_aircraft.append(EnemyAircraft(strike_x, strike_y + 4000, 13000, heading=140))
        target_mgr.enemy_aircraft.append(EnemyAircraft(strike_x + 2500, strike_y - 1000, 10500, heading=140))

    def check_objectives(self, aircraft, target_mgr, carrier):
        strike_alive = sum(
            1 for e in target_mgr.enemy_aircraft
            if e.alive and e.variant in ('bomber', 'fighter')
        )
        if strike_alive == 0:
            self.objectives_met = True
            return "success"
        for enemy in target_mgr.enemy_aircraft:
            if enemy.alive and enemy.variant == 'bomber':
                dist = math.sqrt((enemy.x - carrier.x)**2 + (enemy.y - carrier.y)**2)
                if dist < 4000:
                    return "failed"
        return "active"


class MissionMidwayCAP(Mission):
    NAME = "Midway CAP"
    DIFFICULTY = 5
    OBJECTIVE = "CAP over Midway. Break the first wave of the Japanese attack."
    BRIEFING = [
        "MIDWAY CAP",
        "",
        "June 4, 1942 — the turning point of the Pacific war.",
        "Pilots report a massive inbound strike: Kates, Vals,",
        "and Zero escorts at 15,000 feet.",
        "",
        "You are on combat air patrol. Destroy at least 6 enemy",
        "aircraft before the strike reaches the atoll.",
        "",
        "Fly the Hellcat or SBD in Free Flight; combat missions",
        "launch in the F6F from the carrier deck.",
    ]
    START_ALT = 12000
    START_SPEED = 300
    START_HEADING = 0
    WEATHER = Weather.CLEAR

    def __init__(self):
        super().__init__()
        self.kills_needed = 6

    def setup_targets(self, target_mgr, carrier):
        target_mgr.ships.clear()
        target_mgr.ground_targets.clear()
        target_mgr.enemy_aircraft.clear()
        target_mgr.ground_targets.append(GroundTarget(35000, 35000, 'hangar'))
        base_x, base_y = 35000, 35000
        for i in range(3):
            target_mgr.enemy_aircraft.append(
                EnemyAircraft(base_x + (i - 1) * 2000, 70000, 14000, heading=180, variant='bomber'))
        for i in range(4):
            target_mgr.enemy_aircraft.append(
                EnemyAircraft(base_x + (i - 2) * 1500, 72000, 13000 + i * 300, heading=180))
        for i in range(3):
            target_mgr.enemy_aircraft.append(
                EnemyAircraft(base_x + (i - 1) * 2500, 68000, 15000, heading=180))

    def check_objectives(self, aircraft, target_mgr, carrier):
        enemies_down = sum(1 for e in target_mgr.enemy_aircraft if not e.alive)
        self.kills['aircraft'] = enemies_down
        if enemies_down >= self.kills_needed:
            self.objectives_met = True
            return "success"
        for enemy in target_mgr.enemy_aircraft:
            if enemy.alive and enemy.variant == 'bomber':
                dist = math.sqrt((enemy.x - 35000)**2 + (enemy.y - 35000)**2)
                if dist < 2500:
                    return "failed"
        return "active"


class MissionCarrierQual(Mission):
    """SBD carrier qualification — graded trap required."""
    NAME = "Carrier Qual (SBD)"
    AIRCRAFT_CLASS = SBD_Dauntless
    DIFFICULTY = 2
    OBJECTIVE = "Qualify the Dauntless: trap with grade B or better."
    BRIEFING = [
        "CARRIER QUALIFICATION — SBD",
        "",
        "Before Midway, every Dauntless pilot must prove",
        "they can bring a heavy dive bomber aboard.",
        "",
        "Launch from the deck, fly the pattern, and trap.",
        "LSO grades: S (perfect), A, B (pass), C, F (bolter).",
        "",
        "SBD approach speed: 95–115 kts. Gear down. Flaps on.",
        "Wire 3 is the sweet spot. Hold the centerline.",
        "",
        "Objective: Grade B or better to qualify.",
    ]
    START_ALT = 3000
    START_SPEED = 180
    CARRIER_TAKEOFF = True

    def __init__(self):
        super().__init__()
        self.last_trap_grade = None

    def setup_targets(self, target_mgr, carrier):
        target_mgr.ships.clear()
        target_mgr.ground_targets.clear()
        target_mgr.enemy_aircraft.clear()

    def on_trap(self, grade):
        self.last_trap_grade = grade

    def check_objectives(self, aircraft, target_mgr, carrier):
        if self.last_trap_grade and LandingScorer().grade_at_least(self.last_trap_grade, 'B'):
            if aircraft.on_ground and carrier.check_on_deck(aircraft.x, aircraft.y):
                v = math.sqrt(aircraft.vx**2 + aircraft.vy**2)
                if v < 15:
                    self.returned_to_base = True
                    return "success"
        return "active"

    def get_score(self):
        base = super().get_score()
        grade_bonus = {'S': 800, 'A': 500, 'B': 300}.get(self.last_trap_grade, 0)
        return base + grade_bonus


class MissionMidwayDive(Mission):
    """June 4, 1942 — SBD dive bombing attack on IJN Kaga."""
    NAME = "Midway Dive"
    AIRCRAFT_CLASS = SBD_Dauntless
    DIFFICULTY = 5
    OBJECTIVE = "Dive bomb the carrier Kaga. RTB and trap aboard."
    BRIEFING = [
        "MIDWAY — DIVE BOMBING ATTACK",
        "",
        "June 4, 1942. Scout planes have found the Japanese",
        "carrier Kaga. You are flying an SBD-5 from USS Enterprise.",
        "",
        "Climb to 8,000 ft, locate the carrier 6 miles northeast,",
        "and execute a diving attack. Hold B for dive brakes.",
        "",
        "Drop your 1,000 lb bomb between 1,500 and 3,000 ft.",
        "Sink the Kaga, then return for a carrier landing.",
        "",
        "CAP Zeros are patrolling the fleet. Stay fast in the dive.",
    ]
    START_ALT = 8000
    START_SPEED = 200
    START_HEADING = 45
    CARRIER_TAKEOFF = True

    def __init__(self):
        super().__init__()
        self.carrier_sunk = False

    def setup_targets(self, target_mgr, carrier):
        target_mgr.ships.clear()
        target_mgr.ground_targets.clear()
        target_mgr.enemy_aircraft.clear()
        kaga_x, kaga_y = 35000, 35000
        target_mgr.ships.append(Ship(kaga_x, kaga_y, 'carrier', heading=225))
        target_mgr.ships.append(Ship(kaga_x - 2500, kaga_y - 2000, 'destroyer', heading=225))
        target_mgr.ships.append(Ship(kaga_x + 2000, kaga_y - 1500, 'destroyer', heading=225))
        for i in range(3):
            target_mgr.enemy_aircraft.append(
                EnemyAircraft(kaga_x + (i - 1) * 3000, kaga_y + 8000, 10000 + i * 500, heading=180))

    def check_objectives(self, aircraft, target_mgr, carrier):
        kaga_alive = any(s.alive and s.ship_type == 'carrier' for s in target_mgr.ships)
        if not kaga_alive:
            self.carrier_sunk = True
            self.objectives_met = True

        if self.objectives_met and aircraft.on_ground and carrier.check_on_deck(aircraft.x, aircraft.y):
            v = math.sqrt(aircraft.vx**2 + aircraft.vy**2)
            if v < 15:
                self.returned_to_base = True
                return "success"
        return "active"

    def get_score(self):
        return super().get_score() + (2000 if self.carrier_sunk else 0)


def mission_aircraft_class(mission_cls):
    """Return flyable class for a mission (default: Hellcat)."""
    return getattr(mission_cls, 'AIRCRAFT_CLASS', F6F_Hellcat)


MISSIONS = [
    MissionFlightSchool, MissionCarrierQual, MissionBombBase, MissionScramble,
    MissionCoralSea, MissionMidwayCAP, MissionMidwayDive, MissionDivineWind,
    MissionFlatTop, MissionBomberEscort, MissionTorpedoRun, MissionNightStrike,
]


# ============== CAMPAIGN MODE ==============
class Campaign:
    """Linear mission progression with persistent state between sorties."""
    MISSION_ORDER = [
        MissionFlightSchool, MissionCarrierQual, MissionBombBase, MissionScramble,
        MissionCoralSea, MissionMidwayCAP, MissionMidwayDive, MissionTorpedoRun,
        MissionBomberEscort, MissionDivineWind, MissionFlatTop, MissionNightStrike,
    ]

    def __init__(self):
        self.current_index = 0
        self.active = False
        self.results = []  # list of (mission_name, status)
        self.damage_carry = {}  # carried damage between sorties
        self.ammo_carry = {}    # carried ammo
        self.load()

    def start(self):
        self.active = True
        self.current_index = 0
        self.results = []
        self.damage_carry = {}
        self.ammo_carry = {}

    def get_current_mission_class(self):
        if self.current_index < len(self.MISSION_ORDER):
            return self.MISSION_ORDER[self.current_index]
        return None

    def advance(self, mission):
        """Record result and advance. Returns True if campaign continues."""
        self.results.append((mission.NAME, mission.status))
        if mission.status == "success":
            self.current_index += 1
        # Save state
        self.save()
        return self.current_index < len(self.MISSION_ORDER)

    def is_complete(self):
        return self.current_index >= len(self.MISSION_ORDER)

    def save_aircraft_state(self, aircraft):
        """Save damage/ammo from aircraft for next sortie."""
        self.damage_carry = {
            'engine': aircraft.dmg_engine * 0.5,   # Partial repair between sorties
            'aileron': aircraft.dmg_aileron * 0.5,
            'elevator': aircraft.dmg_elevator * 0.5,
            'rudder': aircraft.dmg_rudder * 0.5,
        }
        self.ammo_carry = {
            'mg_ammo': max(1200, aircraft.mg_ammo),  # At least half reloaded
            'rockets': 6,   # Full rocket rearm
            'bombs': 1,     # Full bomb rearm
            'torpedoes': 1, # Full torpedo rearm
        }
        self.save()

    def apply_aircraft_state(self, aircraft):
        """Apply carried damage/ammo to new sortie aircraft."""
        if self.damage_carry:
            aircraft.dmg_engine = self.damage_carry.get('engine', 0)
            aircraft.dmg_aileron = self.damage_carry.get('aileron', 0)
            aircraft.dmg_elevator = self.damage_carry.get('elevator', 0)
            aircraft.dmg_rudder = self.damage_carry.get('rudder', 0)
            if aircraft.dmg_engine > 0.5:
                aircraft.smoking = True
        if self.ammo_carry:
            aircraft.mg_ammo = self.ammo_carry.get('mg_ammo', 2400)
            aircraft.rockets = self.ammo_carry.get('rockets', 6)
            aircraft.bombs = self.ammo_carry.get('bombs', 1)
            aircraft.torpedoes = self.ammo_carry.get('torpedoes', 1)

    def save(self):
        import json
        data = {
            'current_index': self.current_index,
            'results': self.results,
            'damage_carry': self.damage_carry,
            'ammo_carry': self.ammo_carry,
        }
        try:
            with open(SAVE_FILE) as f:
                save_data = json.load(f)
        except Exception:
            save_data = {}
        save_data['campaign'] = data
        try:
            with open(SAVE_FILE, 'w') as f:
                json.dump(save_data, f, indent=2)
        except Exception:
            pass

    def load(self):
        import json
        try:
            with open(SAVE_FILE) as f:
                data = json.load(f)
            campaign = data.get('campaign', {})
            self.current_index = campaign.get('current_index', 0)
            self.results = campaign.get('results', [])
            self.damage_carry = campaign.get('damage_carry', {})
            self.ammo_carry = campaign.get('ammo_carry', {})
        except Exception:
            pass


def draw_campaign_status(surface, campaign, dossier):
    """Draw campaign progress screen."""
    surface.fill((10, 15, 25))
    title = font_title.render("CAMPAIGN", True, HUD_AMBER)
    surface.blit(title, (WIDTH // 2 - title.get_width() // 2, 40))

    subtitle = font_med.render(f"{dossier.get_rank()} {dossier.name}", True, HUD_GREEN)
    surface.blit(subtitle, (WIDTH // 2 - subtitle.get_width() // 2, 110))

    y = 170
    for i, mission_class in enumerate(Campaign.MISSION_ORDER):
        m = mission_class()
        # Status marker
        if i < len(campaign.results):
            name, status = campaign.results[i]
            if status == "success":
                marker = "[COMPLETE]"
                color = HUD_GREEN
            else:
                marker = "[FAILED - RETRY]"
                color = HUD_RED
        elif i == campaign.current_index:
            marker = ">> NEXT <<"
            color = HUD_AMBER
        else:
            marker = "[LOCKED]"
            color = (80, 80, 80)

        # Mission name
        diff_stars = "*" * m.DIFFICULTY
        line = font_med.render(f"{i+1}. {m.NAME}  {diff_stars}  {marker}", True, color)
        surface.blit(line, (100, y))
        y += 40

    if campaign.is_complete():
        victory = font_large.render("CAMPAIGN VICTORY!", True, (255, 215, 0))
        surface.blit(victory, (WIDTH // 2 - victory.get_width() // 2, y + 30))
        stats = font_med.render(
            f"Missions: {len(campaign.results)} | Score: {dossier.total_score:,}",
            True, HUD_GREEN)
        surface.blit(stats, (WIDTH // 2 - stats.get_width() // 2, y + 80))
    else:
        hint = font_small.render("Press ENTER to launch next mission  |  ESC to return", True, WHITE)
        surface.blit(hint, (WIDTH // 2 - hint.get_width() // 2, HEIGHT - 60))


