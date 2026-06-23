"""Flyable aircraft physics."""
import math
import random
import pygame
from hellcats.bootstrap import (
    MAP_CENTER_LAT, MAP_CENTER_LON, PHYSICS_DT,
)
from hellcats.hotp import hotp_rng

# ============== AIRCRAFT BASE CLASS ==============
class Aircraft:
    G = 32.174  # ft/s^2
    RHO_SL = 0.002377  # slug/ft^3

    def __init__(self):
        self.reset()

    def get_air_density(self, altitude):
        if altitude < 36089:
            T = 518.67 - 0.00356616 * altitude
            p = 2116.22 * (T / 518.67) ** 5.256
        else:
            T = 389.97
            p = 472.68 * math.exp(-0.0000481 * (altitude - 36089))
        return p / (1716.49 * T)

    def get_airspeed_kts(self):
        v = math.sqrt(self.vx**2 + self.vy**2 + self.vz**2)
        return v / 1.68781

    def get_vertical_speed(self):
        return self.vz * 60


# ============== GRUMMAN F6F-5 HELLCAT ==============
class F6F_Hellcat(Aircraft):
    NAME = "F6F-5 Hellcat"
    DESCRIPTION = "WWII Navy Fighter"

    # Specifications
    WING_AREA = 334.0
    WINGSPAN = 42.83
    ASPECT_RATIO = WINGSPAN ** 2 / WING_AREA
    EMPTY_WEIGHT = 9238
    FUEL_WEIGHT = 1880
    COMBAT_WEIGHT = 12598
    MAX_WEIGHT = 15413

    MAX_POWER_HP = 2000
    CRITICAL_ALT = 23400

    # Aerodynamics
    CD0_CLEAN = 0.035
    CD0_GEAR = 0.025
    CD0_FLAPS = 0.10
    OSWALD_E = 0.75
    CLMAX_CLEAN = 1.35
    CLMAX_FLAPS = 1.85
    CL_ALPHA = 0.1
    CL0 = 0.2
    CL_FLAPS_BONUS = 0.4  # Extra lift from flaps

    VNE = 400
    MANEUVERING_SPEED = 250
    FLAPS_MAX_SPEED = 120
    GEAR_MAX_SPEED = 140
    STALL_SPEED_CLEAN = 87
    STALL_SPEED_FLAPS = 70

    # Carrier landing parameters (LSO grading)
    CARRIER_IDEAL_SPEED = (105, 125)
    CARRIER_MAX_WIRE_SPEED = 150
    ENGINE_SOUND = 'radial_fighter'

    def reset(self):
        self.ref_lat = MAP_CENTER_LAT
        self.ref_lon = MAP_CENTER_LON
        self.x, self.y, self.z = 0, 0, 5000
        self.vx, self.vy, self.vz = 0, 250 * 1.68781, 0
        self.pitch, self.roll, self.heading = 2, 0, 0
        self.pitch_rate, self.roll_rate, self.yaw_rate = 0.0, 0.0, 0.0
        self.aoa = 2
        self.throttle = 0.75
        self.flaps = False
        self.gear_down = False
        self.fuel = self.FUEL_WEIGHT
        self.weight = self.COMBAT_WEIGHT
        self.drag_modifier = 1.0
        self.stalled = False
        self.overspeed = False
        self.on_ground = False
        self.lift_deficit = False
        # Weapons - F6F-5 Hellcat armament
        self.mg_ammo = 2400  # 400 rounds per gun x 6 guns
        self.rockets = 6  # 6x HVAR 5-inch rockets
        self.bombs = 1  # 1x 500lb bomb (centerline)
        self.torpedoes = 1  # 1x Mk 13 torpedo (belly mount)
        self.mg_firing = False
        self.last_mg_fire = 0
        self.selected_weapon = 0  # 0=MG, 1=Rockets, 2=Bombs
        self.radar_range = 3  # nm (1, 3, or 15)
        self.near_miss_shake = 0.0  # Screen shake intensity from near-misses
        # Component damage (0.0 = pristine, 1.0 = destroyed)
        self.dmg_engine = 0.0
        self.dmg_aileron = 0.0
        self.dmg_elevator = 0.0
        self.dmg_rudder = 0.0
        self.dmg_flaps = 0.0
        self.dmg_gear = 0.0
        self.dmg_fuel = 0.0  # fuel leak rate
        self.dmg_pilot = 0.0
        self.smoking = False
        self.on_fire = False
        # G-force effects on pilot
        self.g_effect = 0.0    # 0=clear vision, 1=full blackout/redout
        self.g_loc_timer = 0.0 # Seconds until GLOC recovery
        self.g_tolerance = 5.0 # Base positive G tolerance (trained WWII pilot)

    def get_engine_power(self, altitude, throttle):
        if altitude < 8000:
            power_ratio = 1.0
        elif altitude < self.CRITICAL_ALT:
            power_ratio = 1.0 + 0.15 * (altitude - 8000) / (self.CRITICAL_ALT - 8000)
        else:
            power_ratio = 1.15 - 0.4 * (altitude - self.CRITICAL_ALT) / (40000 - self.CRITICAL_ALT)
        power = self.MAX_POWER_HP * throttle * max(0.1, power_ratio)
        # Engine damage reduces power output
        power *= max(0.0, 1.0 - self.dmg_engine)
        return power

    def take_hit(self):
        """Random component takes damage from enemy fire"""
        component = random.choice(['engine', 'aileron', 'elevator', 'rudder',
                                    'flaps', 'gear', 'fuel', 'pilot'])
        dmg = random.uniform(0.15, 0.4)
        if component == 'engine':
            self.dmg_engine = min(1.0, self.dmg_engine + dmg)
            if self.dmg_engine > 0.5:
                self.smoking = True
            if self.dmg_engine > 0.8:
                self.on_fire = True
        elif component == 'aileron':
            self.dmg_aileron = min(1.0, self.dmg_aileron + dmg)
        elif component == 'elevator':
            self.dmg_elevator = min(1.0, self.dmg_elevator + dmg)
        elif component == 'rudder':
            self.dmg_rudder = min(1.0, self.dmg_rudder + dmg)
        elif component == 'flaps':
            self.dmg_flaps = min(1.0, self.dmg_flaps + dmg)
        elif component == 'gear':
            self.dmg_gear = min(1.0, self.dmg_gear + dmg)
        elif component == 'fuel':
            self.dmg_fuel = min(1.0, self.dmg_fuel + dmg * 2)
        elif component == 'pilot':
            self.dmg_pilot = min(1.0, self.dmg_pilot + dmg * 0.5)
        return component

    def calculate_forces(self):
        v_horizontal = math.sqrt(self.vx**2 + self.vy**2)
        airspeed = math.sqrt(self.vx**2 + self.vy**2 + self.vz**2)
        airspeed_kts = airspeed / 1.68781

        rho = self.get_air_density(self.z)
        q = 0.5 * rho * airspeed**2

        if airspeed > 10:
            flight_path_angle = math.degrees(math.atan2(self.vz, v_horizontal))
            self.aoa = self.pitch - flight_path_angle
        else:
            self.aoa = self.pitch

        # Lift coefficient with flaps effect
        cl_max = self.CLMAX_FLAPS if self.flaps else self.CLMAX_CLEAN
        stall_aoa = 18.0 if self.flaps else 14.0
        cl_base = self.CL0 + self.CL_ALPHA * self.aoa

        # Flaps increase lift coefficient
        if self.flaps:
            cl_base += self.CL_FLAPS_BONUS

        if self.aoa < stall_aoa and self.aoa > -8:
            cl = min(cl_base, cl_max)
            self.stalled = False
        else:
            self.stalled = True
            if self.aoa >= stall_aoa:
                excess_aoa = self.aoa - stall_aoa
                cl = cl_max * math.exp(-0.15 * excess_aoa)
                cl = max(cl, 0.3)
            else:
                cl = -0.4

        roll_rad = math.radians(self.roll)
        effective_lift_factor = math.cos(roll_rad)

        # Drag with gear and flaps effects
        cd0 = self.CD0_CLEAN
        if self.gear_down:
            cd0 += self.CD0_GEAR
        if self.flaps:
            cd0 += self.CD0_FLAPS
        if self.stalled:
            cd0 += 0.05
        if self.throttle < 0.3:
            cd0 += 0.02 * (1 - self.throttle / 0.3)

        cd_induced = cl**2 / (math.pi * self.ASPECT_RATIO * self.OSWALD_E)
        cd_total = (cd0 + cd_induced) * self.drag_modifier

        lift = q * self.WING_AREA * cl
        drag = q * self.WING_AREA * cd_total

        power_hp = self.get_engine_power(self.z, self.throttle)
        power_ftlbs = power_hp * 550
        if airspeed > 50:
            thrust = power_ftlbs / airspeed
        else:
            thrust = power_ftlbs / 100 * 0.8

        prop_efficiency = 0.85 - 0.1 * (airspeed_kts / self.VNE)
        thrust *= max(0.4, prop_efficiency)

        weight = self.weight
        return lift, drag, thrust, weight, airspeed_kts, q, effective_lift_factor, cd0

    def update(self, dt, keys):
        # Control surface inputs (-1 to 1)
        elevator = 0  # S = pull back (pitch up), W = push forward (pitch down)
        aileron = 0   # D = right roll, A = left roll
        rudder = 0    # E = right yaw, Q = left yaw

        # During GLOC, all controls are frozen
        gloc = getattr(self, 'g_loc_timer', 0) > 0

        if not gloc and keys[pygame.K_s]: elevator += 1
        if not gloc and keys[pygame.K_w]: elevator -= 1
        if not gloc and keys[pygame.K_d]: aileron += 1
        if not gloc and keys[pygame.K_a]: aileron -= 1
        if not gloc and keys[pygame.K_e]: rudder += 1
        if not gloc and keys[pygame.K_q]: rudder -= 1
        if keys[pygame.K_LSHIFT]:
            self.throttle = min(1.0, self.throttle + 0.5 * dt)
        if keys[pygame.K_LCTRL]:
            self.throttle = max(0.0, self.throttle - 0.5 * dt)
        if keys[pygame.K_UP]:
            self.drag_modifier = min(3.0, self.drag_modifier + 0.5 * dt)
        if keys[pygame.K_DOWN]:
            self.drag_modifier = max(0.5, self.drag_modifier - 0.5 * dt)

        # Control authority scales with dynamic pressure
        airspeed = math.sqrt(self.vx**2 + self.vy**2 + self.vz**2)
        rho = self.get_air_density(self.z)
        q = 0.5 * rho * airspeed**2
        q_ref = 0.5 * self.RHO_SL * (200 * 1.68781)**2
        ctrl = min(q / q_ref, 2.0) if q_ref > 0 else 0

        # Commanded angular rates — F6F Hellcat was renowned for crisp, responsive controls.
        # Original HOTP: small deltas snap instantly. We use higher rates + lower damping
        # to match that responsive feel. Historical: ~75 deg/s roll, fast pitch authority.
        pitch_cmd = elevator * 60 * ctrl * (1.0 - self.dmg_elevator)
        roll_cmd = aileron * 140 * ctrl * (1.0 - self.dmg_aileron)
        yaw_cmd = rudder * 20 * ctrl * (1.0 - self.dmg_rudder)

        # Aerodynamic damping (lower = more responsive, higher = more stable)
        damp_p = 3.0 * ctrl
        damp_r = 3.5 * ctrl
        damp_y = 2.5 * ctrl

        # Stability: trim pitch, wings-level tendency, stall nose-drop
        pitch_stab = 0
        if elevator == 0:
            pitch_stab = (2.0 - self.pitch) * 1.0 * ctrl
        if self.stalled and elevator >= 0:
            pitch_stab -= 20 * ctrl

        # Dihedral effect: restoring moment proportional to sin(roll).
        # Zero at 0° (upright) and 180° (inverted) - both are equilibria.
        # Maximum at ±90° bank. This allows sustained inverted flight.
        roll_stab = 0
        if aileron == 0:
            roll_stab = -math.sin(math.radians(self.roll)) * 50 * ctrl

        # Angular accelerations — high gain for snappy WWII fighter response
        # HOTP original: small corrections apply instantly (delta<8 rule)
        self.pitch_rate += (pitch_cmd + pitch_stab - self.pitch_rate * damp_p) * 8.0 * dt
        self.roll_rate += (roll_cmd + roll_stab - self.roll_rate * damp_r) * 10.0 * dt
        self.yaw_rate += (yaw_cmd - self.yaw_rate * damp_y) * 5.0 * dt

        # Update attitudes from angular rates
        # Full aerobatic pitch range: allows loops, split-S, Immelmann
        self.pitch = max(-89, min(89, self.pitch + self.pitch_rate * dt))
        self.roll = self.roll + self.roll_rate * dt
        # Wrap roll to -180..180
        self.roll = ((self.roll + 180) % 360) - 180
        self.heading = (self.heading + self.yaw_rate * dt) % 360

        # Coordinated turn: bank produces heading change via lift vector tilt.
        # Use tan(roll) directly (correct for all roll angles including inverted).
        # Clamp the TURN RATE, not the roll angle, to avoid singularity at ±90°.
        if airspeed > 100:
            roll_for_turn = math.radians(self.roll)
            cos_roll = math.cos(roll_for_turn)
            if abs(cos_roll) > 0.05:  # Avoid division issues near knife-edge
                bank_turn = math.degrees(self.G * math.sin(roll_for_turn) / (airspeed * cos_roll))
                bank_turn = max(-25, min(25, bank_turn))  # Clamp turn rate
                self.heading = (self.heading + bank_turn * dt) % 360

        lift, drag, thrust, weight, airspeed_kts, q, eff_lift, cd0 = self.calculate_forces()
        self._cached_lift = lift
        self._cached_weight = weight

        v_total = math.sqrt(self.vx**2 + self.vy**2 + self.vz**2)
        v_total = max(v_total, 1)

        ux, uy, uz = self.vx / v_total, self.vy / v_total, self.vz / v_total
        hdg_rad = math.radians(self.heading)
        roll_rad = math.radians(self.roll)
        pitch_rad = math.radians(self.pitch)
        cos_roll = math.cos(roll_rad)

        # Thrust decomposition: thrust acts along body longitudinal axis.
        # The vertical component must account for roll (inverted = thrust pushes down).
        thrust_fwd = thrust * math.cos(pitch_rad)
        thrust_up_body = thrust * math.sin(pitch_rad)
        thrust_x = thrust_fwd * math.sin(hdg_rad) + thrust_up_body * math.sin(roll_rad) * math.cos(hdg_rad)
        thrust_y = thrust_fwd * math.cos(hdg_rad) - thrust_up_body * math.sin(roll_rad) * math.sin(hdg_rad)
        thrust_z = thrust_up_body * cos_roll  # Inverted: cos(180°)=-1 → thrust pushes down

        drag_x, drag_y, drag_z = -drag * ux, -drag * uy, -drag * uz

        # Lift decomposition (already correct: cos(180°) = -1 → lift pushes down when inverted)
        lift_vertical = lift * eff_lift
        lift_horizontal = lift * math.sin(roll_rad)
        lift_x = lift_horizontal * math.cos(hdg_rad)
        lift_y = -lift_horizontal * math.sin(hdg_rad)
        lift_z = lift_vertical

        weight_z = -weight

        fx = thrust_x + drag_x + lift_x
        fy = thrust_y + drag_y + lift_y
        fz = thrust_z + drag_z + lift_z + weight_z

        mass = self.weight / self.G
        ax, ay, az = fx / mass, fy / mass, fz / mass

        self.vx += ax * dt
        self.vy += ay * dt
        self.vz += az * dt

        self.x += self.vx * dt
        self.y += self.vy * dt
        self.z += self.vz * dt

        self.lift_deficit = lift_vertical < weight

        if math.sqrt(self.vx**2 + self.vy**2) > 50:
            vel_heading = math.degrees(math.atan2(self.vx, self.vy))
            hdg_diff = ((vel_heading - self.heading + 180) % 360) - 180
            self.heading = (self.heading + hdg_diff * 3.0 * dt) % 360

        if self.z <= 0:
            self.z = 0
            self.vz = 0
            if v_total * 0.592484 > 150:
                return "CRASHED - Too fast!"
            if abs(self.pitch) > 15:
                return "CRASHED - Bad attitude!"
            if abs(self.roll) > 20:
                return "CRASHED - Wings not level!"
            self.vx *= 0.95
            self.vy *= 0.95
            self.on_ground = True
            if v_total < 5:
                return "LANDED"
            return "ROLLING"
        self.on_ground = False

        self.overspeed = airspeed_kts > self.VNE

        fuel_flow = self.throttle * 150 / 3600
        # Fuel leak from damage
        fuel_leak = self.dmg_fuel * 500 / 3600  # Up to 500 lbs/hr leak
        self.fuel = max(0, self.fuel - (fuel_flow * 6 + fuel_leak) * dt)
        self.weight = self.EMPTY_WEIGHT + self.fuel

        # Fire spreads damage over time
        if self.on_fire:
            self.dmg_engine = min(1.0, self.dmg_engine + 0.05 * dt)
            self.dmg_fuel = min(1.0, self.dmg_fuel + 0.1 * dt)
            self.dmg_pilot = min(1.0, self.dmg_pilot + 0.02 * dt)

        # Pilot incapacitation
        if self.dmg_pilot >= 1.0:
            return "CRASHED - Pilot incapacitated!"

        # G-force effects on pilot vision
        g = self.get_load_factor()
        if g > self.g_tolerance:
            # Positive G: greyout -> tunnel vision -> blackout -> GLOC
            excess = (g - self.g_tolerance) / 3.0  # 3G above tolerance = full blackout
            self.g_effect = min(1.0, self.g_effect + excess * 1.5 * dt)
        elif g < -2.0:
            # Negative G: redout (blood rushes to head, lower tolerance)
            excess = (-g - 2.0) / 2.0  # 2G negative above -2 = full redout
            self.g_effect = min(1.0, self.g_effect + excess * 2.0 * dt)
        else:
            # Recovery: vision clears when G returns to normal
            self.g_effect = max(0.0, self.g_effect - 1.5 * dt)

        # GLOC: if g_effect reaches 1.0, pilot blacks out for a few seconds
        if self.g_effect >= 1.0:
            if self.g_loc_timer <= 0:
                self.g_loc_timer = 3.0  # 3 seconds of unconsciousness
        if self.g_loc_timer > 0:
            self.g_loc_timer -= dt
            self.g_effect = 1.0  # Stay fully blacked out during GLOC
            # Controls frozen during GLOC (pitch/roll/yaw rates decay naturally)
            return "!! G-LOC - UNCONSCIOUS !!"

        if self.stalled:
            return "** STALL **"
        if self.overspeed:
            return "!! OVERSPEED !!"
        if self.on_fire:
            return "!! FIRE - LAND IMMEDIATELY !!"
        if self.smoking:
            return "** ENGINE DAMAGE **"
        if self.g_effect > 0.3:
            if g < 0:
                return "** REDOUT **"
            return "** BLACKOUT **"
        return "FLYING"

    def get_load_factor(self):
        lift = getattr(self, '_cached_lift', None)
        weight = getattr(self, '_cached_weight', None)
        if lift is None or weight is None:
            lift, _, _, weight, _, _, _, _ = self.calculate_forces()
        return lift / weight if weight > 0 else 1.0


