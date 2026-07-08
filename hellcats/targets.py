"""Targets, ships, enemies, target manager."""
import math
import pygame
from hellcats.hotp import (
    hotp_rng, HOTP_FLAG_JITTER_AXIS1, HOTP_FLAG_JITTER_AXIS2,
    HOTP_FLAG_CONTROL_GATE, HOTP_FLAG_SMOOTH_CTRL,
    hotp_delta_smooth, hotp_delta_smooth_s16, hotp_aero_lookup,
    hotp_fun_e570, hotp_fun_e468, _half_toward_zero,
)
from hellcats.bootstrap import PHYSICS_DT

# ============== TARGET SYSTEM ==============
class Target:
    """Base class for all targets"""
    def __init__(self, x, y, z, target_type, health=100):
        self.x, self.y, self.z = x, y, z
        self.target_type = target_type
        self.health = health
        self.max_health = health
        self.alive = True
        self.burning = False
        self.burn_time = 0

    def take_damage(self, damage):
        self.health -= damage
        if self.health <= 0:
            self.alive = False
            self.burning = True
        elif self.health < self.max_health * 0.5:
            self.burning = True

    def update(self, dt):
        if self.burning:
            self.burn_time += dt


class Ship(Target):
    """Naval target - carriers, destroyers, battleships, cruisers"""
    TYPES = {
        'carrier': {'length': 800, 'width': 100, 'health': 500, 'name': 'Carrier', 'aa_rate': 0.06},
        'battleship': {'length': 680, 'width': 95, 'health': 400, 'name': 'Battleship', 'aa_rate': 0.08},
        'cruiser': {'length': 500, 'width': 55, 'health': 200, 'name': 'Cruiser', 'aa_rate': 0.04},
        'destroyer': {'length': 350, 'width': 40, 'health': 200, 'name': 'Destroyer', 'aa_rate': 0.03},
        'transport': {'length': 450, 'width': 60, 'health': 150, 'name': 'Transport', 'aa_rate': 0.01},
    }

    # HOTP scoring per ship type
    SCORE = {
        'carrier': 2500,
        'battleship': 1500,
        'cruiser': 750,
        'destroyer': 500,
        'transport': 250,
    }

    def __init__(self, x, y, ship_type='destroyer', heading=0):
        specs = self.TYPES.get(ship_type, self.TYPES['destroyer'])
        super().__init__(x, y, 0, 'ship', specs['health'])
        self.ship_type = ship_type
        self.length = specs['length']
        self.width = specs['width']
        self.name = specs['name']
        self.aa_rate = specs.get('aa_rate', 0.02)  # Ship AA fire rate
        self.heading = heading
        self.speed = 20 if ship_type == 'carrier' else 25  # knots

    def update(self, dt):
        super().update(dt)
        # Ships move slowly
        if self.alive:
            hdg_rad = math.radians(self.heading)
            speed_fps = self.speed * 1.68781  # knots to ft/s
            self.x += math.sin(hdg_rad) * speed_fps * dt
            self.y += math.cos(hdg_rad) * speed_fps * dt

    def check_hit(self, px, py, pz):
        """Check if a point hits this ship"""
        if pz > 100:  # Too high
            return False
        # Rotate point to ship coordinates
        hdg_rad = math.radians(self.heading)
        dx = px - self.x
        dy = py - self.y
        # Local coordinates
        local_x = dx * math.cos(hdg_rad) - dy * math.sin(hdg_rad)
        local_y = dx * math.sin(hdg_rad) + dy * math.cos(hdg_rad)
        # Check bounds
        return abs(local_x) < self.width / 2 and abs(local_y) < self.length / 2


class GroundTarget(Target):
    """Ground installation - AA guns, bunkers, fuel tanks"""
    TYPES = {
        'aa_gun': {'radius': 20, 'health': 50, 'name': 'AA Gun'},
        'bunker': {'radius': 40, 'health': 150, 'name': 'Bunker'},
        'fuel_tank': {'radius': 30, 'health': 30, 'name': 'Fuel Tank'},
        'hangar': {'radius': 80, 'health': 200, 'name': 'Hangar'},
    }

    def __init__(self, x, y, ground_type='aa_gun'):
        specs = self.TYPES.get(ground_type, self.TYPES['aa_gun'])
        super().__init__(x, y, 0, 'ground', specs['health'])
        self.ground_type = ground_type
        self.radius = specs['radius']
        self.name = specs['name']

    def check_hit(self, px, py, pz):
        """Check if a point hits this target"""
        if pz > 50:  # Too high
            return False
        dist = math.sqrt((px - self.x)**2 + (py - self.y)**2)
        return dist < self.radius