# ============== VOUGHT F4U-1D CORSAIR ==============
class F4U_Corsair(F6F_Hellcat):
    """Vought F4U-1D Corsair - the gull-winged "Whistling Death."

    Shares the Hellcat's flight model, combat systems, and damage model
    (inherited from F6F_Hellcat) but flies as a distinct airframe. The
    R-2800-8W with water injection plus a very clean airframe give it a
    higher top speed and a famously high dive limit, paid for with a
    higher stall speed and a sharper, gull-wing stall.
    """
    NAME = "F4U-1D Corsair"
    DESCRIPTION = "WWII Navy Fighter-Bomber"

    # Specifications (F4U-1D)
    WING_AREA = 314.0
    WINGSPAN = 41.0
    ASPECT_RATIO = WINGSPAN ** 2 / WING_AREA  # ~5.35
    EMPTY_WEIGHT = 8982
    FUEL_WEIGHT = 1700      # ~237 gal internal
    COMBAT_WEIGHT = 12039
    MAX_WEIGHT = 14670

    MAX_POWER_HP = 2250     # R-2800-8W with water injection
    CRITICAL_ALT = 19900

    # Aerodynamics - slightly cleaner than the Hellcat (faster top speed),
    # but the gull wing has a lower clean CLmax and a sharper stall.
    CD0_CLEAN = 0.032
    CD0_GEAR = 0.025
    CD0_FLAPS = 0.10
    OSWALD_E = 0.78
    CLMAX_CLEAN = 1.30
    CLMAX_FLAPS = 1.80
    CL_ALPHA = 0.1
    CL0 = 0.2
    CL_FLAPS_BONUS = 0.4

    VNE = 450               # famous high-speed dive limit
    MANEUVERING_SPEED = 260
    FLAPS_MAX_SPEED = 120
    GEAR_MAX_SPEED = 145
    STALL_SPEED_CLEAN = 92
    STALL_SPEED_FLAPS = 76

    CARRIER_IDEAL_SPEED = (108, 128)
    CARRIER_MAX_WIRE_SPEED = 145
    ENGINE_SOUND = 'radial_corsair'

    def reset(self):
        super().reset()
        # F4U-1D loadout: 6x .50 cal, 8x HVAR rockets, 2x 1000lb bombs.
        # No torpedo - the Corsair served as a fighter-bomber.
        self.mg_ammo = 2350     # ~390 rounds per gun x 6
        self.rockets = 8
        self.bombs = 2
        self.torpedoes = 0


# ============== DOUGLAS SBD-5 DAUNTLESS ==============
class SBD_Dauntless(F6F_Hellcat):
    """Douglas SBD-5 Dauntless - the carrier dive bomber that turned Midway.

    Slower and heavier than fighters, but built for steep diving attacks with
    perforated dive brakes. Armed for precision strikes on ships and airfields.
    """
    NAME = "SBD-5 Dauntless"
    DESCRIPTION = "WWII Navy Dive Bomber"

    WING_AREA = 325.0
    WINGSPAN = 41.5
    ASPECT_RATIO = WINGSPAN ** 2 / WING_AREA
    EMPTY_WEIGHT = 6400
    FUEL_WEIGHT = 1200
    COMBAT_WEIGHT = 9450
    MAX_WEIGHT = 10700

    MAX_POWER_HP = 1200
    CRITICAL_ALT = 18000

    CD0_CLEAN = 0.038
    CD0_GEAR = 0.030
    CD0_FLAPS = 0.14
    OSWALD_E = 0.74
    CLMAX_CLEAN = 1.40
    CLMAX_FLAPS = 1.95
    CL_ALPHA = 0.095
    CL0 = 0.18
    CL_FLAPS_BONUS = 0.45

    VNE = 340
    MANEUVERING_SPEED = 200
    FLAPS_MAX_SPEED = 110
    GEAR_MAX_SPEED = 130
    STALL_SPEED_CLEAN = 78
    STALL_SPEED_FLAPS = 62

    # Heavier approach — slower trap window, steeper LSO standards
    CARRIER_IDEAL_SPEED = (95, 115)
    CARRIER_MAX_WIRE_SPEED = 130
    ENGINE_SOUND = 'radial_sbd'

    def reset(self):
        super().reset()
        self.mg_ammo = 1600
        self.rockets = 0
        self.bombs = 1
        self.bomb_weight = 1000
        self.torpedoes = 0
        self.dive_brakes = False
        self.dive_mode = 'cruise'
        self.dive_start_alt = 0
        self.dive_bomb_armed = False
        self.dive_bomb_released = False

    def update(self, dt, keys):
        import pygame
        from hellcats.dive_bombing import update_dive_state

        if keys[pygame.K_b]:
            self.dive_brakes = True
            self.drag_modifier = max(self.drag_modifier, 2.2)
        else:
            self.dive_brakes = False
            if self.drag_modifier > 1.5:
                self.drag_modifier = 1.0

        dive_status = update_dive_state(self, dt)
        result = super().update(dt, keys)
        if dive_status:
            return dive_status
        return result