class EnemyAircraft(Target):
    """Enemy aircraft - A6M Zero fighters with dogfighting AI"""

    # HOTP Entity Templates (from decompiled entity template struct)
    # Each variant has a template record with performance and weapon specifications
    TEMPLATES = {
        'fighter': {
            'name': 'A6M Zero', 'health': 30,
            'cruise_speed': 250, 'max_speed': 330, 'min_speed': 80,
            'combat_speed': 280, 'max_turn_rate': 12, 'max_climb_rate': 50,
            'max_roll_rate': 90, 'detection_range': 90000,
            'gun_range': 2500, 'gun_max_range': 3000, 'break_range': 500,
            'merge_alt_band': 2000,
            'fire_threshold': 80,       # HOTP template field_1e
            'scaling_factor': 0.70,     # HOTP template field_38 (normalized)
            'speed_threshold': 200,     # HOTP template field_3e
            'direction_adjust': 1.0,    # HOTP template field_40
            'alt_ceiling': 13000,       # Nakajima Sakae 12 critical altitude (ft)
            'hotp_flags': HOTP_FLAG_JITTER_AXIS1 | HOTP_FLAG_JITTER_AXIS2,
        },
        'bomber': {
            'name': 'G4M Betty', 'health': 80,
            'cruise_speed': 180, 'max_speed': 250, 'min_speed': 100,
            'combat_speed': 180, 'max_turn_rate': 4, 'max_climb_rate': 25,
            'max_roll_rate': 30, 'detection_range': 90000,
            'gun_range': 2000, 'gun_max_range': 2500, 'break_range': 800,
            'merge_alt_band': 2000,
            'fire_threshold': 200,
            'scaling_factor': 0.40,
            'speed_threshold': 150,
            'direction_adjust': 0.5,
            'alt_ceiling': 15000,       # Mitsubishi Kasei 11 critical altitude (ft)
            'hotp_flags': HOTP_FLAG_JITTER_AXIS1 | HOTP_FLAG_JITTER_AXIS2 | HOTP_FLAG_SMOOTH_CTRL,
        },
    }

    # Default class constants (overridden per-instance from template)
    CRUISE_SPEED = 250
    MAX_SPEED = 330
    MIN_SPEED = 80
    COMBAT_SPEED = 280
    MAX_TURN_RATE = 12
    MAX_CLIMB_RATE = 50
    MAX_ROLL_RATE = 90
    DETECTION_RANGE = 90000
    GUN_RANGE = 2500
    GUN_MAX_RANGE = 3000
    BREAK_RANGE = 500
    MERGE_ALT_BAND = 2000

    def __init__(self, x, y, z, heading=0, variant='fighter'):
        tmpl = self.TEMPLATES.get(variant, self.TEMPLATES['fighter'])
        super().__init__(x, y, z, 'aircraft', health=tmpl['health'])
        self.heading = heading
        self.pitch = 0
        self.roll = 0
        self.variant = variant
        self.name = tmpl['name']

        # Load performance from HOTP entity template
        self.CRUISE_SPEED = tmpl['cruise_speed']
        self.MAX_SPEED = tmpl['max_speed']
        self.MIN_SPEED = tmpl['min_speed']
        self.COMBAT_SPEED = tmpl['combat_speed']
        self.MAX_TURN_RATE = tmpl['max_turn_rate']
        self.MAX_CLIMB_RATE = tmpl['max_climb_rate']
        self.DETECTION_RANGE = tmpl['detection_range']
        self.GUN_RANGE = tmpl['gun_range']
        self.GUN_MAX_RANGE = tmpl['gun_max_range']
        self.BREAK_RANGE = tmpl['break_range']

        self.speed = self.CRUISE_SPEED
        self.vx = 0
        self.vy = 0
        self.vz = 0

        # AI state machine
        self.ai_state = 'patrol'  # patrol, intercept, attack, evade, kamikaze
        self.state_timer = 0
        self.target_heading = heading
        self.target_alt = z
        self.target_speed = self.speed

        # Patrol parameters
        self.patrol_center_x = x
        self.patrol_center_y = y
        self.patrol_radius = 10000  # ft
        self.patrol_dir = 1  # 1=right, -1=left

        # Combat state
        self.turn_rate = 0
        self.firing = False
        self.burst_timer = 0
        self.burst_cooldown = 0
        self.evasion_dir = 1  # 1=right, -1=left
        self.evasion_timer = 0
        self.last_known_player_x = 0
        self.last_known_player_y = 0
        self.last_known_player_z = 0
        self.smoke_trail = False
        self.erratic_flight = False

        # HOTP authentic mechanics (reconstructed from decompiled 68k binary)
        # Entity flags control per-tick behavior via bitmask (struct offset 0x685)
        self.hotp_flags = tmpl['hotp_flags']
        self.hotp_alt_ceiling = tmpl.get('alt_ceiling', 15000)  # engine critical altitude
        self.hotp_status = 0x0000       # status bitmask (struct offset 0x1A1)
        self.hotp_axis1 = 0             # heading perturbation accumulator [-512, 512]
        self.hotp_axis2 = 0             # altitude perturbation accumulator [-320, 320]
        self.hotp_fire_accum = 0        # weapon fire accumulator (builds toward threshold)
        self.hotp_fire_threshold = tmpl['fire_threshold']  # entity template field_1e
        self.hotp_control_accum = 0     # control input accumulator (signed)
        self.hotp_speed_factor = 1.0    # low-speed damping multiplier (from FUN_0000e468)
        # Three movement smoothing accumulators (from Pacific Conflict.c lines 14179-14244)
        # Only update for player-designated and target-designated entities in original
        self.hotp_move_66a = 0          # combined movement accumulator
        self.hotp_move_66e = 0          # heading-axis smoothed accumulator
        self.hotp_move_672 = 0          # template-scaled smoothed accumulator
        self.hotp_move_669 = 1          # control gate output byte (1=enabled)
        self.hotp_move_62a = 0          # movement base value (speed component)
        # Direction character (struct offset 0x679): '-' (0x2D) = full template adjust
        self.hotp_direction_char = 0x2D if variant == 'fighter' else 0x00
        # Weapon counters (struct offsets 0x67d, 0x67e)
        self.hotp_weapon_67d = 6 if variant == 'fighter' else 2  # primary weapon count
        self.hotp_weapon_67e = 4 if variant == 'fighter' else 8  # secondary weapon count

        # Damage behavior thresholds
        self.kamikaze_threshold = 0.25  # Go kamikaze below 25% health
        self.evade_threshold = 0.50     # Start evading below 50% health

    def _angle_to(self, tx, ty):
        """Get heading angle toward a target point"""
        dx = tx - self.x
        dy = ty - self.y
        return math.degrees(math.atan2(dx, dy)) % 360

    def _dist_to(self, tx, ty, tz=None):
        """Distance to target point"""
        d2 = (tx - self.x)**2 + (ty - self.y)**2
        if tz is not None:
            d2 += (tz - self.z)**2
        return math.sqrt(d2)

    def _hdg_diff(self, target_hdg):
        """Signed heading difference (-180 to 180)"""
        return ((target_hdg - self.heading + 180) % 360) - 180

    def _is_player_behind(self, player):
        """Check if player is in our rear hemisphere"""
        hdg_to_player = self._angle_to(player.x, player.y)
        diff = abs(self._hdg_diff(hdg_to_player))
        return diff > 120

    def _is_facing_target(self, tx, ty, cone=45):
        """Check if we're pointed within cone degrees of target"""
        hdg_to_target = self._angle_to(tx, ty)
        return abs(self._hdg_diff(hdg_to_target)) < cone

    def _get_alt_factor(self):
        """HOTP altitude performance factor from the 9-entry aerodynamic table.
        Maps current altitude through the table with peak at engine critical altitude.
        Zero: peak at 13,000 ft (Sakae 12), cliff above 15,000 ft.
        Betty: peak at 15,000 ft (Kasei 11), cliff above 18,000 ft.
        This creates realistic altitude-dependent performance:
        the F6F Hellcat's R-2800 (critical alt 23,400 ft) dominates above 20,000 ft."""
        # Table peak is at index 4 of 9. Map so critical altitude = peak.
        # alt_ceiling * 2.0 = full table span
        param = min(1.0, max(0.0, self.z / (self.hotp_alt_ceiling * 2.0)))
        return max(0.3, hotp_aero_lookup(param))

    def _steer_toward(self, target_hdg, dt, aggression=1.0):
        """Steer toward target heading using HOTP delta smoothing.
        Small corrections apply instantly; large ones at 1/8 rate per tick."""
        diff = self._hdg_diff(target_hdg)
        alt_factor = self._get_alt_factor()
        max_rate = self.MAX_TURN_RATE * aggression * alt_factor
        if self.variant == 'bomber':
            max_rate *= 0.3  # Bombers turn sluggishly
        desired_rate = max(-max_rate, min(max_rate, diff * 1.5))
        # HOTP delta smoothing: signature floaty-but-responsive feel
        self.turn_rate = hotp_delta_smooth(self.turn_rate, desired_rate, dt)
        self.heading = (self.heading + self.turn_rate * dt) % 360

    def _adjust_altitude(self, target_alt, dt):
        """Climb or descend using HOTP delta smoothing on vertical rate.
        Climb rate scaled by altitude performance factor."""
        alt_diff = target_alt - self.z
        alt_factor = self._get_alt_factor()
        max_climb = self.MAX_CLIMB_RATE * alt_factor
        if self.variant == 'bomber':
            max_climb *= 0.5
        target_climb = max(-max_climb * 1.5, min(max_climb, alt_diff * 0.3))
        # HOTP smoothing: small vz corrections snap, large ones ease in at 1/8
        self.vz = hotp_delta_smooth(self.vz, target_climb, dt)
        self.pitch = math.degrees(math.atan2(self.vz, self.speed * 1.68781))

    def _adjust_speed(self, target_speed, dt):
        """Adjust speed with HOTP low-speed damping and delta smoothing.
        Below 200 kts, effectiveness drops (from FUN_0000e468 stall behavior).
        Uses aero lookup table for performance scaling."""
        speed_diff = target_speed - self.speed
        accel = 15 if speed_diff > 0 else 25  # Decelerate faster
        # HOTP low-speed damping (exact formula from FUN_0000e468):
        # when param_1 < 0x200: param_2 -= (-(param_1-0x200)*param_2) >> 12
        # Map speed (kts) to game units (~2.56x): 200 kts ≈ 0x200 game units
        speed_units = int(self.speed * 2.56)
        effective_accel = hotp_fun_e468(speed_units, accel)
        raw_target = self.speed + max(-effective_accel * dt, min(effective_accel * dt, speed_diff))
        # HOTP delta smoothing on speed
        self.speed = hotp_delta_smooth(self.speed, raw_target, dt)
        # Altitude caps effective max speed (thin air = less thrust)
        alt_factor = self._get_alt_factor()
        effective_max = self.MIN_SPEED + (self.MAX_SPEED - self.MIN_SPEED) * alt_factor
        self.speed = max(self.MIN_SPEED, min(effective_max, self.speed))

    def update(self, dt, player=None, carrier=None):
        super().update(dt)
        self.firing = False

        if not self.alive:
            # Falling aircraft - smoke, tumble
            self.vz -= 32.174 * dt
            self.x += self.vx * dt
            self.y += self.vy * dt
            self.z += self.vz * dt
            self.pitch = min(self.pitch + 30 * dt, 60)
            self.roll += 45 * dt  # Tumbling roll
            self.z = max(0, self.z)
            return

        self.state_timer += dt

        # Check damage-driven state changes
        health_pct = self.health / (30 if self.variant == 'fighter' else 80)
        self.smoke_trail = health_pct < 0.70
        self.erratic_flight = health_pct < 0.40

        if health_pct <= self.kamikaze_threshold and self.ai_state != 'kamikaze':
            # Heavily damaged - kamikaze into nearest friendly ship
            if carrier and self.variant == 'fighter':
                self.ai_state = 'kamikaze'
                self.state_timer = 0
        elif health_pct <= self.evade_threshold and self.ai_state == 'attack':
            self.ai_state = 'evade'
            self.state_timer = 0
            self.evasion_dir = 1 if hotp_rng.coin_flip() else -1

        # Run current AI state
        if self.ai_state == 'patrol':
            self._ai_patrol(dt, player)
        elif self.ai_state == 'intercept':
            self._ai_intercept(dt, player)
        elif self.ai_state == 'attack':
            self._ai_attack(dt, player)
        elif self.ai_state == 'evade':
            self._ai_evade(dt, player)
        elif self.ai_state == 'kamikaze':
            self._ai_kamikaze(dt, carrier)

        # HOTP authentic AI jitter (reconstructed from 68k movement system)
        # Per-tick RNG perturbation on two axes, clamped to original ranges
        # Creates natural "wobble" in AI flight paths; damage amplifies it
        if self.hotp_flags & HOTP_FLAG_JITTER_AXIS1:
            jitter1 = (hotp_rng.next() & 0x7F) - 0x40  # [-64, +63]
            if self.erratic_flight:
                jitter1 *= 3  # Damage triples jitter amplitude
            self.hotp_axis1 += jitter1 * dt * 60
            self.hotp_axis1 = max(-512, min(512, self.hotp_axis1))
            # Map axis1 to heading: 512 units ~ 3 deg deviation
            self.heading += self.hotp_axis1 * 0.006 * dt

        if self.hotp_flags & HOTP_FLAG_JITTER_AXIS2:
            jitter2 = (hotp_rng.next() & 0x7F) - 0x40  # [-64, +63]
            if self.erratic_flight:
                jitter2 *= 3
            self.hotp_axis2 += jitter2 * dt * 60
            self.hotp_axis2 = max(-320, min(320, self.hotp_axis2))
            # Map axis2 to altitude: 320 units ~ 15 ft/s vz deviation
            self.vz += self.hotp_axis2 * 0.05 * dt

        # HOTP status override: forced descent when bit 0x01 set
        # (original: movement_662=0, movement_666=-0x80)
        if self.hotp_status & 0x01:
            self.hotp_axis1 = 0
            self.hotp_axis2 = -128

        # HOTP status bit 0x0040: clear control gate when heading accum reaches zero
        if (self.hotp_status & 0x0040) and self.hotp_move_66e == 0:
            self.hotp_move_669 = 0

        # HOTP status bits 0x0300: disable control gate (prevent weapon fire)
        if self.hotp_status & 0x0300:
            self.hotp_move_669 = 0

        # Three movement smoothing accumulators (Pacific Conflict.c lines 14179-14244)
        # These create the signature smooth movement of the original game.
        # 0x66e: heading-axis accumulator (from jitter + control input)
        target_66e = int(self.hotp_axis1 * 0.5 + self.hotp_control_accum * 2)
        self.hotp_move_66e = hotp_delta_smooth(self.hotp_move_66e, target_66e, dt)

        # 0x672: template-scaled accumulator (gated by 0x669 and status bits)
        if self.hotp_move_669 == 0 or (self.hotp_status & 0x4300) != 0:
            source_672 = 0
        else:
            # FUN_0000e570: template_field_38 * (0x551A / ((param+0x105)>>3)) >> 8
            tmpl = self.TEMPLATES.get(self.variant, self.TEMPLATES['fighter'])
            raw_38 = int(tmpl['scaling_factor'] * 100)  # scale normalized to raw-ish
            source_672 = hotp_fun_e570(raw_38, int(self.speed * 2.56)) >> 9
            # Direction character: '-' = full, other = half
            if self.hotp_direction_char == 0x2D:
                pass  # full adjustment
            else:
                source_672 = _half_toward_zero(source_672)
            if self.hotp_flags & HOTP_FLAG_SMOOTH_CTRL:
                source_672 = _half_toward_zero(source_672)
        self.hotp_move_672 = hotp_delta_smooth(self.hotp_move_672, source_672, dt)

        # 0x66a: combined accumulator (speed + heading interaction)
        speed_component = int(self.hotp_move_62a) >> 2 if self.hotp_move_62a else 0
        target_66a = int(self.hotp_move_66e * 0.5 + speed_component)
        self.hotp_move_66a = hotp_delta_smooth(self.hotp_move_66a, target_66a, dt)

        # Feed smoothed accumulators back into movement
        self.heading += self.hotp_move_66e * 0.001 * dt
        self.vz += self.hotp_move_672 * 0.02 * dt
        self.hotp_move_62a = self.speed * 2.56  # update base value

        # Apply roll from turn rate (visual only)
        target_roll = self.turn_rate * 4  # Bank proportional to turn
        self.roll += (target_roll - self.roll) * min(3.0 * dt, 1.0)
        self.roll = max(-60, min(60, self.roll))

        # Convert heading + speed to velocity
        hdg_rad = math.radians(self.heading)
        speed_fps = self.speed * 1.68781
        self.vx = math.sin(hdg_rad) * speed_fps
        self.vy = math.cos(hdg_rad) * speed_fps

        # Update position
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.z += self.vz * dt
        self.z = max(50, self.z)  # Don't fly into the water

    def _ai_patrol(self, dt, player):
        """Circle patrol point, scanning for player"""
        # Check for player detection
        if player and player.z > 0:
            dist = self._dist_to(player.x, player.y, player.z)
            if dist < self.DETECTION_RANGE:
                self.ai_state = 'intercept'
                self.state_timer = 0
                self.last_known_player_x = player.x
                self.last_known_player_y = player.y
                self.last_known_player_z = player.z
                return

        # Standard patrol circle
        dx = self.x - self.patrol_center_x
        dy = self.y - self.patrol_center_y
        dist = math.sqrt(dx**2 + dy**2)

        if dist > self.patrol_radius * 1.2:
            target_hdg = self._angle_to(self.patrol_center_x, self.patrol_center_y)
            self._steer_toward(target_hdg, dt, aggression=0.5)
        else:
            # Gentle orbit
            self.turn_rate = 2.0 * self.patrol_dir
            self.heading = (self.heading + self.turn_rate * dt) % 360

        self._adjust_speed(self.CRUISE_SPEED if self.variant == 'fighter' else 180, dt)
        self._adjust_altitude(self.target_alt, dt)

    def _ai_intercept(self, dt, player):
        """Close distance to player, set up attack run"""
        if not player or player.z <= 0:
            self.ai_state = 'patrol'
            self.state_timer = 0
            return

        dist = self._dist_to(player.x, player.y, player.z)
        self.last_known_player_x = player.x
        self.last_known_player_y = player.y
        self.last_known_player_z = player.z

        # Lost contact - return to patrol
        if dist > self.DETECTION_RANGE * 1.5:
            self.ai_state = 'patrol'
            self.state_timer = 0
            return

        # Close enough to engage - switch to attack
        if dist < self.GUN_MAX_RANGE * 2:
            self.ai_state = 'attack'
            self.state_timer = 0
            return

        # Intercept: lead the target, climb/descend to engagement altitude
        # Lead pursuit - aim ahead of where player is going
        lead_time = dist / (self.speed * 1.68781) * 0.5
        lead_x = player.x + player.vx * lead_time
        lead_y = player.y + player.vy * lead_time

        target_hdg = self._angle_to(lead_x, lead_y)
        self._steer_toward(target_hdg, dt, aggression=0.8)

        # Speed up for intercept
        self._adjust_speed(self.MAX_SPEED if self.variant == 'fighter' else 200, dt)

        # Match altitude band
        target_alt = player.z
        self._adjust_altitude(target_alt, dt)

    def _ai_attack(self, dt, player):
        """Dogfight - get on player's tail and fire"""
        if not player or player.z <= 0:
            self.ai_state = 'patrol'
            self.state_timer = 0
            return

        dist = self._dist_to(player.x, player.y, player.z)
        self.last_known_player_x = player.x
        self.last_known_player_y = player.y
        self.last_known_player_z = player.z

        # Bombers don't dogfight - they just keep flying toward objective
        if self.variant == 'bomber':
            self._ai_bomber_attack(dt, player)
            return

        # Lost contact
        if dist > self.DETECTION_RANGE:
            self.ai_state = 'intercept'
            self.state_timer = 0
            return

        # Lead pursuit - aim where the player will be
        closing_speed = max(100, self.speed * 1.68781)
        lead_time = min(dist / closing_speed, 2.0)
        lead_x = player.x + player.vx * lead_time
        lead_y = player.y + player.vy * lead_time
        lead_z = player.z + getattr(player, 'vz', 0) * lead_time

        target_hdg = self._angle_to(lead_x, lead_y)

        # If too close, break off and re-engage
        if dist < self.BREAK_RANGE:
            # Break turn - pull hard in current turn direction
            break_hdg = (self.heading + 90 * (1 if self.turn_rate >= 0 else -1)) % 360
            self._steer_toward(break_hdg, dt, aggression=1.0)
            self._adjust_speed(self.COMBAT_SPEED, dt)
            self._adjust_altitude(self.z + 500, dt)
            return

        # Main attack steering
        hdg_diff = abs(self._hdg_diff(target_hdg))

        if hdg_diff < 30:
            # Nearly lined up - fine tracking, maintain speed for gun solution
            self._steer_toward(target_hdg, dt, aggression=0.6)
            self._adjust_speed(self.COMBAT_SPEED, dt)
        else:
            # Turn hard to get on target
            self._steer_toward(target_hdg, dt, aggression=1.0)
            # Tighten turn by slowing down
            turn_speed = self.COMBAT_SPEED - abs(hdg_diff) * 0.5
            self._adjust_speed(max(self.MIN_SPEED + 50, turn_speed), dt)

        # Altitude: try to stay at or slightly above player
        self._adjust_altitude(lead_z + 200, dt)

        # HOTP accumulator-based weapon fire (from _apply_control_threshold_decrement)
        # Control gate conditions (from _apply_control_gate_accumulator):
        #   gate = ((flags & 0x40)==0 OR status_1a3!=0) AND (status & 0x0300)==0 AND ammo>0
        # Accumulator builds; fires when accumulator EXCEEDS threshold (not >=)
        # RNG coin flip selects which weapon counter to decrement
        self.firing = False
        has_ammo = self.hotp_weapon_67d > 0 or self.hotp_weapon_67e > 0
        gate_enabled = (not (self.hotp_flags & HOTP_FLAG_CONTROL_GATE) or
                        (self.hotp_status & 0xFF00) != 0)  # status_1a3 proxy
        gate_enabled = gate_enabled and (self.hotp_status & 0x0300) == 0 and has_ammo

        if dist < self.GUN_MAX_RANGE and hdg_diff < 15 and gate_enabled:
            alt_diff = abs(self.z - player.z)
            if alt_diff < dist * 0.3:
                closeness = 1.0 - dist / self.GUN_MAX_RANGE
                self.hotp_control_accum = max(1, int(10 * closeness))
                # SMOOTH_CTRL: halve accumulator toward zero each tick
                if self.hotp_flags & HOTP_FLAG_SMOOTH_CTRL:
                    self.hotp_control_accum = _half_toward_zero(self.hotp_control_accum)
                self.hotp_fire_accum += self.hotp_control_accum * dt * 60
                # Original fires when accumulator > threshold (strict greater-than)
                if self.hotp_fire_accum > self.hotp_fire_threshold:
                    self.hotp_fire_accum -= self.hotp_fire_threshold
                    # RNG coin flip for weapon type selection (original logic)
                    rng_bit = hotp_rng.next() & 1
                    if rng_bit == 0 or self.hotp_weapon_67d == 0:
                        if self.hotp_weapon_67e > 0:
                            self.hotp_weapon_67e -= 1
                    else:
                        self.hotp_weapon_67d -= 1
                    self.firing = True
            else:
                self.hotp_fire_accum = max(0, self.hotp_fire_accum - 20 * dt * 60)
        else:
            # Gate closed: accumulator decays
            if self.hotp_flags & HOTP_FLAG_SMOOTH_CTRL:
                self.hotp_fire_accum = _half_toward_zero(int(self.hotp_fire_accum))
            else:
                self.hotp_fire_accum = max(0, self.hotp_fire_accum - 40 * dt * 60)
            self.hotp_control_accum = 0

    def _ai_bomber_attack(self, dt, player):
        """Bombers fly straight to objective, minimal maneuvering"""
        # Bombers just fly toward their patrol center (the target)
        target_hdg = self._angle_to(self.patrol_center_x, self.patrol_center_y)
        self._steer_toward(target_hdg, dt, aggression=0.3)
        self._adjust_speed(180, dt)
        self._adjust_altitude(self.target_alt, dt)

    def _ai_evade(self, dt, player):
        """Break away from combat, try to disengage"""
        self.evasion_timer += dt

        if not player:
            self.ai_state = 'patrol'
            self.state_timer = 0
            return

        dist = self._dist_to(player.x, player.y)

        # If we've opened up distance, return to patrol or re-engage
        if dist > self.DETECTION_RANGE * 0.8 or self.evasion_timer > 15:
            self.ai_state = 'patrol'
            self.state_timer = 0
            self.evasion_timer = 0
            return

        # Evasion: turn away from player with jinking
        away_hdg = self._angle_to(player.x, player.y)
        away_hdg = (away_hdg + 180) % 360  # Opposite direction

        # Add jinking - change direction periodically
        jink_period = 3.0
        if int(self.evasion_timer / jink_period) % 2 == 0:
            away_hdg = (away_hdg + 40 * self.evasion_dir) % 360
        else:
            away_hdg = (away_hdg - 40 * self.evasion_dir) % 360

        self._steer_toward(away_hdg, dt, aggression=1.0)
        self._adjust_speed(self.MAX_SPEED, dt)  # Full speed escape

        # Dive for speed if player is behind
        if self._is_player_behind(player):
            self._adjust_altitude(max(500, self.z - 2000), dt)
        else:
            self._adjust_altitude(self.z + 500, dt)

    def _ai_kamikaze(self, dt, carrier):
        """Dive at nearest friendly ship - from manual: damaged enemy loses fear of death"""
        if not carrier:
            # No carrier target, just dive
            self._adjust_altitude(0, dt)
            self._adjust_speed(self.MAX_SPEED, dt)
            return

        target_hdg = self._angle_to(carrier.x, carrier.y)
        dist = self._dist_to(carrier.x, carrier.y)

        self._steer_toward(target_hdg, dt, aggression=1.0)
        self._adjust_speed(self.MAX_SPEED, dt)

        # Dive toward carrier - steeper as we get closer
        if dist < 5000:
            self._adjust_altitude(0, dt)
            self.vz = -100  # Hard dive
            self.pitch = -30
        else:
            # Cruise toward the carrier's altitude (deck level) before the
            # terminal dive; carriers have no z, so default to a low run-in.
            self._adjust_altitude(getattr(carrier, 'z', 200), dt)

    def check_hit(self, px, py, pz):
        """Check if a point hits this aircraft"""
        dist = math.sqrt((px - self.x)**2 + (py - self.y)**2 + (pz - self.z)**2)
        return dist < 40  # ~40 ft hit radius


class TargetManager:
    """Manages all targets in the simulation"""
    def __init__(self, ref_lat, ref_lon):
        self.ref_lat = ref_lat
        self.ref_lon = ref_lon
        self.ships = []
        self.ground_targets = []
        self.enemy_aircraft = []
        self.score = 0
        self.kills = {'ship': 0, 'ground': 0, 'aircraft': 0}
        self.spawn_targets()

    def spawn_targets(self):
        """Create initial target setup - Pacific theater style"""
        # Enemy fleet - visible on 3nm radar from start, south of start position
        fleet_x = 8000   # feet east
        fleet_y = -15000  # feet south (~2.5 nm, visible on 3nm radar)

        # Carrier group
        self.ships.append(Ship(fleet_x, fleet_y, 'carrier', heading=45))
        self.ships.append(Ship(fleet_x - 2000, fleet_y - 3000, 'destroyer', heading=45))
        self.ships.append(Ship(fleet_x + 2000, fleet_y - 2500, 'destroyer', heading=45))
        self.ships.append(Ship(fleet_x - 1000, fleet_y + 4000, 'transport', heading=45))
        self.ships.append(Ship(fleet_x + 3000, fleet_y - 1000, 'battleship', heading=45))

        # Second group further east
        self.ships.append(Ship(fleet_x + 25000, fleet_y - 5000, 'carrier', heading=90))
        self.ships.append(Ship(fleet_x + 23000, fleet_y - 7000, 'destroyer', heading=90))
        self.ships.append(Ship(fleet_x + 26000, fleet_y - 3000, 'cruiser', heading=90))

        # Ground targets on Long Island (simulating enemy-held airfield)
        airfield_x = 25000
        airfield_y = 15000

        # AA defenses
        self.ground_targets.append(GroundTarget(airfield_x - 500, airfield_y - 500, 'aa_gun'))
        self.ground_targets.append(GroundTarget(airfield_x + 500, airfield_y - 500, 'aa_gun'))
        self.ground_targets.append(GroundTarget(airfield_x - 500, airfield_y + 500, 'aa_gun'))
        self.ground_targets.append(GroundTarget(airfield_x + 500, airfield_y + 500, 'aa_gun'))

        # Hangars and fuel
        self.ground_targets.append(GroundTarget(airfield_x, airfield_y, 'hangar'))
        self.ground_targets.append(GroundTarget(airfield_x - 300, airfield_y + 200, 'fuel_tank'))
        self.ground_targets.append(GroundTarget(airfield_x + 300, airfield_y + 200, 'fuel_tank'))
        self.ground_targets.append(GroundTarget(airfield_x, airfield_y - 400, 'bunker'))

        # Enemy aircraft on patrol
        self.enemy_aircraft.append(EnemyAircraft(20000, 0, 8000, heading=180))
        self.enemy_aircraft.append(EnemyAircraft(25000, 5000, 7000, heading=220))
        self.enemy_aircraft.append(EnemyAircraft(10000, -20000, 6000, heading=0))
        self.enemy_aircraft.append(EnemyAircraft(40000, -30000, 9000, heading=270))

    def _get_score(self, target):
        """Get HOTP-accurate score for a destroyed target"""
        if isinstance(target, Ship):
            return Ship.SCORE.get(target.ship_type, 250)
        if isinstance(target, EnemyAircraft):
            return 1000 if target.variant == 'bomber' else 500
        if isinstance(target, GroundTarget):
            return 50 if target.ground_type == 'aa_gun' else 100
        return 100

    def check_hits(self, weapons_mgr):
        """Check for weapon hits on targets"""
        # Check bullets
        for bullet in weapons_mgr.bullets[:]:
            # Check ships
            for ship in self.ships:
                if ship.alive and ship.check_hit(bullet.x, bullet.y, bullet.z):
                    ship.take_damage(5)  # .50 cal does light damage to ships
                    bullet.alive = False
                    if not ship.alive:
                        self.score += self._get_score(ship)
                        self.kills['ship'] += 1
                        weapons_mgr.explosions.append([ship.x, ship.y, 0, 0, 300])
                    break

            # Check ground targets
            for target in self.ground_targets:
                if target.alive and target.check_hit(bullet.x, bullet.y, bullet.z):
                    target.take_damage(10)
                    bullet.alive = False
                    if not target.alive:
                        self.score += self._get_score(target)
                        self.kills['ground'] += 1
                        weapons_mgr.explosions.append([target.x, target.y, 0, 0, 80])
                    break

            # Check enemy aircraft
            for enemy in self.enemy_aircraft:
                if enemy.alive and enemy.check_hit(bullet.x, bullet.y, bullet.z):
                    enemy.take_damage(15)
                    bullet.alive = False
                    if not enemy.alive:
                        self.score += self._get_score(enemy)
                        self.kills['aircraft'] += 1
                        weapons_mgr.explosions.append([enemy.x, enemy.y, enemy.z, 0, 100])
                    break

        # Check rockets (more damage)
        for rocket in weapons_mgr.rockets[:]:
            for ship in self.ships:
                if ship.alive and ship.check_hit(rocket.x, rocket.y, rocket.z):
                    ship.take_damage(75)
                    rocket.alive = False
                    weapons_mgr.explosions.append([rocket.x, rocket.y, rocket.z, 0, 100])
                    if not ship.alive:
                        self.score += self._get_score(ship)
                        self.kills['ship'] += 1
                        weapons_mgr.explosions.append([ship.x, ship.y, 0, 0, 300])
                    break

            for target in self.ground_targets:
                if target.alive and target.check_hit(rocket.x, rocket.y, rocket.z):
                    target.take_damage(100)  # Rockets destroy most ground targets
                    rocket.alive = False
                    weapons_mgr.explosions.append([rocket.x, rocket.y, 0, 0, 80])
                    if not target.alive:
                        self.score += self._get_score(target)
                        self.kills['ground'] += 1
                    break

            for enemy in self.enemy_aircraft:
                if enemy.alive and enemy.check_hit(rocket.x, rocket.y, rocket.z):
                    enemy.take_damage(100)  # Instant kill
                    rocket.alive = False
                    weapons_mgr.explosions.append([enemy.x, enemy.y, enemy.z, 0, 100])
                    if not enemy.alive:
                        self.score += self._get_score(enemy)
                        self.kills['aircraft'] += 1
                    break

        # Check bombs (massive damage). Blast keys on the detonation flag set at
        # surface impact, not a narrow z-band, so a fast-falling bomb can't be
        # reaped before its blast lands. Reap the bomb once processed.
        for bomb in weapons_mgr.bombs[:]:
            if not bomb.detonated:
                continue
            blast_radius = 200 if bomb.weight <= 500 else 280
            max_damage = 300 * (bomb.weight / 500)
            for ship in self.ships:
                if ship.alive:
                    dist = math.sqrt((bomb.x - ship.x)**2 + (bomb.y - ship.y)**2)
                    if dist < blast_radius:
                        damage = max_damage * (1 - dist / blast_radius)
                        ship.take_damage(damage)
                        if not ship.alive:
                            self.score += self._get_score(ship)
                            self.kills['ship'] += 1
                            weapons_mgr.explosions.append([ship.x, ship.y, 0, 0, 300])

            for target in self.ground_targets:
                if target.alive:
                    dist = math.sqrt((bomb.x - target.x)**2 + (bomb.y - target.y)**2)
                    if dist < 150:
                        target.take_damage(200)
                        if not target.alive:
                            self.score += self._get_score(target)
                            self.kills['ground'] += 1

            # Consumed — let weapons_mgr reap it next frame (blast applies once).
            bomb.alive = False

        # Check torpedoes (massive damage to ships, must be armed and in water)
        for torp in weapons_mgr.torpedoes[:]:
            if not torp.in_water or not torp.armed:
                continue
            for ship in self.ships:
                if ship.alive and ship.check_hit(torp.x, torp.y, 0):
                    # Mk 13 torpedo: devastating against ships
                    ship.take_damage(400)
                    torp.alive = False
                    weapons_mgr.explosions.append([torp.x, torp.y, 0, 0, 400])
                    if not ship.alive:
                        self.score += self._get_score(ship)
                        self.kills['ship'] += 1
                        weapons_mgr.explosions.append([ship.x, ship.y, 0, 0, 500])
                    break

    def check_enemy_fire(self, player, dt):
        """Enemy aircraft and AA fire at the player"""
        for enemy in self.enemy_aircraft:
            if not enemy.alive:
                continue
            # Use AI firing state - the AI decides when to shoot
            if not enemy.firing:
                continue
            dx = player.x - enemy.x
            dy = player.y - enemy.y
            dz = player.z - enemy.z
            dist = math.sqrt(dx*dx + dy*dy + dz*dz)
            if dist > enemy.GUN_MAX_RANGE or dist < 50:
                continue
            # Hit probability based on range and deflection
            # Better accuracy when closer, worse when target is maneuvering
            base_chance = 0.08 * dt * (1000 / max(dist, 200))
            # Reduce accuracy if player is turning hard
            player_g = abs(getattr(player, 'roll', 0)) / 90.0
            maneuver_penalty = 1.0 - player_g * 0.6
            hit_chance = base_chance * max(0.2, maneuver_penalty)
            if hotp_rng.fraction() < hit_chance:
                if hasattr(player, 'take_hit'):
                    player.take_hit()
            elif dist < 300:
                # Near miss — bullets crack past, cause screen shake/flinch
                if hasattr(player, 'near_miss_shake'):
                    intensity = 0.3 * (1 - dist / 300)
                    player.near_miss_shake = max(player.near_miss_shake, intensity)

        # AA guns fire at player
        for target in self.ground_targets:
            if not target.alive or target.ground_type != 'aa_gun':
                continue
            dx = player.x - target.x
            dy = player.y - target.y
            dist = math.sqrt(dx*dx + dy*dy)
            if dist > 5000 or player.z > 8000:  # AA range and ceiling
                continue
            hit_chance = 0.02 * dt * (2000 / max(dist, 200))
            if hotp_rng.fraction() < hit_chance:
                if hasattr(player, 'take_hit'):
                    player.take_hit()

        # Ship AA fire at player (scaled by ship type)
        for ship in self.ships:
            if not ship.alive:
                continue
            dx = player.x - ship.x
            dy = player.y - ship.y
            dist = math.sqrt(dx*dx + dy*dy)
            if dist > 8000 or player.z > 12000:  # Ship AA range and ceiling
                continue
            hit_chance = ship.aa_rate * dt * (3000 / max(dist, 300))
            if hotp_rng.fraction() < hit_chance:
                if hasattr(player, 'take_hit'):
                    player.take_hit()
            elif dist < 400 and hasattr(player, 'near_miss_shake'):
                player.near_miss_shake = max(player.near_miss_shake, 0.2)

    def update(self, dt, weapons_mgr, player=None, carrier=None, wingmen=None):
        """Update all targets using HOTP four-array ordering.
        Original game processes entities in strict order:
          Array 1: friendly entities (carrier) with param=0
          Array 2: player entity with param=0
          Array 3: enemy aircraft with param=1
          Array 4: ground/naval targets with param=1
        This order is absolute and cannot be reordered without breaking parity."""
        # Array 1 & 2: friendly entities (param=0) - carrier updated externally
        # Wingmen updated here as friendly array
        if wingmen:
            for wm in wingmen:
                wm.update(dt, player, self.enemy_aircraft)

        # Array 3: enemy aircraft (param=1)
        for enemy in self.enemy_aircraft:
            enemy.update(dt, player=player, carrier=carrier)

        # Array 4: ground/naval targets (param=1)
        for ship in self.ships:
            ship.update(dt)
        for target in self.ground_targets:
            target.update(dt)

        # Post-tick: collision detection and fire
        self.check_hits(weapons_mgr)

        # Enemy fires at player
        if player:
            self.check_enemy_fire(player, dt)

        # Enemy fires at wingmen
        if wingmen:
            for wm in wingmen:
                if wm.alive:
                    self._check_enemy_fire_at_wingman(wm, dt)

    def _check_enemy_fire_at_wingman(self, wingman, dt):
        """Enemy aircraft fire at wingman (simplified)"""
        for enemy in self.enemy_aircraft:
            if not enemy.alive or not enemy.firing:
                continue
            dist = math.sqrt((wingman.x - enemy.x)**2 + (wingman.y - enemy.y)**2 +
                             (wingman.z - enemy.z)**2)
            if dist > enemy.GUN_MAX_RANGE or dist < 50:
                continue
            hit_chance = 0.05 * dt * (800 / max(dist, 200))
            if hotp_rng.fraction() < hit_chance:
                wingman.take_damage(10)

    def clear(self):
        """Reset all targets"""
        self.ships.clear()
        self.ground_targets.clear()
        self.enemy_aircraft.clear()
        self.score = 0
        self.kills = {'ship': 0, 'ground': 0, 'aircraft': 0}
        self.spawn_targets()