# ============== BOEING 747-200 ==============
class Boeing747_200(Aircraft):
    NAME = "Boeing 747-200"
    DESCRIPTION = "Jumbo Jet Airliner"

    # Specifications
    WING_AREA = 5500.0  # sq ft
    WINGSPAN = 195.7  # ft
    ASPECT_RATIO = WINGSPAN ** 2 / WING_AREA  # ~6.96
    EMPTY_WEIGHT = 380000  # lbs
    FUEL_WEIGHT = 300000  # lbs (full tanks)
    TYPICAL_WEIGHT = 600000  # lbs
    MAX_WEIGHT = 833000  # lbs

    # 4x Pratt & Whitney JT9D-7A engines
    MAX_THRUST_PER_ENGINE = 46500  # lbs
    NUM_ENGINES = 4
    MAX_THRUST = MAX_THRUST_PER_ENGINE * NUM_ENGINES  # 186,000 lbs total

    # Aerodynamics
    CD0_CLEAN = 0.018  # Very clean at cruise
    CD0_GEAR = 0.020  # Big gear!
    CD0_FLAPS_10 = 0.015
    CD0_FLAPS_FULL = 0.065  # Full flaps
    OSWALD_E = 0.82
    CLMAX_CLEAN = 1.2
    CLMAX_FLAPS = 2.4  # With full flaps and slats
    CL_ALPHA = 0.08
    CL0 = 0.25
    CL_FLAPS_BONUS = 0.8

    # Speeds (varies with weight, these are typical)
    VNE = 420  # Vmo ~365 KIAS, Mmo 0.92
    MANEUVERING_SPEED = 280
    FLAPS_MAX_SPEED = 250  # Flaps extended speed
    GEAR_MAX_SPEED = 270
    STALL_SPEED_CLEAN = 160  # At typical weight
    STALL_SPEED_FLAPS = 115

    CRUISE_ALTITUDE = 35000
    CRUISE_MACH = 0.84
    ENGINE_SOUND = 'jet_wide'

    def reset(self):
        self.ref_lat = MAP_CENTER_LAT
        self.ref_lon = MAP_CENTER_LON
        self.x, self.y, self.z = 0, 0, 10000  # Start higher
        self.vx, self.vy, self.vz = 0, 280 * 1.68781, 0  # 280 knots
        self.pitch, self.roll, self.heading = 2.5, 0, 0
        self.pitch_rate, self.roll_rate, self.yaw_rate = 0.0, 0.0, 0.0
        self.aoa = 2.5
        self.throttle = 0.70
        self.flaps = False  # 0 = up, True = down (simplified)
        self.flap_setting = 0  # 0, 10, 20, 30 degrees
        self.gear_down = False
        self.fuel = self.FUEL_WEIGHT * 0.7  # 70% fuel
        self.weight = self.TYPICAL_WEIGHT
        self.drag_modifier = 1.0
        self.stalled = False
        self.overspeed = False
        self.on_ground = False
        self.lift_deficit = False
        self.spoilers = False

    def get_engine_thrust(self, altitude, throttle, airspeed_kts):
        # Jet engines: thrust decreases with altitude (air density)
        # and with airspeed (ram drag effect, partially offset by ram compression)
        rho = self.get_air_density(altitude)
        rho_ratio = rho / self.RHO_SL

        # Thrust roughly proportional to air density
        altitude_factor = rho_ratio ** 0.8

        # Speed effect (thrust decreases slightly with speed)
        speed_factor = 1.0 - 0.0003 * airspeed_kts
        speed_factor = max(0.6, speed_factor)

        return self.MAX_THRUST * throttle * altitude_factor * speed_factor

    def calculate_forces(self):
        v_horizontal = math.sqrt(self.vx**2 + self.vy**2)
        airspeed = math.sqrt(self.vx**2 + self.vy**2 + self.vz**2)
        airspeed_kts = airspeed / 1.68781

        rho = self.get_air_density(self.z)
        q = 0.5 * rho * airspeed**2

        if airspeed > 10:
            flight_path_angle = math.degrees(math.atan2(self.vz, v_horizontal))
            self.aoa = self.pitch - flight_path_angle
        else:
            self.aoa = self.pitch

        # Lift coefficient
        cl_max = self.CLMAX_FLAPS if self.flaps else self.CLMAX_CLEAN
        stall_aoa = 16.0 if self.flaps else 12.0
        cl_base = self.CL0 + self.CL_ALPHA * self.aoa

        if self.flaps:
            cl_base += self.CL_FLAPS_BONUS

        if self.aoa < stall_aoa and self.aoa > -6:
            cl = min(cl_base, cl_max)
            self.stalled = False
        else:
            self.stalled = True
            if self.aoa >= stall_aoa:
                excess_aoa = self.aoa - stall_aoa
                cl = cl_max * math.exp(-0.12 * excess_aoa)
                cl = max(cl, 0.2)
            else:
                cl = -0.3

        roll_rad = math.radians(self.roll)
        effective_lift_factor = math.cos(roll_rad)

        # Drag calculation
        cd0 = self.CD0_CLEAN
        if self.gear_down:
            cd0 += self.CD0_GEAR
        if self.flaps:
            cd0 += self.CD0_FLAPS_FULL
        if self.stalled:
            cd0 += 0.03
        if self.spoilers:
            cd0 += 0.04

        cd_induced = cl**2 / (math.pi * self.ASPECT_RATIO * self.OSWALD_E)
        cd_total = (cd0 + cd_induced) * self.drag_modifier

        lift = q * self.WING_AREA * cl
        drag = q * self.WING_AREA * cd_total

        thrust = self.get_engine_thrust(self.z, self.throttle, airspeed_kts)

        weight = self.weight
        return lift, drag, thrust, weight, airspeed_kts, q, effective_lift_factor, cd0

    def update(self, dt, keys):
        # Control surface inputs (-1 to 1)
        elevator = 0
        aileron = 0
        rudder = 0

        if keys[pygame.K_s]: elevator += 1
        if keys[pygame.K_w]: elevator -= 1
        if keys[pygame.K_d]: aileron += 1
        if keys[pygame.K_a]: aileron -= 1
        if keys[pygame.K_e]: rudder += 1
        if keys[pygame.K_q]: rudder -= 1
        if keys[pygame.K_LSHIFT]:
            self.throttle = min(1.0, self.throttle + 0.3 * dt)
        if keys[pygame.K_LCTRL]:
            self.throttle = max(0.0, self.throttle - 0.3 * dt)
        if keys[pygame.K_UP]:
            self.drag_modifier = min(3.0, self.drag_modifier + 0.5 * dt)
        if keys[pygame.K_DOWN]:
            self.drag_modifier = max(0.5, self.drag_modifier - 0.5 * dt)

        # Control authority scales with dynamic pressure
        airspeed = math.sqrt(self.vx**2 + self.vy**2 + self.vz**2)
        rho = self.get_air_density(self.z)
        q = 0.5 * rho * airspeed**2
        q_ref = 0.5 * self.RHO_SL * (280 * 1.68781)**2
        ctrl = min(q / q_ref, 1.5) if q_ref > 0 else 0

        # 747 is much more sluggish than a fighter
        pitch_cmd = elevator * 8 * ctrl
        roll_cmd = aileron * 18 * ctrl
        yaw_cmd = rudder * 5 * ctrl

        # Heavy damping for large aircraft
        damp_p = 3.0 * ctrl
        damp_r = 3.5 * ctrl
        damp_y = 2.5 * ctrl

        # Stability
        pitch_stab = 0
        if elevator == 0:
            pitch_stab = (2.5 - self.pitch) * 0.6 * ctrl
        if self.stalled and elevator >= 0:
            pitch_stab -= 10 * ctrl

        roll_stab = 0
        if aileron == 0:
            roll_stab = -self.roll * 0.5 * ctrl

        # Angular accelerations (747 has high inertia = lower gain)
        self.pitch_rate += (pitch_cmd + pitch_stab - self.pitch_rate * damp_p) * 2.5 * dt
        self.roll_rate += (roll_cmd + roll_stab - self.roll_rate * damp_r) * 3.0 * dt
        self.yaw_rate += (yaw_cmd - self.yaw_rate * damp_y) * 2.0 * dt

        # Update attitudes from angular rates
        self.pitch = max(-20, min(25, self.pitch + self.pitch_rate * dt))
        self.roll = max(-50, min(50, self.roll + self.roll_rate * dt))
        self.heading = (self.heading + self.yaw_rate * dt) % 360

        # Coordinated turn: bank angle naturally changes heading
        if airspeed > 150:
            bank_turn = math.degrees(self.G * math.tan(math.radians(self.roll)) / airspeed)
            self.heading = (self.heading + bank_turn * dt) % 360

        lift, drag, thrust, weight, airspeed_kts, q, eff_lift, cd0 = self.calculate_forces()
        self._cached_lift = lift
        self._cached_weight = weight

        v_total = math.sqrt(self.vx**2 + self.vy**2 + self.vz**2)
        v_total = max(v_total, 1)

        ux, uy, uz = self.vx / v_total, self.vy / v_total, self.vz / v_total
        hdg_rad = math.radians(self.heading)
        roll_rad = math.radians(self.roll)
        pitch_rad = math.radians(self.pitch)

        thrust_x = thrust * math.sin(hdg_rad) * math.cos(pitch_rad)
        thrust_y = thrust * math.cos(hdg_rad) * math.cos(pitch_rad)
        thrust_z = thrust * math.sin(pitch_rad)

        drag_x, drag_y, drag_z = -drag * ux, -drag * uy, -drag * uz

        lift_vertical = lift * eff_lift
        lift_horizontal = lift * math.sin(roll_rad)
        lift_x = lift_horizontal * math.cos(hdg_rad)
        lift_y = -lift_horizontal * math.sin(hdg_rad)
        lift_z = lift_vertical

        weight_z = -weight

        fx = thrust_x + drag_x + lift_x
        fy = thrust_y + drag_y + lift_y
        fz = thrust_z + drag_z + lift_z + weight_z

        mass = self.weight / self.G
        ax, ay, az = fx / mass, fy / mass, fz / mass

        self.vx += ax * dt
        self.vy += ay * dt
        self.vz += az * dt

        self.x += self.vx * dt
        self.y += self.vy * dt
        self.z += self.vz * dt

        self.lift_deficit = lift_vertical < weight

        if math.sqrt(self.vx**2 + self.vy**2) > 50:
            vel_heading = math.degrees(math.atan2(self.vx, self.vy))
            hdg_diff = ((vel_heading - self.heading + 180) % 360) - 180
            self.heading = (self.heading + hdg_diff * 1.5 * dt) % 360

        if self.z <= 0:
            self.z = 0
            self.vz = 0
            touchdown_speed = v_total * 0.592484
            if touchdown_speed > 180:
                return "CRASHED - Too fast!"
            if abs(self.pitch) > 12:
                return "CRASHED - Bad attitude!"
            if abs(self.roll) > 10:
                return "CRASHED - Wings not level!"
            self.vx *= 0.98
            self.vy *= 0.98
            self.on_ground = True
            if v_total < 10:
                return "LANDED"
            return "ROLLING"
        self.on_ground = False

        self.overspeed = airspeed_kts > self.VNE

        # Fuel burn (much higher for 747!)
        fuel_flow = self.throttle * 12000 / 3600  # ~12000 lbs/hr at full throttle
        self.fuel = max(0, self.fuel - fuel_flow * dt)
        self.weight = self.EMPTY_WEIGHT + self.fuel

        if self.stalled:
            return "** STALL **"
        if self.overspeed:
            return "!! OVERSPEED !!"
        return "FLYING"

    def get_load_factor(self):
        lift = getattr(self, '_cached_lift', None)
        weight = getattr(self, '_cached_weight', None)
        if lift is None or weight is None:
            lift, _, _, weight, _, _, _, _ = self.calculate_forces()
        return lift / weight if weight > 0 else 1.0


# ============== BOEING 737-300 ==============
class Boeing737_300(Boeing747_200):
    """Narrowbody airliner — 737-300 class physics (Helios 522, etc.)."""
    NAME = "Boeing 737-300"
    DESCRIPTION = "Narrowbody Airliner"

    WING_AREA = 1240.0
    WINGSPAN = 112.0
    ASPECT_RATIO = WINGSPAN ** 2 / WING_AREA
    EMPTY_WEIGHT = 72000
    FUEL_WEIGHT = 35000
    TYPICAL_WEIGHT = 130000
    MAX_WEIGHT = 155000

    MAX_THRUST_PER_ENGINE = 22000
    NUM_ENGINES = 2
    MAX_THRUST = MAX_THRUST_PER_ENGINE * NUM_ENGINES

    CD0_CLEAN = 0.022
    VNE = 350
    STALL_SPEED_CLEAN = 130
    STALL_SPEED_FLAPS = 105
    CRUISE_ALTITUDE = 35000
    CRUISE_MACH = 0.78

    ENGINE_SOUND = 'jet_narrow'


# ============== AIRBUS A330-200 ==============
class AirbusA330_200(Boeing747_200):
    """Widebody twin — A330-200 class physics (AF 447, etc.)."""
    NAME = "Airbus A330-200"
    DESCRIPTION = "Widebody Twin Airliner"

    WING_AREA = 3140.0
    WINGSPAN = 198.0
    ASPECT_RATIO = WINGSPAN ** 2 / WING_AREA
    EMPTY_WEIGHT = 275000
    FUEL_WEIGHT = 140000
    TYPICAL_WEIGHT = 450000
    MAX_WEIGHT = 507000

    MAX_THRUST_PER_ENGINE = 70000
    NUM_ENGINES = 2
    MAX_THRUST = MAX_THRUST_PER_ENGINE * NUM_ENGINES

    CD0_CLEAN = 0.019
    VNE = 400
    STALL_SPEED_CLEAN = 145
    STALL_SPEED_FLAPS = 115
    CRUISE_ALTITUDE = 37000
    CRUISE_MACH = 0.82

    ENGINE_SOUND = 'jet_wide_twin'


